"""Length-prefixed JSON message protocol.

Wire format
-----------

Every message on the wire is::

    [4-byte big-endian unsigned length][payload bytes]

* During the handshake the payload is **plaintext UTF-8 JSON** (so the two
  sides can agree on a session key).
* After the handshake the payload is the same UTF-8 JSON, but encrypted with
  the session :class:`~blackjack.common.crypto.SecureChannel` (Fernet).

Message envelope
----------------

Every JSON message looks like::

    {"type": "<string>", "data": {...}}

Both ``type`` and ``data`` are required. ``data`` may be an empty object.

Defined message types
---------------------

Handshake (plaintext):

* ``server_hello``     — server -> client, ``{"public_key": "<PEM>"}``
* ``key_exchange``     — client -> server, ``{"encrypted_key": "<base64>"}``
* ``ready``            — server -> client, ``{}`` (channel now encrypted)

Authentication (encrypted):

* ``register``         — client -> server, ``{"username", "password"}``
* ``login``            — client -> server, ``{"username", "password"}``
* ``auth_result``      — server -> client,
  ``{"success": bool, "message": str, "profile": {...} | None}``

Game (encrypted):

* ``lobby_state``      — server -> client, list of seated players
* ``place_bet``        — client -> server, ``{"amount": int}``
* ``action``           — client -> server, ``{"action": "hit"|"stand"|"double"}``
* ``game_state``       — server -> client, full table snapshot
* ``round_result``     — server -> client, per-player outcome + payouts
* ``chat``             — client <-> server, ``{"message": str}`` / ``{"from", "message"}``
* ``error``            — server -> client, ``{"message": str}``
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Dict, Optional

from .crypto import SecureChannel

# --- limits & schema -----------------------------------------------------

MAX_MESSAGE_BYTES = 64 * 1024  # 64 KiB hard cap per message; mitigates DoS
_LENGTH_PREFIX = struct.Struct(">I")  # 4-byte big-endian unsigned int

VALID_TYPES = {
    # handshake
    "server_hello", "key_exchange", "ready",
    # auth
    "register", "login", "auth_result", "logout",
    # game
    "lobby_state", "place_bet", "action", "game_state",
    "round_result", "chat", "error",
}


class ProtocolError(Exception):
    """Raised when a peer sends a malformed or oversized message."""


# --- low-level framed I/O ------------------------------------------------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``sock`` or raise ``ConnectionError``."""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Peer closed connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_frame(sock: socket.socket, payload: bytes) -> None:
    """Send a single length-prefixed frame."""
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Outgoing message exceeds size limit")
    sock.sendall(_LENGTH_PREFIX.pack(len(payload)) + payload)


def recv_frame(sock: socket.socket) -> bytes:
    """Receive a single length-prefixed frame."""
    header = _recv_exact(sock, _LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(header)
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"Invalid frame length: {length}")
    return _recv_exact(sock, length)


# --- JSON envelope helpers ----------------------------------------------

def _encode_message(msg_type: str, data: Optional[Dict[str, Any]]) -> bytes:
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"Unknown message type: {msg_type!r}")
    envelope = {"type": msg_type, "data": data or {}}
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def _decode_message(raw: bytes) -> Dict[str, Any]:
    try:
        envelope = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Malformed JSON: {exc}") from exc
    if not isinstance(envelope, dict):
        raise ProtocolError("Message envelope must be a JSON object")
    msg_type = envelope.get("type")
    data = envelope.get("data", {})
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"Unknown message type: {msg_type!r}")
    if not isinstance(data, dict):
        raise ProtocolError("Message 'data' must be an object")
    return {"type": msg_type, "data": data}


# --- plaintext (handshake-only) -----------------------------------------

def send_plain(sock: socket.socket, msg_type: str,
               data: Optional[Dict[str, Any]] = None) -> None:
    send_frame(sock, _encode_message(msg_type, data))


def recv_plain(sock: socket.socket) -> Dict[str, Any]:
    return _decode_message(recv_frame(sock))


# --- encrypted (post-handshake) -----------------------------------------

def send_encrypted(sock: socket.socket, channel: SecureChannel,
                   msg_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    send_frame(sock, channel.encrypt(_encode_message(msg_type, data)))


def recv_encrypted(sock: socket.socket,
                   channel: SecureChannel) -> Dict[str, Any]:
    return _decode_message(channel.decrypt(recv_frame(sock)))
