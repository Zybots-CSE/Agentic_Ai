# Apex Piquet player v2 — strategic exchange, optimal declarations, and
# Monte-Carlo-determinized minimax trick play (mini double-dummy solver).
#
# ---------------------------------------------------------------------------
# PERFORMANCE NOTES (this revision):
#
#   The search logic and scoring rules are unchanged from the original —
#   only the *implementation* of the hot path (_play / _pimc_move) changed,
#   so the bot's decisions should be identical, just computed faster:
#
#   1. Backtracking instead of copying. The original allocated a brand new
#      {player: list(hand)} dict, with fresh list copies of BOTH hands, at
#      EVERY node of the search tree. That's O(hand_size) allocation work
#      per node, and with alpha-beta visiting hundreds/thousands of nodes
#      per sample, that dominated the runtime. This version mutates the
#      hand lists in place (remove card / recurse / append card back) and
#      restores them on the way back up — O(1) amortized per node instead
#      of O(n) copies. Same for tricks_won (increment / recurse / decrement
#      in place instead of dict(tricks_won) at every node).
#
#   2. Move ordering. Before exploring, candidates are sorted so the side
#      to move tries its most promising cards first (high cards first when
#      maximizing, low cards first when minimizing). Better move ordering
#      means alpha-beta cuts off bad branches earlier, so more of the true
#      game tree gets explored within the same time budget.
#
#   3. Batched time checks. time.monotonic() is a real syscall; calling it
#      at every single recursion node adds measurable overhead once you're
#      making tens of thousands of calls. Now it's checked every N nodes
#      via a shared counter, which is effectively just as safe (the deepest
#      any single node can overrun the deadline by is a handful of extra
#      cheap calls) but far cheaper in aggregate.
#
#   4. Slightly larger sample counts. Because each individual search is now
#      cheaper, _sample_count was bumped up a bit so the same wall-clock
#      budget buys more Monte Carlo samples (i.e. better-calibrated average
#      outcomes) rather than just finishing early.
#
#   Net effect: same move-selection logic and same hard time budget/safety
#   guarantees, but noticeably more search depth/samples fit inside the
#   2-second move timeout.
#
# ---------------------------------------------------------------------------
# TIMEOUT HARDENING (this revision):
#
#   The previous revision could still occasionally run past the move
#   timeout, because the deadline was only checked *between* samples and
#   *between* candidate cards, and inside _play only every 256 nodes. If a
#   single candidate's search (or a burst of nodes between checks) happened
#   to be unusually slow — wide branching, unlucky pruning, GC pause, a
#   slow host — that one call could itself eat the whole remaining budget
#   before the next check point, with no outer guard to catch it.
#
#   Fixes:
#     1. A single wall-clock deadline is captured at the very start of
#        nextMove() (not just inside _pimc_move), so EVERY phase — exchange,
#        declare, and trick — shares one hard budget with real margin left
#        for the engine's own overhead (serialization, transport, etc.)
#        before the 2s limit.
#     2. TIME_BUDGET_SECONDS lowered (1.2 -> 0.8) to leave a bigger safety
#        cushion, and TIME_CHECK_EVERY lowered (256 -> 64) so a runaway
#        branch gets caught faster.
#     3. The deadline is now also checked before starting each candidate
#        card inside _pimc_move's inner loop, not just before each sample —
#        so a slow sample can't spend its whole overrun on one candidate
#        and then barrel into more candidates anyway.
#     4. The whole trick-move computation is wrapped in try/except with a
#        deadline-aware fallback: if anything raises, or the deadline is
#        already blown before/after the PIMC search, control drops straight
#        to the cheap heuristic (and if even that can't be reached in time,
#        to a trivial "first legal card" pick) so nextMove ALWAYS returns
#        quickly no matter what goes wrong.
#
# ---------------------------------------------------------------------------
# REAL TIMEOUT FIX (this revision) — the previous "hardening" was incomplete:
#
#   The earlier per-node deadline check had a real bug: when a node hit the
#   deadline, it did a plain `return` with a fallback value — but that only
#   stops THAT node. Its parent frame is in the middle of a for-loop over
#   its own candidate cards, and a plain return doesn't break that loop; the
#   parent just moves on to its next candidate and recurses again, doing
#   real work (legal-move filtering, equivalence pruning, sorting) before
#   its own check fires. Multiply that across every level of the call stack
#   and the search does NOT actually stop when the deadline is reached — it
#   just gets slower to unwind, node by node, loop by loop.
#
#   The fix: deadline/node-budget hits now raise a dedicated _SearchAbort
#   exception instead of returning a value. Raising unwinds the ENTIRE
#   recursion stack immediately — every pending for-loop at every level is
#   abandoned in one shot, not just the current node — which is the only
#   way to get a real, bounded worst-case stop time in Python.
#
#   On top of that:
#     - A hard, deterministic node cap (MAX_NODES_PER_SEARCH) aborts the
#       search based on a cheap integer comparison alone, with NO reliance
#       on wall-clock precision, timer resolution, or how expensive any one
#       node happens to be. This is checked on every node (not batched)
#       since it's just `int > int`, not a syscall.
#     - The wall-clock deadline is still checked periodically as a second,
#       independent line of defense in case node cost varies wildly.
#     - All budgets were cut substantially (see constants below) since we
#       don't actually know how tight the real external timeout is beyond
#       "the previous margin wasn't enough." When in doubt, use less time.
#     - PIMC_THRESHOLD was lowered so search is only ever attempted with a
#       genuinely small number of cards left, keeping the worst-case tree
#       size (and therefore worst-case pre-first-check cost) small even
#       before any budget check can fire.
#
# ---------------------------------------------------------------------------
# Why this design (unchanged from v2):
#
#   - Declare phase: only the WINNING claim's details ever get published to
#     the engine's public declarations log (engine._resolve_declaration /
#     _claim_summary). A losing claim leaks nothing. So there is never a
#     downside to claiming whenever you hold a valid combination.
#
#   - Trick phase is the real skill test. This engine's PlayerView only ever
#     shows you the CURRENT trick, and only while it's still in progress —
#     so you see your opponent's card when you're the one following, but you
#     never see their response when THEY follow your lead (by the time you
#     act again, the engine has already reset to a fresh empty trick). That
#     means true perfect information about their hand is impossible; instead
#     this bot tracks exactly what it legitimately knows (its own plays and
#     discards, plus any card the opponent has led) and treats everything
#     else as an unseen pool.
#
#   - For the last few tricks of each hand, the bot runs Perfect-Information
#     Monte Carlo (PIMC): it randomly deals the unseen pool into a plausible
#     opponent hand of the correct size, many times, and for each sample
#     solves the rest of the hand EXACTLY with alpha-beta minimax (using
#     card-equivalence pruning, a standard double-dummy trick, to keep the
#     search small). It picks the card with the best average outcome across
#     samples. This correctly accounts for the trick-count bonuses (majority,
#     capot, last-trick) because the search plays out to the true end of the
#     12-trick hand and scores with the same bonus rules as the engine.
#
#   - Earlier tricks (more unresolved cards) fall back to a fast heuristic:
#     play guaranteed winners cheaply, otherwise lead low from the longest
#     suit and duck/beat cheaply when following. Full search that far back
#     is too expensive to safely fit a 2-second move budget.
#
#   - A hard wall-clock budget guards every search so this bot can never be
#     timed out and forfeited, regardless of shuffle or opponent behavior.

