# Bet 5000 when unchecked; call up to 5000, otherwise fold.


def nextMove(gameState):
    if gameState.amount_to_call == 0:
        if gameState.your_stack >= 5000:
            return ("bet", 5000)
        return ("bet", gameState.your_stack)
    if gameState.amount_to_call <= 5000:
        return ("call",)
    return ("fold",)
