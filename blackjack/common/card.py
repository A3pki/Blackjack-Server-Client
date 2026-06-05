"""A single playing card — rank + suit, immutable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True)
class Card:
    """One card in the deck.

    Frozen dataclass so cards are hashable and you can't accidentally
    mutate them once dealt.
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
    def point_value(self) -> int:
        """Raw blackjack value — aces count as 1 here; Hand bumps them to 11."""
        if self.rank == "A":
            return 1
        if self.rank in ("J", "Q", "K"):
            return 10
        return int(self.rank)

    @property
    def is_ace(self) -> bool:
        """True if this card is an ace."""
        return self.rank == "A"

    def to_dict(self) -> dict:
        """Serialize to a plain dict for sending over the wire."""
        return {"rank": self.rank, "suit": self.suit}

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        """Reconstruct a Card from a dict (e.g. received from the server)."""
        return cls(rank=str(data["rank"]), suit=str(data["suit"]))

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"
