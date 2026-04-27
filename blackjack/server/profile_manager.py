"""Persistent user profiles, stored in a JSON file.

Each profile tracks login credentials (hashed), a credit balance, and
win/loss counters used to compute the W/L ratio.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import Dict, Optional

from ..common.crypto import hash_password, verify_password

STARTING_CREDITS = 10_000
MIN_USERNAME_LEN = 3
MAX_USERNAME_LEN = 16
MIN_PASSWORD_LEN = 4
MAX_PASSWORD_LEN = 128
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


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


@dataclass
class _ProfileStore:
    """JSON document layout for the profiles file."""

    users: Dict[str, dict] = field(default_factory=dict)


class ProfileManager:
    """Thread-safe registry of :class:`UserProfile` records."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._users: Dict[str, UserProfile] = {}
        self._load()

    # --- persistence ----------------------------------------------------

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for username, data in raw.get("users", {}).items():
            self._users[username] = UserProfile(
                username=username,
                password_hash=data["password_hash"],
                credits=int(data.get("credits", STARTING_CREDITS)),
                wins=int(data.get("wins", 0)),
                losses=int(data.get("losses", 0)),
                pushes=int(data.get("pushes", 0)),
            )

    def _save_locked(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        document = _ProfileStore(
            users={u.username: asdict(u) for u in self._users.values()}
        )
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(document), f, indent=2)
        os.replace(tmp, self._path)

    # --- validation -----------------------------------------------------

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

    # --- public API -----------------------------------------------------

    def register(self, username: str, password: str) -> UserProfile:
        """Create a brand-new account and persist it."""
        self.validate_username(username)
        self.validate_password(password)
        with self._lock:
            if username in self._users:
                raise ValueError("Username already taken")
            profile = UserProfile(
                username=username,
                password_hash=hash_password(password),
            )
            self._users[username] = profile
            self._save_locked()
            return profile

    def authenticate(self, username: str, password: str) -> Optional[UserProfile]:
        """Return the profile if credentials match; ``None`` otherwise."""
        with self._lock:
            profile = self._users.get(username)
            if profile is None:
                # Still spend the time so timing doesn't leak existence.
                verify_password(password, hash_password("dummy"))
                return None
            if not verify_password(password, profile.password_hash):
                return None
            return profile

    def adjust_credits(self, username: str, delta: int) -> int:
        """Add ``delta`` (may be negative) to the user's balance and persist."""
        with self._lock:
            profile = self._require(username)
            new_balance = profile.credits + delta
            if new_balance < 0:
                raise ValueError("Insufficient credits")
            profile.credits = new_balance
            self._save_locked()
            return profile.credits

    def record_result(self, username: str, outcome: str) -> UserProfile:
        """Update W/L/Push counters; ``outcome`` in ``{"win","loss","push"}``."""
        if outcome not in ("win", "loss", "push"):
            raise ValueError(f"Unknown outcome: {outcome!r}")
        with self._lock:
            profile = self._require(username)
            if outcome == "win":
                profile.wins += 1
            elif outcome == "loss":
                profile.losses += 1
            else:
                profile.pushes += 1
            self._save_locked()
            return profile

    def get(self, username: str) -> UserProfile:
        with self._lock:
            return self._require(username)

    def _require(self, username: str) -> UserProfile:
        profile = self._users.get(username)
        if profile is None:
            raise KeyError(f"Unknown user: {username}")
        return profile
