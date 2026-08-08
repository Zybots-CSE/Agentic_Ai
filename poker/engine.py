# No-Limit Texas Hold'em engine — multi-player (2-10), no blinds.

import csv
import itertools
import random
from collections import Counter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STARTING_STACK = 50_000
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))  # 2..14, Ace = 14

STREETS = ("preflop", "flop", "turn", "river")
STATUS_ACTIVE = "active"
STATUS_FOLDED = "folded"
STATUS_ALL_IN = "all_in"


def build_deck():
    """Return a full 52-card deck as a list of (suit, rank) tuples."""
    return [(s, r) for s in SUITS for r in RANKS]


def card_str(card):
    """Human-readable string for a card tuple, e.g. ('H', 14) -> 'AH'."""
    rank_names = {14: "A", 13: "K", 12: "Q", 11: "J"}
    r = rank_names.get(card[1], str(card[1]))
    return f"{r}{card[0]}"


def _hand_str(hand):
    return " ".join(card_str(c) for c in sorted(hand, key=lambda c: (c[0], c[1])))


def action_str(action):
    kind = action[0]
    if kind in ("fold", "check", "call"):
        return kind
    if kind == "bet":
        return f"bet {action[1]}"
    if kind == "raise":
        return f"raise to {action[1]}"
    return str(action)


# ---------------------------------------------------------------------------
# Hand evaluation
# ---------------------------------------------------------------------------
def _straight_high(ranks):
    """Return top rank of a straight, or None. Supports ace-low wheel."""
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    unique = sorted(set(unique), reverse=True)
    for i in range(len(unique) - 4):
        window = unique[i : i + 5]
        if window[0] - window[4] == 4:
            return window[0]
    return None


def _evaluate_five(cards):
    """Comparable tuple for five cards; higher is better."""
    ranks = sorted((c[1] for c in cards), reverse=True)
    suits = [c[0] for c in cards]
    counts = Counter(ranks)
    by_freq = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(ranks)

    if is_flush and straight_high:
        return (8, straight_high)

    if by_freq[0][1] == 4:
        return (6, by_freq[0][0], by_freq[1][0])

    if by_freq[0][1] == 3 and by_freq[1][1] == 2:
        return (5, by_freq[0][0], by_freq[1][0])

    if is_flush:
        return (4, *ranks)

    if straight_high:
        return (3, straight_high)

    if by_freq[0][1] == 3:
        trips = by_freq[0][0]
        kickers = [r for r in ranks if r != trips]
        return (2, trips, *kickers)

    if by_freq[0][1] == 2 and by_freq[1][1] == 2:
        hi, lo = max(by_freq[0][0], by_freq[1][0]), min(by_freq[0][0], by_freq[1][0])
        kicker = [r for r in ranks if r not in (hi, lo)][0]
        return (1, hi, lo, kicker)

    if by_freq[0][1] == 2:
        pair = by_freq[0][0]
        kickers = [r for r in ranks if r != pair]
        return (0, pair, *kickers)

    return (-1, *ranks)


def evaluate_best_hand(hole, board):
    """Best 5-card hand from hole + board cards."""
    all_cards = list(hole) + list(board)
    best = None
    for combo in itertools.combinations(all_cards, 5):
        score = _evaluate_five(combo)
        if best is None or score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# PlayerView
