import math
import random
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# Constants & Globals
# ---------------------------------------------------------------------------
SUITS = ("S", "H", "D", "C")
RANKS = tuple(range(2, 15))  # 2..14 (A)
RANK_IDX = {r: i for i, r in enumerate(RANKS)}  # 0..12
SPADES = "S"
KITTY_SIZE = 24
TRICKS_PER_ROUND = 13
MAX_BID = TRICKS_PER_ROUND
BAG_LIMIT = 10

# Pre-computed suit lengths for 50-card deck (no 2C, 2D)
SUIT_TOTALS = {"S": 13, "H": 13, "D": 12, "C": 12}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _card_key(card):
    """Sort key: Spades last, then rank."""
    s, r = card
    return (0 if s == SPADES else 1, r)

def _trick_winner(lead_card, follow_card):
    ls, lr = lead_card
    fs, fr = follow_card
    if fs == SPADES and ls != SPADES: return False
    if ls == SPADES and fs != SPADES: return True
    if fs == ls: return fr > lr
    return True  # follow off-suit loses

def _legal_moves(hand, lead_card, spades_broken):
    if lead_card is None:
        non_spades = [c for c in hand if c[0] != SPADES]
        if not non_spades or spades_broken: return list(hand)
        return non_spades
    lead_suit = lead_card[0]
    same = [c for c in hand if c[0] == lead_suit]
    return same if same else list(hand)

# ---------------------------------------------------------------------------
# Opponent Model (Bayesian Card Tracking)
# ---------------------------------------------------------------------------
class OpponentModel:
    """
    Maintains P(opponent has card | history) for every unseen card.
    Updates on every trick: follow suit -> removes void possibility; 
    play specific card -> sets prob to 1.0 for that card, 0 for others in hand.
    """
    def __init__(self, my_hand, dealer_name, my_name):
        self.my_hand_set = set(my_hand)
        self.known_opponent_cards = set()
        self.played_cards = set()
        self.voids = set() # suits opponent has shown void in
        
        # Universe of cards opponent *could* have
        self.universe = [(s, r) for s in SUITS for r in RANKS 
                         if not (s in ("C", "D") and r == 2) 
                         and (s, r) not in my_hand]
        
        # Prior: uniform over combinations. Approximated as independent prob per card.
        # P(card in opp hand) = 13 / 38 (since 50 total - 13 mine = 37 unseen? Wait. 50 deck. 13 me. 13 opp. 24 kitty. Unseen=37. Opp has 13.)
        # Actually: 50 cards. I have 13. Opponent has 13. Kitty 24.
        # Unseen by me = 37 cards. Opponent holds 13 of those.
        # Prior prob any specific unseen card is in opp hand = 13/37.
        self.prob = {c: 13.0 / 37.0 for c in self.universe}
        self.opp_hand_size = 13

    def update_played(self, card, player_name, opponent_name, lead_card=None):
        """Call for every card played."""
        if card in self.prob: del self.prob[card]
        self.played_cards.add(card)
        self.opp_hand_size -= 1 if player_name == opponent_name else 0

        if player_name == opponent_name:
            self.known_opponent_cards.add(card)
            # If they followed suit, they are not void in that suit
            if lead_card and card[0] == lead_card[0]:
                self.voids.discard(card[0])
            # Renormalize remaining probabilities
            self._renormalize()
        else:
            # I played it, or it was in kitty (not visible), but here we only see played.
            # If I lead suit X and they play off-suit -> VOID in X
            if lead_card and card[0] != lead_card[0] and player_name == opponent_name:
                 self.voids.add(lead_card[0])
                 # Zero out prob for all unseen cards of that suit
                 for c in list(self.prob.keys()):
                     if c[0] == lead_card[0]:
                         self.prob[c] = 0.0
                 self._renormalize()

    def _renormalize(self):
        """Scale probs so sum == expected hand size."""
        # Sum of probs should equal remaining cards in opponent hand
        target_sum = self.opp_hand_size
        current_sum = sum(self.prob.values())
        if current_sum == 0: return
        factor = target_sum / current_sum
        for c in self.prob:
            self.prob[c] *= factor
        # Clamp
        for c in self.prob:
            if self.prob[c] > 1.0: self.prob[c] = 1.0
            if self.prob[c] < 0.0: self.prob[c] = 0.0

    def prob_has(self, card):
        return self.prob.get(card, 0.0)

    def prob_void(self, suit):
        return suit in self.voids or all(self.prob.get((s, r), 0) == 0 for s in SUITS if s==suit for r in RANKS)

    def expected_high_cards(self, suit, min_rank):
        """Expected count of cards >= min_rank in opponent hand."""
        return sum(self.prob.get((s, r), 0) for s in SUITS if s==suit for r in RANKS if r >= min_rank)

