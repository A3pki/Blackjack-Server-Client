"""Playing card abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Card:
    """A single playing card.

    Cards are immutable value objects: equality and hashing rely on
    ``rank`` and ``suit`` only.
    """

    SUITS: ClassVar[tuple[str, ...]] = ("S", "H", "D", "C")
    RANKS: ClassVar[tuple[str, ...]] = (
        "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K",
    )

    rank: str
    suit: str

    def __post_init__(self) -> None:
        if self.rank not in Card.RANKS:
            raise ValueError(f"Invalid rank: {self.rank!r}")
        if self.suit not in Card.SUITS:
            raise ValueError(f"Invalid suit: {self.suit!r}")

    @property
    def base_value(self) -> int:
        """Blackjack base value (Ace counted as 1 here; Hand handles soft 11)."""
        if self.rank == "A":
            return 1
        if self.rank in ("J", "Q", "K"):
            return 10
        return int(self.rank)

    @property
    def is_ace(self) -> bool:
        return self.rank == "A"

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit}

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"
