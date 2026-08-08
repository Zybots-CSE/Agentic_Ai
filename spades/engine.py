# Spades game engine — two-player trick-taking to 500 points.

import csv
import random

# ---------------------------------------------------------------------------
# Card helpers
# ---------------------------------------------------------------------------
SUITS = ["H", "D", "C", "S"]
RANKS = list(range(2, 15))  # 2..14, where 14 = Ace
SPADES = "S"
CARDS_PER_HAND = 13
TRICKS_PER_ROUND = 13
MAX_BID = TRICKS_PER_ROUND
KITTY_SIZE = 24
WIN_SCORE = 500
LOSE_SCORE = -200
BAG_LIMIT = 10


def build_deck():
    """Return the 50-card Spades deck (2C and 2D removed)."""
    return [(s, r) for s in SUITS for r in RANKS if not (s in ("C", "D") and r == 2)]


def card_str(card):
    """Human-readable card string, e.g. ('H', 14) -> 'AH'."""
    rank_names = {14: "A", 13: "K", 12: "Q", 11: "J"}
    r = rank_names.get(card[1], str(card[1]))
    return f"{r}{card[0]}"


# ---------------------------------------------------------------------------
# PlayerView
# ---------------------------------------------------------------------------
class PlayerView:
    """Read-only game state visible to the acting player."""

    def __init__(
        self,
        your_hand,
        phase,
        your_name,
        opponent_name,
        dealer,
        turn,
        your_score,
        opponent_score,
        your_bags,
        opponent_bags,
        round_number,
        your_bid=None,
        opponent_bid=None,
        opponent_bid_known=False,
        spades_broken=False,
        tricks_won=None,
        trick_history=None,
        current_trick=None,
        lead=None,
        kitty_remaining=None,
        hand_history=None,
    ):
        self.your_hand = list(your_hand)
        self.phase = phase
        self.your_name = your_name
        self.opponent_name = opponent_name
        self.dealer = dealer
        self.turn = turn
        self.your_score = your_score
        self.opponent_score = opponent_score
        self.your_bags = your_bags
        self.opponent_bags = opponent_bags
        self.round_number = round_number
        self.your_bid = your_bid
        self.opponent_bid = opponent_bid
        self.opponent_bid_known = opponent_bid_known
        self.spades_broken = spades_broken
        self.tricks_won = dict(tricks_won) if tricks_won is not None else {}
        self.trick_history = list(trick_history) if trick_history is not None else []
        self.current_trick = list(current_trick) if current_trick is not None else []
        self.lead = lead
        self.kitty_remaining = kitty_remaining
        self.hand_history = list(hand_history) if hand_history is not None else []


# ---------------------------------------------------------------------------
# GameState
# ---------------------------------------------------------------------------
class GameState:
    def __init__(self, p1, p2):
        self.players = [p1, p2]
        self.hands = {p1: [], p2: []}
        self.scores = {p1: 0, p2: 0}
        self.bags = {p1: 0, p2: 0}
        self.dealer = None
        self.round_number = 0
        self.phase = "bid"
        self.turn = None
        self.bids = {p1: None, p2: None}
        self.spades_broken = False
        self.tricks_won = {p1: 0, p2: 0}
        self.trick_history = []
        self.trick = []
        self.kitty = []
        self.hand_history = []
        self.game_over = False
        self.winner = None

    def opponent(self, player):
        return self.players[1] if player == self.players[0] else self.players[0]

    def non_dealer(self):
        return self.opponent(self.dealer)

    def make_player_view(self, player):
        opp = self.opponent(player)
        your_bid = None
        opponent_bid = None
        opponent_bid_known = False
        spades_broken = False
        tricks_won = None
        trick_history = None
        current_trick = None
        lead = None

        if self.phase == "bid":
            your_bid = self.bids[player]
            if self.bids[opp] is not None:
                opponent_bid = self.bids[opp]
                opponent_bid_known = True
        elif self.phase == "play":
            your_bid = self.bids[player]
            opponent_bid = self.bids[opp]
            opponent_bid_known = True
            spades_broken = self.spades_broken
            tricks_won = self.tricks_won
            trick_history = self.trick_history
            current_trick = self.trick
            lead = self.turn

        return PlayerView(
            your_hand=self.hands[player],
            phase=self.phase,
            your_name=player,
            opponent_name=opp,
            dealer=self.dealer,
            turn=self.turn,
            your_score=self.scores[player],
            opponent_score=self.scores[opp],
            your_bags=self.bags[player],
            opponent_bags=self.bags[opp],
            round_number=self.round_number,
            your_bid=your_bid,
            opponent_bid=opponent_bid,
            opponent_bid_known=opponent_bid_known,
            spades_broken=spades_broken,
            tricks_won=tricks_won,
            trick_history=trick_history,
            current_trick=current_trick,
            lead=lead,
            kitty_remaining=len(self.kitty) if self.phase in ("bid", "play") else None,
            hand_history=self.hand_history,
        )


