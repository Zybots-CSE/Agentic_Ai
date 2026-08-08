# Terminator Spades Player
# Ultra-high performance: Zero lambdas, pure O(N) execution.
# Mathematically calculates Boss cards and tracks opponent voids.

def nextMove(gameState):
    """
    Main entry point. Uses a failsafe to guarantee execution well under
    the 2.0-second timeout limit[cite: 2, 4].
    """
    try:
        if gameState.phase == "bid":
            return _calculate_bid(gameState)
        return _play_card(gameState)
    except Exception:
        # Failsafe fallback to prevent any forfeit[cite: 1, 4]
        if gameState.phase == "bid": return 3
        return _fallback(gameState)

# ---------------------------------------------------------------------------
# Bidding Engine (Bag-Aware)
# ---------------------------------------------------------------------------
def _calculate_bid(gs):
    """
    Calculates exact hand potential. Adjusts aggressively if close to 
    the 10-bag penalty threshold.
    """
    hand = gs.your_hand
    bags = gs.your_bags
    
    bid = 0.0
    spades, hearts, diamonds, clubs = [], [], [], []
    for s, r in hand:
        if s == 'S': spades.append(r)
        elif s == 'H': hearts.append(r)
        elif s == 'D': diamonds.append(r)
        elif s == 'C': clubs.append(r)
        
    # Evaluate Spades
    for r in spades:
        if r >= 11: bid += 1
    if len(spades) > 4:
        bid += (len(spades) - 4)
        
    # Evaluate Off-suits
    for suit in (hearts, diamonds, clubs):
        if 14 in suit: bid += 1
        if 13 in suit:
            if len(suit) >= 2 or len(spades) > 0: bid += 1
            else: bid += 0.5
        if 12 in suit and len(suit) >= 3:
            bid += 0.5
            
    # Void/Singleton bonus (only if we have spades to trump with)
    if len(spades) >= 2:
        for suit in (hearts, diamonds, clubs):
            if len(suit) == 0: bid += 1
            elif len(suit) == 1: bid += 0.5
            
    final_bid = int(bid)
    
    # Bag Avoidance: If we are at 8 or 9 bags, do NOT underbid[cite: 5].
    if bags >= 8 and final_bid < 13:
        final_bid += 1
        
    # Safe Nil check: Never bid nil with high risk cards[cite: 5].
    if final_bid == 0:
        for s, r in hand:
            if r >= 11 or (s == 'S' and r >= 9):
                return 1
        return 0
        
    return min(13, max(0, final_bid))

