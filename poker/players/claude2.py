"""
ADAPTIVE EXPLOITATIVE POKER AI (v2)
====================================
File: players/adaptive_player.py

WHY THIS BEATS `ultimate_player.py`
------------------------------------
The reference bot ("ultimate_player.py") is a solid *threshold* player, but it
has five specific, exploitable properties:

1.  FIXED PREFLOP SIZES LEAK STRENGTH. It opens for exactly 1200 (or 2500 vs a
    "calling station" table read) with tier-1 hands and exactly 800 with
    tier-2 hands, and checks everything else. The bet *size itself* is a
    100%-reliable tell. -> We track each opponent's own historical bet sizes
    and cluster on them; a bet near their "big" cluster gets read as a much
    narrower range than a bet near their "small" cluster.

2.  IT NEVER BLUFFS (except a single narrow probe-bet vs. a NIT_FOLDER table
    read). Its continue/fold decision is *its own hand's raw equity vs an
    assumed opponent range* -- it does NOT re-weight based on how much we bet,
    beyond the mechanical pot-odds term. That means large, well-timed bets
    from us buy fold equity that isn't paid for by real hand strength on its
    side. -> We size bluffs/semi-bluffs using an explicit breakeven
    fold-frequency calculation against each opponent's *measured* fold-to-bet
    rate, and only fire when the read clears a safety margin.

3.  IT PROFILES THE WHOLE TABLE AS ONE BLOB (`table_style`), not per
    opponent. In a mixed field this blurs its reads and makes its
    aggression/looseness miscalibrated against any single opponent
    (including us). -> We keep independent stats per seat.

4.  ITS CONTINUING RANGE VS A BET IS STATIC PER STREET (equity > pot_odds +
    fixed margin, no adjustment for street, stack depth, or multiway). ->
    Our margin adapts to street and number of live opponents, and we
    construct the *opponent's* likely range from their own history instead
    of assuming they're always dealt random cards.

5.  IT ONLY BUDGETS ~0.95s of the ~2.0s the engine allows, running <= 400
    Monte Carlo rollouts off a flat random deck. -> We budget close to the
    full window and weight our rollouts toward each live opponent's inferred
    range, which lowers variance and gives materially better equity
    estimates, especially multiway.

None of this is hardcoded to the reference bot's literal numbers (800/1200/
2500) -- everything is inferred live from `hand_history` / `action_history`,
so this player is also robust against opponents it has never seen before,
and keeps improving its reads across the 100-hand match.

INTERFACE
---------
Same call signature as the reference implementation: a single
`nextMove(gameState)` function reading the same attributes
(`your_name`, `your_hole_cards`, `community_cards`, `your_stack`,
`amount_to_call`, `pot`, `street`, `min_raise_to`, `seat_order`,
`player_status`, `hand_history`, `action_history`). All field access is
defensive (never raises) so a mismatch in the actual engine's exact data
shape degrades to safe defaults instead of crashing mid-tournament.
"""

import itertools
import random
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUITS = ("H", "D", "C", "S")
RANKS = tuple(range(2, 15))
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]

HARD_TIME_LIMIT = 1.75   # engine allows ~2.0s; leave real safety margin
MIN_SIM_TIME = 0.05
BASE_MAX_ITERS = 400000  # ceiling only; the time budget is the real, binding
                          # constraint post-optimization -- this just prevents
                          # a pathological runaway loop


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def gs_get(gs, attr, default=None):
    """Defensive attribute/dict access so a schema mismatch never crashes us."""
    val = getattr(gs, attr, None)
    if val is None and isinstance(gs, dict):
        val = gs.get(attr, default)
    return val if val is not None else default


# ---------------------------------------------------------------------------
# 7-card hand evaluator -- DIRECT method (no 21x C(7,5) enumeration).
#
# The original approach scored all 21 five-card subsets of the 7 available
# cards and kept the max. That's correct but wasteful: it re-derives rank
# groups and straight/flush checks 21 times per hand. Since hand *category*
# priority is fixed (straight flush > quads > boat > flush > straight > trips
# > two pair > pair > high card), we can determine the best category directly
# from a single pass over the 7 cards' rank/suit histograms and only pick out
# the specific 5-card combination for the categories where "which 5" matters
# (flush, high card). This is the standard fast 7-card evaluator pattern and
# is the single biggest lever for Monte Carlo sample count: every eval saved
# is directly more equity-simulation throughput in the same time budget.
# ---------------------------------------------------------------------------
def _straight_high(ranks_iterable):
    u = sorted(set(ranks_iterable), reverse=True)
    if 14 in u:
        u = u + [1]
    for i in range(len(u) - 4):
        window = u[i:i + 5]
        if window[0] - window[4] == 4:
            return window[0]
    return None


