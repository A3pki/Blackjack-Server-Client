"""Server-side game logic: cards, bets, turns, dealer, and scoring.

Flow of a round:
  WAITING -> BETTING -> PLAYING -> DEALER -> RESULTS -> WAITING

The Table class is not thread-safe on its own — callers must hold
Table.lock before mutating anything.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from ..common.deck import Deck
from ..common.hand import Hand


class Phase(str, Enum):
    """Which stage of the round we're currently in."""
    WAITING = "waiting"   # nobody has bet yet
    BETTING = "betting"   # waiting for everyone to place a bet
    PLAYING = "playing"   # players take turns hitting/standing
    DEALER  = "dealer"    # dealer reveals + plays
    RESULTS = "results"   # short pause so everyone can see the outcome


# --- participants --------------------------------------------------------

class Participant:
    """Base for anyone holding cards at the table (player or dealer)."""

    def __init__(self, name: str) -> None:
        """Set up with a display name and an empty hand."""
        self.name = name
        self.hand = Hand()

    def reset(self) -> None:
        """Clear the hand between rounds."""
        self.hand.clear()


class Dealer(Participant):
    """The house dealer — hits on 16 or less, stands on 17 (including soft 17)."""

    def __init__(self) -> None:
        super().__init__(name="Dealer")

    def wants_card(self) -> bool:
        """True when the dealer's rules say they must keep hitting."""
        return self.hand.value < 17


class Player(Participant):
    """A human player sitting at the table."""

    def __init__(self, username: str) -> None:
        """Set up a fresh player slot for the given username."""
        super().__init__(name=username)
        self.username = username
        self.bet: int = 0
        self.has_bet: bool = False
        self.is_done: bool = False       # stood, busted, got blackjack, or doubled
        self.has_doubled: bool = False
        self.outcome: Optional[str] = None   # "win" / "loss" / "push"
        self.payout: int = 0             # credits returned at end of round

    def reset(self) -> None:
        """Wipe the hand and all round-specific state. Keep the username."""
        super().reset()
        self.bet = 0
        self.has_bet = False
        self.is_done = False
        self.has_doubled = False
        self.outcome = None
        self.payout = 0


# --- round result --------------------------------------------------------

@dataclass
class RoundResult:
    """One player's outcome from a finished round."""
    username: str
    outcome: str   # "win" / "loss" / "push"
    payout: int    # credits returned (0 on a loss)


# --- table ---------------------------------------------------------------