# ---------------------------------------------------------------------------
class PlayerView:
    """Read-only game state visible to the acting player."""

    def __init__(
        self,
        your_name,
        your_hole_cards,
        community_cards,
        your_stack,
        player_stacks,
        player_status,
        seat_order,
        dealer,
        action_on,
        street,
        pot,
        amount_to_call,
        min_raise_to,
        hand_number,
        action_history,
        hand_history=None,
    ):
        self.your_name = your_name
        self.your_hole_cards = list(your_hole_cards)
        self.community_cards = list(community_cards)
        self.your_stack = your_stack
        self.player_stacks = dict(player_stacks)
        self.player_status = dict(player_status)
        self.seat_order = list(seat_order)
        self.dealer = dealer
        self.action_on = action_on
        self.street = street
        self.pot = pot
        self.amount_to_call = amount_to_call
        self.min_raise_to = min_raise_to
        self.hand_number = hand_number
        self.action_history = list(action_history)
        self.hand_history = list(hand_history) if hand_history is not None else []


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------
class GameState:
    def __init__(self, seat_order, hand_number, dealer, hand_history=None):
        self.seat_order = list(seat_order)
        self.hand_number = hand_number
        self.dealer = dealer
        self.deck = []
        self.hole_cards = {name: [] for name in seat_order}
        self.board = []
        self.street = "preflop"
        self.stacks = {name: STARTING_STACK for name in seat_order}
        self.street_wager = {name: 0 for name in seat_order}
        self.total_committed = {name: 0 for name in seat_order}
        self.status = {name: STATUS_ACTIVE for name in seat_order}
        self.current_bet_level = 0
        self.last_raise_size = 0
        self.action_on = None
        self.pending_actors = set()
        self.action_history = []
        self.hand_history = hand_history if hand_history is not None else []

    def seat_after(self, player, n=1):
        idx = self.seat_order.index(player)
        for _ in range(n):
            idx = (idx + 1) % len(self.seat_order)
        return self.seat_order[idx]

    def active_players(self):
        return [p for p in self.seat_order if self.status[p] != STATUS_FOLDED]

    def contenders(self):
        return [p for p in self.seat_order if self.status[p] in (STATUS_ACTIVE, STATUS_ALL_IN)]

    def can_act(self, player):
        return self.status[player] == STATUS_ACTIVE and self.stacks[player] > 0

    def pot_total(self):
        return sum(self.total_committed.values())

    def amount_to_call(self, player):
        return max(0, self.current_bet_level - self.street_wager[player])

    def make_player_view(self, player):
        min_raise = None
        to_call = self.amount_to_call(player)
        if to_call > 0 and self.can_act(player):
            min_to = _min_raise_to(self, player)
            max_to = self.street_wager[player] + self.stacks[player]
            if min_to <= max_to:
                min_raise = min_to
        return PlayerView(
            your_name=player,
            your_hole_cards=self.hole_cards[player],
            community_cards=self.board,
            your_stack=self.stacks[player],
            player_stacks=dict(self.stacks),
            player_status=dict(self.status),
            seat_order=self.seat_order,
            dealer=self.dealer,
            action_on=self.action_on,
            street=self.street,
            pot=self.pot_total(),
            amount_to_call=to_call,
            min_raise_to=min_raise,
            hand_number=self.hand_number,
            action_history=self.action_history,
            hand_history=self.hand_history,
        )


# ---------------------------------------------------------------------------
# Betting helpers
# ---------------------------------------------------------------------------
def _min_raise_to(gs, player):
    if gs.last_raise_size > 0:
        return gs.current_bet_level + gs.last_raise_size
    if gs.current_bet_level > 0:
        return gs.current_bet_level * 2
    return gs.street_wager[player] + 1


def _first_actor(gs):
    player = gs.dealer
    for _ in range(len(gs.seat_order)):
        if gs.can_act(player):
            return player
        player = gs.seat_after(player)
    return None


def _start_betting_round(gs):
    gs.street_wager = {name: 0 for name in gs.seat_order}
    gs.current_bet_level = 0
    gs.last_raise_size = 0
    gs.action_history = []
    gs.pending_actors = {p for p in gs.seat_order if gs.can_act(p)}
    gs.action_on = _first_actor(gs)


def _put_chips(gs, player, amount):
    amount = min(amount, gs.stacks[player])
    if amount <= 0:
        return 0
    gs.stacks[player] -= amount
    gs.street_wager[player] += amount
    gs.total_committed[player] += amount
    if gs.stacks[player] == 0:
        gs.status[player] = STATUS_ALL_IN
    return amount


def _reopen_after_aggression(gs, aggressor):
    gs.pending_actors = set()
    for p in gs.seat_order:
        if p != aggressor and gs.can_act(p):
            gs.pending_actors.add(p)


