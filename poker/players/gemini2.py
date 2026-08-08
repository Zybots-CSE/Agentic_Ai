"""
CHAMPION EXPLOITATIVE & MATHEMATICAL POKER AI
Designed for No-Limit Texas Hold'em (No Blinds)

File: players/champion_player.py
"""

import itertools
import random
import time
from collections import Counter

# ---------------------------------------------------------------------------
# Global Constants
# ---------------------------------------------------------------------------
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))  # 2..14, Ace = 14


# ---------------------------------------------------------------------------
# Engine-Identical Fast Hand Evaluator
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
# Preflop Tier Classification Matrix (No-Blinds Context)
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

    # Tier 2: Strong Value Hands
    if is_pair and r1 >= 7:  # 77, 88, 99
        return 2
    if r1 == 14 and r2 >= 11:  # AQ, AJ
        return 2
    if r1 == 13 and r2 >= 12:  # KQ
        return 2
    if is_suited and r1 >= 12 and r2 >= 10:  # KQs, KJs, QJs
        return 2

    # Tier 3: Medium / Speculative / Small Pairs
    if is_pair:  # 22-66
        return 3
    if is_suited and (r1 == 14 or (r1 - r2 == 1 and r2 >= 5)):  # Suited Aces, Suited Connectors
        return 3
    if r1 >= 12 and r2 >= 10:  # QJ, KJ, KT
        return 3

    # Tier 4: Weak Broadways / Marginal
    if r1 >= 11 or (is_suited and r1 >= 10):
        return 4

    # Tier 5: Pure Trash
    return 5


# ---------------------------------------------------------------------------
# Real-time Bayesian Opponent Profiler
# ---------------------------------------------------------------------------
class BayesianProfiler:
    @staticmethod
    def profile_all(hand_history, seat_order, my_name):
        stats = {
            p: {"folds": 0, "calls": 0, "bets": 0, "total_actions": 0}
            for p in seat_order
            if p != my_name
        }

        if not hand_history:
            return {p: "BALANCED" for p in stats}

        for hand in hand_history:
            actions = hand.get("actions", {})
            for street, street_actions in actions.items():
                for p_name, act in street_actions:
                    if p_name not in stats:
                        continue
                    kind = act[0]
                    stats[p_name]["total_actions"] += 1
                    if kind == "call":
                        stats[p_name]["calls"] += 1
                    elif kind == "fold":
                        stats[p_name]["folds"] += 1
                    elif kind in ("bet", "raise"):
                        stats[p_name]["bets"] += 1

        profiles = {}
        for p_name, s in stats.items():
            tot = s["total_actions"]
            if tot == 0:
                profiles[p_name] = "BALANCED"
                continue

            call_rate = s["calls"] / tot
            fold_rate = s["folds"] / tot
            bet_rate = s["bets"] / tot

            if call_rate > 0.40 and fold_rate < 0.20:
                profiles[p_name] = "CALLING_STATION"
            elif fold_rate > 0.48:
                profiles[p_name] = "NIT_FOLDER"
            elif bet_rate > 0.35:
                profiles[p_name] = "HYPER_AGGRESSIVE"
            else:
                profiles[p_name] = "BALANCED"

        return profiles


# ---------------------------------------------------------------------------
# Range-Weighted Monte Carlo Simulator
# ---------------------------------------------------------------------------
def range_weighted_equity(hole_cards, community_cards, active_opponents, opponent_profiles, max_time=0.85, start_time=None):
    if start_time is None:
        start_time = time.perf_counter()

    full_deck = [(s, r) for s in SUITS for r in RANKS]
    known_cards = set(hole_cards + community_cards)
    remaining_deck = [c for c in full_deck if c not in known_cards]

    cards_needed_board = 5 - len(community_cards)
    wins = 0.0
    simulations = 0

    num_opponents = len(active_opponents)
    if num_opponents == 0:
        return 1.0

    while True:
        # Time Guard Check (< 0.85s)
        if (time.perf_counter() - start_time) >= max_time:
            break
        if simulations >= 350:
            break

        random.shuffle(remaining_deck)
        idx = 0

        # Draw missing board cards
        sim_board = list(community_cards) + remaining_deck[idx : idx + cards_needed_board]
        idx += cards_needed_board

        hero_score = evaluate_best_hand(hole_cards, sim_board)

        # Draw opponent holdings with range-filtering
        opponent_scores = []
        for opp_name in active_opponents:
            opp_profile = opponent_profiles.get(opp_name, "BALANCED")
            opp_hole = remaining_deck[idx : idx + 2]
            idx += 2

            # Range filter: Tight/aggressive opponents hold fewer trash hands
            if opp_profile in ("NIT_FOLDER", "HYPER_AGGRESSIVE") and random.random() < 0.40:
                tier = classify_preflop_hand(opp_hole)
                if tier in (4, 5) and idx + 2 <= len(remaining_deck):
                    opp_hole = remaining_deck[idx : idx + 2]
                    idx += 2

            opponent_scores.append(evaluate_best_hand(opp_hole, sim_board))

        max_opp_score = max(opponent_scores)

        if hero_score > max_opp_score:
            wins += 1.0
        elif hero_score == max_opp_score:
            wins += 0.5

        simulations += 1

    if simulations == 0:
        return 0.5
    return wins / simulations


# ---------------------------------------------------------------------------
# Helper: Compute Hero's Street Wager Accurately
# ---------------------------------------------------------------------------
def compute_hero_street_wager(action_history, my_name):
    wager = 0
    current_level = 0
    for player, act in action_history:
        kind = act[0]
        if kind == "bet":
            current_level = act[1]
            if player == my_name:
                wager = act[1]
        elif kind == "raise":
            current_level = act[1]
            if player == my_name:
                wager = act[1]
        elif kind == "call":
            if player == my_name:
                wager = current_level
    return wager