# ---------------------------------------------------------------------------
# Trick Simulation (Monte Carlo for Bidding/Play)
# ---------------------------------------------------------------------------
def _simulate_tricks(my_hand, opp_model, spades_broken, num_sims=500):
    """
    Fast Monte Carlo to estimate trick distribution.
    Returns: (mean_tricks, prob_make_nil, trick_distribution_list)
    """
    my_cards_base = list(my_hand)
    unseen_cards = [c for c in opp_model.universe if c not in opp_model.played_cards and c not in opp_model.known_opponent_cards]
    
    # Build weighted deck for opponent
    # We sample opponent hands proportional to probabilities
    weights = [opp_model.prob.get(c, 0) for c in unseen_cards]
    total_w = sum(weights)
    if total_w == 0: return (0, 1.0, [1.0]+[0]*13)
    norm_weights = [w/total_w for w in weights]

    trick_counts = []
    
    for _ in range(num_sims):
        # Sample opponent hand (13 cards remaining usually, but decreases)
        # Simple weighted sample without replacement approximation:
        # Shuffle by weight key
        opp_hand = random.choices(unseen_cards, weights=norm_weights, k=opp_model.opp_hand_size)
        # Deduplicate (crude but fast for sim)
        opp_hand = list(dict.fromkeys(opp_hand))
        while len(opp_hand) < opp_model.opp_hand_size:
             c = random.choice(unseen_cards)
             if c not in opp_hand: opp_hand.append(c)

        # Simulate optimal play for both sides (simplified: High card wins, follow suit)
        # We simulate *tricks I take* assuming I play optimally vs optimal opponent.
        # This is hard to do perfectly fast. 
        # HEURISTIC: Count "Sure Tricks" + "Finessable Tricks" based on sampled hand.
        
        tricks = _evaluate_hand_vs_opp(my_cards_base, opp_hand, spades_broken)
        trick_counts.append(tricks)

    if not trick_counts: return (0, 1.0, [1.0]+[0]*13)
    
    mean = sum(trick_counts) / len(trick_counts)
    dist = [0]*14
    for t in trick_counts: dist[t] += 1
    dist = [d/len(trick_counts) for d in dist]
    p_nil = dist[0]
    return mean, p_nil, dist

def _evaluate_hand_vs_opp(my_hand, opp_hand, spades_broken):
    """
    Heuristic trick estimator for a specific deal.
    Plays out tricks greedily: Leader leads best suit. Follower beats if can.
    """
    my_h = {s: sorted([r for su, r in my_hand if su==s]) for s in SUITS}
    opp_h = {s: sorted([r for su, r in opp_hand if su==s]) for s in SUITS}
    
    my_tricks = 0
    lead = "me" # Non-dealer leads first trick usually, but we avg over sims so start random or fixed.
    # Actually, bidding happens before play. We don't know who leads first trick.
    # Assume 50/50 lead start.
    lead = random.choice(["me", "opp"])
    
    broken = spades_broken
    
    for _ in range(TRICKS_PER_ROUND):
        if lead == "me":
            # I lead: Pick suit with highest win prob
            # Heuristic: Lead longest/strongest non-spade, or spade if broken/only
            lead_card = _choose_lead_sim(my_h, opp_h, broken)
            if not lead_card: break
            s, r = lead_card
            my_h[s].remove(r)
            
            # Opp follows
            follow_card = _choose_follow_sim(opp_h, s, r, broken)
            if follow_card:
                fs, fr = follow_card
                opp_h[fs].remove(fr)
                if not _trick_winner(lead_card, follow_card): # I lost
                    lead = "opp"
                else:
                    my_tricks += 1
            else: # Opp has no cards? (end game)
                my_tricks += 1
                
        else: # Opp leads
            lead_card = _choose_lead_sim(opp_h, my_h, broken)
            if not lead_card: break
            s, r = lead_card
            opp_h[s].remove(r)
            
            # I follow
            follow_card = _choose_follow_sim(my_h, s, r, broken)
            if follow_card:
                fs, fr = follow_card
                my_h[fs].remove(fr)
                if _trick_winner(lead_card, follow_card): # Opp won
                    lead = "opp"
                else:
                    my_tricks += 1
                    lead = "me"
            else:
                lead = "opp" # I couldn't follow? impossible if cards left
        
        if lead_card[0] == SPADES or (follow_card and follow_card[0] == SPADES):
            broken = True
            
    return my_tricks

