"""Shoe / deck of cards used by the dealer."""

from __future__ import annotations

import secrets
from typing import List

from .card import Card


class Deck:
    """A multi-deck shoe.

    Uses ``secrets`` for cryptographically strong shuffling so cards cannot
    be predicted from a seeded PRNG even if the source is leaked.
    """

    def __init__(self, num_decks: int = 4) -> None:
        if num_decks < 1:
            raise ValueError("num_decks must be >= 1")
        self._num_decks = num_decks
        self._cards: List[Card] = []
        self.reshuffle()

    def reshuffle(self) -> None:
        """Rebuild the shoe and shuffle securely."""
        self._cards = [
            Card(rank=rank, suit=suit)
            for _ in range(self._num_decks)
            for suit in Card.SUITS
            for rank in Card.RANKS
        ]
        # Fisher-Yates with secrets.randbelow for unbiased secure shuffling.
        for i in range(len(self._cards) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            self._cards[i], self._cards[j] = self._cards[j], self._cards[i]

    def draw(self) -> Card:
        """Draw a single card; reshuffles automatically when low."""
        if len(self._cards) < 15:
            self.reshuffle()
        return self._cards.pop()

    def __len__(self) -> int:
        return len(self._cards)
