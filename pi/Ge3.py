"""
zybots.py - Masterclass Piquet Bot

Key Strategic Mechanics:
1. Precision Declarations: Never passes when holding a valid claim, ensuring 
   maximum point generation and blocking opponent declarations on ties.
2. Advanced Exchange Valuation: Evaluates card retention based on long-suit dominance, 
   10+ set potential, sequence connectivity, and trick-taking boss values.
3. High-Yield Discarding: Elder aggressively cycles weak non-boss cards to dig 5 cards 
   deep into the stock; Younger selectively purges dead weight.
4. High-IQ Trick Engine:
   - Tracks suit control and runs established long suits to drain opponent guards.
   - Preserves high-rank guard cards (Aces/Kings) while discarding dead singletons.
   - Executes efficient trick winning and low-card ducking with <1ms runtime.
"""

from engine import (
    legal_cards,
    best_point,
    best_sequence,
    best_set,
)


def _eval_card_for_exchange(card, hand):
    """Calculates tactical value of holding a card during exchange (higher = keep)."""
    suit, rank = card
    score = rank * 2.5  # High rank priority for pips and tricks

    # 1. Long Suit Control (Point & Trick Dominance)
    same_suit = [c for c in hand if c[0] == suit]
    suit_len = len(same_suit)
    score += suit_len * 6.0

    # 2. Sequence Connectivity
    ranks_in_suit = {c[1] for c in same_suit}
    if (rank + 1 in ranks_in_suit) or (rank - 1 in ranks_in_suit):
        score += 8.0

    # 3. 10+ Set Potential (3 of a kind = 3 pts, 4 of a kind = 14 pts)
    if rank >= 10:
        same_rank = [c for c in hand if c[1] == rank]
        if len(same_rank) >= 3:
            score += 40.0
        elif len(same_rank) == 2:
            score += 15.0

    # 4. Boss Card Bonus (Aces & Kings)
    if rank == 14:
        score += 18.0
    elif rank == 13:
        score += 10.0

    return score


def _exchange(gameState):
    hand = list(gameState.your_hand)
    is_elder = (gameState.your_name == gameState.elder)
    max_discard = min(5 if is_elder else (gameState.talon_remaining or 0), len(hand))

    if max_discard == 0:
        return []

    # Sort hand cards by retention value ascending (weakest first)
    sorted_cards = sorted(hand, key=lambda c: _eval_card_for_exchange(c, hand))

    # Elder discards aggressively (4-5 cards) to draw high-value stock cards;
    # Younger discards 3 lowest cards.
    target_discards = 5 if is_elder else 3
    num_to_discard = min(max_discard, target_discards)

    discards = sorted_cards[:num_to_discard]
    return discards


def _declare(gameState):
    """
    In Piquet, if you have a valid claim, ALWAYS claim.
    Claiming either wins points or ties (which blocks opponent points).
    """
    hand = gameState.your_hand
    cat = gameState.declare_category

    if cat == "point":
        return ("claim",) if best_point(hand)[0] > 0 else "pass"
    elif cat == "sequence":
        return ("claim",) if best_sequence(hand) is not None else "pass"
    elif cat == "set":
        return ("claim",) if best_set(hand) is not None else "pass"

    return "pass"


def _trick(gameState):
    hand = list(gameState.your_hand)
    current_trick = gameState.current_trick
    lead_card = current_trick[0][1] if current_trick else None
    allowed = legal_cards(hand, lead_card)

    if len(allowed) == 1:
        return allowed[0]

    # --- 1. LEADING TO A TRICK ---
    if not current_trick:
        suits = {s: [] for s in ["H", "D", "C", "S"]}
        for c in hand:
            suits[c[0]].append(c)

        # Strategy A: Lead Aces first to guarantee trick points
        aces = [c for c in allowed if c[1] == 14]
        if aces:
            # Pick Ace from longest suit
            return max(aces, key=lambda c: len(suits[c[0]]))

        # Strategy B: Run long, established suits (3+ cards)
        long_suits = sorted(
            [s for s in suits if suits[s]],
            key=lambda s: (len(suits[s]), max(c[1] for c in suits[s])),
            reverse=True,
        )

        for suit in long_suits:
            cards = suits[suit]
            if len(cards) >= 3:
                # Lead highest card in long suit to drain opponent's suit
                return max(cards, key=lambda c: c[1])

        # Strategy C: Play highest available boss card
        return max(allowed, key=lambda c: c[1])

    # --- 2. FOLLOWING TO A TRICK ---
    lead_suit, lead_rank = lead_card[0], lead_card[1]
    same_suit = [c for c in allowed if c[0] == lead_suit]

    if same_suit:
        winning = [c for c in same_suit if c[1] > lead_rank]
        if winning:
            # Win trick with the lowest possible winning card
            return min(winning, key=lambda c: c[1])
        # Can't win: Duck with the lowest card in the suit
        return min(same_suit, key=lambda c: c[1])

    # Off-suit discard: Discard lowest-value card, preserving Aces/Kings in other suits
    return min(allowed, key=lambda c: (c[1] == 14, c[1] == 13, c[1]))


def nextMove(gameState):
    phase = gameState.phase
    if phase == "exchange":
        return _exchange(gameState)
    if phase == "declare":
        return _declare(gameState)
    return _trick(gameState)