"""
Champion No-Limit Texas Hold'em Bot (No-Blinds Engine)
------------------------------------------------------
Features:
- Monte Carlo Equity Engine (correct N-way tie splitting)
- No-Blinds Free-Flop Exploitation
- Pot Odds & Expected Value (EV) Decision Matrix
- Opponent Tendency Profiling from Hand History (actually wired in)
- Strict Time-Budget & Exception Protection Guardrails

Assumptions about the engine's API (verify these against your actual
engine and adjust if they don't hold):
- `hole` / `board` cards are (suit, rank) tuples, suit in {"H","D","C","S"},
  rank an int 2-14, matching FULL_DECK below.
- `gameState.min_raise_to` is the minimum legal amount you can bet/raise TO,
  and applies to opening bets as well as raises. If your engine exposes a
  separate minimum for *opening* action, swap it in inside `_size_wager`.
- `gameState.amount_to_call` is already clamped to your stack (i.e. you're
  never asked to "call" an amount bigger than what you have). If that's not
  true for your engine, the call branch below needs to send an explicit
  all-in amount instead of a bare ("call",) tuple.
"""

import random
import sys
import time
import itertools
from collections import Counter

# ---------------------------------------------------------------------------
# Hand Evaluation Core
# ---------------------------------------------------------------------------
def _straight_high(ranks):
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)  # wheel: A-2-3-4-5
    unique = sorted(set(unique), reverse=True)
    for i in range(len(unique) - 4):
        if unique[i] - unique[i + 4] == 4:
            return unique[i]
    return None


