"""Persistent user profiles stored in a SQLite database.

The database is created automatically on first run at the path supplied to
:class:`ProfileManager`.  A single table ``users`` holds all account data.
All public methods acquire an ``RLock`` before touching the connection so the
module is safe to call from multiple threads.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass
from typing import Optional

from ..common.crypto import hash_password, verify_password

STARTING_CREDITS = 10_000
MIN_USERNAME_LEN = 3
MAX_USERNAME_LEN = 16
MIN_PASSWORD_LEN = 4
MAX_PASSWORD_LEN = 128
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    username      TEXT    PRIMARY KEY,
    password_hash TEXT    NOT NULL,
    credits       INTEGER NOT NULL DEFAULT 10000,
    wins          INTEGER NOT NULL DEFAULT 0,
    losses        INTEGER NOT NULL DEFAULT 0,
    pushes        INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class UserProfile:
    """In-memory representation of a single player's account."""

    username: str
    password_hash: str
    credits: int = STARTING_CREDITS
    wins: int = 0
    losses: int = 0
    pushes: int = 0

    @property
    def games_played(self) -> int:
        return self.wins + self.losses + self.pushes

    @property
    def wl_ratio(self) -> float:
        if self.losses == 0:
            return float(self.wins) if self.wins else 0.0
        return self.wins / self.losses

    def to_public_dict(self) -> dict:
        """Profile fields safe to send to the client (no password hash)."""
        return {
            "username": self.username,
            "credits": self.credits,
            "wins": self.wins,
            "losses": self.losses,
            "pushes": self.pushes,
            "games_played": self.games_played,
            "wl_ratio": round(self.wl_ratio, 3),
        }


def _row_to_profile(row: tuple) -> UserProfile:
    username, password_hash, credits, wins, losses, pushes = row
    return UserProfile(
        username=username,
        password_hash=password_hash,
        credits=credits,
        wins=wins,
        losses=losses,
        pushes=pushes,
    )


class ProfileManager:
    """Thread-safe registry of :class:`UserProfile` records backed by SQLite."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.RLock()
        # check_same_thread=False because we guard all access with our own lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # --- validation -------------------------------------------------------

    @staticmethod
    def validate_username(username: str) -> None:
        if not isinstance(username, str):
            raise ValueError("Username must be a string")
        if not (MIN_USERNAME_LEN <= len(username) <= MAX_USERNAME_LEN):
            raise ValueError(
                f"Username must be {MIN_USERNAME_LEN}-{MAX_USERNAME_LEN} chars"
            )
        if not _USERNAME_RE.match(username):
            raise ValueError("Username may only contain letters, digits and _")

    @staticmethod
    def validate_password(password: str) -> None:
        if not isinstance(password, str):
            raise ValueError("Password must be a string")
        if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
            raise ValueError(
                f"Password must be {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} chars"
            )

    # --- public API -------------------------------------------------------

    def register(self, username: str, password: str) -> UserProfile:
        """Create a brand-new account and persist it to the database."""
        self.validate_username(username)
        self.validate_password(password)
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM users WHERE username = ?", (username,)
            ).fetchone()
            if existing:
                raise ValueError("Username already taken")
            ph = hash_password(password)
            self._conn.execute(
                "INSERT INTO users (username, password_hash, credits, wins, losses, pushes) "
                "VALUES (?, ?, ?, 0, 0, 0)",
                (username, ph, STARTING_CREDITS),
            )
            self._conn.commit()
            return UserProfile(username=username, password_hash=ph)

    def authenticate(self, username: str, password: str) -> Optional[UserProfile]:
        """Return the profile if credentials match; ``None`` otherwise."""
        with self._lock:
            row = self._conn.execute(
                "SELECT username, password_hash, credits, wins, losses, pushes "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                # Spend the same time so timing does not leak user existence.
                verify_password(password, hash_password("dummy"))
                return None
            profile = _row_to_profile(row)
            if not verify_password(password, profile.password_hash):
                return None
            return profile

    def adjust_credits(self, username: str, delta: int) -> int:
        """Add ``delta`` (may be negative) to the user's balance and persist."""
        with self._lock:
            row = self._conn.execute(
                "SELECT credits FROM users WHERE username = ?", (username,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown user: {username}")
            new_balance = row[0] + delta
            if new_balance < 0:
                raise ValueError("Insufficient credits")
            self._conn.execute(
                "UPDATE users SET credits = ? WHERE username = ?",
                (new_balance, username),
            )
            self._conn.commit()
            return new_balance

    def record_result(self, username: str, outcome: str) -> UserProfile:
        """Increment W/L/Push counter; ``outcome`` in ``{"win","loss","push"}``."""
        if outcome not in ("win", "loss", "push"):
            raise ValueError(f"Unknown outcome: {outcome!r}")
        col = {"win": "wins", "loss": "losses", "push": "pushes"}[outcome]
        with self._lock:
            self._conn.execute(
                f"UPDATE users SET {col} = {col} + 1 WHERE username = ?",
                (username,),
            )
            self._conn.commit()
            return self._require(username)

    def get(self, username: str) -> UserProfile:
        with self._lock:
            return self._require(username)

    # --- internal ---------------------------------------------------------

    def _require(self, username: str) -> UserProfile:
        """Fetch a profile row; raise KeyError if the user does not exist."""
        row = self._conn.execute(
            "SELECT username, password_hash, credits, wins, losses, pushes "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown user: {username}")
        return _row_to_profile(row)