def _choose_lead_sim(hand, opp_hand, broken):
    # Try to lead a suit where I have advantage
    best_card = None
    best_score = -1
    
    for s in SUITS:
        if not hand[s]: continue
        if s == SPADES and not broken: continue
        
        # Score = My Highest - Opp Highest (approx)
        my_high = hand[s][-1]
        opp_high = opp_hand[s][-1] if opp_hand[s] else 0
        
        # Prefer suits where I have high cards and they are short/low
        score = my_high - opp_high + len(hand[s]) * 0.5
        if score > best_score:
            best_score = score
            best_card = (s, my_high) # Lead high? No, lead low usually. But for sim eval, lead high to test winning.
            # Actually for sim, lead the card I *would* play.
    return best_card

def _choose_follow_sim(hand, lead_suit, lead_rank, broken):
    # Must follow suit
    if hand[lead_suit]:
        # Play lowest winner, else lowest card
        winners = [r for r in hand[lead_suit] if r > lead_rank]
        if winners: return (lead_suit, min(winners))
        return (lead_suit, hand[lead_suit][0])
    
    # Can't follow: Play spade if have, else lowest off-suit
    if hand[SPADES]:
        return (SPADES, hand[SPADES][0]) # Trump low
    
    # Discard lowest card overall
    min_c = None
    for s in SUITS:
        if hand[s]:
            c = (s, hand[s][0])
            if min_c is None or _card_key(c) < _card_key(min_c):
                min_c = c
    return min_c

# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------
def nextMove(gameState):
    try:
        # Initialize persistent state in gameState object (hack for stateful bot)
        if not hasattr(gameState, '_bot_state'):
            gameState._bot_state = BotState(gameState)
        
        bot = gameState._bot_state
        bot.update(gameState)
        
        if gameState.phase == "bid":
            return bot.choose_bid()
        else:
            return bot.play_card()
    except Exception as e:
        # Fallback
        if gameState.phase == "bid": return 1
        legal = _legal_moves(gameState.your_hand, gameState.current_trick[0][1] if gameState.current_trick else None, gameState.spades_broken)
        return legal[0]

