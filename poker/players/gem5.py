"""
Champion No-Limit Texas Hold'em Bot (No-Blinds Engine)
------------------------------------------------------
Features:
- Fast vectorized-style Monte Carlo Equity Engine
- No-Blinds Free-Flop Exploitation
- Pot Odds & Expected Value (EV) Decision Matrix
- Opponent Tendency Profiling from Hand History
- Strict Time-Budget & Exception Protection Guardrails
"""

import random
import time
import itertools
from collections import Counter

# ---------------------------------------------------------------------------
# Hand Evaluation Core (Fast internal implementation)
# ---------------------------------------------------------------------------
def _straight_high(ranks):
    unique = sorted(set(ranks), reverse=True)
    if 14 in unique:
        unique.append(1)
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
    Simulates random runouts to calculate equity (win% + 0.5 * tie%).
    Respects a hard execution time limit.
    """
    if num_opponents <= 0:
        return 1.0

    known_cards = set(hole) | set(board)
    remaining_deck = [c for c in FULL_DECK if c not in known_cards]
    cards_needed_board = 5 - len(board)
    cards_needed_opps = 2 * num_opponents
    total_needed = cards_needed_board + cards_needed_opps

    wins = 0
    ties = 0
    sims_done = 0

    start_time = time.time()

    for _ in range(num_sims):
        if time.time() - start_time > max_time:
            break

        sample = random.sample(remaining_deck, total_needed)
        sim_board = list(board) + sample[:cards_needed_board]
        
        my_score = evaluate_best_7(hole, sim_board)
        
        opp_best = None
        idx = cards_needed_board
        for _ in range(num_opponents):
            opp_hole = sample[idx : idx + 2]
            idx += 2
            opp_score = evaluate_best_7(opp_hole, sim_board)
            if opp_best is None or opp_score > opp_best:
                opp_best = opp_score

        if my_score > opp_best:
            wins += 1
        elif my_score == opp_best:
            ties += 0.5

        sims_done += 1

    if sims_done == 0:
        return 0.5
    return (wins + ties) / sims_done

# ---------------------------------------------------------------------------
# Opponent Profiling
# ---------------------------------------------------------------------------
def analyze_opponents(hand_history):
    """
    Analyzes public hand history to estimate global field aggression.
    Returns estimated average fold frequency when facing bets.
    """
    if not hand_history:
        return 0.4  # Default fallback

    folds = 0
    bets_faced = 0

    for hand in hand_history[-20:]:  # Look at recent 20 hands
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
# Main Policy Decision Loop
# ---------------------------------------------------------------------------
def nextMove(gameState):
    """
    Main entry point invoked by engine.
    Must return a legal action tuple within timeout window.
    """
    try:
        # Extract basic variables
        hole = gameState.your_hole_cards
        board = gameState.community_cards
        stack = gameState.your_stack
        to_call = gameState.amount_to_call
        pot = gameState.pot
        min_raise = gameState.min_raise_to
        street = gameState.street

        # Count active/contending opponents
        active_opponents = [
            p for p in gameState.seat_order
            if p != gameState.your_name and gameState.player_status[p] in ("active", "all_in")
        ]
        num_opps = max(1, len(active_opponents))

        # -------------------------------------------------------------------
        # Rule 1: Exploiting No-Blinds Preflop (FREE FLOPS)
        # -------------------------------------------------------------------
        if to_call == 0:
            # Checking is always free. We evaluate equity to decide whether to check or value bet.
            equity = estimate_equity(hole, board, num_opps, num_sims=400)

            # High Equity -> Bet for Value
            if equity > 0.65:
                bet_size = max(1, int(pot * 0.6))
                bet_size = min(bet_size, stack)
                if bet_size > 0:
                    return ("bet", bet_size)
            
            # Semi-bluff / Moderate bet on postflop if field is passive
            elif equity > 0.50 and street != "preflop":
                bet_size = max(1, int(pot * 0.33))
                bet_size = min(bet_size, stack)
                if bet_size > 0:
                    return ("bet", bet_size)

            return ("check",)

        # -------------------------------------------------------------------
        # Rule 2: Facing Aggression (to_call > 0)
        # -------------------------------------------------------------------
        # In no-blinds, we fold trash preflop instantly to conserve computation time
        if street == "preflop" and to_call > stack * 0.05:
            ranks = sorted([c[1] for c in hole], reverse=True)
            is_pair = ranks[0] == ranks[1]
            is_high = ranks[0] >= 11 and ranks[1] >= 10
            is_suited = hole[0][0] == hole[1][0] and ranks[0] >= 10
            
            # If not a strong hand, fold facing significant bet
            if not (is_pair or is_high or is_suited):
                return ("fold",)

        # Calculate exact equity via Monte Carlo
        num_sims = 600 if street in ("turn", "river") else 400
        equity = estimate_equity(hole, board, num_opps, num_sims=num_sims)

        # Calculate Pot Odds
        pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.5
        
        # Buffer required for profitability
        safety_margin = 0.05
        req_equity = pot_odds + safety_margin

        # Premium Equity -> Raise
        if equity > req_equity + 0.20 and min_raise is not None:
            max_wager = stack  # All-in upper bound
            if min_raise <= max_wager:
                # Size raise dynamically based on hand strength
                target_raise = int(min_raise * 1.5) if equity < 0.85 else int(min_raise * 2.5)
                target_raise = max(min_raise, min(target_raise, max_wager))
                return ("raise", target_raise)

        # Positive Expected Value -> Call
        if equity >= req_equity:
            if to_call <= stack:
                return ("call",)

        # Negative EV -> Fold (Costs 0 chips!)
        return ("fold",)

    except Exception:
        # Ultimate Safe Fallback Guarantee
        if gameState.amount_to_call == 0:
            return ("check",)
        return ("fold",)
