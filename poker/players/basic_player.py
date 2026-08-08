# Basic poker player for smoke tests.


def nextMove(gameState):
    if gameState.amount_to_call == 0:
        if gameState.your_stack > 1000:
            return ("bet", 500)
        return ("check",)
    if gameState.amount_to_call <= 1000:
        return ("call",)
    return ("fold",)
