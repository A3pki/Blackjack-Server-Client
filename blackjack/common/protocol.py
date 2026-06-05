"""Wire protocol: length-prefixed JSON frames, optionally encrypted.

Every message on the wire looks like:
    [4-byte big-endian length][payload bytes]

During the handshake the payload is plain UTF-8 JSON.
After the handshake the payload is that same JSON, but Fernet-encrypted.

Every JSON message is an envelope:
    {"type": "<string>", "data": {...}}

Message types
-------------
Handshake (plain):
  server_hello  — server -> client  {"public_key": "<PEM>"}
  key_exchange  — client -> server  {"encrypted_key": "<b64>"}
  ready         — server -> client  {}

Auth (encrypted):
  register      — client -> server  {"username", "password"}
  login         — client -> server  {"username", "password"}
  auth_result   — server -> client  {"success", "message", "profile"|null}

Game (encrypted):
  lobby_state   — server -> client  list of seated players
  place_bet     — client -> server  {"amount": int}
  action        — client -> server  {"action": "hit"|"stand"|"double"}
  game_state    — server -> client  full table snapshot
  round_result  — server -> client  per-player outcome + payouts
  chat          — both ways         {"message"} / {"from", "message"}
  error         — server -> client  {"message": str}
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Dict, Optional

from .crypto import SecureChannel

# 64 KiB hard cap per message — keeps a misbehaving client from eating all our RAM
MAX_MESSAGE_BYTES = 64 * 1024
_LEN_PREFIX = struct.Struct(">I")  # 4-byte big-endian unsigned int

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
    """Raised when a peer sends something malformed, oversized, or unexpected."""


# --- low-level framed I/O ------------------------------------------------

def _read_exactly(sock: socket.socket, n: int) -> bytes:
    """Keep reading from the socket until we have exactly n bytes."""
    chunks: list[bytes] = []
    remaining = n
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("Peer closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_frame(sock: socket.socket, payload: bytes) -> None:
    """Send a length-prefixed frame down the socket."""
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Outgoing message is too large")
    sock.sendall(_LEN_PREFIX.pack(len(payload)) + payload)


def recv_frame(sock: socket.socket) -> bytes:
    """Read one length-prefixed frame from the socket."""
    header = _read_exactly(sock, _LEN_PREFIX.size)
    (length,) = _LEN_PREFIX.unpack(header)
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ProtocolError(f"Bad frame length: {length}")
    return _read_exactly(sock, length)


# --- JSON envelope helpers ----------------------------------------------

def _pack(msg_type: str, data: Optional[Dict[str, Any]]) -> bytes:
    """Serialize a message envelope to UTF-8 JSON bytes."""
    if msg_type not in VALID_TYPES:
        raise ProtocolError(f"Unknown message type: {msg_type!r}")
    envelope = {"type": msg_type, "data": data or {}}
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def _unpack(raw: bytes) -> Dict[str, Any]:
    """Parse a raw frame back into {type, data}. Raises ProtocolError on garbage."""
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
        raise ProtocolError("Message 'data' must be a JSON object")
    return {"type": msg_type, "data": data}


# --- plaintext (handshake only) -----------------------------------------

def send_plain(sock: socket.socket, msg_type: str,
               data: Optional[Dict[str, Any]] = None) -> None:
    """Send a plaintext (unencrypted) frame — handshake only."""
    send_frame(sock, _pack(msg_type, data))


def recv_plain(sock: socket.socket) -> Dict[str, Any]:
    """Receive a plaintext frame — handshake only."""
    return _unpack(recv_frame(sock))


# --- encrypted (post-handshake) -----------------------------------------

def send_encrypted(sock: socket.socket, channel: SecureChannel,
                   msg_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    """Encrypt and send a message on the established session channel."""
    send_frame(sock, channel.encrypt(_pack(msg_type, data)))


def recv_encrypted(sock: socket.socket,
                   channel: SecureChannel) -> Dict[str, Any]:
    """Receive and decrypt a message from the session channel."""
    return _unpack(channel.decrypt(recv_frame(sock)))
