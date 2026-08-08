"""
Advanced Exploitative & Mathematical Poker AI for No-Limit Texas Hold'em (No Blinds)
File: players/advanced_player.py
"""

import itertools
import random
import time
from collections import Counter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
STARTING_STACK = 50_000
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))


# ---------------------------------------------------------------------------
# Fast Engine-Compatible Hand Evaluator
# ---------------------------------------------------------------------------
def _straight_high(ranks):
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
    best = None
    for combo in itertools.combinations(all_cards, 5):
        score = _evaluate_five(combo)
        if best is None or score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Preflop Strength Evaluator
# ---------------------------------------------------------------------------
def classify_preflop_hand(hole_cards):
    c1, c2 = hole_cards[0], hole_cards[1]
    r1, r2 = max(c1[1], c2[1]), min(c1[1], c2[1])
    is_suited = c1[0] == c2[0]
    is_pair = r1 == r2

    # Tier 1: Premium Monsters
    if is_pair and r1 >= 10:  # TT, JJ, QQ, KK, AA
        return 1
    if r1 == 14 and r2 >= 13:  # AKs, AKo
        return 1

    # Tier 2: Strong
    if is_pair and r1 >= 7:  # 77, 88, 99
        return 2
    if r1 == 14 and r2 >= 11:  # AQ, AJ
        return 2
    if r1 == 13 and r2 >= 12:  # KQ
        return 2
    if is_suited and r1 >= 12 and r2 >= 10:  # KQs, KJs, QJs
        return 2

    # Tier 3: Speculative / Small Pairs / Suited Connectors
    if is_pair:  # 22-66
        return 3
    if is_suited and (r1 == 14 or (r1 - r2 == 1 and r2 >= 5)):  # Suited Aces, Suited Connectors
        return 3
    if r1 >= 12 and r2 >= 10:  # QJ, KJ, KT
        return 3

    # Tier 4: Trash
    return 4


# ---------------------------------------------------------------------------
# Fast Monte Carlo Simulator
# ---------------------------------------------------------------------------
def simulate_equity(hole_cards, community_cards, num_opponents, num_simulations=250, time_limit=0.5, start_time=None):
    """Simulates hand win-rate against N random opponent holdings within time budget."""
    if start_time is None:
        start_time = time.perf_counter()

    full_deck = [(s, r) for s in SUITS for r in RANKS]
    known_cards = set(hole_cards + community_cards)
    remaining_deck = [c for c in full_deck if c not in known_cards]

    cards_needed_board = 5 - len(community_cards)
    wins = 0
    ties = 0

    for i in range(num_simulations):
        # Time Guard Enforcement
        if (time.perf_counter() - start_time) > time_limit:
            break

        random.shuffle(remaining_deck)
        idx = 0

        # Draw remaining board cards
        sim_board = list(community_cards) + remaining_deck[idx : idx + cards_needed_board]
        idx += cards_needed_board

        hero_score = evaluate_best_hand(hole_cards, sim_board)

        # Draw opponent hands
        opponent_scores = []
        for _ in range(num_opponents):
            opp_hole = remaining_deck[idx : idx + 2]
            idx += 2
            opponent_scores.append(evaluate_best_hand(opp_hole, sim_board))

        max_opp_score = max(opponent_scores)

        if hero_score > max_opp_score:
            wins += 1
        elif hero_score == max_opp_score:
            ties += 0.5

    total_sims = wins + ties + max(1, (num_simulations - wins - ties))
    return (wins + ties) / total_sims


# ---------------------------------------------------------------------------
# Opponent Profiler
# ---------------------------------------------------------------------------
def profile_opponents(hand_history, active_players, my_name):
    """Analyzes opponent tendencies from past hand history."""
    if not hand_history:
        return {"calling_station_ratio": 0.5, "fold_heavy_ratio": 0.5}

    total_opp_actions = 0
    opp_calls = 0
    opp_folds = 0

    for hand in hand_history:
        actions = hand.get("actions", {})
        for street, street_actions in actions.items():
            for p_name, act in street_actions:
                if p_name == my_name or p_name not in active_players:
                    continue
                kind = act[0]
                total_opp_actions += 1
                if kind == "call":
                    opp_calls += 1
                elif kind == "fold":
                    opp_folds += 1

    if total_opp_actions == 0:
        return {"calling_station_ratio": 0.5, "fold_heavy_ratio": 0.5}

    return {
        "calling_station_ratio": opp_calls / total_opp_actions,
        "fold_heavy_ratio": opp_folds / total_opp_actions,
    }


