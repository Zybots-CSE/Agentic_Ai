# Example Piquet player — documents PlayerView and phase-specific nextMove returns.
# Not loaded in tournaments (see main.py).

# ------------------------------------------------------------------
# gameState (PlayerView) attributes:
#
#   gameState.your_hand         - list of (suit, rank); suit H/D/C/S, rank 7-14 (14=Ace)
#   gameState.phase             - "exchange", "declare", or "tricks"
#   gameState.your_name         - your player name
#   gameState.opponent_name     - opponent's name
#   gameState.dealer            - who dealt this hand
#   gameState.elder             - non-dealer; acts first in exchange/declare/trick 1
#   gameState.turn              - who must act now
#   gameState.your_score        - cumulative match score (toward 100)
#   gameState.opponent_score    - opponent's cumulative match score
#   gameState.hand_points       - dict {name: int} points scored this deal so far
#   gameState.hand_history      - list of completed previous hands (public info only):
#                                 [{"dealer", "elder", "exchange_counts",
#                                   "declarations", "tricks", "tricks_won",
#                                   "hand_points", "scores_after"}, ...]
#
#   Exchange phase only:
#   gameState.talon_remaining   - int, cards left in stock (not their identities)
#   gameState.opponent_discarded - int or None, how many cards opponent exchanged
#
#   Declare phase only:
#   gameState.declare_category   - "point", "sequence", or "set" (current category)
#   gameState.elder_claim        - opponent elder's claim summary when you respond, else None
#   gameState.declarations       - list of resolved declarations so far this hand
#
#   Tricks phase only:
#   gameState.current_trick      - [(player_name, card), ...] for this trick
#   gameState.lead               - name of player leading this trick
#   gameState.tricks_won         - dict {name: int} tricks won this deal
#
# Return value depends on phase:
#   exchange  -> list of cards to discard (subset of your_hand)
#                elder: 0-5 cards; younger: 0..talon_remaining cards
#   declare   -> "pass" or ("pass",) or ("claim",) / ("claim", category, ...)
#                claim only if you have a valid combination in declare_category
#   tricks    -> (suit, rank) card; must follow suit when possible
#
# Invalid moves or exceptions forfeit the entire match.
# Each nextMove call must finish within 2 seconds or the match is forfeited.
# ------------------------------------------------------------------


def nextMove(gameState):
    phase = gameState.phase

    if phase == "exchange":
        return _exchange_move(gameState)
    if phase == "declare":
        return _declare_move(gameState)
    return _trick_move(gameState)


def _exchange_move(gameState):
    hand = gameState.your_hand
    if gameState.your_name == gameState.elder:
        return hand[: min(3, len(hand))]
    max_disc = gameState.talon_remaining or 0
    return hand[: min(3, max_disc, len(hand))]


def _declare_move(gameState):
    hand = gameState.your_hand
    cat = gameState.declare_category
    if cat == "set" and not _has_set(hand):
        return "pass"
    if cat == "sequence" and not _has_sequence(hand):
        return "pass"
    return ("claim",)


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


def _trick_move(gameState):
    if gameState.current_trick:
        lead_suit = gameState.current_trick[0][1][0]
        same_suit = [c for c in gameState.your_hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]
    return gameState.your_hand[0]
