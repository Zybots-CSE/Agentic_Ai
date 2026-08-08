# Basic player: simple bid estimate and first legal card in play.


def nextMove(gameState):
    if gameState.phase == "bid":
        strength = sum(1 for card in gameState.your_hand if card[1] >= 11)
        spades = sum(1 for card in gameState.your_hand if card[0] == "S" and card[1] >= 10)
        return min(strength + spades // 2, 13)

    return _first_legal_card(gameState)


def _first_legal_card(gameState):
    hand = gameState.your_hand
    trick = gameState.current_trick

    if trick:
        lead_suit = trick[0][1][0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]

    if not gameState.spades_broken:
        non_spades = [c for c in hand if c[0] != "S"]
        if non_spades:
            return non_spades[0]

    return hand[0]
