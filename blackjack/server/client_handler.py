"""Per-connection thread that handles a single client."""

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

_moderator = ChatModerator()


class ClientHandler(threading.Thread):
    """One of these runs per connected client.

    The handler owns the socket and the per-connection :class:`SecureChannel`.
    Sends are serialized with a per-handler lock so the game thread and the
    receive loop can both push messages safely.
    """

    def __init__(self, sock: socket.socket, addr,
                 server: "BlackjackServer",
                 keypair: RSAKeyPair,
                 profiles: ProfileManager) -> None:
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

    # --- public helpers used by the server -----------------------------

    @property
    def is_authenticated(self) -> bool:
        return self.profile is not None

    @property
    def username(self) -> Optional[str]:
        return self.profile.username if self.profile else None

    def send(self, msg_type: str, data: Optional[dict] = None) -> None:
        """Send an encrypted message; safe to call from any thread."""
        if self._channel is None:
            raise RuntimeError("Channel not yet established")
        try:
            with self._send_lock:
                protocol.send_encrypted(
                    self._sock, self._channel, msg_type, data or {},
                )
        except (OSError, ProtocolError) as exc:
            log.debug("send to %s failed: %s", self._addr, exc)
            self.shutdown()

    def shutdown(self) -> None:
        """Close the socket and stop the thread."""
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
        try:
            self._handshake()
            self._main_loop()
        except (ConnectionError, ProtocolError) as exc:
            log.info("Client %s disconnected: %s", self._addr, exc)
        except Exception:
            log.exception("Unhandled error in client handler %s", self._addr)
        finally:
            self._cleanup()

    # --- handshake -----------------------------------------------------

    def _handshake(self) -> None:
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
        # Now switch to the encrypted channel for the rest of the conversation.
        protocol.send_encrypted(self._sock, self._channel, "ready", {})
        log.info("Handshake complete with %s", self._addr)

    # --- main message loop --------------------------------------------

    def _main_loop(self) -> None:
        assert self._channel is not None
        while not self._stop_event.is_set():
            try:
                msg = protocol.recv_encrypted(self._sock, self._channel)
            except (ConnectionError, ProtocolError):
                raise
            try:
                self._dispatch(msg["type"], msg["data"])
            except ValueError as exc:
                # Validation / game-rule errors -> reportable to the client.
                self.send("error", {"message": str(exc)})

    def _dispatch(self, msg_type: str, data: dict) -> None:
        if msg_type == "register":
            self._handle_register(data)
        elif msg_type == "login":
            self._handle_login(data)
        elif msg_type == "place_bet":
            self._require_auth()
            self._server.handle_place_bet(self, int(data.get("amount", 0)))
        elif msg_type == "action":
            self._require_auth()
            action = str(data.get("action", ""))
            self._server.handle_action(self, action)
        elif msg_type == "chat":
            self._require_auth()
            text = str(data.get("message", "")).strip()
            if text:
                text = text[:200]
                allowed, reason = _moderator.check(text)
                if not allowed:
                    self.send("error", {"message": reason})
                else:
                    self._server.handle_chat(self, text)
        elif msg_type == "logout":
            self._require_auth()
            self.shutdown()
        else:
            raise ValueError(f"Unsupported message type: {msg_type!r}")

    def _require_auth(self) -> None:
        if not self.is_authenticated:
            raise ValueError("You must be logged in to do that")

    def _handle_register(self, data: dict) -> None:
        if self.is_authenticated:
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
            "profile": profile.to_public_dict(),
        })
        self._server.on_client_authenticated(self)

    def _handle_login(self, data: dict) -> None:
        if self.is_authenticated:
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
        if self._server.is_username_online(username):
            self.send("auth_result", {
                "success": False, "message": "User already logged in elsewhere",
            })
            return
        self.profile = profile
        self.send("auth_result", {
            "success": True,
            "message": f"Welcome back, {profile.username}!",
            "profile": profile.to_public_dict(),
        })
        self._server.on_client_authenticated(self)

    # --- cleanup -------------------------------------------------------

    def _cleanup(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
        self._server.on_client_disconnected(self)