class Table:
    """Manages one shared blackjack table — all players, the deck, and round flow.

    The server passes in callbacks so the Table can trigger broadcasts
    without knowing about sockets or handlers directly.
    """

    MIN_BET = 50
    MAX_BET = 5_000

    def __init__(self,
                 broadcast: Callable[[], None],
                 on_round_finished: Callable[[List[RoundResult]], None]) -> None:
        """Set up an empty table. broadcast is called whenever state changes."""
        self.lock = threading.RLock()
        self._players: Dict[str, Player] = {}
        self._dealer = Dealer()
        self._deck = Deck(num_decks=4)
        self._phase: Phase = Phase.WAITING
        self._turn_order: List[str] = []
        self._turn_index: int = 0
        self._broadcast = broadcast
        self._on_round_finished = on_round_finished

    # --- accessors -------------------------------------------------------

    @property
    def phase(self) -> Phase:
        """Current phase of the round."""
        return self._phase

    def get_player(self, username: str) -> Optional[Player]:
        """Look up a player by username. Returns None if not at the table."""
        return self._players.get(username)

    def current_player(self) -> Optional[Player]:
        """Who's turn is it right now? Returns None if we're not in the PLAYING phase."""
        if self._phase != Phase.PLAYING:
            return None
        if not self._turn_order:
            return None
        return self._players.get(self._turn_order[self._turn_index])

    # --- lifecycle -------------------------------------------------------

    def add_player(self, username: str) -> Player:
        """Seat a player at the table. If mid-round they just wait for the next one."""
        with self.lock:
            if username in self._players:
                return self._players[username]
            player = Player(username)
            self._players[username] = player
            # If the table was idle, kick it into betting phase.
            if self._phase == Phase.WAITING:
                self._phase = Phase.BETTING
            return player

    def remove_player(self, username: str) -> None:
        """Remove a player who disconnected. Advances the turn if it was their go."""
        with self.lock:
            self._players.pop(username, None)
            self._turn_order = [u for u in self._turn_order if u != username]
            if not self._players:
                # Table is empty — reset everything.
                self._phase = Phase.WAITING
                self._dealer.reset()
            elif self._phase == Phase.PLAYING:
                # If the leaver was the current player, move on.
                if self._turn_index >= len(self._turn_order):
                    self._advance_turn()

    # --- betting ---------------------------------------------------------

    def place_bet(self, username: str, amount: int, balance: int) -> None:
        """Record a bet for a player.

        The server already deducted the credits before calling here.
        balance is just informational (not used by the Table itself).
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
                raise ValueError(f"Bet must be between {self.MIN_BET} and {self.MAX_BET}")
            player.bet = amount
            player.has_bet = True
            if self._phase == Phase.WAITING:
                self._phase = Phase.BETTING
            del balance  # not stored here — the server tracks balances

            if self._everyone_bet():
                self._begin_round()

    def _everyone_bet(self) -> bool:
        """True when all seated players have placed a bet."""
        return bool(self._players) and all(p.has_bet for p in self._players.values())

    # --- round flow ------------------------------------------------------

    def _begin_round(self) -> None:
        """Deal initial cards and start the playing phase."""
        self._phase = Phase.PLAYING
        self._dealer.reset()
        self._turn_order = list(self._players.keys())
        self._turn_index = 0

        # Reset hands but keep the bets that were already placed.
        for player in self._players.values():
            player.hand.clear()
            player.is_done = False
            player.has_doubled = False
            player.outcome = None
            player.payout = 0

        # Initial deal: two cards to each player, then two to the dealer.
        for _ in range(2):
            for username in self._turn_order:
                self._players[username].hand.add(self._deck.draw())
            self._dealer.hand.add(self._deck.draw())

        # Anyone who got a natural blackjack is immediately done.
        for player in self._players.values():
            if player.hand.is_blackjack:
                player.is_done = True

        # If everyone got blackjack, skip straight to the dealer phase.
        self._advance_turn()

    def _advance_turn(self) -> None:
        """Skip past any players who are already done, then run the dealer if everyone's finished."""
        while (self._turn_index < len(self._turn_order)
               and self._players[self._turn_order[self._turn_index]].is_done):
            self._turn_index += 1
        if self._turn_index >= len(self._turn_order):
            self._dealer_turn()

    def handle_action(self, username: str, action: str,
                      can_afford_double: bool) -> None:
        """Apply a hit, stand, or double action from a player.

        can_afford_double is checked by the server before calling here.
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
                    raise ValueError("You can only double on your first move")
                if not can_afford_double:
                    raise ValueError("Insufficient credits to double down")
                current.has_doubled = True
                # The server charges the extra bet — we just record it happened.
                current.bet *= 2
                current.hand.add(self._deck.draw())
                current.is_done = True
                self._turn_index += 1
            else:
                raise ValueError(f"Unknown action: {action!r}")

            self._advance_turn()

    # --- dealer phase ----------------------------------------------------

    def _dealer_turn(self) -> None:
        """Run the dealer's hand, then score everyone."""
        self._phase = Phase.DEALER
        # Only draw cards if at least one player is still alive (not busted / not BJ).
        any_alive = any(
            not p.hand.is_bust and not p.hand.is_blackjack
            for p in self._players.values()
        )
        if any_alive:
            while self._dealer.wants_card():
                self._dealer.hand.add(self._deck.draw())

        results = self._score_round()
        self._phase = Phase.RESULTS
        self._on_round_finished(results)

    def _score_round(self) -> List[RoundResult]:
        """Compare each player's hand to the dealer and build the result list."""
        dealer_val = self._dealer.hand.value
        dealer_bj  = self._dealer.hand.is_blackjack
        dealer_bust = self._dealer.hand.is_bust
        results: List[RoundResult] = []

        for player in self._players.values():
            payout = 0
            if player.hand.is_blackjack and not dealer_bj:
                outcome = "win"
                payout = int(player.bet * 2.5)  # 3:2 payout — bet returned + 1.5× bonus
            elif player.hand.is_blackjack and dealer_bj:
                outcome = "push"
                payout = player.bet
            elif player.hand.is_bust:
                outcome = "loss"
            elif dealer_bust or player.hand.value > dealer_val:
                outcome = "win"
                payout = player.bet * 2
            elif player.hand.value == dealer_val:
                outcome = "push"
                payout = player.bet
            else:
                outcome = "loss"

            player.outcome = outcome
            player.payout = payout
            results.append(RoundResult(
                username=player.username, outcome=outcome, payout=payout,
            ))
        return results

    # --- next round ------------------------------------------------------

    def reset_for_next_round(self) -> None:
        """Clear all round state so players can bet again."""
        with self.lock:
            for player in self._players.values():
                player.reset()
            self._dealer.reset()
            self._turn_order = []
            self._turn_index = 0
            self._phase = Phase.BETTING if self._players else Phase.WAITING

    # --- snapshot for clients -------------------------------------------

    def snapshot_for(self, username: str) -> dict:
        """Build the full table state from one player's point of view.

        Hides the dealer's hole card during the playing phase.
        """
        with self.lock:
            current = self.current_player()
            current_username = current.username if current else None

            # During play, show only the dealer's face-up card.
            if self._phase in (Phase.PLAYING, Phase.BETTING, Phase.WAITING):
                dealer_cards = (
                    [self._dealer.hand.cards[0].to_dict(), {"rank": "?", "suit": "?"}]
                    if len(self._dealer.hand) >= 1 else []
                )
                dealer_value = (
                    self._dealer.hand.cards[0].point_value
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