import random
import time

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(7, 15))  # 7..14, 14 = Ace
FULL_DECK = [(s, r) for s in SUITS for r in RANKS]

PIMC_THRESHOLD = 5          # search exactly once <= this many cards remain
                             # (lowered from 7 — keeps worst-case tree small)
TIME_BUDGET_SECONDS = 0.35  # per-search budget, cut hard for real margin
TIME_CHECK_EVERY = 16       # how often (in nodes) to check the wall clock
MAX_NODES_PER_SEARCH = 4000  # deterministic hard cap, independent of timer
                              # precision or how expensive any one node is
NEXTMOVE_HARD_DEADLINE = 0.7  # absolute ceiling for the whole nextMove() call


class _SearchAbort(Exception):
    """Raised to unwind the ENTIRE search stack in one shot the moment the
    time or node budget is exceeded — a plain `return` from deep inside the
    recursion only stops the current node, not the ancestors' loops, so it
    can't actually bound worst-case runtime. Raising can."""
    pass

_state = {}  # per-matchup memory: {(your_name, opponent_name): {"seen": set()}}


def nextMove(gameState):
    start_time = time.monotonic()  # single shared clock for this whole call
    key = (gameState.your_name, gameState.opponent_name)
    mem = _state.setdefault(key, {"seen": set()})

    if gameState.phase == "exchange":
        if all(v == 0 for v in gameState.hand_points.values()):
            mem["seen"] = set()  # fresh hand starting
        discard = _exchange_move(gameState)
        mem["seen"].update(discard)
        return discard

    if gameState.phase == "declare":
        return _declare_move(gameState)

    _record_seen(gameState, mem)

    # Trick play is the only phase that runs real search, so it's the only
    # phase that can meaningfully overrun. Guard it end-to-end: try the
    # normal (PIMC-or-heuristic) path, but if anything raises or the hard
    # deadline is already gone, fall back to the cheap heuristic, and if
    # even that can't be trusted, fall back further to a trivial legal
    # move — nextMove must always return, and quickly.
    try:
        card = _trick_move(gameState, mem, start_time)
    except Exception:
        card = None

    if card is None or card not in gameState.your_hand:
        try:
            card = _heuristic_trick_move(gameState, mem)
        except Exception:
            card = None

    if card is None or card not in gameState.your_hand:
        lead_card = gameState.current_trick[0][1] if gameState.current_trick else None
        legal = _legal(gameState.your_hand, lead_card)
        card = legal[0] if legal else gameState.your_hand[0]

    mem["seen"].add(card)
    return card


