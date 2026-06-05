"""Top-level server — accepts connections, owns the table, and coordinates everything.

One accept thread + one ClientHandler thread per connection.
The Table and ProfileManager are shared across all of them.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Dict, List, Optional

from ..common.crypto import RSAKeyPair
from .client_handler import ClientHandler
from .game import Phase, RoundResult, Table
from .profile_manager import ProfileManager

log = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5050
DATA_DIR    = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PROFILES_DB  = os.path.join(DATA_DIR, "profiles.db")
RSA_KEY_FILE = os.path.join(DATA_DIR, "server_rsa.pem")

# How long to show round results before starting the next round.
RESULTS_PAUSE = 6.0


class BlackjackServer:
    """The whole server in one class — networking, game state, and player tracking."""

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        """Set up the server. Call serve_forever() to start accepting connections."""
        self._host = host
        self._port = port
        self._listen_sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._clients_lock = threading.RLock()
        self._clients: List[ClientHandler] = []
        self._online: Dict[str, ClientHandler] = {}  # username -> handler

        os.makedirs(DATA_DIR, exist_ok=True)
        self._keypair = RSAKeyPair.load_or_create(RSA_KEY_FILE)
        self._profiles = ProfileManager(PROFILES_DB)
        self._table = Table(
            broadcast=self._broadcast,
            on_round_finished=self._on_round_finished,
        )
        self._results_timer: Optional[threading.Timer] = None

    # --- lifecycle -------------------------------------------------------

    def serve_forever(self) -> None:
        """Start listening and block until stop() is called."""
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
        """Shut down the server and disconnect all clients."""
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

    # --- client tracking ------------------------------------------------

    def is_online(self, username: str) -> bool:
        """True if a player with this username is currently connected."""
        with self._clients_lock:
            return username in self._online

    def on_player_joined(self, handler: ClientHandler) -> None:
        """Called by ClientHandler after a successful login or register."""
        assert handler.username is not None
        with self._clients_lock:
            self._online[handler.username] = handler
            self._table.add_player(handler.username)
        self._broadcast()

    def on_player_left(self, handler: ClientHandler) -> None:
        """Called by ClientHandler when a connection closes (disconnect or logout)."""
        with self._clients_lock:
            if handler in self._clients:
                self._clients.remove(handler)
            if handler.username and self._online.get(handler.username) is handler:
                self._online.pop(handler.username, None)
                self._table.remove_player(handler.username)
        self._broadcast()

    # --- game actions (called from ClientHandler threads) ---------------

    def on_bet(self, handler: ClientHandler, amount: int) -> None:
        """Handle a place_bet message — charge the player and tell the table."""
        assert handler.username is not None
        username = handler.username
        if amount <= 0:
            raise ValueError("Bet must be positive")
        # Charge up front so they can't double-commit across rounds.
        try:
            new_balance = self._profiles.adjust_credits(username, -amount)
        except ValueError as exc:
            raise ValueError(str(exc))
        try:
            self._table.place_bet(username, amount, balance=new_balance)
        except (ValueError, KeyError) as exc:
            # Table rejected the bet — refund it.
            self._profiles.adjust_credits(username, amount)
            raise ValueError(str(exc))
        # Send the updated balance back to this player, then update everyone.
        self._push_profile(handler)
        self._broadcast()

    def on_action(self, handler: ClientHandler, action: str) -> None:
        """Handle a hit/stand/double action from a player."""
        assert handler.username is not None
        username = handler.username
        if action == "double":
            # Figure out if the player can afford to match their bet.
            current_player = self._table.get_player(username)
            if current_player is None:
                raise ValueError("You are not at the table")
            balance = self._profiles.get(username).credits
            extra = current_player.bet
            can_afford = balance >= extra
            if can_afford:
                self._profiles.adjust_credits(username, -extra)
            try:
                self._table.handle_action(username, action, can_afford_double=can_afford)
            except ValueError:
                if can_afford:
                    self._profiles.adjust_credits(username, extra)  # refund on error
                raise
            self._push_profile(handler)
        else:
            self._table.handle_action(username, action, can_afford_double=False)
        self._broadcast()

    def on_chat(self, handler: ClientHandler, message: str) -> None:
        """Relay a chat message to every connected player."""
        assert handler.username is not None
        payload = {"from": handler.username, "message": message}
        with self._clients_lock:
            recipients = list(self._online.values())
        for c in recipients:
            try:
                c.send("chat", payload)
            except Exception:
                pass  # don't let one broken client interrupt the others

    # --- internal helpers -----------------------------------------------

    def _push_profile(self, handler: ClientHandler) -> None:
        """Re-send auth_result with the player's latest profile so the UI refreshes."""
        if handler.username is None:
            return
        profile = self._profiles.get(handler.username)
        handler.send("auth_result", {
            "success": True,
            "message": "Profile updated",
            "profile": profile.to_dict(),
        })

    def _broadcast(self) -> None:
        """Push a fresh game_state snapshot to every logged-in player."""
        with self._clients_lock:
            recipients = list(self._online.values())
        for handler in recipients:
            assert handler.username is not None
            snapshot = self._table.snapshot_for(handler.username)
            try:
                handler.send("game_state", snapshot)
            except Exception:
                pass  # disconnected clients will clean themselves up

    def _on_round_finished(self, results: List[RoundResult]) -> None:
        """Credit wins, record W/L/push stats, then send round_result to each player."""
        per_user = []
        for r in results:
            if r.payout > 0:
                self._profiles.adjust_credits(r.username, r.payout)
            outcome_key = r.outcome if r.outcome in ("win", "loss", "push") else "loss"
            updated = self._profiles.record_result(r.username, outcome_key)
            per_user.append((r, updated))

        # Show the resolved table to everyone first.
        self._broadcast()

        # Then send each player their personal result + refreshed profile.
        with self._clients_lock:
            online = dict(self._online)
        for r, profile in per_user:
            handler = online.get(r.username)
            if handler is None:
                continue
            handler.send("round_result", {
                "outcome": r.outcome,
                "payout": r.payout,
                "profile": profile.to_dict(),
            })

        # Wait a few seconds then start the next round.
        self._results_timer = threading.Timer(RESULTS_PAUSE, self._begin_next_round)
        self._results_timer.daemon = True
        self._results_timer.start()

    def _begin_next_round(self) -> None:
        """Reset the table and let players bet again."""
        self._table.reset_for_next_round()
        self._broadcast()