def _eval_5card(cards):
    ranks = sorted((c[1] for c in cards), reverse=True)
    suits = [c[0] for c in cards]
    counts = Counter(ranks)
    by_freq = sorted(counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
    is_flush = len(set(suits)) == 1
    st_high = _straight_high(ranks)

    if is_flush and st_high:
        return (8, st_high)
    if by_freq[0][1] == 4:
        return (6, by_freq[0][0], by_freq[1][0])
    if by_freq[0][1] == 3 and by_freq[1][1] == 2:
        return (5, by_freq[0][0], by_freq[1][0])
    if is_flush:
        return (4, *ranks)
    if st_high:
        return (3, st_high)
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


def evaluate_best_7(hole, board):
    all_cards = list(hole) + list(board)
    if len(all_cards) < 5:
        # Every call site in this module always simulates out to a full 7
        # cards, so this shouldn't trigger in practice. Fail loudly instead
        # of silently returning None if something upstream changes.
        raise ValueError(f"evaluate_best_7 needs >=5 cards, got {len(all_cards)}")
    best = None
    for combo in itertools.combinations(all_cards, 5):
        score = _eval_5card(combo)
        if best is None or score > best:
            best = score
    return best

# ---------------------------------------------------------------------------
# Monte Carlo Equity Engine
# ---------------------------------------------------------------------------
ALL_SUITS = ["H", "D", "C", "S"]
ALL_RANKS = list(range(2, 15))
FULL_DECK = [(s, r) for s in ALL_SUITS for r in ALL_RANKS]


def estimate_equity(hole, board, num_opponents, num_sims=500, max_time=0.8):
    """
    Simulates random runouts to calculate equity (win% + fair share of ties).
    Respects a hard execution time limit.
    """
    if num_opponents <= 0:
        return 1.0

    known_cards = set(hole) | set(board)
    remaining_deck = [c for c in FULL_DECK if c not in known_cards]
    cards_needed_board = 5 - len(board)

    # Bound how many opponents we actually simulate so random.sample() can
    # never be asked for more cards than exist in the deck (large fields +
    # a nearly-full board could otherwise raise ValueError, which the
    # caller's except-block would silently interpret as "always fold").
    max_simmable_opps = max(1, (len(remaining_deck) - cards_needed_board) // 2)
    sim_opponents = min(num_opponents, max_simmable_opps)

    cards_needed_opps = 2 * sim_opponents
    total_needed = cards_needed_board + cards_needed_opps
    if total_needed > len(remaining_deck) or total_needed < 0:
        return 0.5  # Degenerate state — refuse to guess.

    equity_sum = 0.0
    sims_done = 0
    start_time = time.time()

    for _ in range(num_sims):
        if time.time() - start_time > max_time:
            break

        sample = random.sample(remaining_deck, total_needed)
        sim_board = list(board) + sample[:cards_needed_board]

        my_score = evaluate_best_7(hole, sim_board)

        opp_scores = []
        idx = cards_needed_board
        for _ in range(sim_opponents):
            opp_hole = sample[idx: idx + 2]
            idx += 2
            opp_scores.append(evaluate_best_7(opp_hole, sim_board))

        all_scores = [my_score] + opp_scores
        best_score = max(all_scores)
        if my_score == best_score:
            # Split equity fairly across N-way ties instead of assuming a
            # heads-up 50/50 split whenever we're not strictly best.
            winners = all_scores.count(best_score)
            equity_sum += 1.0 / winners

        sims_done += 1

    if sims_done == 0:
        return 0.5
    return equity_sum / sims_done

# ---------------------------------------------------------------------------
# Opponent Profiling
# ---------------------------------------------------------------------------
def analyze_opponents(hand_history):
    """
    Analyzes public hand history to estimate global field aggression.
    Returns an estimated fold frequency in [0.2, 0.8] (higher = folds more).
    """
    if not hand_history:
        return 0.4  # Neutral default

    folds = 0
    bets_faced = 0

    for hand in hand_history[-20:]:
        for street, actions in hand.get("actions", {}).items():
            for name, act in actions:
                kind = act[0]
                if kind in ("bet", "raise"):
                    bets_faced += 1
                elif kind == "fold":
                    folds += 1

    if bets_faced == 0:
        return 0.4
    return min(0.8, max(0.2, folds / bets_faced))

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
VALUE_BET_EQUITY = 0.65
SEMIBLUFF_EQUITY = 0.50
VALUE_BET_POT_FRAC = 0.6
SEMIBLUFF_POT_FRAC = 0.33

PREFLOP_SNAP_FOLD_STACK_FRAC = 0.05   # "significant bet" threshold preflop
MIN_PAIR_RANK_TO_CONTINUE = 7          # 77+ continues vs. a big preflop bet
MIN_SUITED_KICKER = 8                  # both cards must clear this rank

SAFETY_MARGIN = 0.05
RAISE_EQUITY_EDGE = 0.20
RAISE_SMALL_MULT = 1.5
RAISE_BIG_MULT = 2.5
RAISE_BIG_EQUITY = 0.85


def _size_wager(raw_size, min_raise, stack):
    """
    Clamp a proposed wager so it's never below the table minimum (when
    known) and never above our remaining stack — so we never send an
    illegally tiny "bet" when the pot is 0, and never wager more than we
    have. If the stack itself is below the minimum, this correctly produces
    an all-in-for-less rather than an illegal amount.
    """
    size = max(int(raw_size), 1)
    if min_raise:
        size = max(size, min_raise)
    return min(size, stack)

# ---------------------------------------------------------------------------
# Main Policy Decision Loop
# ---------------------------------------------------------------------------
def nextMove(gameState):
    """
    Main entry point invoked by engine.
    Must return a legal action tuple within the timeout window.
    """
    try:
        hole = gameState.your_hole_cards
        board = gameState.community_cards
        stack = gameState.your_stack
        to_call = gameState.amount_to_call
        pot = gameState.pot
        min_raise = gameState.min_raise_to
        street = gameState.street
        hand_history = getattr(gameState, "hand_history", [])

        active_opponents = [
            p for p in gameState.seat_order
            if p != gameState.your_name and gameState.player_status[p] in ("active", "all_in")
        ]
        num_opps = max(1, len(active_opponents))

        fold_freq = analyze_opponents(hand_history)

        # -----------------------------------------------------------
        # Rule 1: Free flops (to_call == 0)
        # -----------------------------------------------------------
        if to_call == 0:
            equity = estimate_equity(hole, board, num_opps, num_sims=400)

            # Opponents who fold a lot make thin bets more profitable;
            # opponents who rarely fold make them less so. Nudge the
            # semi-bluff bar by up to +/-0.05 based on observed field fold
            # frequency (0.4 is the neutral default -> no adjustment).
            semibluff_threshold = SEMIBLUFF_EQUITY + (0.4 - fold_freq) * 0.125

            if equity > VALUE_BET_EQUITY:
                bet_size = _size_wager(pot * VALUE_BET_POT_FRAC, min_raise, stack)
                if bet_size > 0:
                    return ("bet", bet_size)

            elif equity > semibluff_threshold and street != "preflop":
                bet_size = _size_wager(pot * SEMIBLUFF_POT_FRAC, min_raise, stack)
                if bet_size > 0:
                    return ("bet", bet_size)

            return ("check",)

        # -----------------------------------------------------------
        # Rule 2: Facing a bet (to_call > 0)
        # -----------------------------------------------------------
        # No blinds means folding costs nothing, so snap-fold trash facing
        # a significant preflop bet rather than spending time on Monte Carlo.
        if street == "preflop" and to_call > stack * PREFLOP_SNAP_FOLD_STACK_FRAC:
            ranks = sorted((c[1] for c in hole), reverse=True)
            is_pair = ranks[0] == ranks[1] and ranks[0] >= MIN_PAIR_RANK_TO_CONTINUE
            is_high = ranks[0] >= 11 and ranks[1] >= 10
            is_suited = (
                hole[0][0] == hole[1][0]
                and ranks[0] >= 10
                and ranks[1] >= MIN_SUITED_KICKER
            )

            if not (is_pair or is_high or is_suited):
                return ("fold",)

        num_sims = 600 if street in ("turn", "river") else 400
        equity = estimate_equity(hole, board, num_opps, num_sims=num_sims)

        # If to_call exceeds our stack, side-pot rules mean we can only ever
        # risk our stack (an all-in call for less) — pot odds must be based
        # on what we actually put in, not the nominal to_call, or short
        # stacks will look artificially unprofitable and fold too much.
        effective_call = min(to_call, stack)
        pot_odds = (
            effective_call / (pot + effective_call)
            if (pot + effective_call) > 0 else 0.5
        )
        req_equity = pot_odds + SAFETY_MARGIN

        # Premium equity -> raise
        if (
            equity > req_equity + RAISE_EQUITY_EDGE
            and min_raise is not None
            and min_raise > to_call     # a "raise" must exceed the call
            and min_raise <= stack
        ):
            mult = RAISE_SMALL_MULT if equity < RAISE_BIG_EQUITY else RAISE_BIG_MULT
            target_raise = int(min_raise * mult)
            target_raise = max(min_raise, min(target_raise, stack))
            return ("raise", target_raise)

        # Positive EV -> call. Assumes the engine caps amount_to_call at our
        # stack (see module docstring); if not, this must send an explicit
        # all-in amount instead of a bare ("call",).
        if equity >= req_equity:
            return ("call",)

        # Negative EV -> fold, costs 0 chips in a no-blinds game
        return ("fold",)

    except Exception as exc:
        # Log so real bugs aren't silently invisible, then fall back safely
        # using getattr so a malformed/partial gameState can't throw again.
        print(f"[nextMove] falling back after error: {exc!r}", file=sys.stderr)
        if getattr(gameState, "amount_to_call", 0) == 0:
            return ("check",)
        return ("fold",)