# ---------------------------------------------------------------------------
# Rules helpers
# ---------------------------------------------------------------------------
def legal_cards(hand, lead_card, spades_broken):
    """Return cards legal to play given the lead card and spades-broken state."""
    if lead_card is None:
        non_spades = [c for c in hand if c[0] != SPADES]
        if not non_spades:
            return list(hand)
        if spades_broken:
            return list(hand)
        return non_spades

    lead_suit = lead_card[0]
    same_suit = [c for c in hand if c[0] == lead_suit]
    return same_suit if same_suit else list(hand)


def resolve_trick(lead_card, follow_card):
    """Return True if lead_card wins the trick, False if follow_card wins."""
    lead_suit, lead_rank = lead_card
    follow_suit, follow_rank = follow_card

    if lead_suit == SPADES or follow_suit == SPADES:
        if lead_suit == SPADES and follow_suit == SPADES:
            return lead_rank >= follow_rank
        if lead_suit == SPADES:
            return True
        return False

    if follow_suit == lead_suit:
        return lead_rank >= follow_rank
    return True


def _spade_played(card):
    return card[0] == SPADES


def _update_spades_broken(gs, lead_card, follow_card):
    if _spade_played(lead_card) or _spade_played(follow_card):
        gs.spades_broken = True


def legal_bids():
    return list(range(0, MAX_BID + 1))


def score_round(bid, tricks, bags_before):
    """Return (round_points, bags_after) for one player this round."""
    if bid == 0:
        round_points = 100 if tricks == 0 else -100
        return round_points, bags_before

    if tricks >= bid:
        overtricks = tricks - bid
        round_points = bid * 10 + overtricks
        bags_after = bags_before + overtricks
    else:
        round_points = -(bid * 10)
        bags_after = bags_before

    while bags_after >= BAG_LIMIT:
        round_points -= 100
        bags_after -= BAG_LIMIT

    return round_points, bags_after


# ---------------------------------------------------------------------------
# playGame
# ---------------------------------------------------------------------------
def playGame(name1, func1, name2, func2, logger):
    """Play one full Spades match. Returns 1, 2, or 0."""
    funcs = {name1: func1, name2: func2}
    gs = GameState(name1, name2)
    gs.dealer = name2

    logger.log_setup(gs)

    while not gs.game_over:
        gs.round_number += 1
        gs.dealer = gs.opponent(gs.dealer)
        result = _play_round(gs, funcs, name1, name2, logger)
        if result is not None:
            return result

    return 1 if gs.winner == name1 else 2 if gs.winner == name2 else 0


