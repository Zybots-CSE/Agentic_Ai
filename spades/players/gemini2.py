# Apex Spades Player
# Max Effort implementation. Features absolute card counting, void tracking, 
# boss-card calculation, and bag-aware play.

def nextMove(gameState):
    """
    Tournament entry point wrapped in a failsafe to guarantee sub-second execution
    and zero forfeits[cite: 2, 4].
    """
    try:
        if gameState.phase == "bid":
            return _calculate_apex_bid(gameState)
        return _play_apex_card(gameState)
    except Exception as e:
        # Failsafe: return the absolute simplest legal move to prevent a forfeit crash[cite: 2].
        if gameState.phase == "bid":
            return max(1, sum(1 for c in gameState.your_hand if c[1] >= 11))
        return _fallback_legal_card(gameState)


# ---------------------------------------------------------------------------
# Advanced Bidding: Bag-Aware & Voids
# ---------------------------------------------------------------------------
def _calculate_apex_bid(gs):
    """
    Calculates bid based on raw strength, short suits, and exact bag proximity.
    """
    hand = gs.your_hand
    bags = gs.your_bags  #
    
    bid = 0.0
    s_ranks, h_ranks, d_ranks, c_ranks = [], [], [], []
    for suit, rank in hand:
        if suit == 'S': s_ranks.append(rank)
        elif suit == 'H': h_ranks.append(rank)
        elif suit == 'D': d_ranks.append(rank)
        elif suit == 'C': c_ranks.append(rank)
        
    # Evaluate Spades
    for r in s_ranks:
        if r >= 11: bid += 1
    if len(s_ranks) > 3:
        bid += (len(s_ranks) - 3)
        
    # Evaluate Off-suits
    for ranks in (h_ranks, d_ranks, c_ranks):
        if 14 in ranks: bid += 1
        if 13 in ranks:
            bid += 0.8 if (len(ranks) >= 2 or s_ranks) else 0.4
        if 12 in ranks and len(ranks) >= 3:
            bid += 0.5
            
    # Short Suit Bonus (Ability to trump)
    if s_ranks:
        for ranks in (h_ranks, d_ranks, c_ranks):
            if len(ranks) == 0: bid += 1
            elif len(ranks) == 1: bid += 0.5
            
    final_bid = int(round(bid))
    
    # Bag penalty avoidance: If we are at 8 or 9 bags, DO NOT underbid. 
    # We round UP aggressively to avoid accidentally taking overtricks.
    if bags >= 8 and final_bid < 13:
        if (bid % 1) > 0.1: # Even slightly over, push the bid up to cap bags
            final_bid += 1
            
    # Safe Nil Validation[cite: 5]
    if final_bid == 0:
        for s, r in hand:
            if r > 10 or (s == 'S' and r > 9):
                return 1
        return 0
        
    return min(13, max(1, final_bid))


