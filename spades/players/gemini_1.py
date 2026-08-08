# Master Spades Player - Ultra Optimized
# Zero lambdas, pure O(N) execution for <1ms response time to defeat timeouts.
# Decodes engine mechanics for precise trick calculation, bag dodging, and Nil-busting.

def nextMove(gameState):
    """
    Entry point wrapped in an absolute failsafe to guarantee sub-second execution
    and zero forfeits[cite: 1, 4].
    """
    try:
        if gameState.phase == "bid":
            return _fast_bid(gameState.your_hand)
        return _fast_play(gameState)
    except Exception:
        # Failsafe: if a freak error occurs, instantly return a basic legal move
        # to prevent threading timeout / crash[cite: 2].
        if gameState.phase == "bid":
            return 3
        return _fallback_card(gameState)


# ---------------------------------------------------------------------------
# High-Speed Bidding Engine
# ---------------------------------------------------------------------------
def _fast_bid(hand):
    """Calculates bid using primitive loops for absolute maximum speed[cite: 5]."""
    bid = 0.0
    s_ranks, h_ranks, d_ranks, c_ranks = [], [], [], []
    
    # Categorize hand
    for suit, rank in hand:
        if suit == 'S': s_ranks.append(rank)
        elif suit == 'H': h_ranks.append(rank)
        elif suit == 'D': d_ranks.append(rank)
        elif suit == 'C': c_ranks.append(rank)
        
    # 1. Evaluate Spades
    for r in s_ranks:
        if r >= 11: 
            bid += 1
    if len(s_ranks) > 3:
        bid += (len(s_ranks) - 3)
        
    # 2. Evaluate Off-suits
    for ranks in (h_ranks, d_ranks, c_ranks):
        if 14 in ranks: 
            bid += 1
        if 13 in ranks:
            if len(ranks) >= 2 or s_ranks:
                bid += 0.8
            else:
                bid += 0.4
        if 12 in ranks and len(ranks) >= 3:
            bid += 0.5
            
    # 3. Short Suit Bonus (allows trumping)
    if s_ranks:
        if not h_ranks: bid += 1
        elif len(h_ranks) == 1: bid += 0.5
        if not d_ranks: bid += 1
        elif len(d_ranks) == 1: bid += 0.5
        if not c_ranks: bid += 1
        elif len(c_ranks) == 1: bid += 0.5
        
    final_bid = int(bid + 0.5)  # Fast rounding
    
    # 4. Safe Nil Validation
    if final_bid == 0:
        for s, r in hand:
            # Do not risk Nil if holding high cards[cite: 5]
            if r > 10 or (s == 'S' and r > 9):
                return 1
        return 0
        
    if final_bid > 13: 
        return 13
    return final_bid


# ---------------------------------------------------------------------------
# High-Speed Play Engine
# ---------------------------------------------------------------------------
def _fast_play(gs):
    """Core play logic stripped of heavy iterators[cite: 4, 5]."""
    hand = gs.your_hand
    trick = gs.current_trick
    
    # 1. Fast Legal Cards Calculation[cite: 1]
    legal = []
    if not trick:
        if gs.spades_broken:
            legal = hand
        else:
            for c in hand:
                if c[0] != 'S':
                    legal.append(c)
            if not legal:
                legal = hand
    else:
        lead_suit = trick[0][1][0]
        for c in hand:
            if c[0] == lead_suit:
                legal.append(c)
        if not legal:
            legal = hand
            
    if len(legal) == 1:
        return legal[0]
        
    # 2. Define Goals
    my_bid = gs.your_bid
    my_tricks = gs.tricks_won.get(gs.your_name, 0)
    need_tricks = (my_tricks < my_bid)
    
    # Nil-busting
    opp_bid = gs.opponent_bid
    opp_tricks = gs.tricks_won.get(gs.opponent_name, 0)
    if opp_bid == 0 and opp_tricks == 0:
        need_tricks = False
        
    # 3. Leading Phase
    if not trick:
        best = legal[0]
        for c in legal[1:]:
            # Use manual comparison instead of lambdas for speed
            c_is_s = (c[0] == 'S')
            b_is_s = (best[0] == 'S')
            
            if need_tricks:  # We want high cards (prefer non-spades)
                if c_is_s != b_is_s:
                    if b_is_s: best = c
                elif c[1] > best[1]: best = c
            else:  # We want low cards (prefer non-spades)
                if c_is_s != b_is_s:
                    if b_is_s: best = c
                elif c[1] < best[1]: best = c
        return best

    # 4. Following Phase
    lead_card = trick[0][1]
    winners = []
    losers = []
    
    for c in legal:
        if _wins(lead_card, c):
            winners.append(c)
        else:
            losers.append(c)
            
    # Extract optimal card manually to avoid max/min overhead
    if need_tricks:
        return _get_extreme(winners if winners else losers, want_high=False)
    else:
        return _get_extreme(losers if losers else winners, want_high=True)


# ---------------------------------------------------------------------------
# Lightning Fast Helpers
# ---------------------------------------------------------------------------
def _wins(lead_card, follow_card):
    """Engine trick resolution replication[cite: 1, 5]."""
    ls, lr = lead_card
    fs, fr = follow_card
    if ls == 'S' or fs == 'S':
        if ls == 'S' and fs == 'S':
            return fr > lr
        return fs == 'S'
    return fs == ls and fr > lr

def _get_extreme(cards, want_high):
    """Replaces min() and max() lambda keys with raw loops."""
    best = cards[0]
    for c in cards[1:]:
        c_is_s = (c[0] == 'S')
        b_is_s = (best[0] == 'S')
        if c_is_s != b_is_s:
            if b_is_s: best = c
        else:
            if want_high:
                if c[1] > best[1]: best = c
            else:
                if c[1] < best[1]: best = c
    return best

def _fallback_card(gs):
    """Bare minimum legal card generator in case of emergency[cite: 3]."""
    hand = gs.your_hand
    trick = gs.current_trick
    if trick:
        lead_suit = trick[0][1][0]
        same = [c for c in hand if c[0] == lead_suit]
        if same: return same[0]
    if not gs.spades_broken:
        ns = [c for c in hand if c[0] != 'S']
        if ns: return ns[0]
    return hand[0]