def _play_round(gs, funcs, name1, name2, logger):
    """Deal, bid, play tricks, and score one round. Return forfeit result or None."""
    deck = build_deck()
    random.shuffle(deck)
    p1, p2 = gs.players
    non_dealer = gs.non_dealer()
    dealer = gs.dealer

    gs.hands[p1] = []
    gs.hands[p2] = []
    for i in range(CARDS_PER_HAND * 2):
        if i % 2 == 0:
            gs.hands[non_dealer].append(deck.pop())
        else:
            gs.hands[dealer].append(deck.pop())
    gs.kitty = deck
    assert len(gs.hands[p1]) == CARDS_PER_HAND
    assert len(gs.hands[p2]) == CARDS_PER_HAND
    assert len(gs.kitty) == KITTY_SIZE
    gs.bids = {p1: None, p2: None}
    gs.spades_broken = False
    gs.tricks_won = {p1: 0, p2: 0}
    gs.trick_history = []
    gs.trick = []
    gs.phase = "bid"

    logger.log_round_start(gs)

    bidder_order = [gs.non_dealer(), gs.dealer]
    for player in bidder_order:
        gs.turn = player
        bid = _get_bid(gs, player, funcs[player], logger)
        if bid is None:
            return _forfeit(gs, player, name1, name2, logger)
        gs.bids[player] = bid
        logger.log_bid(player, bid)

    gs.phase = "play"
    gs.turn = gs.non_dealer()
    logger.log_phase_change("play")

    for trick_num in range(1, TRICKS_PER_ROUND + 1):
        leader = gs.turn
        follower = gs.opponent(leader)
        gs.trick = []

        leader_card = _get_card(gs, leader, funcs[leader], lead_card=None, logger=logger)
        if leader_card is None:
            return _forfeit(gs, leader, name1, name2, logger)
        gs.trick.append((leader, leader_card))
        gs.hands[leader].remove(leader_card)

        follower_card = _get_card(gs, follower, funcs[follower], lead_card=leader_card, logger=logger)
        if follower_card is None:
            return _forfeit(gs, follower, name1, name2, logger)
        gs.trick.append((follower, follower_card))
        gs.hands[follower].remove(follower_card)

        _update_spades_broken(gs, leader_card, follower_card)
        leader_wins = resolve_trick(leader_card, follower_card)
        trick_winner = leader if leader_wins else follower
        gs.tricks_won[trick_winner] += 1
        gs.trick_history.append(
            {
                "leader": leader,
                "plays": [(leader, leader_card), (follower, follower_card)],
                "winner": trick_winner,
            }
        )

        logger.log_trick(trick_num, leader, leader_card, follower, follower_card, trick_winner)
        gs.turn = trick_winner

    _apply_round_scoring(gs, logger)
    return _check_match_end(gs, name1, name2, logger)


def _apply_round_scoring(gs, logger):
    round_scores = {}
    for player in gs.players:
        bid = gs.bids[player]
        tricks = gs.tricks_won[player]
        bags_before = gs.bags[player]
        points, gs.bags[player] = score_round(bid, tricks, bags_before)
        gs.scores[player] += points
        round_scores[player] = points

    logger.log_round_score(gs, round_scores)
    gs.hand_history.append(
        {
            "round_number": gs.round_number,
            "dealer": gs.dealer,
            "bids": dict(gs.bids),
            "tricks": [dict(t) for t in gs.trick_history],
            "tricks_won": dict(gs.tricks_won),
            "round_scores": dict(round_scores),
            "bags_after": dict(gs.bags),
            "scores_after": dict(gs.scores),
        }
    )


def _check_match_end(gs, name1, name2, logger):
    p1, p2 = gs.players
    s1, s2 = gs.scores[p1], gs.scores[p2]

    if s1 >= WIN_SCORE and s2 >= WIN_SCORE:
        if s1 > s2:
            gs.game_over = True
            gs.winner = p1
            logger.log_result(gs)
            return 1 if p1 == name1 else 2
        if s2 > s1:
            gs.game_over = True
            gs.winner = p2
            logger.log_result(gs)
            return 1 if p2 == name1 else 2
        return None

    if s1 >= WIN_SCORE:
        gs.game_over = True
        gs.winner = p1
        logger.log_result(gs)
        return 1 if p1 == name1 else 2

    if s2 >= WIN_SCORE:
        gs.game_over = True
        gs.winner = p2
        logger.log_result(gs)
        return 1 if p2 == name1 else 2

    if s1 <= LOSE_SCORE:
        gs.game_over = True
        gs.winner = p2
        logger.log_result(gs)
        return 1 if p2 == name1 else 2

    if s2 <= LOSE_SCORE:
        gs.game_over = True
        gs.winner = p1
        logger.log_result(gs)
        return 1 if p1 == name1 else 2

    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _get_bid(gs, player, func, logger):
    view = gs.make_player_view(player)
    allowed = legal_bids()

    try:
        bid = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    if not isinstance(bid, int):
        logger.log_error(player, f"bid {bid!r} is not an integer")
        return None
    if bid not in allowed:
        logger.log_error(player, f"bid {bid} is not in range 0-{MAX_BID}")
        return None

    return bid


