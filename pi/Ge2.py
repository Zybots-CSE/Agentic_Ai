"""
zybots.py - Advanced Piquet Engine Competitor

Strategic Enhancements:
1. Dynamic Card Evaluation: Scores retention based on exact Piquet combination rules 
   (Point length/pips, Sequence potential, 10+ Set depth) and card boss values.
2. Intelligent Exchange:
   - Elder: Aggressively sheds weak non-boss cards to maximize drawing from stock.
   - Younger: Evaluates stock depth left after Elder's exchange to selectively cycle weak cards.
3. Perfect Declaration Validation: Directly invokes engine comparison primitives to eliminate 
   illegal claims while guaranteeing high-scoring declarations are claimed.
4. Strategic Trick Engine:
   - Tracks trick-level tempo: leads boss cards to establish long suits and extract opponent cards.
   - Smart Follow: Ducks minimally when unable to win, or overtakes with the lowest possible winning card.
"""

from engine import best_point, best_sequence, best_set

# ---------------------------------------------------------------------------
# Card & Hand Analytics
# ---------------------------------------------------------------------------
def _eval_card(card, hand):
    """Calculates tactical value of holding a card based on combination potential."""
    suit, rank = card
    score = rank * 2.5  # High rank priority for tricks and pips
    
    same_suit = [c for c in hand if c[0] == suit]
    suit_len = len(same_suit)
    score += suit_len * 4.0  # Point category priority

    # Sequence potential (connected ranks in same suit)
    ranks_in_suit = {c[1] for c in same_suit}
    if (rank + 1 in ranks_in_suit) or (rank - 1 in ranks_in_suit):
        score += 7.0

    # Set potential (3 or 4 of a kind, 10-Ace)
    if rank >= 10:
        same_rank = [c for c in hand if c[1] == rank]
        if len(same_rank) >= 3:
            score += 30.0
        elif len(same_rank) == 2:
            score += 10.0

    return score


def _get_suit_groups(hand):
    groups = {s: [] for s in ["H", "D", "C", "S"]}
    for card in hand:
        groups[card[0]].append(card)
    return groups


# ---------------------------------------------------------------------------
# Phase Handlers
# ---------------------------------------------------------------------------
def _exchange(gameState):
    hand = list(gameState.your_hand)
    is_elder = (gameState.your_name == gameState.elder)
    
    if is_elder:
        max_discard = min(5, len(hand))
    else:
        max_discard = min(gameState.talon_remaining or 0, len(hand))

    if max_discard == 0:
        return []

    # Sort cards by retention score ascending (weakest first)
    card_scores = [(card, _eval_card(card, hand)) for card in hand]
    card_scores.sort(key=lambda x: x[1])

    discards = []
    # Elder should draw heavily to rebuild hand; Younger discards lower-tier cards selectively
    min_discard = 3 if is_elder else 0
    
    for card, score in card_scores:
        if len(discards) >= max_discard:
            break
        if score < 42.0 or len(discards) < min_discard:
            discards.append(card)

    return discards


def _declare(gameState):
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

    # 1. Lead Trick Strategy
    if not current_trick:
        suit_groups = _get_suit_groups(hand)
        
        # Priority: Lead high/boss cards from long suits (3+ cards)
        long_suits = sorted(
            [s for s in suit_groups if suit_groups[s]],
            key=lambda s: (len(suit_groups[s]), max(c[1] for c in suit_groups[s])),
            reverse=True
        )
        
        for suit in long_suits:
            cards = suit_groups[suit]
            if len(cards) >= 3:
                # Lead highest rank card in the suit
                return max(cards, key=lambda c: c[1])

        # Fallback: Play highest card overall
        return max(hand, key=lambda c: c[1])

    # 2. Follow Trick Strategy
    lead_player, lead_card = current_trick[0]
    lead_suit, lead_rank = lead_card
    same_suit = [c for c in hand if c[0] == lead_suit]

    if same_suit:
        winning_cards = [c for c in same_suit if c[1] > lead_rank]
        if winning_cards:
            # Win trick efficiently with lowest winning card
            return min(winning_cards, key=lambda c: c[1])
        else:
            # Duck with lowest card in led suit
            return min(same_suit, key=lambda c: c[1])
    else:
        # Off-suit discard: discard lowest retention-value card
        return min(hand, key=lambda c: _eval_card(c, hand))


# ---------------------------------------------------------------------------
# Tournament Entry Point
# ---------------------------------------------------------------------------
def nextMove(gameState):
    phase = gameState.phase
    if phase == "exchange":
        return _exchange(gameState)
    if phase == "declare":
        return _declare(gameState)
    return _trick(gameState)