# ---------------------------------------------------------------------------
# Shared hand-evaluation helpers (self-contained; do not rely on engine.py)
# ---------------------------------------------------------------------------
def _pip(card):
    r = card[1]
    if r == 14:
        return 11
    if r >= 10:
        return 10
    return r


def _best_point_suit(hand):
    by_suit = {s: [] for s in SUITS}
    for c in hand:
        by_suit[c[0]].append(c)
    best_len, best_pips, best_suit = 0, 0, None
    for s, cards in by_suit.items():
        length = len(cards)
        pips = sum(_pip(c) for c in cards)
        if length == 0:
            continue
        if (length, pips) > (best_len, best_pips):
            best_len, best_pips, best_suit = length, pips, s
    return best_len, best_pips, best_suit


def _sequences(hand):
    result = []
    for s in SUITS:
        ranks = sorted({c[1] for c in hand if c[0] == s})
        i = 0
        while i < len(ranks):
            j = i
            while j + 1 < len(ranks) and ranks[j + 1] == ranks[j] + 1:
                j += 1
            if j - i + 1 >= 3:
                run = ranks[i:j + 1]
                result.append((len(run), run[-1], s, [(s, r) for r in run]))
            i = j + 1
    return result


def _sets(hand):
    by_rank = {}
    for c in hand:
        if c[1] >= 10:
            by_rank.setdefault(c[1], []).append(c)
    return [(len(v), r, v) for r, v in by_rank.items() if len(v) >= 3]


def _card_scores(hand):
    scores = {c: 0.0 for c in hand}

    _, _, point_suit = _best_point_suit(hand)
    if point_suit:
        for c in hand:
            if c[0] == point_suit:
                scores[c] += 8 + _pip(c) * 0.5

    for seq_len, _top, _s, cards in _sequences(hand):
        bonus = 12 + seq_len * 2
        for c in cards:
            scores[c] += bonus

    for count, rank, cards in _sets(hand):
        bonus = 10 + count * 4 + (rank - 10) * 2
        for c in cards:
            scores[c] += bonus

    for c in hand:
        scores[c] += (c[1] - 7) * 0.6  # raw trick-taking strength

    return scores


# ---------------------------------------------------------------------------
# Exchange phase
# ---------------------------------------------------------------------------
def _exchange_move(gameState):
    hand = gameState.your_hand

    if gameState.your_name == gameState.elder:
        max_disc = min(5, len(hand))
    else:
        max_disc = min(gameState.talon_remaining or 0, len(hand))

    if max_disc <= 0:
        return []

    scores = _card_scores(hand)
    ranked = sorted(hand, key=lambda c: scores[c])
    return ranked[:max_disc]


# ---------------------------------------------------------------------------
# Declare phase — always claim when you hold something (see notes above)
# ---------------------------------------------------------------------------
def _declare_move(gameState):
    hand = gameState.your_hand
    cat = gameState.declare_category

    if cat == "point":
        length, _pips, _suit = _best_point_suit(hand)
        return ("claim",) if length > 0 else "pass"
    if cat == "sequence":
        return ("claim",) if _sequences(hand) else "pass"
    if cat == "set":
        return ("claim",) if _sets(hand) else "pass"
    return "pass"


# ---------------------------------------------------------------------------
# Trick phase — rules helpers (local copies, no dependency on engine.py)
# ---------------------------------------------------------------------------
def _legal(hand, lead_card):
    if lead_card is None:
        return list(hand)
    same = [c for c in hand if c[0] == lead_card[0]]
    return same if same else list(hand)


def _resolve(lead_card, follow_card):
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card
    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    return True


def _record_seen(gameState, mem):
    for _name, card in gameState.current_trick:
        mem["seen"].add(card)


