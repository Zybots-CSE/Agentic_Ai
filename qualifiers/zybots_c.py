"""
Titan German Whist Player Bot (Fixed & Optimized)
"""

SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))
FULL_DECK = set((s, r) for s in SUITS for r in RANKS)


def legal_cards(hand, lead_card):
    if lead_card is None:
        return list(hand)
    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def resolve_trick(lead_card, follow_card, trump_suit):
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card

    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    elif follow_suit == trump_suit:
        return False
    return True


class BotMemory:
    def __init__(self):
        self.seen_cards = set()

    def sync(self, view):
        if view.phase == 1 and view.stock_remaining == 25 and len(view.your_hand) == 13:
            self.seen_cards.clear()

        for card in view.your_hand:
            self.seen_cards.add(card)
        if view.face_up_card:
            self.seen_cards.add(view.face_up_card)
        for _, card in view.current_trick:
            self.seen_cards.add(card)

    def deduce_opponent_hand(self, your_hand):
        unseen = FULL_DECK - self.seen_cards - set(your_hand)
        return list(unseen)


MEMORY = BotMemory()


def solve_phase2_move(hand, opp_hand, trump, lead_card):
    allowed = legal_cards(hand, lead_card)

    def card_power(c):
        return (20 if c[0] == trump else 0) + c[1]

    allowed_sorted = sorted(allowed, key=card_power)

    if lead_card is None:
        boss_cards = []
        for card in hand:
            c_suit, c_rank = card
            opp_higher = [
                oc for oc in opp_hand
                if oc[0] == c_suit and oc[1] > c_rank
            ]

            if not opp_higher:
                if c_suit == trump:
                    boss_cards.append(card)
                else:
                    opp_has_trumps = any(oc[0] == trump for oc in opp_hand)
                    opp_has_suit = any(oc[0] == c_suit for oc in opp_hand)
                    if not opp_has_trumps or opp_has_suit:
                        boss_cards.append(card)

        if boss_cards:
            non_trump_bosses = [c for c in boss_cards if c[0] != trump]
            if non_trump_bosses:
                return max(non_trump_bosses, key=lambda c: c[1])
            return max(boss_cards, key=lambda c: c[1])

        non_trumps = [c for c in allowed_sorted if c[0] != trump]
        if non_trumps:
            suit_counts = {}
            for c in non_trumps:
                suit_counts[c[0]] = suit_counts.get(c[0], 0) + 1
            shortest_suit = min(suit_counts, key=suit_counts.get)
            shortest_candidates = [c for c in non_trumps if c[0] == shortest_suit]
            return shortest_candidates[0]

        return allowed_sorted[0]

    else:
        lead_suit = lead_card[0]
        can_follow = (allowed[0][0] == lead_suit)

        if can_follow:
            winners = [c for c in allowed_sorted if c[1] > lead_card[1]]
            if winners:
                return winners[0]
            return allowed_sorted[0]

        if lead_suit != trump:
            trumps = [c for c in allowed_sorted if c[0] == trump]
            if trumps:
                return trumps[0]

        return allowed_sorted[0]


def nextMove(view):
    MEMORY.sync(view)

    hand = view.your_hand
    trump = view.trump_suit

    lead_card = None
    if view.current_trick and view.current_trick[0][0] != view.your_name:
        lead_card = view.current_trick[0][1]

    allowed = legal_cards(hand, lead_card)

    if view.phase == 1:
        prize = view.face_up_card

        is_good_prize = False
        if prize:
            p_suit, p_rank = prize
            is_good_prize = (p_suit == trump) or (p_rank >= 12)

        sorted_allowed = sorted(allowed, key=lambda c: (1 if c[0] == trump else 0, c[1]))

        if lead_card is None:
            if is_good_prize:
                return sorted_allowed[-1]
            else:
                non_trumps = [c for c in sorted_allowed if c[0] != trump]
                return non_trumps[0] if non_trumps else sorted_allowed[0]
        else:
            lead_suit = lead_card[0]
            can_follow = (allowed[0][0] == lead_suit)

            if is_good_prize:
                if can_follow:
                    winners = [c for c in sorted_allowed if c[1] > lead_card[1]]
                    if winners:
                        return winners[0]
                elif trump in [c[0] for c in allowed]:
                    trumps = [c for c in sorted_allowed if c[0] == trump]
                    return trumps[0]

                return sorted_allowed[0]
            else:
                return sorted_allowed[0]

    else:
        opp_hand = MEMORY.deduce_opponent_hand(hand)
        return solve_phase2_move(hand, opp_hand, trump, lead_card)