# ---------------------------------------------------------------------------
# Apex Play Engine (Card Counting)
# ---------------------------------------------------------------------------
def _play_apex_card(gs):
    """
    Dominates play by tracking exactly which cards have been played, 
    detecting opponent voids, and forcing optimal trades[cite: 1, 4].
    """
    hand = gs.your_hand
    trick = gs.current_trick
    spades_broken = gs.spades_broken
    
    # 1. State Reconstruction (Card Counting)
    played_cards = set()
    opp_voids = {'H': False, 'D': False, 'C': False, 'S': False}
    
    # Analyze trick history to track voids[cite: 4]
    for t in gs.trick_history:
        plays = t["plays"]
        leader, lead_card = plays[0]
        follower, follow_card = plays[1]
        
        played_cards.add(lead_card)
        played_cards.add(follow_card)
        
        # If follower didn't match lead suit, they are void in it[cite: 5]
        if follow_card[0] != lead_card[0]:
            if follower == gs.opponent_name:
                opp_voids[lead_card[0]] = True
                
    if trick:
        played_cards.add(trick[0][1])

    # 2. Get Legal Moves[cite: 1]
    legal = []
    if not trick:
        if spades_broken:
            legal = hand
        else:
            legal = [c for c in hand if c[0] != 'S'] or hand
    else:
        lead_suit = trick[0][1][0]
        legal = [c for c in hand if c[0] == lead_suit] or hand
        
    if len(legal) == 1:
        return legal[0]

    # 3. Define Motivations
    my_bid = gs.your_bid
    my_tricks = gs.tricks_won.get(gs.your_name, 0)
    need_tricks = (my_tricks < my_bid)
    
    opp_bid = gs.opponent_bid
    opp_tricks = gs.tricks_won.get(gs.opponent_name, 0)
    bust_nil = (opp_bid == 0 and opp_tricks == 0)
    
    if bust_nil:
        need_tricks = False

    # 4. Helper to find "Boss" cards (highest unplayed card in a suit)
    def is_boss(card):
        s, r = card
        for rank in range(r + 1, 15):
            if (s, rank) not in played_cards and (s, rank) not in hand:
                return False
        return True

    # -----------------------------------------------------------
    # LEADING PHASE
    # -----------------------------------------------------------
    if not trick:
        if need_tricks:
            # Play a guaranteed winner (Boss card) if we have one
            for c in sorted(legal, key=lambda x: x[1], reverse=True):
                # Only lead boss non-spades if opponent isn't void, or boss spades
                if is_boss(c):
                    if c[0] == 'S' or not opp_voids[c[0]]:
                        return c
            # Fallback: Bleed their high cards by leading our highest off-suit
            non_spades = [c for c in legal if c[0] != 'S']
            if non_spades: return max(non_spades, key=lambda x: x[1])
            return max(legal, key=lambda x: x[1])
            
        else:
            # We want to LOSE (Evasion / Bust Nil)
            # Find the absolute lowest card in a suit the opponent is NOT void in.
            safe_losers = [c for c in legal if not opp_voids[c[0]]]
            if safe_losers:
                # Prefer leading off-suits over spades to dodge tricks safely
                non_spades = [c for c in safe_losers if c[0] != 'S']
                if non_spades: return min(non_spades, key=lambda x: x[1])
                return min(safe_losers, key=lambda x: x[1])
                
            # If forced to lead a suit they ARE void in, lead our HIGHEST card. 
            # They will trump it, taking the trick and stripping our high cards.
            void_suits = [c for c in legal if opp_voids[c[0]]]
            if void_suits:
                return max(void_suits, key=lambda x: x[1])
                
            return min(legal, key=lambda x: x[1])

    # -----------------------------------------------------------
    # FOLLOWING PHASE
    # -----------------------------------------------------------
    lead_card = trick[0][1]
    
    winners = []
    losers = []
    for c in legal:
        if _wins_trick(lead_card, c): winners.append(c)
        else: losers.append(c)
        
    if need_tricks:
        if winners:
            # Win as cheaply as possible
            return min(winners, key=lambda x: x[1] if x[0] != 'S' else x[1] + 20)
        else:
            # Throw away the absolute cheapest card
            return min(losers, key=lambda x: x[1] if x[0] != 'S' else x[1] + 20)
            
    else: # We want to LOSE
        if losers:
            # Safely dump our HIGHEST losing card.
            return max(losers, key=lambda x: x[1] if x[0] != 'S' else x[1] + 20)
        else:
            # Forced to win: Dump the HIGHEST winning card so it can't accidentally win later.
            return max(winners, key=lambda x: x[1] if x[0] != 'S' else x[1] + 20)


# ---------------------------------------------------------------------------
# Base Helpers
# ---------------------------------------------------------------------------
def _wins_trick(lead_card, follow_card):
    """Engine trick resolution mapping[cite: 1, 5]."""
    ls, lr = lead_card
    fs, fr = follow_card
    if ls == 'S' or fs == 'S':
        if ls == 'S' and fs == 'S': return fr > lr
        return fs == 'S'
    return fs == ls and fr > lr


def _fallback_legal_card(gs):
    """Ultimate failsafe legal move generator[cite: 3]."""
    hand, trick = gs.your_hand, gs.current_trick
    if trick:
        same = [c for c in hand if c[0] == trick[0][1][0]]
        if same: return same[0]
    if not gs.spades_broken:
        ns = [c for c in hand if c[0] != 'S']
        if ns: return ns[0]
    return hand[0]