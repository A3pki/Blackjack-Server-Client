"""Cryptographic primitives used by the protocol.

Two layers are exposed:

* :class:`RSAKeyPair` — RSA-2048 key pair used by the **server** to receive
  the per-session symmetric key from each client.
* :class:`SecureChannel` — Symmetric Fernet (AES-128-CBC + HMAC-SHA256) channel
  used for every message after the handshake completes.

Password hashing uses PBKDF2-HMAC-SHA256 with a random per-user salt.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


# --- symmetric session channel ------------------------------------------

class SecureChannel:
    """Wraps a Fernet symmetric key for the lifetime of a TCP connection."""

    def __init__(self, key: bytes) -> None:
        self._key = key
        self._fernet = Fernet(key)  # raises if the key is malformed

    @classmethod
    def generate(cls) -> "SecureChannel":
        """Create a brand-new channel with a fresh random key."""
        return cls(Fernet.generate_key())

    @property
    def key(self) -> bytes:
        return self._key

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt message (invalid token)") from exc


# --- RSA key pair (server-side) -----------------------------------------

@dataclass
class RSAKeyPair:
    """Convenience wrapper around an RSA-2048 key pair."""

    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey

    @classmethod
    def generate(cls) -> "RSAKeyPair":
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return cls(private_key=priv, public_key=priv.public_key())

    @classmethod
    def load_or_create(cls, path: str) -> "RSAKeyPair":
        """Load an RSA key from ``path`` or create + persist a new one."""
        if os.path.exists(path):
            with open(path, "rb") as f:
                priv = serialization.load_pem_private_key(f.read(), password=None)
            if not isinstance(priv, rsa.RSAPrivateKey):
                raise ValueError(f"Key file {path} is not RSA")
            return cls(private_key=priv, public_key=priv.public_key())

        kp = cls.generate()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        pem = kp.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with open(path, "wb") as f:
            f.write(pem)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return kp

    def public_pem(self) -> str:
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def decrypt_session_key(self, encrypted_b64: str) -> bytes:
        """Decrypt a Fernet key sent through :func:`encrypt_session_key`."""
        ciphertext = base64.b64decode(encrypted_b64.encode("ascii"))
        return self.private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )


def encrypt_session_key(public_pem: str, session_key: bytes) -> str:
    """Encrypt a Fernet key with the server's RSA public key (PEM)."""
    public_key = serialization.load_pem_public_key(public_pem.encode("ascii"))
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise ValueError("Server public key is not RSA")
    ciphertext = public_key.encrypt(
        session_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return base64.b64encode(ciphertext).decode("ascii")


# --- password hashing ----------------------------------------------------

_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16
_HASH_BYTES = 32


def hash_password(password: str) -> str:
    """Return ``"<salt_b64>$<hash_b64>"`` for a plaintext password."""
    if not isinstance(password, str) or not password:
        raise ValueError("Password must be a non-empty string")
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt,
        _PBKDF2_ITERATIONS, dklen=_HASH_BYTES,
    )
    return (
        base64.b64encode(salt).decode("ascii")
        + "$"
        + base64.b64encode(derived).decode("ascii")
    )


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against the value returned by ``hash_password``."""
    try:
        salt_b64, hash_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt,
        _PBKDF2_ITERATIONS, dklen=len(expected),
    )
    return hmac.compare_digest(candidate, expected)