def _unseen_pool(gameState, mem):
    hand = set(gameState.your_hand)
    seen = mem["seen"]
    return [c for c in FULL_DECK if c not in hand and c not in seen]


def _trick_move(gameState, mem, start_time):
    hand = gameState.your_hand

    # If we've somehow already burned most of the hard deadline before even
    # starting search (slow host, GC pause, whatever), don't gamble on PIMC
    # at all — go straight to the cheap heuristic.
    elapsed = time.monotonic() - start_time
    safety_margin = 0.15
    if elapsed > NEXTMOVE_HARD_DEADLINE - safety_margin:
        return _heuristic_trick_move(gameState, mem)

    if len(hand) <= PIMC_THRESHOLD:
        remaining_budget = NEXTMOVE_HARD_DEADLINE - safety_margin - elapsed
        move = _pimc_move(gameState, mem, start_time, remaining_budget)
        if move is not None:
            return move
    return _heuristic_trick_move(gameState, mem)


# ---------------------------------------------------------------------------
# Fast heuristic (used for early tricks, where exact search is too expensive)
# ---------------------------------------------------------------------------
def _unseen_ranks_in_suit(gameState, mem, suit):
    hand_ranks = {c[1] for c in gameState.your_hand if c[0] == suit}
    seen_ranks = {c[1] for c in mem["seen"] if c[0] == suit}
    return set(RANKS) - hand_ranks - seen_ranks


def _heuristic_trick_move(gameState, mem):
    hand = gameState.your_hand
    trick = gameState.current_trick

    if not trick:
        sure_winners = []
        for c in hand:
            unseen = _unseen_ranks_in_suit(gameState, mem, c[0])
            if not unseen or c[1] > max(unseen):
                sure_winners.append(c)
        if sure_winners:
            return min(sure_winners, key=lambda c: c[1])

        by_suit = {}
        for c in hand:
            by_suit.setdefault(c[0], []).append(c)
        longest_suit = max(by_suit, key=lambda s: len(by_suit[s]))
        return min(by_suit[longest_suit], key=lambda c: c[1])

    lead_card = trick[0][1]
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]

    if same_suit:
        winners = [c for c in same_suit if c[1] > lead_card[1]]
        if winners:
            return min(winners, key=lambda c: c[1])
        return min(same_suit, key=lambda c: c[1])

    return min(hand, key=lambda c: c[1])


# ---------------------------------------------------------------------------
# PIMC endgame solver: sample plausible opponent hands, solve each exactly.
# ---------------------------------------------------------------------------
def _prune_equivalent(candidates, opponent_hand):
    """Collapse cards that are provably interchangeable given the opponent's
    known remaining cards in this sample (standard double-dummy pruning)."""
    if len(candidates) <= 1:
        return candidates

    by_suit = {}
    for c in candidates:
        by_suit.setdefault(c[0], []).append(c)

    result = []
    for suit, cards in by_suit.items():
        opp_ranks = sorted(r for (s, r) in opponent_hand if s == suit)
        cards_sorted = sorted(cards, key=lambda c: c[1])
        group = [cards_sorted[0]]
        for prev, cur in zip(cards_sorted, cards_sorted[1:]):
            if any(prev[1] < r < cur[1] for r in opp_ranks):
                result.append(group[0])
                group = [cur]
            else:
                group.append(cur)
        result.append(group[0])
    return result


def _final_points(tricks_won, last_winner, me, opp):
    pts = {}
    for name in (me, opp):
        p = tricks_won[name]
        if name == last_winner:
            p += 1
        pts[name] = p
    if tricks_won[me] > tricks_won[opp]:
        w = me
    elif tricks_won[opp] > tricks_won[me]:
        w = opp
    else:
        return pts
    wc = tricks_won[w]
    if wc == 12:
        pts[w] += 40
    elif wc >= 7:
        pts[w] += 10
    return pts