def _get_card(gs, player, func, lead_card, logger):
    view = gs.make_player_view(player)
    allowed = legal_cards(gs.hands[player], lead_card, gs.spades_broken)

    try:
        card = func(view)
    except Exception as e:
        logger.log_error(player, f"nextMove raised {type(e).__name__}: {e}")
        return None

    if card not in gs.hands[player]:
        logger.log_error(player, f"played {card!r} which is not in their hand")
        return None
    if card not in allowed:
        if lead_card is None:
            logger.log_error(player, f"played {card_str(card)} but cannot lead spades yet")
        else:
            logger.log_error(player, f"played {card_str(card)} but must follow suit")
        return None

    return card


def _forfeit(gs, forfeiting_player, name1, name2, logger):
    gs.game_over = True
    winner = gs.opponent(forfeiting_player)
    gs.winner = winner
    logger.log_forfeit(forfeiting_player, winner)
    return 1 if winner == name1 else 2


# ---------------------------------------------------------------------------
# GameLogger
# ---------------------------------------------------------------------------
class GameLogger:
    """Simple file-based logger for a matchup between two players."""

    def __init__(self, filepath):
        self.filepath = filepath
        self._lines = []

    def start_game(self, game_number):
        self._lines.append(f"\n{'=' * 60}")
        self._lines.append(f"Game {game_number}")
        self._lines.append(f"{'=' * 60}")

    def log_setup(self, gs):
        self._lines.append(f"Players: {gs.players[0]} vs {gs.players[1]}")
        self._lines.append(f"Target: {WIN_SCORE} points (sandbag loss at {LOSE_SCORE})")

    def log_round_start(self, gs):
        p1, p2 = gs.players
        self._lines.append(
            f"\n--- Round {gs.round_number}: dealer {gs.dealer} | "
            f"scores {gs.scores[p1]} / {gs.scores[p2]} | "
            f"bags {gs.bags[p1]} / {gs.bags[p2]} ---"
        )
        self._lines.append(f"{p1} hand: {_hand_str(gs.hands[p1])}")
        self._lines.append(f"{p2} hand: {_hand_str(gs.hands[p2])}")
        self._lines.append(f"Kitty: {len(gs.kitty)} cards (unseen)")

    def log_phase_change(self, phase):
        self._lines.append(f"Phase: {phase}")

    def log_bid(self, player, bid):
        label = "nil" if bid == 0 else str(bid)
        self._lines.append(f"  {player} bids {label}")

    def log_trick(self, trick_num, leader, leader_card, follower, follower_card, winner):
        self._lines.append(
            f"  Trick {trick_num:>2}: {leader} leads {card_str(leader_card)}, "
            f"{follower} plays {card_str(follower_card)} -> {winner} wins"
        )

    def log_round_score(self, gs, round_scores):
        p1, p2 = gs.players
        self._lines.append(
            f"  Round score: {p1} {round_scores[p1]:+d} ({gs.tricks_won[p1]} tricks, "
            f"bid {gs.bids[p1]}, bags {gs.bags[p1]}) | "
            f"{p2} {round_scores[p2]:+d} ({gs.tricks_won[p2]} tricks, "
            f"bid {gs.bids[p2]}, bags {gs.bags[p2]})"
        )
        self._lines.append(
            f"  Totals: {p1} {gs.scores[p1]} | {p2} {gs.scores[p2]}"
        )

    def log_error(self, player, message):
        self._lines.append(f"  ERROR ({player}): {message}")

    def log_forfeit(self, loser, winner):
        self._lines.append(f"  FORFEIT: {loser} forfeits. {winner} wins.")

    def log_result(self, gs):
        p1, p2 = gs.players
        self._lines.append(
            f"  Final: {p1} {gs.scores[p1]} (bags {gs.bags[p1]}) - "
            f"{gs.scores[p2]} (bags {gs.bags[p2]}) {p2}"
        )
        if gs.winner:
            self._lines.append(f"  Winner: {gs.winner}")
        else:
            self._lines.append("  Draw")

    def flush(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self._lines) + "\n")

    @staticmethod
    def write_leaderboard_csv(filepath, scores):
        rows = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["player", "score"])
            for name, score in rows:
                writer.writerow([name, f"{score:.1f}"])


def _hand_str(hand):
    return " ".join(card_str(c) for c in sorted(hand, key=lambda c: (c[0], c[1])))
