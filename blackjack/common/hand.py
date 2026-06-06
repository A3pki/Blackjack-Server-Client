"""A hand of cards with blackjack-aware scoring."""

from __future__ import annotations

from typing import Iterable, List

from .card import Card


class Hand:
    """Holds the cards for one player (or the dealer) and knows their value.

    Aces count as 11 unless that would bust, in which case they drop to 1.
    Multiple aces are handled correctly too.
    """

    def __init__(self, cards: Iterable[Card] | None = None) -> None:
        """Start with an optional list of cards (usually empty)."""
        self._cards: List[Card] = list(cards or [])

    @property
    def cards(self) -> List[Card]:
        """A copy of the card list — mutate via add() instead."""
        return list(self._cards)

    def add(self, card: Card) -> None:
        """Deal a card into this hand."""
        self._cards.append(card)

    def clear(self) -> None:
        """Discard all cards — called between rounds."""
        self._cards.clear()

    @property
    def value(self) -> int:
        """Best blackjack score for this hand — never needlessly busts on aces."""
        total = sum(c.base_value for c in self._cards)
        aces = sum(1 for c in self._cards if c.is_ace)
        # Promote aces from 1 → 11 as long as we don't bust.
        while aces > 0 and total + 10 <= 21:
            total += 10
            aces -= 1
        return total

    @property
    def is_soft(self) -> bool:
        """True when at least one ace is currently being counted as 11."""
        hard_total = sum(c.base_value for c in self._cards)
        return any(c.is_ace for c in self._cards) and hard_total + 10 <= 21

    @property
    def is_blackjack(self) -> bool:
        """Natural blackjack — exactly two cards totalling 21."""
        return len(self._cards) == 2 and self.value == 21

    @property
    def is_bust(self) -> bool:
        """Over 21, regardless of how the aces fall."""
        return self.value > 21

    def to_list(self) -> list:
        """Serialize the hand to a list of dicts for the wire protocol."""
        return [c.to_dict() for c in self._cards]

    def __len__(self) -> int:
        return len(self._cards)

    def __str__(self) -> str:
        return " ".join(str(c) for c in self._cards) + f" ({self.value})"
