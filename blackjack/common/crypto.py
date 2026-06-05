"""All the crypto stuff: RSA handshake, Fernet session channel, password hashing.

Two layers:
- RSAKeyPair: server uses this to receive the session key from each client.
- SecureChannel: symmetric Fernet (AES-128-CBC + HMAC-SHA256) for everything after.

Passwords use PBKDF2-HMAC-SHA256 with a random per-user salt.
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
    """Wraps a Fernet key for the lifetime of one TCP connection.

    Create one per connection after the RSA handshake.
    """

    def __init__(self, key: bytes) -> None:
        """Initialize with an existing Fernet key (32 url-safe base64 bytes)."""
        self._key = key
        self._fernet = Fernet(key)  # blows up immediately if the key is wrong

    @classmethod
    def generate(cls) -> "SecureChannel":
        """Make a brand-new channel with a fresh random key."""
        return cls(Fernet.generate_key())

    @property
    def key(self) -> bytes:
        """The raw Fernet key — only share this over the RSA-encrypted handshake."""
        return self._key

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt a message. Returns a Fernet token."""
        return self._fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        """Decrypt a Fernet token. Raises ValueError if anything looks wrong."""
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt message (bad token)") from exc


# --- RSA key pair (server-side) -----------------------------------------

@dataclass
class RSAKeyPair:
    """Server's RSA-2048 key pair — used once per connection to exchange the session key."""

    private_key: rsa.RSAPrivateKey
    public_key: rsa.RSAPublicKey

    @classmethod
    def generate(cls) -> "RSAKeyPair":
        """Generate a fresh 2048-bit RSA key pair."""
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return cls(private_key=priv, public_key=priv.public_key())

    @classmethod
    def load_or_create(cls, path: str) -> "RSAKeyPair":
        """Load the server's RSA key from disk, or generate + save a new one.

        The file gets chmod 0o600 so only the owner can read it.
        """
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
            pass  # Windows doesn't care about this anyway
        return kp

    def public_pem(self) -> str:
        """Return the public key as a PEM string to send to clients."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")

    def decrypt_session_key(self, encrypted_b64: str) -> bytes:
        """Decrypt a Fernet key that was encrypted by the client with our public key."""
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
    """Client-side: encrypt a Fernet key with the server's RSA public key.

    Returns a base64 string safe to put in JSON.
    """
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
    """Hash a password with PBKDF2-SHA256 and a random salt.

    Returns the string "salt_b64$hash_b64" that gets stored in the DB.
    """
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
    """Check a plaintext password against a stored hash — constant-time so timing attacks don't work."""
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