# ---------------------------------------------------------------------------
# Main NextMove Function
# ---------------------------------------------------------------------------
def nextMove(gameState):
    t0 = time.perf_counter()
    TIME_BUDGET = 1.2  # Hard stop at 1.2s (engine timeout is 2.0s)

    # 1. Gather Context
    my_name = gameState.your_name
    hole_cards = gameState.your_hole_cards
    board = gameState.community_cards
    stack = gameState.your_stack
    to_call = gameState.amount_to_call
    pot = gameState.pot
    street = gameState.street
    min_raise_to = gameState.min_raise_to

    # Count active opponents (excluding self)
    active_opponents = [
        p for p in gameState.seat_order
        if p != my_name and gameState.player_status.get(p) in ("active", "all_in")
    ]
    num_opponents = max(1, len(active_opponents))

    # Profile Opponents
    opp_profile = profile_opponents(gameState.hand_history, active_opponents, my_name)
    is_calling_station_table = opp_profile["calling_station_ratio"] > 0.45
    is_fold_heavy_table = opp_profile["fold_heavy_ratio"] > 0.55

    # Calculate Max Legal Raise
    max_raise_to = stack + (to_call if to_call > 0 else 0)

    # Helper: Sanitize & Validate Output
    def sanitize_action(action):
        kind = action[0]

        if to_call == 0:
            if kind in ("fold", "check"):
                return ("check",)
            if kind == "bet":
                amount = max(1, min(action[1], stack))
                return ("bet", amount)
            return ("check",)

        else:  # Facing a bet (to_call > 0)
            if kind == "fold":
                return ("fold",)
            if kind == "call":
                if stack <= to_call:
                    return ("call",)  # All-in call
                return ("call",)
            if kind == "raise":
                if min_raise_to is None or stack <= to_call:
                    return ("call",)
                raise_amt = max(min_raise_to, min(action[1], max_raise_to))
                return ("raise", raise_amt)
            return ("fold",)

    # -----------------------------------------------------------------------
    # PREFLOP STRATEGY (No Blinds Context)
    # -----------------------------------------------------------------------
    if street == "preflop":
        tier = classify_preflop_hand(hole_cards)

        if to_call == 0:
            if tier == 1:
                bet_size = 2000 if is_calling_station_table else 1000
                return sanitize_action(("bet", min(bet_size, stack)))
            elif tier == 2:
                return sanitize_action(("bet", min(600, stack)))
            elif tier == 3:
                return sanitize_action(("check",))
            else:  # Tier 4 Trash
                return sanitize_action(("check",))  # Checking costs $0!

        else:  # Facing a bet preflop
            if tier == 1:
                if min_raise_to and min_raise_to <= stack:
                    return sanitize_action(("raise", min(min_raise_to * 2, max_raise_to)))
                return sanitize_action(("call",))
            elif tier == 2:
                if to_call <= 3000 or (to_call <= stack * 0.15):
                    return sanitize_action(("call",))
                return sanitize_action(("fold",))
            elif tier == 3:
                if to_call <= 500:  # Call small bets for implied odds
                    return sanitize_action(("call",))
                return sanitize_action(("fold",))
            else:
                return sanitize_action(("fold",))

    # -----------------------------------------------------------------------
    # POSTFLOP STRATEGY (Flop / Turn / River)
    # -----------------------------------------------------------------------
    equity = simulate_equity(
        hole_cards,
        board,
        num_opponents,
        num_simulations=300,
        time_limit=TIME_BUDGET,
        start_time=t0,
    )

    pot_after_call = pot + to_call
    pot_odds = to_call / pot_after_call if pot_after_call > 0 else 0.0

    # Decision Logic Based on Postflop Equity
    if to_call == 0:
        if equity >= 0.75:  # Monster Hand -> Heavy Value Bet
            bet_size = int(pot * (1.2 if is_calling_station_table else 0.8))
            bet_size = max(500, min(bet_size, stack))
            return sanitize_action(("bet", bet_size))

        elif equity >= 0.55:  # Medium Strong -> Standard Value Bet
            bet_size = max(300, min(int(pot * 0.5), stack))
            return sanitize_action(("bet", bet_size))

        elif equity < 0.35 and is_fold_heavy_table:  # Semi-Bluff / Steal
            steal_size = max(200, min(int(pot * 0.4), stack))
            return sanitize_action(("bet", steal_size))

        else:  # Moderate Equity / Pure Check
            return sanitize_action(("check",))

    else:  # Facing a Bet Postflop
        # EV Check: Is Equity > Pot Odds?
        if equity > pot_odds + 0.05:  # +5% margin of safety
            if equity >= 0.80 and min_raise_to and (min_raise_to <= max_raise_to):
                # Raise strong hands for value
                raise_size = max(min_raise_to, min(int(pot * 0.8) + to_call, max_raise_to))
                return sanitize_action(("raise", raise_size))
            return sanitize_action(("call",))

        elif to_call <= stack * 0.02 and equity >= 0.25:  # Cheap call for draw
            return sanitize_action(("call",))

        else:
            return sanitize_action(("fold",))