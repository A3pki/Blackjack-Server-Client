"""User accounts, stored in a SQLite database.

One table, one file, thread-safe via an RLock.
The DB is created automatically on first run.
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
    """Everything we know about one player's account.

    Passed around in memory after loading from the DB.
    """

    username: str
    password_hash: str
    credits: int = STARTING_CREDITS
    wins: int = 0
    losses: int = 0
    pushes: int = 0

    @property
    def games_played(self) -> int:
        """Total hands the player has finished."""
        return self.wins + self.losses + self.pushes

    @property
    def win_loss_ratio(self) -> float:
        """Wins divided by losses — returns wins as float when losses = 0."""
        if self.losses == 0:
            return float(self.wins) if self.wins else 0.0
        return self.wins / self.losses

    def to_dict(self) -> dict:
        """Safe subset of the profile to send to the client — no password hash."""
        return {
            "username": self.username,
            "credits": self.credits,
            "wins": self.wins,
            "losses": self.losses,
            "pushes": self.pushes,
            "games_played": self.games_played,
            "wl_ratio": round(self.win_loss_ratio, 3),
        }


def _profile_from_row(row: tuple) -> UserProfile:
    """Turn a raw DB row tuple into a UserProfile object."""
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
    """Thread-safe interface to the users table in profiles.db.

    All writes go through an RLock so multiple client threads can call
    this concurrently without corrupting the database.
    """

    def __init__(self, db_path: str) -> None:
        """Open (or create) the database at db_path and make sure the table exists."""
        self._lock = threading.RLock()
        # check_same_thread=False is fine because we guard everything with our own lock.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # --- validation -------------------------------------------------------

    @staticmethod
    def validate_username(username: str) -> None:
        """Raise ValueError if the username doesn't meet the rules."""
        if not isinstance(username, str):
            raise ValueError("Username must be a string")
        if not (MIN_USERNAME_LEN <= len(username) <= MAX_USERNAME_LEN):
            raise ValueError(
                f"Username must be {MIN_USERNAME_LEN}–{MAX_USERNAME_LEN} chars"
            )
        if not _USERNAME_RE.match(username):
            raise ValueError("Username may only contain letters, digits, and _")

    @staticmethod
    def validate_password(password: str) -> None:
        """Raise ValueError if the password is too short or too long."""
        if not isinstance(password, str):
            raise ValueError("Password must be a string")
        if not (MIN_PASSWORD_LEN <= len(password) <= MAX_PASSWORD_LEN):
            raise ValueError(
                f"Password must be {MIN_PASSWORD_LEN}–{MAX_PASSWORD_LEN} chars"
            )

    # --- public API -------------------------------------------------------

    def register(self, username: str, password: str) -> UserProfile:
        """Create a new account and write it to the DB. Raises ValueError on duplicates."""
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
        """Check credentials and return the profile, or None if they don't match.

        Always takes the same amount of time whether the user exists or not,
        so an attacker can't figure out which usernames are registered.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT username, password_hash, credits, wins, losses, pushes "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                # Burn time on a fake hash so the response time doesn't leak anything.
                verify_password(password, hash_password("dummy"))
                return None
            profile = _profile_from_row(row)
            if not verify_password(password, profile.password_hash):
                return None
            return profile

    def adjust_credits(self, username: str, delta: int) -> int:
        """Add delta (negative = deduct) to the player's balance and persist it.

        Raises ValueError if the result would go below zero.
        """
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
        """Bump the win, loss, or push counter for a player after a round."""
        if outcome not in ("win", "loss", "push"):
            raise ValueError(f"Unknown outcome: {outcome!r}")
        col = {"win": "wins", "loss": "losses", "push": "pushes"}[outcome]
        with self._lock:
            self._conn.execute(
                f"UPDATE users SET {col} = {col} + 1 WHERE username = ?",
                (username,),
            )
            self._conn.commit()
            return self._fetch(username)

    def get(self, username: str) -> UserProfile:
        """Fetch a player's profile. Raises KeyError if they don't exist."""
        with self._lock:
            return self._fetch(username)

    # --- internal ---------------------------------------------------------

    def _fetch(self, username: str) -> UserProfile:
        """Load a profile row from the DB, raising KeyError if not found."""
        row = self._conn.execute(
            "SELECT username, password_hash, credits, wins, losses, pushes "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown user: {username}")
        return _profile_from_row(row)