# ---------------------------------------------------------------------------
# Bot State Class
# ---------------------------------------------------------------------------
class BotState:
    def __init__(self, gs):
        self.my_name = gs.your_name
        self.opp_name = gs.opponent_name
        self.opp_model = OpponentModel(gs.your_hand, gs.dealer, gs.your_name)
        self.spades_broken = False
        self.trick_history = []
        self.my_bid = None
        self.opp_bid = None
        self.round_num = gs.round_number
        
    def update(self, gs):
        self.my_hand = list(gs.your_hand)
        self.spades_broken = gs.spades_broken
        self.my_bid = gs.your_bid
        self.opp_bid = gs.opponent_bid if gs.opponent_bid_known else None
        self.tricks_won_me = gs.tricks_won.get(self.my_name, 0)
        self.tricks_won_opp = gs.tricks_won.get(self.opp_name, 0)
        self.my_bags = gs.your_bags
        self.opp_bags = gs.opponent_bags
        self.my_score = gs.your_score
        self.opp_score = gs.opponent_score
        self.current_trick = list(gs.current_trick)
        self.lead_player = gs.turn # Who is leading *this* decision
        
        # Update opponent model with new trick history
        # We only get current_trick and trick_history. 
        # We need to process trick_history incrementally.
        # Since we can't easily know what we processed last, we reprocess full history every turn (cheap).
        self.opp_model = OpponentModel(self.my_hand, gs.dealer, self.my_name) # Reset? No, need persistence.
        # BETTER: Keep model persistent. But we don't have 'previous trick history length'.
        # HACK: Store processed index in bot state.
        if not hasattr(self, '_processed_tricks'):
            self._processed_tricks = 0
            
        history = gs.trick_history
        for i in range(self._processed_tricks, len(history)):
            t = history[i]
            leader, lead_card = t["plays"][0]
            follower, follow_card = t["plays"][1]
            
            self.opp_model.update_played(lead_card, leader, self.opp_name)
            self.opp_model.update_played(follow_card, follower, self.opp_name, lead_card)
            
        self._processed_tricks = len(history)
        
        # Current partial trick
        if self.current_trick:
            leader, lead_card = self.current_trick[0]
            self.opp_model.update_played(lead_card, leader, self.opp_name)
            # Follower hasn't played yet (it's us)

    # -----------------------------------------------------------------------
    # BIDDING
    # -----------------------------------------------------------------------
    def choose_bid(self):
        # Run Monte Carlo Simulation
        mean_tricks, p_nil, dist = _simulate_tricks(
            self.my_hand, self.opp_model, self.spades_broken, num_sims=800
        )
        
        # --- NIL DECISION ---
        # Bid Nil if: P(0 tricks) > 75% AND Mean tricks < 1.0 AND not too many spades
        spade_count = sum(1 for s, _ in self.my_hand if s == SPADES)
        high_spades = sum(1 for s, r in self.my_hand if s == SPADES and r >= 12) # Q, K, A
        
        if p_nil > 0.75 and mean_tricks < 1.0 and spade_count <= 4 and high_spades == 0:
            # Safety check: Do we have an unprotected Ace/King offsuit?
            risky = False
            for s in ("H", "D", "C"):
                ranks = [r for su, r in self.my_hand if su == s]
                if 14 in ranks and len(ranks) == 1: risky = True # Singleton Ace
                if 13 in ranks and len(ranks) <= 2: risky = True # Kx or K singleton
            if not risky:
                return 0

        # --- REGULAR BID ---
        # Target: Bid slightly below mean to avoid bags (overtricks cost 1, missed bid costs 10)
        # Bid = Floor(Mean - Safety_Margin)
        # Safety margin increases with bags.
        safety = 0.7
        if self.my_bags >= 8: safety = 1.2  # Very scared of bags
        if self.my_bags >= 9: safety = 1.5
        
        # Opponent bid awareness: If opp bid high (7+), they are vulnerable. 
        # We might bid aggressively to set them? No, bidding doesn't affect play directly.
        # But if WE bid high, we commit to taking tricks.
        
        raw_bid = mean_tricks - safety
        bid = max(1, min(13, int(math.floor(raw_bid + 0.5)))) # Round to nearest
        
        # Bag Management: If we are at 9 bags, bid 1 lower than calculated to guarantee miss? 
        # No, missing bid costs 100. Taking 1 bag costs 100. Same.
        # But taking 2 bags costs 200 (100 penalty + 100 next penalty). 
        # If bags >= 9, bid *exactly* what we think we take (floor mean).
        if self.my_bags >= 9:
            bid = max(1, min(13, int(math.floor(mean_tricks))))
            
        # Score desperation: If losing badly late game, bid up.
        if self.my_score < self.opp_score - 100 and self.round_num > 5:
            bid = min(13, bid + 1)
            
        return bid

    # -----------------------------------------------------------------------
    # CARD PLAY
    # -----------------------------------------------------------------------
    def play_card(self):
        legal = _legal_moves(self.my_hand, 
                             self.current_trick[0][1] if self.current_trick else None, 
                             self.spades_broken)
        if len(legal) == 1: return legal[0]

        # Determine Game Phase Context
        tricks_left = 13 - len(self.trick_history) - (1 if self.current_trick else 0)
        need_tricks = self.my_bid - self.tricks_won_me
        opp_need_tricks = (self.opp_bid or 7) - self.tricks_won_opp # Assume 7 if unknown
        
        # SCENARIOS
        is_nil = (self.my_bid == 0)
        opp_is_nil = (self.opp_bid == 0)
        bag_danger = self.my_bags >= 9
        set_opp_mode = (opp_need_tricks > 0 and tricks_left <= opp_need_tricks + 1) # They are close to making bid
        make_bid_mode = (need_tricks > 0)
        
        if not self.current_trick:
            return self._lead_card(legal, need_tricks, opp_need_tricks, is_nil, opp_is_nil, bag_danger, set_opp_mode)
        else:
            lead_card = self.current_trick[0][1]
            return self._follow_card(legal, lead_card, need_tricks, opp_need_tricks, is_nil, opp_is_nil, bag_danger, set_opp_mode)

    # -----------------------------------------------------------------------
    # LEADING LOGIC
    # -----------------------------------------------------------------------
    def _lead_card(self, legal, need, opp_need, is_nil, opp_nil, bag_danger, set_opp):
        # 1. NIL PLAYER: Lead lowest card of longest non-spade suit. Avoid spades.
        if is_nil:
            non_spades = [c for c in legal if c[0] != SPADES]
            if not non_spades: return min(legal, key=lambda c: c[1]) # Forced spade
            # Group by suit, pick longest suit, lead lowest
            by_suit = defaultdict(list)
            for c in non_spades: by_suit[c[0]].append(c)
            longest_suit = max(by_suit.keys(), key=lambda s: len(by_suit[s]))
            return min(by_suit[longest_suit], key=lambda c: c[1])

        # 2. OPPONENT NIL: Lead high cards to force them to win (or trump)
        # Actually, vs Nil, lead LOW cards from suits they might be void in? 
        # Standard: Lead Aces/Kings to force them to play high/trump. 
        # But in 2p, if they are void, they trump and win. 
        # Best vs Nil: Lead suits where YOU are short (they likely long) -> they must follow high.
        if opp_nil:
            # Find suit where I have few cards (they have many)
            suit_counts = Counter(c[0] for c in self.my_hand)
            # Prefer non-spades
            candidates = [c for c in legal if c[0] != SPADES]
            if not candidates: candidates = legal
            # Sort by my length ascending (short suit lead)
            candidates.sort(key=lambda c: (suit_counts[c[0]], -c[1])) 
            return candidates[0]

        # 3. BAG DANGER (9 bags): Try to LOSE tricks. Lead low off-suit.
        if bag_danger and need <= 0:
            safe_lose = [c for c in legal if c[0] != SPADES]
            if safe_lose:
                # Lead suit where opponent is likely void? No, that lets them trump (win).
                # Lead suit where opponent likely HAS cards (they win).
                # But we don't want to win.
                # Lead lowest card of longest suit (they likely have higher).
                by_suit = defaultdict(list)
                for c in safe_lose: by_suit[c[0]].append(c)
                longest = max(by_suit.keys(), key=lambda s: len(by_suit[s]))
                return min(by_suit[longest], key=lambda c: c[1])
            return max(legal, key=lambda c: (c[0]==SPADES, c[1])) # Lead high spade if forced

        # 4. NEED TRICKS (Make Bid)
        if need > 0:
            # Lead "Boss" cards (unbeatable) or establish long suits.
            bosses = [c for c in legal if self._is_boss(c)]
            if bosses:
                # Lead lowest boss to conserve high cards? Or highest to cash?
                # Cash highest boss first usually.
                return max(bosses, key=lambda c: (c[0]==SPADES, c[1]))
            
            # No bosses: Lead from longest/strongest non-spade suit
            non_spades = [c for c in legal if c[0] != SPADES]
            if non_spades:
                by_suit = defaultdict(list)
                for c in non_spades: by_suit[c[0]].append(c)
                # Score suit: Length * Avg Rank
                best_suit = max(by_suit.keys(), key=lambda s: len(by_suit[s]) * (sum(r for _,r in by_suit[s])/len(by_suit[s])))
                # Lead low from long suit to drive out high cards? Or high to cash?
                # Lead LOW (3rd/4th best) to promote partners? No partner. Lead HIGH to take trick now.
                return max(by_suit[best_suit], key=lambda c: c[1])
            
            # Only spades left
            return max(legal, key=lambda c: c[1])

        # 5. DON'T NEED TRICKS (Avoid Bags / Set Opponent)
        # If setting opponent: Lead suits they are void in (force trump) OR lead high cards they must beat?
        # Actually, to SET them, we want THEM to win tricks they don't want? No, we want them to MISS their bid.
        # If they bid 5 and have 4 tricks, they NEED 1 more. We want to WIN the remaining tricks.
        # So if set_opp_mode: We act like "Need Tricks".
        if set_opp and need <= 0:
             # We need to win tricks to prevent them getting theirs.
             return self._lead_card(legal, 1, opp_need, False, False, False, False) # Recurse with need=1

        # Default: Avoid bags. Lead low off-suit.
        non_spades = [c for c in legal if c[0] != SPADES]
        if non_spades:
            # Lead lowest card of suit where opponent likely has higher (my shortest suit)
            suit_counts = Counter(c[0] for c in self.my_hand)
            non_spades.sort(key=lambda c: (suit_counts[c[0]], c[1])) # Short suit, low rank
            return non_spades[0]
        
        return min(legal, key=lambda c: c[1]) # Lowest spade

    # -----------------------------------------------------------------------
    # FOLLOWING LOGIC (Second Hand Play)
    # -----------------------------------------------------------------------
    def _follow_card(self, legal, lead_card, need, opp_need, is_nil, opp_nil, bag_danger, set_opp):
        ls, lr = lead_card
        winners = [c for c in legal if _trick_winner(lead_card, c)]
        losers = [c for c in legal if c not in winners]
        
        # 1. NIL PLAYER: Must lose. Play highest loser (smooth discard) or lowest winner if forced.
        if is_nil:
            if losers:
                # Play highest loser to unload high cards safely
                return max(losers, key=lambda c: c[1])
            # Forced to win: Play lowest winner
            return min(winners, key=lambda c: c[1])

        # 2. OPPONENT NIL: We want THEM to win the trick (they led).
        # But we are following. They led. If we can win, we SHOULD win to deny them the trick? 
        # Wait. If Opp leads and we are Nil? Handled above.
        # If Opp is Nil and THEY led: We want to LOSE the trick (give it to Nil player).
        if opp_nil:
            if losers:
                # Lose with highest card (unload)
                return max(losers, key=lambda c: c[1])
            # Forced to win (we have only winners). Win cheaply.
            return min(winners, key=lambda c: c[1])

        # 3. BAG DANGER & Don't Need Tricks: Avoid winning.
        if bag_danger and need <= 0:
            if losers:
                return max(losers, key=lambda c: c[1]) # Shed high card
            return min(winners, key=lambda c: c[1]) # Win cheap

        # 4. NEED TRICKS (or Setting Opponent): Win as cheaply as possible.
        if need > 0 or (set_opp and need <= 0):
            if winners:
                # Second hand low? No, in 2p, if we can win, we win. 
                # But "Second hand low" applies to PARTNERSHIP. 
                # In 2p, if opponent leads, they are the only opponent. 
                # If we beat their card, we win the trick. 
                # We want to win the trick. Play lowest winner.
                return min(winners, key=lambda c: _card_value(c))
            # Can't win: Discard lowest value card (usually low off-suit, or low spade if spades led)
            return min(losers, key=lambda c: _card_value(c))

        # 5. DON'T NEED TRICKS (Comfortable): Lose if possible, shed high cards.
        if losers:
            # Shed highest card that loses (high off-suit, or high spade if spades led)
            return max(losers, key=lambda c: _card_value(c))
        return max(winners, key=lambda c: _card_value(c)) # Forced win, shed highest

    # -----------------------------------------------------------------------
    # HELPERS
    # -----------------------------------------------------------------------
    def _is_boss(self, card):
        """Is this card guaranteed to win the trick if led?"""
        s, r = card
        if s == SPADES: return True # High spade is boss if spades broken or only suit
        if not self.spades_broken: return True # Non-spade boss if spades not broken? No, opp can trump later.
        # Check if opponent can beat it in suit
        opp_higher = sum(1 for rr in range(r+1, 15) if self.opp_model.prob_has((s, rr)) > 0.1)
        # Check if opponent void (can trump)
        opp_void_prob = 1.0 if self.opp_model.prob_void(s) else 0.0
        
        # Heuristic: Boss if no higher cards likely held AND not likely to be trumped
        return opp_higher == 0 and opp_void_prob < 0.3

def _card_value(card):
    """Value for discarding: High spades > High off-suit > Low spades > Low off-suit"""
    s, r = card
    if s == SPADES: return r + 20
    return r