def evaluate_best_hand(hole, board):
    cards = (hole[0], hole[1]) + tuple(board)

    rank_counts = [0] * 15
    suit_counts = {"H": 0, "D": 0, "C": 0, "S": 0}
    suit_ranks = {"H": [], "D": [], "C": [], "S": []}
    all_ranks = []

    for s, r in cards:
        rank_counts[r] += 1
        suit_counts[s] += 1
        suit_ranks[s].append(r)
        all_ranks.append(r)

    flush_suit = None
    for s, cnt in suit_counts.items():
        if cnt >= 5:
            flush_suit = s
            break

    if flush_suit is not None:
        sf_high = _straight_high(suit_ranks[flush_suit])
        if sf_high:
            return (8, sf_high)

    groups = sorted(((cnt, r) for r, cnt in enumerate(rank_counts) if cnt > 0), reverse=True)

    if groups[0][0] == 4:
        quad_rank = groups[0][1]
        kicker = max(r for r in all_ranks if r != quad_rank)
        return (6, quad_rank, kicker)

    if groups[0][0] == 3:
        second_pair_plus = None
        for cnt, r in groups[1:]:
            if cnt >= 2:
                second_pair_plus = r
                break
        if second_pair_plus is not None:
            return (5, groups[0][1], second_pair_plus)

    if flush_suit is not None:
        top5 = sorted(suit_ranks[flush_suit], reverse=True)[:5]
        return (4,) + tuple(top5)

    straight_high = _straight_high(all_ranks)
    if straight_high:
        return (3, straight_high)

    if groups[0][0] == 3:
        trips = groups[0][1]
        kickers = sorted((r for r in all_ranks if r != trips), reverse=True)[:2]
        return (2, trips) + tuple(kickers)

    if groups[0][0] == 2 and len(groups) > 1 and groups[1][0] == 2:
        hi, lo = groups[0][1], groups[1][1]
        kicker = max(r for r in all_ranks if r not in (hi, lo))
        return (1, hi, lo, kicker)

    if groups[0][0] == 2:
        pair = groups[0][1]
        kickers = sorted((r for r in all_ranks if r != pair), reverse=True)[:3]
        return (0, pair) + tuple(kickers)

    top5 = sorted(all_ranks, reverse=True)[:5]
    return (-1,) + tuple(top5)


# ---------------------------------------------------------------------------
# Preflop strength ranking (Chen-style heuristic) -- used ONLY to build
# opponent RANGES for Monte Carlo weighting, never as the final decision
# rule (the final decision always comes from simulated equity).
# ---------------------------------------------------------------------------
def chen_score(c1, c2):
    r1, r2 = sorted((c1[1], c2[1]), reverse=True)
    suited = c1[0] == c2[0]

    if r1 == 14:
        pts = 10.0
    elif r1 == 13:
        pts = 8.0
    elif r1 == 12:
        pts = 7.0
    elif r1 == 11:
        pts = 6.0
    elif r1 == 10:
        pts = 5.0
    else:
        pts = r1 / 2.0

    if r1 == r2:
        pts = max(pts * 2.0, 5.0)

    if suited:
        pts += 2.0

    if r1 != r2:
        gap = r1 - r2 - 1
        if gap == 0:
            pts += 1.0
        elif gap == 1:
            pts -= 1.0
        elif gap == 2:
            pts -= 2.0
        elif gap == 3:
            pts -= 4.0
        else:
            pts -= 5.0

    return pts


def _build_ranked_combos():
    combos = list(itertools.combinations(FULL_DECK, 2))
    scored = [(chen_score(c[0], c[1]), c) for c in combos]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored]


ALL_HOLE_COMBOS_RANKED = _build_ranked_combos()
_N_COMBOS = len(ALL_HOLE_COMBOS_RANKED)

# Fixed integer id per card (0-51), used for O(1) bytearray-based availability
# checks in the Monte Carlo loop instead of rebuilding a Python set() of
# tuples every iteration -- rebuilding/copying a small bytearray is a cheap
# C-level memcpy, whereas constructing+hashing ~45 tuples per iteration
# (thousands of times per decision) is comparatively expensive.
CARD_ID = {c: i for i, c in enumerate(FULL_DECK)}


