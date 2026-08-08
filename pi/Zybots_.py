# Apex Piquet player — strategic exchange, optimal declarations, tracked trick play.
#
# Strategy notes:
#   - Declare phase: only the WINNING claim's details are ever revealed to the
#     engine's public `declarations` log (see engine._resolve_declaration /
#     _claim_summary). A losing claim leaks nothing. So there is never a
#     downside to claiming whenever you hold a valid combination — this bot
#     always does, and never passes with something to show.
#   - Exchange phase: cards are scored by how much they contribute to your
#     best point-suit, best sequence, and best set, plus a small baseline for
#     raw trick-taking strength (high cards win tricks). The weakest-scoring
#     cards are discarded up to the maximum allowed each turn.
#   - Trick phase: the bot remembers every card it has seen played this hand
#     (built up call-by-call from `current_trick`, since it acts every trick).
#     Combined with its own hand, this tells it exactly which cards of a suit
#     are still unaccounted for (i.e. must be in the opponent's hand or yet
#     to be played). It leads guaranteed winners cheaply, otherwise leads low
#     from its longest suit; when following it wins as cheaply as possible or
#     ducks with its lowest card if it can't beat the lead.

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(7, 15))  # 7..14, 14 = Ace

_state = {}  # per-matchup memory: {(your_name, opponent_name): {"seen": set()}}


def nextMove(gameState):
    key = (gameState.your_name, gameState.opponent_name)
    mem = _state.setdefault(key, {"seen": set()})

    if gameState.phase == "exchange":
        if all(v == 0 for v in gameState.hand_points.values()):
            mem["seen"] = set()  # fresh hand starting
        return _exchange_move(gameState)

    if gameState.phase == "declare":
        return _declare_move(gameState)

    _record_seen(gameState, mem)
    return _trick_move(gameState, mem)


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
    """All runs of 3+ per suit: (length, top_rank, suit, cards)."""
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
    """All 3/4-of-a-kind among rank >= 10: (count, rank, cards)."""
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
# Trick phase
# ---------------------------------------------------------------------------
def _record_seen(gameState, mem):
    for _name, card in gameState.current_trick:
        mem["seen"].add(card)


def _unseen_ranks_in_suit(gameState, mem, suit):
    hand_ranks = {c[1] for c in gameState.your_hand if c[0] == suit}
    seen_ranks = {c[1] for c in mem["seen"] if c[0] == suit}
    return set(RANKS) - hand_ranks - seen_ranks


def _trick_move(gameState, mem):
    hand = gameState.your_hand
    trick = gameState.current_trick

    if not trick:
        # Leading: play a guaranteed winner (lowest such card, to save big
        # cards for later) if one exists; otherwise lead low from our
        # longest suit to preserve strength and draw out the opponent.
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

    # Following: must follow suit if possible.
    lead_card = trick[0][1]
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]

    if same_suit:
        winners = [c for c in same_suit if c[1] > lead_card[1]]
        if winners:
            return min(winners, key=lambda c: c[1])  # win as cheaply as possible
        return min(same_suit, key=lambda c: c[1])  # can't win, duck low

    # Void in the led suit: discard our overall weakest card.
    return min(hand, key=lambda c: c[1])