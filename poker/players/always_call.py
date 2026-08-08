# Always call any amount, otherwise fold.


def nextMove(gameState):
    if gameState.amount_to_call > 0:
        return ("call",)
    return ("check",)
