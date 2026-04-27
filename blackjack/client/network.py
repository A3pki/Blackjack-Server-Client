"""Client-side networking layer.

Spawns one background thread that reads encrypted messages from the server
and forwards them to a callback (typically into the Tk event loop).
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Callable, Optional

from ..common import protocol
from ..common.crypto import SecureChannel, encrypt_session_key
from ..common.protocol import ProtocolError

log = logging.getLogger(__name__)


class BlackjackClient:
    """Encrypted JSON-message client."""

    def __init__(self,
                 host: str,
                 port: int,
                 on_message: Callable[[str, dict], None],
                 on_disconnect: Callable[[Optional[str]], None]) -> None:
        self._host = host
        self._port = port
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._sock: Optional[socket.socket] = None
        self._channel: Optional[SecureChannel] = None
        self._send_lock = threading.Lock()
        self._recv_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # --- connection ----------------------------------------------------

    def connect(self) -> None:
        sock = socket.create_connection((self._host, self._port), timeout=10)
        sock.settimeout(None)
        self._sock = sock
        self._handshake()
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="ClientRecv", daemon=True,
        )
        self._recv_thread.start()

    def _handshake(self) -> None:
        assert self._sock is not None
        msg = protocol.recv_plain(self._sock)
        if msg["type"] != "server_hello":
            raise ProtocolError("Expected server_hello")
        public_pem = msg["data"].get("public_key")
        if not isinstance(public_pem, str):
            raise ProtocolError("server_hello missing public_key")
        # Generate a fresh session key and ship it back encrypted with the
        # server's RSA public key.
        self._channel = SecureChannel.generate()
        encrypted_b64 = encrypt_session_key(public_pem, self._channel.key)
        protocol.send_plain(self._sock, "key_exchange",
                            {"encrypted_key": encrypted_b64})
        ready = protocol.recv_encrypted(self._sock, self._channel)
        if ready["type"] != "ready":
            raise ProtocolError("Expected 'ready' after key exchange")

    # --- send / recv ---------------------------------------------------

    def send(self, msg_type: str, data: Optional[dict] = None) -> None:
        if self._sock is None or self._channel is None:
            raise RuntimeError("Not connected")
        with self._send_lock:
            protocol.send_encrypted(self._sock, self._channel, msg_type, data or {})

    def _recv_loop(self) -> None:
        assert self._sock is not None and self._channel is not None
        reason: Optional[str] = None
        try:
            while not self._stop_event.is_set():
                msg = protocol.recv_encrypted(self._sock, self._channel)
                self._on_message(msg["type"], msg["data"])
        except (ConnectionError, ProtocolError, OSError, ValueError) as exc:
            reason = str(exc)
            log.info("Disconnected from server: %s", exc)
        finally:
            self._on_disconnect(reason)

    def close(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                self._sock.close()
            except OSError:
                pass
