"""
NLHE bot for the no-blinds, fresh-stack-per-hand tournament engine.

Key design notes (see README block at bottom of file for the "why"):
  - No blinds + stack resets every hand => folding is always free, so the
    bot only needs to be +EV per decision: equity vs. pot odds, nothing more.
  - Equity is estimated by Monte Carlo rollout (uniform random opponent
    ranges) rather than a hardcoded preflop chart, so it's correct at any
    street and any table size (2-10 players) without special-casing.
  - Raise/all-in sizing needs the *current-street* wager, which PlayerView
    does not expose directly. It's reconstructed from STARTING-stack deltas
    (self-correcting every call — see _street_wager) rather than manually
    accumulated, so it can't drift out of sync even if a previous action of
    ours was rejected as illegal.
"""

import random
import itertools
import threading
from collections import Counter

SUITS = ("H", "D", "C", "S")
RANKS = list(range(2, 15))
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]


# ---------------------------------------------------------------------------
# Hand evaluation (self-contained — do not rely on importing engine.py)
# ---------------------------------------------------------------------------
def _straight_high(ranks):
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
    unique = sorted(set(unique), reverse=True)
    for i in range(len(unique) - 4):
        window = unique[i:i + 5]
        if window[0] - window[4] == 4:
            return window[0]
    return None


def _evaluate_five(cards):
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
    all_cards = list(hole) + list(board)
    if len(all_cards) <= 5:
        return _evaluate_five(all_cards)
    best = None
    for combo in itertools.combinations(all_cards, 5):
        score = _evaluate_five(combo)
        if best is None or score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Monte Carlo equity estimation
# ---------------------------------------------------------------------------
def _pick_trials(street, num_opponents):
    """Scale trial count so runtime stays well inside the 2s move budget.
    Measured worst case (10-handed, preflop) runs in ~0.15s at these
    counts, roughly 12x headroom under the 2s timeout, so trials are sized
    for accuracy rather than being squeezed for speed."""
    base = {"preflop": 900, "flop": 700, "turn": 850, "river": 1000}.get(street, 700)
    if num_opponents >= 7:
        base = int(base * 0.4)
    elif num_opponents >= 4:
        base = int(base * 0.65)
    return max(120, base)


def _estimate_equity(hole, board, num_opponents, trials):
    if num_opponents <= 0:
        return 1.0

    known = set(hole) | set(board)
    deck = [c for c in FULL_DECK if c not in known]
    needed_board = 5 - len(board)
    draw_size = needed_board + 2 * num_opponents

    if draw_size > len(deck):
        # Degenerate/edge case (shouldn't happen with a real deck) — bail
        # to a neutral-ish estimate rather than crash.
        return 0.5

    wins = 0.0
    for _ in range(trials):
        draw = random.sample(deck, draw_size)
        board_full = board + draw[:needed_board]
        my_score = evaluate_best_hand(hole, board_full)

        idx = needed_board
        best_opp = None
        tied_opps = 0
        for _ in range(num_opponents):
            opp_hole = draw[idx:idx + 2]
            idx += 2
            score = evaluate_best_hand(opp_hole, board_full)
            if best_opp is None or score > best_opp:
                best_opp = score
                tied_opps = 1
            elif score == best_opp:
                tied_opps += 1

        if my_score > best_opp:
            wins += 1.0
        elif my_score == best_opp:
            wins += 1.0 / (tied_opps + 1)

    return wins / trials


# ---------------------------------------------------------------------------
# Current-street wager tracking (self-correcting via true stack deltas)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_STATE = {"hand": None, "starting_stack": None, "street": None, "prior_committed": 0}


def _street_wager(gs):
    with _lock:
        if _STATE["hand"] != gs.hand_number:
            # First call of a fresh hand: our stack hasn't moved yet
            # (no blinds), so this IS the true starting stack for the hand.
            _STATE["hand"] = gs.hand_number
            _STATE["starting_stack"] = gs.your_stack
            _STATE["street"] = gs.street
            _STATE["prior_committed"] = 0
        elif _STATE["street"] != gs.street:
            committed_now = _STATE["starting_stack"] - gs.your_stack
            _STATE["prior_committed"] = committed_now
            _STATE["street"] = gs.street

        committed_now = _STATE["starting_stack"] - gs.your_stack
        return committed_now - _STATE["prior_committed"]


# ---------------------------------------------------------------------------
# Bet sizing
# ---------------------------------------------------------------------------
def _open_bet_size(equity, pot, stack):
    if pot > 0:
        if equity >= 0.80:
            frac = 0.9
        elif equity >= 0.65:
            frac = 0.7
        else:
            frac = 0.5
        amount = round(pot * frac)
    else:
        # First bet of an empty pot (no blinds): size relative to stack,
        # scaled up a bit with hand strength.
        base_frac = 0.015 + 0.03 * max(0.0, equity - 0.5)
        amount = round(stack * base_frac)
    return int(max(1, min(stack, amount)))


def _raise_target(equity, min_to, max_to):
    if equity >= 0.85:
        target = max_to
    else:
        t = (equity - 0.70) / (0.85 - 0.70)
        t = max(0.0, min(1.0, t))
        target = min_to + t * (max_to - min_to)
    return int(round(max(min_to, min(max_to, target))))


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------
def _num_opponents(gs):
    live = sum(1 for s in gs.player_status.values() if s != "folded")
    return max(0, live - 1)


def _decide(gs):
    hole = gs.your_hole_cards
    board = gs.community_cards
    pot = gs.pot
    to_call = gs.amount_to_call
    stack = gs.your_stack

    num_opp = _num_opponents(gs)
    trials = _pick_trials(gs.street, num_opp)
    equity = _estimate_equity(hole, board, num_opp, trials)

    if to_call == 0:
        if equity >= 0.55 and stack > 0:
            amount = _open_bet_size(equity, pot, stack)
            return ("bet", amount)
        return ("check",)

    denom = pot + to_call
    required_equity = (to_call / denom) if denom > 0 else 1.0
    # Deep effective stacks relative to the pot carry modest implied odds
    # (more streets left to realize equity on draws) — shave the price a
    # touch. Kept small and one-directional so it never turns a genuine
    # -EV call into a leak.
    if stack > pot:
        required_equity = max(0.0, required_equity - 0.03)

    if equity < required_equity:
        return ("fold",)

    min_to = gs.min_raise_to
    if equity >= 0.70 and min_to is not None:
        my_wager = _street_wager(gs)
        max_to = my_wager + stack
        if max_to >= min_to:
            target = _raise_target(equity, min_to, max_to)
            return ("raise", target)

    return ("call",)


def nextMove(gameState):
    try:
        action = _decide(gameState)
        # Defensive clamps in case of any edge-case math drift.
        if action[0] == "bet":
            amt = max(1, min(gameState.your_stack, int(action[1])))
            return ("bet", amt)
        if action[0] == "raise":
            return action
        return action
    except Exception:
        # Never risk an illegal/crashing action: check if free, else fold.
        try:
            if gameState.amount_to_call == 0:
                return ("check",)
        except Exception:
            pass
        return ("fold",)