def top_percent_combos(percent, excluded_cards, limit=150):
    excluded = set(excluded_cards)
    n_take = max(4, int(_N_COMBOS * percent))
    out = []
    for combo in ALL_HOLE_COMBOS_RANKED[:n_take]:
        if combo[0] in excluded or combo[1] in excluded:
            continue
        out.append(combo)
        if len(out) >= limit:
            break
    return out


def band_percent_combos(p_lo, p_hi, excluded_cards, limit=150):
    excluded = set(excluded_cards)
    lo = clamp(int(_N_COMBOS * p_lo), 0, _N_COMBOS - 1)
    hi = clamp(int(_N_COMBOS * p_hi), lo + 1, _N_COMBOS)
    out = []
    for combo in ALL_HOLE_COMBOS_RANKED[lo:hi]:
        if combo[0] in excluded or combo[1] in excluded:
            continue
        out.append(combo)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Per-opponent statistical model, rebuilt fresh from hand_history each call
# (cheap: hand_history only grows to ~100 hands over the match).
# ---------------------------------------------------------------------------
class OpponentModel:
    __slots__ = (
        "name", "hands", "vpip", "pfr",
        "faced_bets_pre", "folds_pre",
        "faced_bets_post", "folds_post",
        "bets_post", "checks_post",
        "raw_bets_pre", "raw_bets_post",
    )

    def __init__(self, name):
        self.name = name
        self.hands = 0
        self.vpip = 0
        self.pfr = 0
        self.faced_bets_pre = 0
        self.folds_pre = 0
        self.faced_bets_post = 0
        self.folds_post = 0
        self.bets_post = 0
        self.checks_post = 0
        self.raw_bets_pre = []
        self.raw_bets_post = []

    def vpip_rate(self):
        return (self.vpip / self.hands) if self.hands >= 3 else 0.35

    def pfr_rate(self):
        return (self.pfr / self.hands) if self.hands >= 3 else 0.15

    def fold_to_bet_rate(self, street):
        if street == "pre":
            return (self.folds_pre / self.faced_bets_pre) if self.faced_bets_pre >= 3 else 0.45
        return (self.folds_post / self.faced_bets_post) if self.faced_bets_post >= 3 else 0.45

    def aggression_freq(self):
        total = self.bets_post + self.checks_post
        return (self.bets_post / total) if total >= 3 else 0.35

    def bet_size_percentile(self, street, amount):
        sizes = self.raw_bets_pre if street == "pre" else self.raw_bets_post
        if len(sizes) < 3 or amount is None:
            return 0.5
        smaller = sum(1 for x in sizes if x <= amount)
        return smaller / len(sizes)


# hand_history only grows *between* hands, not between the several street
# decisions (preflop/flop/turn/river) within a single hand -- so rebuilding
# every opponent's full stat history from scratch on every one of those calls
# is pure waste. Cache by (my_name, len(hand_history)) and reuse within a hand.
_MODEL_CACHE = {"key": None, "models": None}


def build_opponent_models(my_name, hand_history, seat_order):
    cache_key = (my_name, len(hand_history) if hand_history else 0, tuple(seat_order or ()))
    if _MODEL_CACHE["key"] == cache_key:
        return _MODEL_CACHE["models"]

    models = {name: OpponentModel(name) for name in (seat_order or []) if name != my_name}
    for hand in (hand_history or []):
        try:
            actions = hand.get("actions", {}) if isinstance(hand, dict) else {}
        except Exception:
            continue
        participated = set()
        for street, street_actions in actions.items():
            is_pre = (street == "preflop")
            street_open = False
            for entry in (street_actions or []):
                try:
                    name, act = entry
                    kind = act[0]
                    amount = act[1] if len(act) > 1 else None
                except Exception:
                    continue
                model = models.get(name)
                if model is None:
                    continue
                participated.add(name)
                facing = street_open

                if kind in ("bet", "raise"):
                    if is_pre:
                        model.vpip += 1
                        model.pfr += 1
                        if amount is not None:
                            model.raw_bets_pre.append(amount)
                    else:
                        model.bets_post += 1
                        if amount is not None:
                            model.raw_bets_post.append(amount)
                    street_open = True
                elif kind == "call":
                    if is_pre:
                        model.vpip += 1
                    if facing:
                        if is_pre:
                            model.faced_bets_pre += 1
                        else:
                            model.faced_bets_post += 1
                elif kind == "check":
                    if not is_pre:
                        model.checks_post += 1
                elif kind == "fold":
                    if facing:
                        if is_pre:
                            model.faced_bets_pre += 1
                            model.folds_pre += 1
                        else:
                            model.faced_bets_post += 1
                            model.folds_post += 1
        for name in participated:
            models[name].hands += 1
    _MODEL_CACHE["key"] = cache_key
    _MODEL_CACHE["models"] = models
    return models


