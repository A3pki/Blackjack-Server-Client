"""Blackjack hand: a list of cards plus value calculation."""

from __future__ import annotations

from typing import Iterable, List

from .card import Card


class Hand:
    """A collection of cards with Blackjack-aware scoring.

    Aces count as 11 unless that would bust the hand, in which case enough
    aces drop to 1 to keep the score under 22.
    """

    def __init__(self, cards: Iterable[Card] | None = None) -> None:
        self._cards: List[Card] = list(cards or [])

    @property
    def cards(self) -> List[Card]:
        return list(self._cards)

    def add(self, card: Card) -> None:
        self._cards.append(card)

    def clear(self) -> None:
        self._cards.clear()

    @property
    def value(self) -> int:
        """Best (highest non-busting) Blackjack value of this hand."""
        total = sum(c.base_value for c in self._cards)
        aces = sum(1 for c in self._cards if c.is_ace)
        # Promote aces from 1 to 11 while it's safe.
        while aces > 0 and total + 10 <= 21:
            total += 10
            aces -= 1
        return total

    @property
    def is_soft(self) -> bool:
        """A hand is 'soft' if at least one ace is currently counted as 11."""
        hard_total = sum(c.base_value for c in self._cards)
        return any(c.is_ace for c in self._cards) and hard_total + 10 <= 21

    @property
    def is_blackjack(self) -> bool:
        return len(self._cards) == 2 and self.value == 21

    @property
    def is_bust(self) -> bool:
        return self.value > 21

    def to_list(self) -> list:
        return [c.to_dict() for c in self._cards]

    def __len__(self) -> int:
        return len(self._cards)

    def __str__(self) -> str:
        return " ".join(str(c) for c in self._cards) + f" ({self.value})"
