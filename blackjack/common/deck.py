"""Multi-deck shoe of cards used at the table."""

from __future__ import annotations

import secrets
from typing import List

from .card import Card


class Deck:
    """A shoe made of multiple standard decks shuffled together.

    Uses the secrets module for shuffling so the order can't be predicted
    even if someone somehow knows the RNG state — overkill, but why not.
    """

    def __init__(self, num_decks: int = 4) -> None:
        """Create a shoe with the given number of decks (default 4)."""
        if num_decks < 1:
            raise ValueError("num_decks must be >= 1")
        self._num_decks = num_decks
        self._cards: List[Card] = []
        self.shuffle()

    def shuffle(self) -> None:
        """Rebuild the shoe from scratch and shuffle it.

        Called automatically on init and whenever cards run low.
        """
        self._cards = [
            Card(rank=rank, suit=suit)
            for _ in range(self._num_decks)
            for suit in Card.SUITS
            for rank in Card.RANKS
        ]
        # Fisher-Yates with secrets.randbelow — cryptographically unbiased.
        for i in range(len(self._cards) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            self._cards[i], self._cards[j] = self._cards[j], self._cards[i]

    def draw(self) -> Card:
        """Pull the top card. Reshuffles automatically when the shoe runs low."""
        if len(self._cards) < 15:
            self.shuffle()
        return self._cards.pop()

    def __len__(self) -> int:
        return len(self._cards)
