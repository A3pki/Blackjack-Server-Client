"""Top-level multi-threaded Blackjack server.

* Accepts connections on a dedicated accept thread.
* Spawns one :class:`ClientHandler` thread per connection.
* Owns the shared :class:`Table`, :class:`ProfileManager` and RSA key pair.
* Coordinates broadcast of game state to all logged-in clients.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Dict, List, Optional

from ..common.crypto import RSAKeyPair
from .chat_filter import is_allowed
from .client_handler import ClientHandler
from .game import Phase, Table, _PendingResult
from .profile_manager import ProfileManager

log = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5050
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PROFILES_FILE = os.path.join(DATA_DIR, "profiles.json")
RSA_KEY_FILE = os.path.join(DATA_DIR, "server_rsa.pem")

# Pause between revealing results and starting the next round.
RESULTS_PAUSE_SECONDS = 6.0


class BlackjackServer:
    """Top-level coordinator: networking + game state."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._host = host
        self._port = port
        self._listen_sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._clients_lock = threading.RLock()
        self._clients: List[ClientHandler] = []
        self._online_usernames: Dict[str, ClientHandler] = {}

        os.makedirs(DATA_DIR, exist_ok=True)
        self._keypair = RSAKeyPair.load_or_create(RSA_KEY_FILE)
        self._profiles = ProfileManager(PROFILES_FILE)
        self._table = Table(
            broadcast=self._broadcast_state,
            on_round_finished=self._handle_round_finished,
        )
        self._results_timer: Optional[threading.Timer] = None

    # --- lifecycle ------------------------------------------------------

    def serve_forever(self) -> None:
        self._listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listen_sock.bind((self._host, self._port))
        self._listen_sock.listen(16)
        log.info("Server listening on %s:%d", self._host, self._port)
        try:
            while not self._stop_event.is_set():
                try:
                    sock, addr = self._listen_sock.accept()
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                handler = ClientHandler(
                    sock=sock, addr=addr, server=self,
                    keypair=self._keypair, profiles=self._profiles,
                )
                with self._clients_lock:
                    self._clients.append(handler)
                handler.start()
                log.info("Accepted connection from %s", addr)
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        log.info("Stopping server...")
        if self._listen_sock is not None:
            try:
                self._listen_sock.close()
            except OSError:
                pass
        if self._results_timer is not None:
            self._results_timer.cancel()
        with self._clients_lock:
            clients = list(self._clients)
        for c in clients:
            c.shutdown()

    # --- client tracking -----------------------------------------------

    def is_username_online(self, username: str) -> bool:
        with self._clients_lock:
            return username in self._online_usernames

    def on_client_authenticated(self, handler: ClientHandler) -> None:
        assert handler.username is not None
        with self._clients_lock:
            self._online_usernames[handler.username] = handler
            self._table.add_player(handler.username)
        self._broadcast_state()

    def on_client_disconnected(self, handler: ClientHandler) -> None:
        with self._clients_lock:
            if handler in self._clients:
                self._clients.remove(handler)
            if handler.username and self._online_usernames.get(handler.username) is handler:
                self._online_usernames.pop(handler.username, None)
                self._table.remove_player(handler.username)
        self._broadcast_state()

    # --- game actions (called from client handler threads) -------------

    def handle_place_bet(self, handler: ClientHandler, amount: int) -> None:
        assert handler.username is not None
        username = handler.username
        if amount <= 0:
            raise ValueError("Bet must be positive")
        # Charge the player up-front so they cannot over-commit across rounds.
        try:
            new_balance = self._profiles.adjust_credits(username, -amount)
        except ValueError as exc:
            raise ValueError(str(exc))
        try:
            self._table.place_bet(username, amount, balance=new_balance)
        except (ValueError, KeyError) as exc:
            # Refund the bet on rejection.
            self._profiles.adjust_credits(username, amount)
            raise ValueError(str(exc))
        # Confirm new balance to the bettor and broadcast state to everyone.
        self._send_profile(handler)
        self._broadcast_state()

    def handle_action(self, handler: ClientHandler, action: str) -> None:
        assert handler.username is not None
        username = handler.username
        if action == "double":
            current_player = self._table.get_player(username)
            if current_player is None:
                raise ValueError("You are not at the table")
            balance = self._profiles.get(username).credits
            extra = current_player.bet
            can_afford = balance >= extra
            if can_afford:
                self._profiles.adjust_credits(username, -extra)
            try:
                self._table.player_action(username, action, can_afford_double=can_afford)
            except ValueError:
                if can_afford:
                    self._profiles.adjust_credits(username, extra)
                raise
            self._send_profile(handler)
        else:
            self._table.player_action(username, action, can_afford_double=False)
        self._broadcast_state()

    def handle_chat(self, handler: ClientHandler, message: str) -> None:
        assert handler.username is not None

        allowed, reason = is_allowed(message)
        if not allowed:
            log.info(
                "chat blocked for %s (reason: %s): %r",
                handler.username, reason, message[:60],
            )
            handler.send("error", {
                "message": (
                    "Your message was blocked by the chat filter. "
                    "Please keep the chat friendly and on-topic."
                )
            })
            return

        payload = {"from": handler.username, "message": message}
        with self._clients_lock:
            recipients = list(self._online_usernames.values())
        for c in recipients:
            try:
                c.send("chat", payload)
            except Exception:  # pragma: no cover - defensive
                pass

    # --- internal helpers ----------------------------------------------

    def _send_profile(self, handler: ClientHandler) -> None:
        if handler.username is None:
            return
        profile = self._profiles.get(handler.username)
        # Re-send auth_result with updated profile so the client UI refreshes.
        handler.send("auth_result", {
            "success": True,
            "message": "Profile updated",
            "profile": profile.to_public_dict(),
        })

    def _broadcast_state(self) -> None:
        with self._clients_lock:
            recipients = list(self._online_usernames.values())
        for handler in recipients:
            assert handler.username is not None
            snapshot = self._table.snapshot_for(handler.username)
            try:
                handler.send("game_state", snapshot)
            except Exception:  # pragma: no cover - defensive
                pass

    def _handle_round_finished(self, results: List[_PendingResult]) -> None:
        # Update credits + W/L counters and tell each player the outcome.
        per_user_results = []
        for r in results:
            if r.payout > 0:
                self._profiles.adjust_credits(r.username, r.payout)
            outcome_for_record = "win" if r.outcome == "win" else (
                "loss" if r.outcome == "loss" else "push"
            )
            updated = self._profiles.record_result(r.username, outcome_for_record)
            per_user_results.append((r, updated))

        # Push state once so everyone sees the resolved table.
        self._broadcast_state()

        # Then send per-user round_result + refreshed profile.
        with self._clients_lock:
            online = dict(self._online_usernames)
        for r, profile in per_user_results:
            handler = online.get(r.username)
            if handler is None:
                continue
            handler.send("round_result", {
                "outcome": r.outcome,
                "payout": r.payout,
                "profile": profile.to_public_dict(),
            })

        # Schedule next round.
        self._results_timer = threading.Timer(
            RESULTS_PAUSE_SECONDS, self._start_next_round,
        )
        self._results_timer.daemon = True
        self._results_timer.start()

    def _start_next_round(self) -> None:
        self._table.prepare_next_round()
        self._broadcast_state()
