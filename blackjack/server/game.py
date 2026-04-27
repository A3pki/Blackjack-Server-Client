"""Server-side Blackjack game state machine.

Concepts
--------

* :class:`Participant` — base class for anyone holding cards (player / dealer).
* :class:`Player` — a seated user with a hand, bet and outcome.
* :class:`Dealer` — the house; subclasses :class:`Participant`.
* :class:`Game` — orchestrates a single round across all seated players.
* :class:`Table` — coordinates rounds, manages players joining / leaving,
  collects bets, and runs the round when everyone is ready.

Phases of a round
-----------------

``WAITING`` -> ``BETTING`` -> ``PLAYING`` -> ``DEALER`` -> ``RESULTS`` -> ``WAITING``

The :class:`Table` is **not** thread-safe on its own; callers (the server)
must hold ``Table.lock`` for any mutation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from ..common.deck import Deck
from ..common.hand import Hand


class Phase(str, Enum):
    WAITING = "waiting"     # round not started
    BETTING = "betting"     # waiting for everyone to place a bet
    PLAYING = "playing"     # players take turns
    DEALER = "dealer"       # dealer reveals + plays
    RESULTS = "results"     # short pause to display outcomes


# --- participants --------------------------------------------------------

class Participant:
    """Base class for anyone holding a Blackjack hand."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.hand = Hand()

    def reset(self) -> None:
        self.hand.clear()


class Dealer(Participant):
    """The house dealer; hits on 16, stands on 17 (including soft 17)."""

    def __init__(self) -> None:
        super().__init__(name="Dealer")

    def should_hit(self) -> bool:
        return self.hand.value < 17


class Player(Participant):
    """A seated human player."""

    def __init__(self, username: str) -> None:
        super().__init__(name=username)
        self.username = username
        self.bet: int = 0
        self.has_bet: bool = False
        self.is_done: bool = False           # stood / busted / blackjack / doubled
        self.has_doubled: bool = False
        self.outcome: Optional[str] = None   # "win" / "loss" / "push" / "blackjack"
        self.payout: int = 0                 # total credits returned (bet + winnings)

    def reset(self) -> None:
        super().reset()
        self.bet = 0
        self.has_bet = False
        self.is_done = False
        self.has_doubled = False
        self.outcome = None
        self.payout = 0


# --- table & round orchestration ----------------------------------------

@dataclass
class _PendingResult:
    username: str
    outcome: str
    payout: int  # total credits returned to the user