def legal_actions(gs, player):
    if not gs.can_act(player):
        return []
    actions = [("fold",)]
    to_call = gs.amount_to_call(player)
    stack = gs.stacks[player]

    if to_call == 0:
        actions.append(("check",))
        bet_amounts = {1, stack, max(1, stack // 2)}
        for amount in sorted(bet_amounts):
            if 1 <= amount <= stack:
                actions.append(("bet", amount))
        return actions

    actions.append(("call",))
    if stack > to_call:
        min_to = _min_raise_to(gs, player)
        max_to = gs.street_wager[player] + stack
        if min_to <= max_to:
            actions.append(("raise", min_to))
            if max_to > min_to:
                actions.append(("raise", max_to))
    return actions


def _action_is_legal(gs, player, action):
    if action in legal_actions(gs, player):
        return True
    kind = action[0]
    if kind == "bet" and len(action) == 2:
        amount = action[1]
        return gs.amount_to_call(player) == 0 and 1 <= amount <= gs.stacks[player]
    if kind == "raise" and len(action) == 2:
        to_total = action[1]
        if gs.amount_to_call(player) == 0:
            return False
        min_to = _min_raise_to(gs, player)
        max_to = gs.street_wager[player] + gs.stacks[player]
        return min_to <= to_total <= max_to
    return False


def apply_action(gs, player, action):
    kind = action[0]
    if kind == "fold":
        gs.status[player] = STATUS_FOLDED
        gs.pending_actors.discard(player)
        return True

    if kind == "check":
        gs.pending_actors.discard(player)
        return True

    if kind == "call":
        _put_chips(gs, player, gs.amount_to_call(player))
        gs.pending_actors.discard(player)
        return True

    if kind == "bet":
        prev_level = gs.current_bet_level
        _put_chips(gs, player, action[1])
        gs.current_bet_level = gs.street_wager[player]
        gs.last_raise_size = gs.current_bet_level - prev_level
        _reopen_after_aggression(gs, player)
        return True

    if kind == "raise":
        prev_level = gs.current_bet_level
        additional = action[1] - gs.street_wager[player]
        _put_chips(gs, player, additional)
        gs.current_bet_level = gs.street_wager[player]
        gs.last_raise_size = gs.current_bet_level - prev_level
        _reopen_after_aggression(gs, player)
        return True

    return False


def _return_uncalled_bets(gs):
    contenders = gs.contenders()
    if len(contenders) <= 1:
        return
    matched = min(gs.street_wager[p] for p in contenders)
    for p in gs.seat_order:
        excess = gs.street_wager[p] - matched
        if excess > 0:
            gs.stacks[p] += excess
            gs.street_wager[p] -= excess
            gs.total_committed[p] -= excess
    gs.current_bet_level = matched


def betting_round_complete(gs):
    if len(gs.active_players()) <= 1:
        return True
    if gs.pending_actors:
        return False
    for p in gs.active_players():
        if gs.can_act(p) and gs.street_wager[p] < gs.current_bet_level:
            return False
    return True


def _advance_action(gs):
    if betting_round_complete(gs):
        return
    player = gs.action_on
    for _ in range(len(gs.seat_order)):
        player = gs.seat_after(player)
        if player in gs.pending_actors:
            gs.action_on = player
            return
    gs.action_on = None


def _run_betting_round(gs, funcs, logger):
    """Run one betting street. Returns True if hand should end early."""
    _start_betting_round(gs)
    while not betting_round_complete(gs):
        if len(gs.active_players()) <= 1:
            return True
        player = gs.action_on
        if player is None or player not in gs.pending_actors:
            _advance_action(gs)
            continue
        action = _get_move(gs, player, funcs[player], logger)
        if action is None:
            action = ("fold",)
        gs.action_history.append((player, action))
        apply_action(gs, player, action)
        logger.log_action(player, action, gs)
        if len(gs.active_players()) <= 1:
            return True
        _advance_action(gs)
    _return_uncalled_bets(gs)
    return len(gs.active_players()) <= 1


# ---------------------------------------------------------------------------
# Pots and showdown
# ---------------------------------------------------------------------------
def _build_pots(gs):
    contributors = {
        p: gs.total_committed[p]
        for p in gs.seat_order
        if gs.total_committed[p] > 0
    }
    if not contributors:
        return []

    levels = sorted(set(contributors.values()))
    pots = []
    prev = 0
    for level in levels:
        layer_players = [p for p, c in contributors.items() if c >= level]
        layer_amount = (level - prev) * len(layer_players)
        eligible = [p for p in layer_players if gs.status[p] in (STATUS_ACTIVE, STATUS_ALL_IN)]
        if layer_amount > 0:
            pots.append((layer_amount, eligible))
        prev = level
    return pots


def _winners_clockwise_from_dealer(gs, players):
    ordered = []
    player = gs.dealer
    for _ in range(len(gs.seat_order)):
        if player in players:
            ordered.append(player)
        player = gs.seat_after(player)
    return ordered


def _award_amount(gs, amount, winners):
    if not winners or amount <= 0:
        return {}
    share, remainder = divmod(amount, len(winners))
    order = _winners_clockwise_from_dealer(gs, winners)
    payouts = {p: 0 for p in gs.seat_order}
    for p in winners:
        payouts[p] += share
    for i in range(remainder):
        payouts[order[i % len(order)]] += 1
    for p, amt in payouts.items():
        gs.stacks[p] += amt
    return payouts


def _best_contenders(gs, players):
    scores = {p: evaluate_best_hand(gs.hole_cards[p], gs.board) for p in players}
    best = max(scores.values())
    return [p for p, s in scores.items() if s == best]


def resolve_showdown(gs, logger):
    """Award all pots at showdown."""
    reveals = {p: list(gs.hole_cards[p]) for p in gs.contenders()}
    logger.log_showdown(reveals)
    pots = _build_pots(gs)
    all_winners = []
    for amount, eligible in pots:
        if not eligible:
            continue
        if len(eligible) == 1:
            winners = eligible
        else:
            winners = _best_contenders(gs, eligible)
        _award_amount(gs, amount, winners)
        all_winners.extend(winners)
        logger.log_pot_award(amount, winners)
    gs.total_committed = {name: 0 for name in gs.seat_order}
    return reveals, all_winners


def award_uncontested_pot(gs, logger):
    """Single remaining player wins all committed chips."""
    active = gs.active_players()
    if len(active) != 1:
        return None
    winner = active[0]
    amount = gs.pot_total()
    gs.stacks[winner] += amount
    gs.total_committed = {name: 0 for name in gs.seat_order}
    logger.log_uncontested(winner, amount)
    return winner


# ---------------------------------------------------------------------------
# playHand
# ---------------------------------------------------------------------------
def playHand(players, logger, hand_number, hand_history=None):
    """Play one NLHE hand. Returns {player_name: ending_stack}."""
    if hand_history is None:
        hand_history = []
    seat_order = sorted(players.keys())
    dealer_idx = (hand_number - 1) % len(seat_order)
    dealer = seat_order[dealer_idx]
    funcs = players
    gs = GameState(seat_order, hand_number, dealer, hand_history=hand_history)

    deck = build_deck()
    random.shuffle(deck)
    for name in seat_order:
        gs.hole_cards[name] = [deck.pop(), deck.pop()]

    logger.log_deal(gs)

    board_counts = {"flop": 3, "turn": 1, "river": 1}
    street_actions = {}

    for street in STREETS:
        gs.street = street
        if street != "preflop":
            deck.pop()  # burn
            new_cards = [deck.pop() for _ in range(board_counts[street])]
            gs.board.extend(new_cards)
            logger.log_board(street, gs.board)

        hand_over = _run_betting_round(gs, funcs, logger)
        street_actions[street] = list(gs.action_history)
        if hand_over:
            break

    showdown = None
    uncontested_winner = None
    if len(gs.active_players()) == 1:
        uncontested_winner = award_uncontested_pot(gs, logger)
    else:
        showdown, _winners = resolve_showdown(gs, logger)

    ending = {name: gs.stacks[name] for name in seat_order}
    logger.log_hand_scores(ending)
    hand_history.append(
        {
            "hand_number": hand_number,
            "dealer": dealer,
            "seat_order": list(seat_order),
            "actions": street_actions,
            "board": list(gs.board),
            "showdown": showdown,
            "uncontested_winner": uncontested_winner,
            "ending_stacks": dict(ending),
        }
    )
    return ending


# ---------------------------------------------------------------------------
# Move pipeline
# ---------------------------------------------------------------------------
def _get_move(gs, player, func, logger):
    view = gs.make_player_view(player)
    try:
        action = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    if not isinstance(action, tuple) or not action:
        logger.log_error(player, f"invalid action {action!r}")
        return None

    if not _action_is_legal(gs, player, action):
        logger.log_error(player, f"illegal action {action_str(action)}")
        return None

    return action


# ---------------------------------------------------------------------------
# GameLogger
# ---------------------------------------------------------------------------
class GameLogger:
    """Buffered logger for a poker tournament."""

    def __init__(self, filepath):
        self.filepath = filepath
        self._lines = []

    def start_hand(self, hand_number):
        self._lines.append(f"\n{'='*60}")
        self._lines.append(f"Hand {hand_number}")
        self._lines.append(f"{'='*60}")

    def log_deal(self, gs):
        self._lines.append(f"Dealer: {gs.dealer}")
        self._lines.append(f"Seats: {', '.join(gs.seat_order)}")
        for name in gs.seat_order:
            self._lines.append(
                f"  {name}: stack {gs.stacks[name]}  hole {_hand_str(gs.hole_cards[name])}"
            )

    def log_board(self, street, board):
        self._lines.append(
            f"  {street}: {' '.join(card_str(c) for c in board)}"
        )

    def log_action(self, player, action, gs):
        self._lines.append(
            f"  [{gs.street}] {player}: {action_str(action)} "
            f"(pot {gs.pot_total()})"
        )

    def log_showdown(self, reveals):
        self._lines.append("  Showdown:")
        for name, cards in reveals.items():
            self._lines.append(f"    {name}: {_hand_str(cards)}")

    def log_pot_award(self, amount, winners):
        names = ", ".join(winners)
        self._lines.append(f"  Pot {amount} -> {names}")

    def log_uncontested(self, winner, amount):
        self._lines.append(f"  Uncontested pot {amount} -> {winner}")

    def log_hand_scores(self, ending_stacks):
        parts = [f"{n}={ending_stacks[n]}" for n in sorted(ending_stacks)]
        self._lines.append(f"  End stacks: {', '.join(parts)}")

    def log_error(self, player, message):
        self._lines.append(f"  ERROR ({player}): {message}")

    def flush(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._lines) + "\n")

    @staticmethod
    def write_leaderboard_csv(filepath, scores):
        rows = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player", "score"])
            for name, score in rows:
                writer.writerow([name, f"{score:.1f}"])