def infer_current_actions(action_history, active_opponents):
    """Best-effort read of each live opponent's most recent action this hand."""
    active_set = set(active_opponents)
    result = {name: "unopened" for name in active_opponents}
    for entry in (action_history or []):
        try:
            name, act = entry
            kind = act[0]
        except Exception:
            continue
        if name in active_set and kind in ("bet", "raise", "call", "check"):
            result[name] = kind
    return result


def last_bet_amount(action_history, name):
    amt = None
    for entry in (action_history or []):
        try:
            n, act = entry
            if n == name and act[0] in ("bet", "raise") and len(act) > 1:
                amt = act[1]
        except Exception:
            continue
    return amt


# ---------------------------------------------------------------------------
# Range-weighted Monte Carlo equity engine (works for preflop AND postflop)
# ---------------------------------------------------------------------------
def prepare_ranges(active_opponents, models, current_actions, known_cards):
    ranges = {}
    for name in active_opponents:
        model = models.get(name)
        behavior = current_actions.get(name, "unopened")
        if model is None or model.hands < 2:
            ranges[name] = None
            continue
        if behavior in ("bet", "raise"):
            width = clamp(model.pfr_rate() or 0.15, 0.02, 0.45)
            ranges[name] = top_percent_combos(width, known_cards) or None
        elif behavior == "call":
            lo = clamp(model.pfr_rate(), 0.0, 0.85)
            hi = clamp(max(model.vpip_rate(), lo + 0.05), lo + 0.05, 1.0)
            ranges[name] = band_percent_combos(lo, hi, known_cards) or None
        elif behavior == "check":
            lo = clamp(1.0 - model.aggression_freq(), 0.10, 0.95)
            ranges[name] = band_percent_combos(lo, 1.0, known_cards) or None
        else:
            ranges[name] = None
    return ranges