def _play(hands, tricks_won, last_winner, turn, lead_card, alpha, beta,
          me, opp, deadline, node_counter):
    """Alpha-beta search over the remaining tricks.

    `hands` and `tricks_won` are mutated in place and always restored before
    returning (backtracking search), instead of being copied at every node —
    this is the main speedup over the naive copy-everywhere version.

    Raises _SearchAbort the instant the node cap or wall-clock deadline is
    exceeded, which unwinds the WHOLE call stack immediately — this is the
    only way to get a real bound on worst-case time (a plain early `return`
    only stops the current node; ancestors' for-loops keep going).
    """
    if not hands[me] and not hands[opp]:
        pts = _final_points(tricks_won, last_winner, me, opp)
        return pts[me] - pts[opp]

    node_counter[0] += 1
    if node_counter[0] > MAX_NODES_PER_SEARCH:
        raise _SearchAbort()
    if node_counter[0] % TIME_CHECK_EVERY == 0 and time.monotonic() > deadline:
        raise _SearchAbort()

    other = opp if turn == me else me
    turn_hand = hands[turn]
    candidates = _legal(turn_hand, lead_card)
    candidates = _prune_equivalent(candidates, hands[other])

    maximizing = turn == me
    # Move ordering: try the most promising cards first so alpha-beta prunes
    # more aggressively (higher cards first for the maximizer, lower first
    # for the minimizer — a cheap but effective heuristic ordering).
    candidates.sort(key=lambda c: c[1], reverse=maximizing)

    best_val = -10 ** 9 if maximizing else 10 ** 9

    for card in candidates:
        turn_hand.remove(card)

        try:
            if lead_card is None:
                val = _play(hands, tricks_won, last_winner, other, card,
                            alpha, beta, me, opp, deadline, node_counter)
            else:
                leader = other
                leader_wins = _resolve(lead_card, card)
                winner = leader if leader_wins else turn
                tricks_won[winner] += 1
                try:
                    val = _play(hands, tricks_won, winner, winner, None,
                                alpha, beta, me, opp, deadline, node_counter)
                finally:
                    tricks_won[winner] -= 1
        finally:
            turn_hand.append(card)  # restore — even if we're about to raise

        if maximizing:
            if val > best_val:
                best_val = val
            if best_val > alpha:
                alpha = best_val
        else:
            if val < best_val:
                best_val = val
            if best_val < beta:
                beta = best_val
        if alpha >= beta:
            break

    return best_val


def _sample_count(remaining):
    # Rescaled for the lower PIMC_THRESHOLD (5): fewer cards left means a
    # much smaller tree, so more samples fit in the same tight budget.
    if remaining <= 2:
        return 40
    if remaining <= 3:
        return 22
    return 12


def _pimc_move(gameState, mem, start_time, remaining_budget):
    hand = gameState.your_hand
    me = gameState.your_name
    opp = gameState.opponent_name
    trick = gameState.current_trick
    lead_card = trick[0][1] if trick else None

    legal = _legal(hand, lead_card)
    if len(legal) <= 1:
        return legal[0] if legal else None

    pool = _unseen_pool(gameState, mem)
    opp_remaining = max(0, 12 - sum(gameState.tricks_won.values()))
    opp_remaining = min(opp_remaining, len(pool))

    samples = _sample_count(len(hand))

    # The search deadline is whichever is tighter: the per-search budget, or
    # what's actually left of the whole-call hard deadline.
    per_search_budget = min(TIME_BUDGET_SECONDS, max(0.0, remaining_budget))
    deadline = time.monotonic() + per_search_budget
    node_counter = [0]

    totals = {c: 0.0 for c in legal}
    completed = 0

    my_hand_list = list(hand)  # one mutable working copy, reused every sample

    try:
        for _ in range(samples):
            if time.monotonic() > deadline:
                break
            opp_hand = random.sample(pool, opp_remaining) if opp_remaining else []
            tw0 = dict(gameState.tricks_won)
            hands = {me: my_hand_list, opp: opp_hand}

            sample_totals = {}
            for card in legal:
                my_hand_list.remove(card)
                try:
                    if lead_card is None:
                        val = _play(hands, dict(tw0), None, opp, card,
                                    -10 ** 9, 10 ** 9, me, opp, deadline,
                                    node_counter)
                    else:
                        leader_wins = _resolve(lead_card, card)
                        winner = opp if leader_wins else me
                        tw = dict(tw0)
                        tw[winner] += 1
                        val = _play(hands, tw, winner, winner, None,
                                    -10 ** 9, 10 ** 9, me, opp, deadline,
                                    node_counter)
                finally:
                    my_hand_list.append(card)  # restore no matter what
                sample_totals[card] = val

            # Only a fully-evaluated sample counts, so partial data never
            # unfairly favors whichever candidates happened to run first.
            for card, val in sample_totals.items():
                totals[card] += val
            completed += 1
    except _SearchAbort:
        # Node budget or deadline blown mid-search. hands/tricks_won are
        # already fully restored by the try/finally chain above and inside
        # _play, so it's always safe to just stop here and use whatever
        # complete samples we already gathered.
        pass

    if completed == 0:
        return None

    return max(legal, key=lambda c: totals[c])