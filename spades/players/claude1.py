import math


def nextMove(gameState):
    try:
        if gameState.phase == "bid":
            return _choose_bid(gameState)
        return _play_card(gameState)
    except Exception:
        if gameState.phase == "bid":
            return 1
        return _fallback(gameState)


# ---------------------------------------------------------------------------
# Bidding
# ---------------------------------------------------------------------------

def _suit_ranks(suit):
    return range(2, 15) if suit in ("S", "H") else range(3, 15)


def _p_opponent_has_none(higher_count, unseen, opp_size):
    """Probability none of *higher_count* specific unseen cards are in the
    opponent's *opp_size*-card hand, given *unseen* total unseen cards.

    The kitty (24 cards) never gets played, so only ~1/3 of unseen cards are
    ever actually in the opponent's hand — most "dangerous" higher cards
    never show up. That's why decent (not just top) cards win tricks here.
    """
    if higher_count <= 0:
        return 1.0
    if higher_count > unseen - opp_size:
        return 0.0
    return math.comb(unseen - higher_count, opp_size) / math.comb(unseen, opp_size)


def _estimate_tricks(hand):
    unseen = 50 - len(hand)
    opp_size = 13

    by_suit = {"S": [], "H": [], "D": [], "C": []}
    for suit, rank in hand:
        by_suit[suit].append(rank)

    spade_count = len(by_suit["S"])
    est = 0.0

    for suit, ranks in by_suit.items():
        for r in ranks:
            higher_outside = sum(1 for x in _suit_ranks(suit) if x > r and x not in ranks)
            p_clear = _p_opponent_has_none(higher_outside, unseen, opp_size)
            if suit == "S":
                est += p_clear
            else:
                # Even if no higher card of the suit exists in their hand,
                # a void opponent can still trump it — small discount.
                trump_risk = 0.12 if spade_count else 0.0
                est += p_clear * (1 - trump_risk)

        if suit != "S" and spade_count:
            if not ranks:
                est += 0.5  # void: likely to get a ruff in eventually
            elif len(ranks) == 1:
                est += 0.25  # singleton: probably ruffable after one round

    # Calibration: "no higher card in the opponent's hand" per card understates
    # real trick counts, because the two hands are dealt symmetrically from the
    # same pool, so average tricks across a hand must converge to 6.5 (half of
    # 13), not the ~3.4 the raw per-card sum produces. Scale to match reality.
    return est * 1.9


def _nil_safe(hand):
    est = _estimate_tricks(hand)
    spade_count = sum(1 for s, _ in hand if s == "S")
    return est <= 1.7 and spade_count <= 5


def _choose_bid(gs):
    hand = gs.your_hand
    est = _estimate_tricks(hand)

    if est <= 2.8 and _nil_safe(hand):
        return 0

    # Missing a bid costs bid*10; an overtrick only costs 1 point (plus a
    # bag). Bidding at the raw expectation misses ~50% of the time, so shade
    # the bid below the expected trick count to trade a few cheap overtricks
    # for far fewer expensive misses.
    bid = max(1, min(13, int(round(est - 1.6))))

    # Close to the bag penalty: round up rather than risk overtricks.
    if gs.your_bags >= 8 and bid < 13 and (est - int(est)) > 0.15:
        bid += 1

    return bid


# ---------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------

def _legal_moves(hand, trick, spades_broken):
    if not trick:
        non_spades = [c for c in hand if c[0] != "S"]
        if not non_spades or spades_broken:
            return list(hand)
        return non_spades
    lead_suit = trick[0][1][0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def _beats(lead, candidate):
    ls, lr = lead
    cs, cr = candidate
    if cs == "S" and ls != "S":
        return True
    if ls == "S":
        return cs == "S" and cr > lr
    if cs == ls:
        return cr > lr
    return False


def _card_value(card):
    suit, rank = card
    return rank + (20 if suit == "S" else 0)


def _play_card(gs):
    hand = gs.your_hand
    trick = gs.current_trick
    legal = _legal_moves(hand, trick, gs.spades_broken)
    if len(legal) == 1:
        return legal[0]

    played = set()
    opp_voids = set()
    for t in gs.trick_history:
        (leader, lead_card), (follower, follow_card) = t["plays"]
        played.add(lead_card)
        played.add(follow_card)
        if follow_card[0] != lead_card[0] and follower == gs.opponent_name:
            opp_voids.add(lead_card[0])
    if trick:
        played.add(trick[0][1])

    need_tricks = gs.tricks_won.get(gs.your_name, 0) < gs.your_bid

    def outstanding(suit):
        return [r for r in range(2, 15) if (suit, r) not in played and (suit, r) not in hand]

    spades_gone = not outstanding("S")

    def is_safe_boss(card):
        suit, rank = card
        if any(r > rank for r in outstanding(suit)):
            return False
        return suit == "S" or "S" in opp_voids or spades_gone

    if not trick:
        return _lead(legal, need_tricks, opp_voids, is_safe_boss)

    lead_card = trick[0][1]
    return _follow(legal, lead_card, need_tricks)


def _lead(legal, need_tricks, opp_voids, is_safe_boss):
    if need_tricks:
        bosses = [c for c in legal if is_safe_boss(c)]
        if bosses:
            return max(bosses, key=lambda c: c[1])
        pool = [c for c in legal if c[0] != "S"] or legal
        return max(pool, key=lambda c: c[1])

    # Trying to lose this trick: lead low in a suit the opponent can follow,
    # since a suit they're void in lets them trump us for free.
    safe = [c for c in legal if c[0] not in opp_voids]
    if safe:
        pool = [c for c in safe if c[0] != "S"] or safe
        return min(pool, key=lambda c: c[1])
    return max(legal, key=_card_value)


def _follow(legal, lead_card, need_tricks):
    winners = [c for c in legal if _beats(lead_card, c)]
    losers = [c for c in legal if c not in winners]

    if need_tricks:
        if winners:
            return min(winners, key=_card_value)
        return min(losers, key=_card_value)

    if losers:
        return max(losers, key=_card_value)
    return max(winners, key=_card_value)  # forced to win: shed the priciest card


def _fallback(gs):
    hand, trick = gs.your_hand, gs.current_trick
    if trick:
        same = [c for c in hand if c[0] == trick[0][1][0]]
        if same:
            return same[0]
    if not gs.spades_broken:
        non_spades = [c for c in hand if c[0] != "S"]
        if non_spades:
            return non_spades[0]
    return hand[0]