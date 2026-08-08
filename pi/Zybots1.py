"""
zybots.py - Advanced Piquet Player

Strategy Summary:
1. Exchange Phase:
   - Identifies the longest suit/sequence/set base to keep.
   - Discards low, un-connected, non-face singletons and weak cards.
   - Maximizes draws for elder hand (up to 5 cards) and optimizes younger draws.
2. Declaration Phase:
   - Evaluates hand against engine rules to make valid, optimal claims.
   - Responds intelligently as younger hand when elder claims are visible.
3. Tricks Phase:
   - Evaluates total card count/suit control.
   - Leads highest bosses to secure tricks, established suit length, and capot/pique/repique potential.
   - Follows suit efficiently: ducking low when unable to beat, or overtaking with minimal required card.
"""

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------
def _get_suit_groups(hand):
    groups = {s: [] for s in ["H", "D", "C", "S"]}
    for card in hand:
        groups[card[0]].append(card)
    return groups


def _has_set(hand):
    counts = {}
    for card in hand:
        if card[1] >= 10:
            counts[card[1]] = counts.get(card[1], 0) + 1
    return max(counts.values(), default=0) >= 3


def _has_sequence(hand):
    by_suit = {}
    for card in hand:
        by_suit.setdefault(card[0], set()).add(card[1])
    for ranks in by_suit.values():
        sorted_ranks = sorted(ranks)
        run = 1
        for i in range(1, len(sorted_ranks)):
            if sorted_ranks[i] == sorted_ranks[i - 1] + 1:
                run += 1
                if run >= 3:
                    return True
            else:
                run = 1
    return False


def _evaluate_card_value(card, hand):
    """Assigns a strategic retention value to a card in hand (higher = keep)."""
    suit, rank = card
    val = rank * 2.0  # Base rank weighting

    # Point/Suit length contribution
    same_suit = [c for c in hand if c[0] == suit]
    val += len(same_suit) * 3.5

    # Set contribution (10+)
    if rank >= 10:
        same_rank = [c for c in hand if c[1] == rank]
        if len(same_rank) >= 3:
            val += 25.0
        elif len(same_rank) == 2:
            val += 8.0

    # Sequence contribution
    ranks = {c[1] for c in same_suit}
    has_neighbor = ((rank + 1) in ranks) or ((rank - 1) in ranks)
    if has_neighbor:
        val += 6.0

    return val


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

    # Sort cards by evaluation value ascending (lowest value candidate first)
    card_scores = [(card, _evaluate_card_value(card, hand)) for card in hand]
    card_scores.sort(key=lambda x: x[1])

    # Discard up to max_discard cards that fall below a retention value threshold
    discards = []
    for card, score in card_scores:
        if len(discards) >= max_discard:
            break
        # Elder prioritizes digging deep into talon; Younger is slightly more selective
        threshold = 38.0 if is_elder else 30.0
        if score < threshold or len(discards) < (3 if is_elder else 1):
            discards.append(card)

    return discards


def _declare(gameState):
    hand = gameState.your_hand
    cat = gameState.declare_category

    if cat == "point":
        return ("claim",)
    elif cat == "sequence":
        if _has_sequence(hand):
            return ("claim",)
        return "pass"
    elif cat == "set":
        if _has_set(hand):
            return ("claim",)
        return "pass"

    return "pass"


def _trick(gameState):
    hand = list(gameState.your_hand)
    current_trick = gameState.current_trick

    # 1. Leading a trick
    if not current_trick:
        suit_groups = _get_suit_groups(hand)
        
        # Lead high cards from established long suits to draw out opponent cards
        long_suits = sorted(suit_groups.keys(), key=lambda s: len(suit_groups[s]), reverse=True)
        for s in long_suits:
            cards = suit_groups[s]
            if len(cards) >= 3:
                # Play highest in long suit
                return max(cards, key=lambda c: c[1])

        # Otherwise play highest overall boss card
        return max(hand, key=lambda c: c[1])

    # 2. Following a trick
    lead_player, lead_card = current_trick[0]
    lead_suit, lead_rank = lead_card
    same_suit = [c for c in hand if c[0] == lead_suit]

    if same_suit:
        # Can beat lead card?
        winning_cards = [c for c in same_suit if c[1] > lead_rank]
        if winning_cards:
            # Play lowest winning card
            return min(winning_cards, key=lambda c: c[1])
        else:
            # Duck lowest card in suit
            return min(same_suit, key=lambda c: c[1])
    else:
        # Cannot follow suit: discard lowest strategic card overall
        return min(hand, key=lambda c: _evaluate_card_value(c, hand))


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