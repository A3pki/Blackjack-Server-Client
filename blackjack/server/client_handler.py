"""One of these runs per connected client — owns the socket and the session key."""

from __future__ import annotations

import logging
import socket
import threading
from typing import TYPE_CHECKING, Optional

from ..common import protocol
from ..common.crypto import RSAKeyPair, SecureChannel
from ..common.protocol import ProtocolError
from .chat_moderator import ChatModerator
from .profile_manager import ProfileManager, UserProfile

if TYPE_CHECKING:
    from .server import BlackjackServer

log = logging.getLogger(__name__)

# One shared moderator for the whole server process.
_moderator = ChatModerator()


class ClientHandler(threading.Thread):
    """Handles all communication for a single connected client.

    Runs its own daemon thread. Sends are protected by a lock so both the
    receive loop and game callbacks can push messages safely at the same time.
    """

    def __init__(self, sock: socket.socket, addr,
                 server: "BlackjackServer",
                 keypair: RSAKeyPair,
                 profiles: ProfileManager) -> None:
        """Set up the handler. Call start() to kick off the thread."""
        super().__init__(name=f"Client-{addr[1]}", daemon=True)
        self._sock = sock
        self._addr = addr
        self._server = server
        self._keypair = keypair
        self._profiles = profiles
        self._channel: Optional[SecureChannel] = None
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self.profile: Optional[UserProfile] = None

    # --- public helpers used by the server ------------------------------

    @property
    def is_logged_in(self) -> bool:
        """True once the player has authenticated successfully."""
        return self.profile is not None

    @property
    def username(self) -> Optional[str]:
        """The logged-in username, or None if not yet authenticated."""
        return self.profile.username if self.profile else None

    def send(self, msg_type: str, data: Optional[dict] = None) -> None:
        """Send an encrypted message — safe to call from any thread."""
        if self._channel is None:
            raise RuntimeError("Channel not established yet")
        try:
            with self._send_lock:
                protocol.send_encrypted(
                    self._sock, self._channel, msg_type, data or {},
                )
        except (OSError, ProtocolError) as exc:
            log.debug("send to %s failed: %s", self._addr, exc)
            self.shutdown()

    def shutdown(self) -> None:
        """Close the socket and let the thread exit cleanly."""
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass

    # --- thread main ---------------------------------------------------

    def run(self) -> None:
        """Entry point for the client thread — handshake then message loop."""
        try:
            self._handshake()
            self._message_loop()
        except (ConnectionError, ProtocolError) as exc:
            log.info("Client %s disconnected: %s", self._addr, exc)
        except Exception:
            log.exception("Unhandled error for client %s", self._addr)
        finally:
            self._cleanup()

    # --- handshake -----------------------------------------------------

    def _handshake(self) -> None:
        """RSA key exchange — ends with both sides on the same Fernet key."""
        protocol.send_plain(self._sock, "server_hello",
                            {"public_key": self._keypair.public_pem()})
        msg = protocol.recv_plain(self._sock)
        if msg["type"] != "key_exchange":
            raise ProtocolError("Expected key_exchange from client")
        encrypted_key = msg["data"].get("encrypted_key")
        if not isinstance(encrypted_key, str):
            raise ProtocolError("Missing encrypted_key in key_exchange")
        session_key = self._keypair.decrypt_session_key(encrypted_key)
        self._channel = SecureChannel(session_key)
        # From here on, everything is encrypted.
        protocol.send_encrypted(self._sock, self._channel, "ready", {})
        log.info("Handshake complete with %s", self._addr)

    # --- main message loop --------------------------------------------

    def _message_loop(self) -> None:
        """Read incoming messages and route them until the connection drops."""
        assert self._channel is not None
        while not self._stop_event.is_set():
            try:
                msg = protocol.recv_encrypted(self._sock, self._channel)
            except (ConnectionError, ProtocolError):
                raise
            try:
                self._handle(msg["type"], msg["data"])
            except ValueError as exc:
                # Game rule / validation errors — tell the client but stay connected.
                self.send("error", {"message": str(exc)})

    def _handle(self, msg_type: str, data: dict) -> None:
        """Route an incoming message to the right handler method."""
        if msg_type == "register":
            self._on_register(data)
        elif msg_type == "login":
            self._on_login(data)
        elif msg_type == "place_bet":
            self._must_be_logged_in()
            self._server.on_bet(self, int(data.get("amount", 0)))
        elif msg_type == "action":
            self._must_be_logged_in()
            self._server.on_action(self, str(data.get("action", "")))
        elif msg_type == "chat":
            self._must_be_logged_in()
            text = str(data.get("message", "")).strip()
            if text:
                text = text[:200]  # cap length before sending to AI
                allowed, reason = _moderator.check(text)
                if not allowed:
                    self.send("error", {"message": reason})
                else:
                    self._server.on_chat(self, text)
        elif msg_type == "logout":
            self._must_be_logged_in()
            self.shutdown()
        else:
            raise ValueError(f"Unsupported message type: {msg_type!r}")

    def _must_be_logged_in(self) -> None:
        """Raise ValueError if the client tries to do anything before logging in."""
        if not self.is_logged_in:
            raise ValueError("You must be logged in to do that")

    def _on_register(self, data: dict) -> None:
        """Handle a register request — create an account and log the player in."""
        if self.is_logged_in:
            raise ValueError("Already logged in")
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        try:
            profile = self._profiles.register(username, password)
        except ValueError as exc:
            self.send("auth_result", {"success": False, "message": str(exc)})
            return
        self.profile = profile
        self.send("auth_result", {
            "success": True,
            "message": "Account created",
            "profile": profile.to_dict(),
        })
        self._server.on_player_joined(self)

    def _on_login(self, data: dict) -> None:
        """Handle a login request — authenticate and seat the player."""
        if self.is_logged_in:
            raise ValueError("Already logged in")
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        try:
            ProfileManager.validate_username(username)
            ProfileManager.validate_password(password)
        except ValueError as exc:
            self.send("auth_result", {"success": False, "message": str(exc)})
            return
        profile = self._profiles.authenticate(username, password)
        if profile is None:
            self.send("auth_result", {
                "success": False, "message": "Invalid username or password",
            })
            return
        if self._server.is_online(username):
            self.send("auth_result", {
                "success": False, "message": "User already logged in elsewhere",
            })
            return
        self.profile = profile
        self.send("auth_result", {
            "success": True,
            "message": f"Welcome back, {profile.username}!",
            "profile": profile.to_dict(),
        })
        self._server.on_player_joined(self)

    # --- cleanup -------------------------------------------------------

    def _cleanup(self) -> None:
        """Close the socket and tell the server this client is gone."""
        try:
            self._sock.close()
        except OSError:
            pass
        self._server.on_player_left(self)
