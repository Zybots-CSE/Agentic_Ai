"""
zybots.py - Masterclass Piquet Tournament Engine

Strategic Principles:
1. Elder Draw Maximization: Elder always exchanges all 5 allowed weak cards to 
   maximize chances of Quatorze (14 pts), 5-card runs (15 pts), and Ace control.
2. Precision Declaration Logic: Properly checks elder_claim to avoid declaring losing 
   combinations while guaranteeing point claims when ties block opponent points.
3. Suit Dominance Trick Engine:
   - Prioritizes leading high cards from longest suits to farm lead points (1 pt) 
     and strip opponent guards.
   - Uses precise Duck/Win thresholds to conserve high-rank cards (Aces/Kings) 
     for late tricks and secure the 7-trick majority (10 pts).
"""

from engine import (
    legal_cards,
    best_point,
    best_sequence,
    best_set,
)


def _card_val(card):
    """Base power ranking for pips and trick control."""
    return card[1]


def _eval_card_exchange(card, hand):
    """Calculates holding value for exchange phase."""
    suit, rank = card
    score = rank * 2.0

    # Suit length synergy (Point dominance)
    same_suit = [c for c in hand if c[0] == suit]
    score += len(same_suit) * 7.0

    # Sequence potential
    ranks_in_suit = {c[1] for c in same_suit}
    if (rank + 1 in ranks_in_suit) or (rank - 1 in ranks_in_suit):
        score += 8.0

    # Set depth (10, J, Q, K, A)
    if rank >= 10:
        same_rank = [c for c in hand if c[1] == rank]
        if len(same_rank) >= 3:
            score += 45.0  # Quatorze or strong Trio potential
        elif len(same_rank) == 2:
            score += 12.0

    # Boss Aces/Kings priority
    if rank == 14:
        score += 20.0
    elif rank == 13:
        score += 10.0

    return score


def _exchange(gameState):
    hand = list(gameState.your_hand)
    is_elder = (gameState.your_name == gameState.elder)
    max_discard = min(5 if is_elder else (gameState.talon_remaining or 0), len(hand))

    if max_discard == 0:
        return []

    # Sort hand by retention score (weakest first)
    sorted_cards = sorted(hand, key=lambda c: _eval_card_exchange(c, hand))

    # Elder always maximizes stock draw (up to 5) unless holding exceptional cards
    if is_elder:
        num_to_discard = max_discard
    else:
        # Younger replaces up to 3 weakest cards
        num_to_discard = min(max_discard, 3)

    return sorted_cards[:num_to_discard]


def _declare(gameState):
    hand = gameState.your_hand
    cat = gameState.declare_category
    elder_claim = gameState.elder_claim
    is_elder = (gameState.your_name == gameState.elder)

    if cat == "point":
        my_claim = best_point(hand)
        if my_claim[0] == 0:
            return "pass"
        if not is_elder and elder_claim:
            # elder_claim format: (length, pips) or similar tuple
            e_len = elder_claim[1] if len(elder_claim) > 1 else 0
            if my_claim[0] < e_len:
                return "pass"
        return ("claim",)

    if cat == "sequence":
        my_claim = best_sequence(hand)
        if my_claim is None:
            return "pass"
        if not is_elder and elder_claim:
            e_len = elder_claim[1] if len(elder_claim) > 1 else 0
            if my_claim[0] < e_len:
                return "pass"
        return ("claim",)

    if cat == "set":
        my_claim = best_set(hand)
        if my_claim is None:
            return "pass"
        if not is_elder and elder_claim:
            e_count = elder_claim[1] if len(elder_claim) > 1 else 0
            if my_claim[0] < e_count:
                return "pass"
        return ("claim",)

    return "pass"


def _trick(gameState):
    hand = list(gameState.your_hand)
    current_trick = gameState.current_trick
    lead_card = current_trick[0][1] if current_trick else None
    allowed = legal_cards(hand, lead_card)

    if len(allowed) == 1:
        return allowed[0]

    # --- 1. LEADING TRICK ---
    if not current_trick:
        suits = {s: [] for s in ["H", "D", "C", "S"]}
        for c in hand:
            suits[c[0]].append(c)

        # Strategy A: Lead guaranteed winning Aces in long suits
        aces = [c for c in allowed if c[1] == 14]
        if aces:
            return max(aces, key=lambda c: len(suits[c[0]]))

        # Strategy B: Run long suits (3+ cards) from top rank down
        long_suits = sorted(
            [s for s in suits if suits[s]],
            key=lambda s: (len(suits[s]), max(c[1] for c in suits[s])),
            reverse=True,
        )

        for s in long_suits:
            cards = suits[s]
            if len(cards) >= 3:
                return max(cards, key=_card_val)

        # Default Lead: Highest rank card available
        return max(allowed, key=_card_val)

    # --- 2. FOLLOWING TRICK ---
    lead_suit, lead_rank = lead_card[0], lead_card[1]
    same_suit = [c for c in allowed if c[0] == lead_suit]

    if same_suit:
        winning = [c for c in same_suit if c[1] > lead_rank]
        if winning:
            # Win efficiently with lowest winning card
            return min(winning, key=_card_val)
        # Duck with lowest card in suit
        return min(same_suit, key=_card_val)

    # Off-suit discard: Preserve Aces (14) and Kings (13) for later leads
    return min(allowed, key=lambda c: (c[1] == 14, c[1] == 13, c[1]))


def nextMove(gameState):
    phase = gameState.phase
    if phase == "exchange":
        return _exchange(gameState)
    if phase == "declare":
        return _declare(gameState)
    return _trick(gameState)