# ---------------------------------------------------------------------------
# Main Action Decision Function
# ---------------------------------------------------------------------------
def nextMove(gameState):
    t0 = time.perf_counter()
    TIME_BUDGET = 0.85  # Hard stop at 0.85s (engine timeout is 2.0s)

    # 1. State Extraction
    my_name = gameState.your_name
    hole_cards = gameState.your_hole_cards
    board = gameState.community_cards
    stack = gameState.your_stack
    to_call = gameState.amount_to_call
    pot = gameState.pot
    street = gameState.street
    min_raise_to = gameState.min_raise_to

    # 2. Identify Active Opponents
    active_opponents = [
        p for p in gameState.seat_order
        if p != my_name and gameState.player_status.get(p) in ("active", "all_in")
    ]

    # 3. Profiling & Table Analysis
    profiles = BayesianProfiler.profile_all(
        gameState.hand_history, gameState.seat_order, my_name
    )
    active_profiles = [profiles.get(p, "BALANCED") for p in active_opponents]
    is_station_table = active_profiles.count("CALLING_STATION") >= 1
    is_nit_table = active_profiles.count("NIT_FOLDER") >= max(1, len(active_opponents) // 2)

    # 4. Calculate Street Wager & Max Legal Raise Target
    my_wager = compute_hero_street_wager(gameState.action_history, my_name)
    max_raise_to = my_wager + stack

    # 5. Fail-Safe Action Sanitizer
    def sanitize_action(action):
        kind = action[0]

        if to_call == 0:
            if kind == "bet" and len(action) == 2:
                amt = int(action[1])
                amt = max(1, min(amt, stack))
                return ("bet", amt)
            return ("check",)

        else:  # Facing a bet
            if kind == "raise" and len(action) == 2:
                if min_raise_to is not None and stack > to_call:
                    target = int(action[1])
                    target = max(min_raise_to, min(target, max_raise_to))
                    if min_raise_to <= target <= max_raise_to:
                        return ("raise", target)
                return ("call",)
            elif kind == "call":
                return ("call",)
            return ("fold",)

    # -----------------------------------------------------------------------
    # PREFLOP STRATEGY (No Blinds Context)
    # -----------------------------------------------------------------------
    if street == "preflop":
        tier = classify_preflop_hand(hole_cards)

        if to_call == 0:
            if tier == 1:
                # Premium: Overbet vs Calling Stations to build massive pot
                bet_amt = 3000 if is_station_table else 1500
                return sanitize_action(("bet", min(bet_amt, stack)))
            elif tier == 2:
                return sanitize_action(("bet", min(800, stack)))
            elif tier == 3:
                return sanitize_action(("check",))  # $0 check
            else:
                return sanitize_action(("check",))  # $0 check

        else:  # Facing a preflop bet
            if tier == 1:
                if min_raise_to and min_raise_to <= max_raise_to:
                    return sanitize_action(("raise", min(min_raise_to * 2, max_raise_to)))
                return sanitize_action(("call",))
            elif tier == 2:
                if to_call <= 3500 or to_call <= (stack * 0.15):
                    return sanitize_action(("call",))
                return sanitize_action(("fold",))
            elif tier == 3:
                if to_call <= 800 or to_call <= (stack * 0.04):
                    return sanitize_action(("call",))
                return sanitize_action(("fold",))
            else:
                return sanitize_action(("fold",))  # Trash folds ($0 cost)

    # -----------------------------------------------------------------------
    # POSTFLOP STRATEGY (Flop / Turn / River)
    # -----------------------------------------------------------------------
    equity = range_weighted_equity(
        hole_cards,
        board,
        active_opponents,
        profiles,
        max_time=TIME_BUDGET,
        start_time=t0,
    )

    pot_after_call = pot + to_call
    pot_odds = to_call / pot_after_call if pot_after_call > 0 else 0.0

    # CASE A: No Bet to Call (Check or Bet)
    if to_call == 0:
        if equity >= 0.72:  # High Equity -> Value Extraction
            overbet_mult = 1.5 if is_station_table else 0.85
            value_bet = max(500, min(int(pot * overbet_mult), stack))
            return sanitize_action(("bet", value_bet))

        elif equity >= 0.52:  # Medium Equity -> Thin Value / Pot Control
            if is_station_table:
                value_bet = max(350, min(int(pot * 0.55), stack))
                return sanitize_action(("bet", value_bet))
            return sanitize_action(("check",))

        elif equity < 0.38 and is_nit_table:  # Exploitative Probe Steal
            probe_size = max(250, min(int(pot * 0.38), stack))
            return sanitize_action(("bet", probe_size))

        else:
            return sanitize_action(("check",))

    # CASE B: Facing a Bet (Fold, Call, or Raise)
    else:
        # Require positive EV margin over pot odds
        margin = 0.02 if is_station_table else 0.05

        if equity > (pot_odds + margin):
            # Extremely high equity -> Raise for value
            if equity >= 0.80 and min_raise_to and min_raise_to <= max_raise_to:
                raise_target = int(pot * 0.90) + to_call
                return sanitize_action(("raise", max(min_raise_to, min(raise_target, max_raise_to))))
            return sanitize_action(("call",))

        elif to_call <= (stack * 0.025) and equity >= 0.22:  # Cheap float call
            return sanitize_action(("call",))

        else:  # Negative EV -> Fold ($0 cost)
            return sanitize_action(("fold",))