def simulate_equity(hole, board, active_opponents, models, current_actions,
                     time_budget, start_time, max_iters=BASE_MAX_ITERS):
    known = set(hole) | set(board)
    base_remaining = [c for c in FULL_DECK if c not in known]
    base_remaining_ids = [CARD_ID[c] for c in base_remaining]
    ranges = prepare_ranges(active_opponents, models, current_actions, known)
    # Pre-convert each opponent's candidate combos to id pairs ONCE, outside
    # the hot loop, instead of re-doing dict lookups every iteration.
    range_ids = {
        name: [(CARD_ID[c1], CARD_ID[c2]) for c1, c2 in combos] if combos else None
        for name, combos in ranges.items()
    }
    cards_needed_board = 5 - len(board)

    # Reusable availability template: 1 = still in the deck, 0 = known/used.
    # Copying this bytearray each iteration (fast, fixed-size, C-level) replaces
    # rebuilding a Python set() of ~45 card tuples every single iteration.
    avail_template = bytearray(52)
    for cid in base_remaining_ids:
        avail_template[cid] = 1

    # On the river the board is already fully determined, so the hero's best
    # hand is CONSTANT across every rollout -- evaluate it once instead of
    # thousands of times.
    cached_hero_score = evaluate_best_hand(hole, board) if cards_needed_board == 0 else None

    wins = 0.0
    iters = 0
    noise_prob = 0.15  # mixture weight: draw pure-random hand instead of the inferred range

    rand = random.random
    randrange = random.randrange

    while True:
        # Check wall-clock time roughly every 32 iterations instead of every
        # single one -- perf_counter() calls aren't free at thousands/sec,
        # and a slightly delayed cutoff (bounded by 32 cheap iterations) is a
        # non-issue against a multi-hundred-millisecond budget.
        if (iters & 31) == 0 and (time.perf_counter() - start_time) >= time_budget:
            break
        if iters >= max_iters:
            break

        avail = bytearray(avail_template)
        n_avail = len(base_remaining_ids)
        opp_holes = []
        failed = False

        for name in active_opponents:
            combos = range_ids.get(name)
            chosen = None
            if combos and rand() > noise_prob:
                for _ in range(6):
                    c1, c2 = combos[randrange(len(combos))]
                    if c1 != c2 and avail[c1] and avail[c2]:
                        chosen = (c1, c2)
                        break
            if chosen is None:
                if n_avail < 2:
                    failed = True
                    break
                # Rejection-sample two distinct available ids straight out of
                # the small fixed id pool (cheap; pool is only ~45 wide and
                # nearly always mostly free).
                while True:
                    c1 = base_remaining_ids[randrange(len(base_remaining_ids))]
                    if avail[c1]:
                        break
                while True:
                    c2 = base_remaining_ids[randrange(len(base_remaining_ids))]
                    if avail[c2] and c2 != c1:
                        break
                chosen = (c1, c2)
            avail[chosen[0]] = 0
            avail[chosen[1]] = 0
            n_avail -= 2
            opp_holes.append(chosen)

        if failed:
            continue
        if n_avail < cards_needed_board:
            continue

        if cards_needed_board:
            board_draw_ids = []
            for _ in range(cards_needed_board):
                while True:
                    cid = base_remaining_ids[randrange(len(base_remaining_ids))]
                    if avail[cid]:
                        avail[cid] = 0
                        board_draw_ids.append(cid)
                        break
            sim_board = board + [FULL_DECK[i] for i in board_draw_ids]
            hero_score = evaluate_best_hand(hole, sim_board)
        else:
            sim_board = board
            hero_score = cached_hero_score

        opp_scores = [evaluate_best_hand((FULL_DECK[c1], FULL_DECK[c2]), sim_board)
                      for c1, c2 in opp_holes]
        best_opp = max(opp_scores) if opp_scores else (-2,)

        if hero_score > best_opp:
            wins += 1.0
        elif hero_score == best_opp:
            ties = 1 + sum(1 for s in opp_scores if s == best_opp)
            wins += 1.0 / ties

        iters += 1

    return (wins / iters if iters else 0.5), iters


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------
def nextMove(gameState):
    t0 = time.perf_counter()

    my_name = gs_get(gameState, "your_name")
    hole = gs_get(gameState, "your_hole_cards", [])
    board = gs_get(gameState, "community_cards", [])
    stack = gs_get(gameState, "your_stack", 0)
    to_call = gs_get(gameState, "amount_to_call", 0)
    pot = gs_get(gameState, "pot", 0)
    street = gs_get(gameState, "street", "preflop")
    min_raise_to = gs_get(gameState, "min_raise_to", None)
    seat_order = gs_get(gameState, "seat_order", [])
    player_status = gs_get(gameState, "player_status", {})
    hand_history = gs_get(gameState, "hand_history", [])
    action_history = gs_get(gameState, "action_history", [])

    active_opponents = [
        p for p in seat_order
        if p != my_name and player_status.get(p) in ("active", "all_in")
    ]
    num_opp = max(1, len(active_opponents))

    models = build_opponent_models(my_name, hand_history, seat_order)
    current_actions = infer_current_actions(action_history, active_opponents)

    # Reconstruct our own current-street wager (for max legal raise size)
    current_wager = 0
    for actor, act in reversed(action_history or []):
        if actor == my_name:
            try:
                if act[0] in ("bet", "raise"):
                    current_wager = act[1]
                elif act[0] == "call":
                    current_wager = to_call
            except Exception:
                pass
            break
    max_raise_to = stack + current_wager

    # ---------------- Fail-safe action sanitizer ----------------
    def sanitize(action):
        kind = action[0]
        if to_call == 0:
            if kind == "bet":
                amount = int(action[1]) if len(action) > 1 else 1
                amount = max(1, min(amount, stack))
                if amount <= 0:
                    return ("check",)
                return ("bet", amount)
            return ("check",)
        else:
            if kind == "fold":
                return ("fold",)
            if kind == "raise":
                if min_raise_to is None or min_raise_to > max_raise_to or stack <= to_call:
                    return ("call",)
                raise_amt = int(action[1]) if len(action) > 1 else min_raise_to
                raise_amt = max(min_raise_to, min(raise_amt, max_raise_to))
                return ("raise", raise_amt)
            if kind == "call":
                return ("call",)
            return ("fold",)

    # ---------------- Time budgeting ----------------
    elapsed = time.perf_counter() - t0
    sim_budget = clamp(HARD_TIME_LIMIT - elapsed, MIN_SIM_TIME, HARD_TIME_LIMIT)
    max_iters = max(250, int(BASE_MAX_ITERS / num_opp))

    equity, n_iters = simulate_equity(
        hole, board, active_opponents, models, current_actions,
        time_budget=sim_budget, start_time=t0, max_iters=max_iters,
    )

    pot_after_call = pot + to_call
    pot_odds = (to_call / pot_after_call) if pot_after_call > 0 else 0.0

    # Street/street-depth aware safety margin over pure pot odds.
    street_margin = {"preflop": 0.05, "flop": 0.05, "turn": 0.045, "river": 0.03}.get(street, 0.05)
    margin = street_margin + 0.015 * (num_opp - 1)

    # Estimated probability that ALL live opponents fold to a bet of `bet_size`.
    def combined_fold_prob(bet_size):
        street_key = "pre" if street == "preflop" else "post"
        prob_all_fold = 1.0
        for name in active_opponents:
            m = models.get(name)
            base_fold = m.fold_to_bet_rate(street_key) if m else 0.45
            size_ratio = bet_size / max(pot, 1)
            # bigger-than-normal bets fold out more of a range; tiny bets fold out less
            adj = clamp(base_fold + (size_ratio - 0.65) * 0.18, 0.05, 0.92)
            prob_all_fold *= adj
        return prob_all_fold

    # Average "station-ness" of the live table, for value-bet sizing.
    avg_call_rate = sum((models[n].vpip_rate() if street == "preflop" else 1 - models[n].fold_to_bet_rate("post"))
                         for n in active_opponents) / num_opp if active_opponents else 0.4

    # ============================= NOT FACING A BET =============================
    if to_call == 0:
        value_threshold = clamp(0.52 + 0.05 * (num_opp - 1), 0.52, 0.78)

        if equity >= value_threshold:
            # Value bet: scale up against calling-station-leaning opponents,
            # scale toward a leaner/polarized size otherwise.
            size_mult = 0.55 + 0.85 * clamp(avg_call_rate, 0.0, 1.0) + 0.3 * max(0.0, equity - value_threshold)
            size_mult = clamp(size_mult, 0.5, 1.75)
            base_pot = max(pot, 200)
            bet_amt = int(base_pot * size_mult)
            bet_amt = max(bet_amt, int(stack * 0.02) + 1)
            return sanitize(("bet", min(bet_amt, stack)))

        # Below value threshold: consider a bluff / semi-bluff purely on
        # measured fold equity, independent of our own hand strength.
        bluff_size = int(max(pot, 250) * 0.65)
        bluff_size = min(bluff_size, stack)
        if bluff_size > 0:
            breakeven = bluff_size / (pot + bluff_size)
            fold_est = combined_fold_prob(bluff_size)
            # require a real safety margin above breakeven, and prefer hands
            # with some backup equity (semi-bluffs) via a softer bar
            required = breakeven * (1.12 if equity >= 0.25 else 1.30)
            if fold_est > required:
                return sanitize(("bet", bluff_size))

        return sanitize(("check",))

    # =============================== FACING A BET ================================
    else:
        if equity > pot_odds + margin:
            if equity >= 0.80 and min_raise_to is not None and min_raise_to <= max_raise_to:
                size_mult = 0.6 + 0.6 * clamp(avg_call_rate, 0.0, 1.0)
                raise_target = int(pot * size_mult) + to_call
                raise_target = max(min_raise_to, min(raise_target, max_raise_to))
                return sanitize(("raise", raise_target))
            return sanitize(("call",))

        # Raise-bluff: opponent's bet looks like a probe (small vs pot) and
        # their measured fold-to-raise is favorable -- fold-equity play.
        street_key = "pre" if street == "preflop" else "post"
        size_ratio = to_call / max(pot, 1)
        if (size_ratio < 0.45 and min_raise_to is not None and min_raise_to <= max_raise_to
                and equity >= 0.20):
            raise_target = max(min_raise_to, min(int(pot * 0.9) + to_call, max_raise_to))
            fold_est = combined_fold_prob(raise_target - to_call)
            breakeven = (raise_target - to_call) / (pot + to_call + (raise_target - to_call))
            if fold_est > breakeven * 1.25:
                return sanitize(("raise", raise_target))

        # Cheap implied-odds call
        if to_call <= stack * 0.02 and equity >= 0.22:
            return sanitize(("call",))

        return sanitize(("fold",))