class Table:
    """A single Blackjack table shared by all currently logged-in clients."""

    MIN_BET = 50
    MAX_BET = 5_000
    BETTING_AUTOSTART_DELAY = 0.0  # round starts as soon as everyone has bet

    def __init__(self,
                 broadcast: Callable[[], None],
                 on_round_finished: Callable[[List[_PendingResult]], None]) -> None:
        self.lock = threading.RLock()
        self._players: Dict[str, Player] = {}
        self._dealer = Dealer()
        self._deck = Deck(num_decks=4)
        self._phase: Phase = Phase.WAITING
        self._turn_order: List[str] = []
        self._turn_index: int = 0
        self._broadcast = broadcast
        self._on_round_finished = on_round_finished

    # --- accessors ------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def get_player(self, username: str) -> Optional[Player]:
        return self._players.get(username)

    def current_player(self) -> Optional[Player]:
        if self._phase != Phase.PLAYING:
            return None
        if not self._turn_order:
            return None
        return self._players.get(self._turn_order[self._turn_index])

    # --- lifecycle ------------------------------------------------------

    def add_player(self, username: str) -> Player:
        with self.lock:
            if username in self._players:
                return self._players[username]
            player = Player(username)
            self._players[username] = player
            # If we're mid-round, the new player simply waits for the next one.
            if self._phase == Phase.WAITING:
                self._phase = Phase.BETTING
            return player

    def remove_player(self, username: str) -> None:
        with self.lock:
            self._players.pop(username, None)
            self._turn_order = [u for u in self._turn_order if u != username]
            if not self._players:
                self._phase = Phase.WAITING
                self._dealer.reset()
            else:
                # If the leaving player was current, advance turn.
                if self._phase == Phase.PLAYING:
                    if self._turn_index >= len(self._turn_order):
                        self._maybe_finish_player_phase()

    # --- betting --------------------------------------------------------

    def place_bet(self, username: str, amount: int, balance: int) -> None:
        """Record a bet for ``username``.

        ``balance`` is the player's *current* credit balance (after the bet
        has already been deducted by the caller).
        """
        with self.lock:
            if self._phase not in (Phase.BETTING, Phase.WAITING):
                raise ValueError("Bets are only accepted before the round starts")
            player = self._players.get(username)
            if player is None:
                raise KeyError("Player not at table")
            if player.has_bet:
                raise ValueError("You already placed a bet for this round")
            if not (self.MIN_BET <= amount <= self.MAX_BET):
                raise ValueError(
                    f"Bet must be between {self.MIN_BET} and {self.MAX_BET}"
                )
            player.bet = amount
            player.has_bet = True
            if self._phase == Phase.WAITING:
                self._phase = Phase.BETTING
            del balance  # the value is recorded by the server, not the table

            if self._all_bets_in():
                self._start_round_locked()

    def _all_bets_in(self) -> bool:
        return bool(self._players) and all(p.has_bet for p in self._players.values())

    # --- round flow -----------------------------------------------------

    def _start_round_locked(self) -> None:
        self._phase = Phase.PLAYING
        self._dealer.reset()
        self._turn_order = list(self._players.keys())
        self._turn_index = 0

        # Reset hands but keep bets.
        for player in self._players.values():
            player.hand.clear()
            player.is_done = False
            player.has_doubled = False
            player.outcome = None
            player.payout = 0

        # Initial deal: two cards per player, then dealer.
        for _ in range(2):
            for username in self._turn_order:
                self._players[username].hand.add(self._deck.draw())
            self._dealer.hand.add(self._deck.draw())

        # Auto-resolve naturals: a player with blackjack is immediately done.
        for player in self._players.values():
            if player.hand.is_blackjack:
                player.is_done = True

        # If everyone got blackjack we skip straight to dealer phase.
        self._maybe_finish_player_phase()

    def _maybe_finish_player_phase(self) -> None:
        # Advance turn index past anyone already done.
        while (self._turn_index < len(self._turn_order)
               and self._players[self._turn_order[self._turn_index]].is_done):
            self._turn_index += 1
        if self._turn_index >= len(self._turn_order):
            self._run_dealer_locked()

    def player_action(self, username: str, action: str,
                      can_afford_double: bool) -> None:
        """Apply a player action.

        ``can_afford_double`` is supplied by the server and reflects whether
        the user has enough free credits to double down.
        """
        with self.lock:
            if self._phase != Phase.PLAYING:
                raise ValueError("It is not the playing phase")
            current = self.current_player()
            if current is None or current.username != username:
                raise ValueError("It is not your turn")

            if action == "hit":
                current.hand.add(self._deck.draw())
                if current.hand.is_bust or current.hand.value == 21:
                    current.is_done = True
                    self._turn_index += 1
            elif action == "stand":
                current.is_done = True
                self._turn_index += 1
            elif action == "double":
                if len(current.hand) != 2:
                    raise ValueError("You can only double on the first move")
                if not can_afford_double:
                    raise ValueError("Insufficient credits to double down")
                current.has_doubled = True
                # Caller (server) is responsible for actually charging the
                # extra bet against the user's account; we just remember it.
                current.bet *= 2
                current.hand.add(self._deck.draw())
                current.is_done = True
                self._turn_index += 1
            else:
                raise ValueError(f"Unknown action: {action!r}")

            self._maybe_finish_player_phase()

    # --- dealer ---------------------------------------------------------

    def _run_dealer_locked(self) -> None:
        self._phase = Phase.DEALER
        # Only play out the dealer if at least one player isn't busted.
        any_alive = any(
            (not p.hand.is_bust) and (not p.hand.is_blackjack)
            for p in self._players.values()
        )
        # We still reveal naturals even if no one is alive -> always play
        # at least once so the second card is "shown".
        if any_alive:
            while self._dealer.should_hit():
                self._dealer.hand.add(self._deck.draw())

        results = self._resolve_locked()
        self._phase = Phase.RESULTS
        self._on_round_finished(results)

    def _resolve_locked(self) -> List[_PendingResult]:
        dealer_value = self._dealer.hand.value
        dealer_bj = self._dealer.hand.is_blackjack
        dealer_bust = self._dealer.hand.is_bust
        results: List[_PendingResult] = []
        for player in self._players.values():
            payout = 0
            if player.hand.is_blackjack and not dealer_bj:
                outcome = "win"
                payout = int(player.bet * 2.5)  # 1:1 + 1.5x bonus = 2.5x bet returned
            elif player.hand.is_blackjack and dealer_bj:
                outcome = "push"
                payout = player.bet
            elif player.hand.is_bust:
                outcome = "loss"
            elif dealer_bust or player.hand.value > dealer_value:
                outcome = "win"
                payout = player.bet * 2
            elif player.hand.value == dealer_value:
                outcome = "push"
                payout = player.bet
            else:
                outcome = "loss"
            player.outcome = outcome
            player.payout = payout
            results.append(_PendingResult(
                username=player.username, outcome=outcome, payout=payout,
            ))
        return results

    # --- prepare next round --------------------------------------------

    def prepare_next_round(self) -> None:
        with self.lock:
            for player in self._players.values():
                player.reset()
            self._dealer.reset()
            self._turn_order = []
            self._turn_index = 0
            self._phase = Phase.BETTING if self._players else Phase.WAITING

    # --- snapshot for clients ------------------------------------------

    def snapshot_for(self, username: str) -> dict:
        """Return the table state from ``username``'s point of view."""
        with self.lock:
            current = self.current_player()
            current_username = current.username if current else None

            # Hide dealer's hole card during the playing phase.
            if self._phase in (Phase.PLAYING, Phase.BETTING, Phase.WAITING):
                dealer_cards = (
                    [self._dealer.hand.cards[0].to_dict(), {"rank": "?", "suit": "?"}]
                    if len(self._dealer.hand) >= 1 else []
                )
                dealer_value = (
                    self._dealer.hand.cards[0].base_value
                    if len(self._dealer.hand) >= 1 else 0
                )
                dealer_value_hidden = True
            else:
                dealer_cards = self._dealer.hand.to_list()
                dealer_value = self._dealer.hand.value
                dealer_value_hidden = False

            players_view = []
            for p in self._players.values():
                players_view.append({
                    "username": p.username,
                    "is_self": p.username == username,
                    "bet": p.bet,
                    "has_bet": p.has_bet,
                    "is_done": p.is_done,
                    "has_doubled": p.has_doubled,
                    "outcome": p.outcome,
                    "payout": p.payout,
                    "cards": p.hand.to_list(),
                    "value": p.hand.value,
                    "is_blackjack": p.hand.is_blackjack,
                    "is_bust": p.hand.is_bust,
                })
            return {
                "phase": self._phase.value,
                "min_bet": self.MIN_BET,
                "max_bet": self.MAX_BET,
                "current_username": current_username,
                "dealer": {
                    "cards": dealer_cards,
                    "value": dealer_value,
                    "value_hidden": dealer_value_hidden,
                    "is_blackjack": (
                        self._dealer.hand.is_blackjack
                        and self._phase in (Phase.DEALER, Phase.RESULTS)
                    ),
                    "is_bust": (
                        self._dealer.hand.is_bust
                        and self._phase in (Phase.DEALER, Phase.RESULTS)
                    ),
                },
                "players": players_view,
            }
