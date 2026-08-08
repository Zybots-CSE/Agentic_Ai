"""
Apex-Prob Spades Player (2-player, kitty variant)
---------------------------------------------------
Merges the probabilistic, kitty-aware trick/bid estimation from the
second implementation with the void-tracking, boss-card, and
nil-busting play heuristics from the first. Also fixes a few
correctness issues found in both originals (see inline notes).
"""

import math


def nextMove(gameState):
    """
    Tournament entry point. Wrapped in a failsafe so a bug never causes
    a forfeit: on any exception we fall back to the simplest guaranteed
    legal action instead of crashing.
    """
    try:
        if gameState.phase == "bid":
            return _choose_bid(gameState)
        return _play_card(gameState)
    except Exception:
        if gameState.phase == "bid":
            return _fallback_bid(gameState)
        return _fallback_card(gameState)


# ---------------------------------------------------------------------------
# Bidding: probability-weighted trick estimation
# ---------------------------------------------------------------------------

def _suit_ranks(suit):
    # Spades and Hearts run 2-14 here; Diamonds/Clubs start at 3 in this
    # variant's deck (kept from the original — do not "fix" without
    # confirming against the actual deck construction).
    return range(2, 15) if suit in ("S", "H") else range(3, 15)


def _p_opponent_has_none(higher_count, unseen, opp_size):
    """
    Probability that none of `higher_count` specific unseen cards are in
    the opponent's `opp_size`-card hand, given `unseen` total unseen cards.
    The kitty never gets played, so only a fraction of unseen cards are
    ever actually live in the opponent's hand.
    """
    if higher_count <= 0:
        return 1.0
    if higher_count > unseen - opp_size:
        return 0.0
    return math.comb(unseen - higher_count, opp_size) / math.comb(unseen, opp_size)


def _estimate_tricks(hand, unseen_total=None, opp_size=13):
    unseen = unseen_total if unseen_total is not None else 50 - len(hand)

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
                # Even with no higher card of the suit live, a void
                # opponent can still trump it.
                trump_risk = 0.12 if spade_count else 0.0
                est += p_clear * (1 - trump_risk)

        if suit != "S" and spade_count:
            if not ranks:
                est += 0.5   # void: likely to score a ruff eventually
            elif len(ranks) == 1:
                est += 0.25  # singleton: probably ruffable after one round

    # Calibration: raw per-card sum understates true expected tricks
    # (both hands are dealt symmetrically from the same pool, so the
    # average must converge to half the tricks in play). Scale to match.
    return est * 1.9


def _nil_safe(hand):
    """
    Belt-and-suspenders nil check: the probabilistic estimate must be low
    AND we must not be holding a card that is individually too dangerous
    to nil with (any card above 10, or a spade above 9).
    """
    est = _estimate_tricks(hand)
    spade_count = sum(1 for s, _ in hand if s == "S")
    if est > 1.7 or spade_count > 5:
        return False
    for suit, rank in hand:
        if rank > 10 or (suit == "S" and rank > 9):
            return False
    return True


def _choose_bid(gs):
    hand = gs.your_hand
    bags = gs.your_bags
    est = _estimate_tricks(hand)

    if est <= 2.8 and _nil_safe(hand):
        # Nil is only ever worth it while not already deep in bags —
        # an accidental trick on nil is expensive, and so is stacking
        # bags on top of it.
        if bags < 8:
            return 0

    # Missing a bid costs far more than an overtrick, so shade the bid
    # below the raw expectation to trade cheap overtricks for fewer
    # expensive misses.
    bid = max(1, min(13, int(round(est - 1.6))))

    # Close to the bag penalty threshold: round up rather than risk
    # overtricks pushing us over.
    if bags >= 8 and bid < 13 and (est - int(est)) > 0.15:
        bid += 1

    return bid


def _fallback_bid(gs):
    # Simplest guaranteed-legal bid: count our obvious high cards, bid at
    # least 1. Guarded so this can never itself raise.
    try:
        return max(1, sum(1 for c in gs.your_hand if c[1] >= 11))
    except Exception:
        return 1  # always a legal bid regardless of what gs looks like


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


def _track_state(gs, trick):
    """Reconstruct played cards and opponent void suits from trick history."""
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
    return played, opp_voids


def _play_card(gs):
    hand = gs.your_hand
    trick = gs.current_trick
    legal = _legal_moves(hand, trick, gs.spades_broken)
    if len(legal) == 1:
        return legal[0]

    played, opp_voids = _track_state(gs, trick)

    my_bid = gs.your_bid
    my_tricks = gs.tricks_won.get(gs.your_name, 0)
    need_tricks = my_tricks < my_bid

    opp_bid = gs.opponent_bid
    opp_tricks = gs.tricks_won.get(gs.opponent_name, 0)
    # Opponent is nil and hasn't broken it yet: forcing them to take even
    # one trick is usually worth far more than us grinding out one more
    # trick of our own, so we deprioritize winning and play to feed them
    # the trick instead.
    bust_nil = (opp_bid == 0 and opp_tricks == 0)
    if bust_nil:
        need_tricks = False

    def outstanding(suit):
        return [r for r in range(2, 15) if (suit, r) not in played and (suit, r) not in hand]

    spades_gone = not outstanding("S")

    def is_safe_boss(card):
        suit, rank = card
        if any(r > rank for r in outstanding(suit)):
            return False
        # Guaranteed winner if it's the top spade, or if the opponent is
        # already known void in this suit (or all spades are gone so
        # nothing can trump it).
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

    # Trying to lose this trick: lead low in a suit the opponent can
    # follow — leading a suit they're void in just lets them trump us
    # for free and win anyway (while we also lose our card for nothing).
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
            return min(winners, key=_card_value)  # win as cheaply as possible
        return min(losers, key=_card_value)        # can't win: dump the cheapest

    if losers:
        return max(losers, key=_card_value)         # safely dump the priciest loser
    return max(winners, key=_card_value)             # forced to win: shed the priciest card


def _fallback_card(gs):
    """
    Ultimate failsafe: must NEVER itself raise, or the outer try/except
    can't save us from a forfeit. Every attribute access is guarded.
    """
    try:
        hand = gs.your_hand
    except Exception:
        return None  # nothing we can safely construct without a hand
    try:
        trick = gs.current_trick
    except Exception:
        trick = None
    try:
        if trick:
            same = [c for c in hand if c[0] == trick[0][1][0]]
            if same:
                return same[0]
    except Exception:
        pass
    try:
        if not gs.spades_broken:
            non_spades = [c for c in hand if c[0] != "S"]
            if non_spades:
                return non_spades[0]
    except Exception:
        pass
    try:
        return hand[0]
    except Exception:
        return None