# ---------------------------------------------------------------------------
# Core Play Logic (Boss Cards & Voids)
# ---------------------------------------------------------------------------
def _play_card(gs):
    hand = gs.your_hand
    trick = gs.current_trick
    
    # 1. Track played cards and opponent voids[cite: 4]
    played = set()
    opp_voids = {'S': False, 'H': False, 'D': False, 'C': False}
    
    for t in gs.trick_history:
        l_player, l_card = t["plays"][0]
        f_player, f_card = t["plays"][1]
        played.add(l_card)
        played.add(f_card)
        # If follower didn't match lead suit, they are void[cite: 5]
        if f_card[0] != l_card[0] and f_player == gs.opponent_name:
            opp_voids[l_card[0]] = True
            
    if trick:
        played.add(trick[0][1])
        
    # 2. Calculate the highest unseen cards to find our "Boss" cards
    highest_unseen = {'S': 0, 'H': 0, 'D': 0, 'C': 0}
    for s in ['S', 'H', 'D', 'C']:
        max_r = 0
        for r in range(2, 15):
            if s in ('C', 'D') and r == 2: continue
            if (s, r) not in played and (s, r) not in hand:
                if r > max_r: max_r = r
        highest_unseen[s] = max_r
        
    def is_boss(card):
        return card[1] > highest_unseen[card[0]]

    # 3. Determine Legal Moves[cite: 1, 5]
    legal = []
    if not trick:
        if gs.spades_broken:
            legal = hand
        else:
            for c in hand:
                if c[0] != 'S': legal.append(c)
            if not legal: legal = hand
    else:
        lead_suit = trick[0][1][0]
        for c in hand:
            if c[0] == lead_suit: legal.append(c)
        if not legal: legal = hand
        
    if len(legal) == 1:
        return legal[0]

    # 4. Strategy Goals
    need_tricks = gs.tricks_won.get(gs.your_name, 0) < gs.your_bid
    if gs.opponent_bid == 0 and gs.tricks_won.get(gs.opponent_name, 0) == 0:
        need_tricks = False # Nil-busting mode

    # -----------------------------------------------------------
    # LEADING PHASE
    # -----------------------------------------------------------
    if not trick:
        if need_tricks:
            # A. Play Boss Spades to strip their trumps
            for c in legal:
                if c[0] == 'S' and is_boss(c): return c
            # B. Play Boss Off-suits (only if they aren't void)
            for c in legal:
                if c[0] != 'S' and is_boss(c) and not opp_voids[c[0]]: return c
            # C. Dump lowest off-suit to build our own voids
            return _get_extreme(legal, want_high=False, prefer_offsuit=True)
        else:
            # A. Force them to win: Lead a suit they are void in with our HIGHEST card
            void_suits = [c for c in legal if opp_voids[c[0]]]
            if void_suits:
                return _get_extreme(void_suits, want_high=True, prefer_offsuit=False)
            # B. Dump lowest safe card
            safe_cards = [c for c in legal if not opp_voids[c[0]]]
            if safe_cards:
                return _get_extreme(safe_cards, want_high=False, prefer_offsuit=True)
            return _get_extreme(legal, want_high=False, prefer_offsuit=True)

    # -----------------------------------------------------------
    # FOLLOWING PHASE
    # -----------------------------------------------------------
    lead_card = trick[0][1]
    winners, losers = [], []
    for c in legal:
        if _wins_trick(lead_card, c): winners.append(c)
        else: losers.append(c)
        
    if need_tricks:
        if winners:
            # Win as cheaply as possible
            return _get_extreme(winners, want_high=False, prefer_offsuit=True)
        # Cannot win, dump worst card
        return _get_extreme(losers, want_high=False, prefer_offsuit=True)
    else:
        if losers:
            # Safely dump our highest losing card (avoids bags)
            return _get_extreme(losers, want_high=True, prefer_offsuit=True)
        # Forced to win, dump highest winner so it can't accidentally win again
        return _get_extreme(winners, want_high=True, prefer_offsuit=True)

# ---------------------------------------------------------------------------
# Optimized Pure-Python Helpers
# ---------------------------------------------------------------------------
def _wins_trick(lead_card, follow_card):
    """Accurate trick resolution logic[cite: 1, 5]."""
    ls, lr = lead_card
    fs, fr = follow_card
    if ls == 'S' or fs == 'S':
        if ls == 'S' and fs == 'S': return fr > lr
        return fs == 'S'
    return fs == ls and fr > lr

def _get_extreme(cards, want_high, prefer_offsuit):
    """
    O(N) search replacing slow min/max lambda functions. 
    Guarantees sub-millisecond execution time.
    """
    best = cards[0]
    for c in cards[1:]:
        c_is_s = (c[0] == 'S')
        b_is_s = (best[0] == 'S')
        
        if prefer_offsuit and c_is_s != b_is_s:
            if b_is_s: best = c # non-spade beats spade
        else:
            if want_high:
                if c[1] > best[1]: best = c
            else:
                if c[1] < best[1]: best = c
    return best

def _fallback(gs):
    """Absolute simplest valid card in case of catastrophic failure[cite: 1, 3]."""
    hand, trick = gs.your_hand, gs.current_trick
    if trick:
        same = [c for c in hand if c[0] == trick[0][1][0]]
        if same: return same[0]
    if not gs.spades_broken:
        ns = [c for c in hand if c[0] != 'S']
        if ns: return ns[0]
    return hand[0]