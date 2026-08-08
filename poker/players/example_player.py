# Example poker player — documents PlayerView and action encoding.
# Not loaded in tournaments (see main.py).

# ------------------------------------------------------------------
# gameState (PlayerView) attributes:
#
#   gameState.your_name          - your player name (string)
#   gameState.your_hole_cards    - list of 2 (suit, rank) tuples
#                                  suit: "H", "D", "C", "S"
#                                  rank: 2-14 (14 = Ace)
#   gameState.community_cards    - board cards dealt so far (0, 3, 4, or 5)
#   gameState.your_stack         - chips available to bet this hand
#   gameState.player_stacks      - dict {name: int} all seated stacks
#   gameState.player_status      - dict {name: str} "active", "folded", "all_in"
#   gameState.seat_order         - names clockwise from dealer
#   gameState.dealer             - dealer / Player 1 for action order
#   gameState.action_on          - whose turn it is now
#   gameState.street             - "preflop", "flop", "turn", or "river"
#   gameState.pot                - total chips in all pots
#   gameState.amount_to_call     - chips needed for you to call
#   gameState.min_raise_to       - min legal raise total this street, or None
#   gameState.hand_number        - 1-based hand index in the tournament
#   gameState.action_history     - [(name, action), ...] this betting street
#   gameState.hand_history       - list of completed previous hands (public info only):
#                                  [{"hand_number", "dealer", "seat_order", "actions",
#                                    "board", "showdown", "uncontested_winner",
#                                    "ending_stacks"}, ...]
#                                  showdown is {name: hole_cards} for contenders only,
#                                  or None if the pot was won uncontested
#
# Return one action tuple:
#   ("fold",)
#   ("check",)              - only if amount_to_call == 0
#   ("call",)
#   ("bet", amount)         - opening bet; 1 <= amount <= your_stack
#   ("raise", total)        - total chips you will have wagered this street
#
# Invalid moves or exceptions cause an auto-fold for this hand.
# Each nextMove call must finish within 2 seconds or you auto-fold.
# ------------------------------------------------------------------


def nextMove(gameState):
    if gameState.amount_to_call == 0:
        return ("check",)
    if gameState.amount_to_call <= gameState.your_stack // 10:
        return ("call",)
    return ("fold",)
