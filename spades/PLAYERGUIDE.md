# Spades Player Guide

This guide explains how to write a bot for the two-player Spades competition in `spades/`.

## Quick start

1. Create a file in `spades/players/`, e.g. `my_bot.py`.
2. Define a single function named `nextMove`.
3. Run the tournament from the `spades/` folder:

```bash
cd spades
python main.py
```

Your bot’s **filename** (without `.py`) becomes its leaderboard name. `example_player.py` is documentation only and is not loaded.

## The `nextMove` contract

```python
def nextMove(gameState):
    ...
```

- **`gameState`** is a read-only `PlayerView` object built by the engine.
- **Return type depends on phase:**
  - `"bid"` → `int` from `0` to `13` (`0` = nil)
  - `"play"` → `(suit, rank)` tuple, e.g. `("H", 14)` for the ace of hearts

Invalid returns or any raised exception **forfeit the entire match** to your opponent. Each `nextMove` call must finish within **2 seconds** or you forfeit (even if a legal move is returned later).

## Card encoding

Cards are `(suit, rank)` tuples:

| Suit | Code |
|------|------|
| Hearts | `"H"` |
| Diamonds | `"D"` |
| Clubs | `"C"` |
| Spades | `"S"` |

| Rank | Value |
|------|-------|
| 2–10 | `2`–`10` |
| Jack | `11` |
| Queen | `12` |
| King | `13` |
| Ace | `14` |

Spades are always trump. Each round you receive **13 cards**; the other 24 cards sit in an unseen kitty (`gameState.kitty_remaining == 24`).

## What you can see

### Always available

| Attribute | Meaning |
|-----------|---------|
| `your_hand` | Your current cards (copied list) |
| `phase` | `"bid"` or `"play"` |
| `your_name` / `opponent_name` | Player names |
| `dealer` | Who dealt this round |
| `turn` | Who must act now |
| `your_score` / `opponent_score` | Match totals (first to 500 wins) |
| `your_bags` / `opponent_bags` | Sandbag counts (penalty at 10) |
| `round_number` | Current round (1-based) |
| `kitty_remaining` | Kitty size (identities not revealed) |
| `hand_history` | Completed previous rounds (public info only; see below) |

### Bidding phase

| Attribute | Meaning |
|-----------|---------|
| `your_bid` | Your bid if already submitted, else `None` |
| `opponent_bid` | Opponent’s bid if known, else `None` |
| `opponent_bid_known` | `True` once opponent has bid |

Non-dealer bids first. If you are second to bid, you can see the opponent’s bid.

### Play phase

| Attribute | Meaning |
|-----------|---------|
| `your_bid` / `opponent_bid` | Bids for this round |
| `spades_broken` | Whether spades have been played this round |
| `tricks_won` | `{name: int}` tricks taken this round |
| `trick_history` | Completed tricks: `[{"leader", "plays", "winner"}, ...]` |
| `current_trick` | Cards played so far this trick (`[]` if you lead) |
| `lead` | Name of the player leading this trick |

You never see the opponent’s hand or kitty cards.

## Data structures

The engine passes plain Python lists and dicts. Collections on `PlayerView` are **copies** — mutating them does not affect the game.

### Cards and hands

A card is always a 2-tuple:

```python
("H", 14)   # ace of hearts
("S", 5)    # five of spades
```

`your_hand` is a list of cards still in your hand, e.g.:

```python
[("C", 10), ("D", 13), ("H", 7), ("S", 14), ...]
```

Order is not guaranteed to be sorted. A card you play is removed before you are asked again.

### Scores and counts

```python
gameState.tricks_won
# {"alice": 4, "bob": 2}   — tricks won *this round only*

gameState.your_score      # int, cumulative match score
gameState.opponent_score  # int
gameState.your_bags       # int, sandbags carried across rounds
```

Keys in `tricks_won` are player name strings (same as `your_name` / `opponent_name`).

### Bids

During bidding, `your_bid` and `opponent_bid` are `int` or `None` if not yet submitted. In play phase both are always set (`0` means nil).

### `current_trick` — trick in progress

A list of `(player_name, card)` pairs played so far **this trick**. It is empty when you are leading.

**You lead** (first to play the trick):

```python
gameState.current_trick == []
gameState.lead == gameState.your_name
```

**You follow** (opponent already played):

```python
gameState.current_trick == [
    ("bob", ("H", 13)),   # opponent led king of hearts
]
lead_suit = gameState.current_trick[0][1][0]  # "H"
lead_card = gameState.current_trick[0][1]       # ("H", 13)
```

There are only two players, so `current_trick` has length `0` or `1` when you are asked to move. After both play, the trick is resolved and cleared before the next one.

### `trick_history` — completed tricks

A list of dicts, one per finished trick, in **play order** (trick 1 first). Each entry:

```python
{
    "leader": "alice",                    # str: who led this trick
    "plays": [                            # list of (name, card), leader first
        ("alice", ("C", 14)),
        ("bob", ("C", 8)),
    ],
    "winner": "alice",                    # str: who won the trick
}
```

Example after three tricks:

```python
[
    {
        "leader": "bob",
        "plays": [("bob", ("D", 10)), ("alice", ("D", 14))],
        "winner": "alice",
    },
    {
        "leader": "alice",
        "plays": [("alice", ("H", 2)), ("bob", ("S", 3))],
        "winner": "bob",
    },
    {
        "leader": "bob",
        "plays": [("bob", ("S", 14)), ("alice", ("S", 9))],
        "winner": "bob",
    },
]
```

From this you can reconstruct the line of play, see when spades were first played (`"S"` in any `plays` entry where the led suit was not spades), and count how many tricks each player has taken (`len([t for t in trick_history if t["winner"] == my_name])` — or use `tricks_won` directly).

### `hand_history` — previous rounds

A list of completed **previous** rounds (empty on round 1). The current round is never included. Each entry is public information only (kitty cards are never revealed):

```python
{
    "round_number": 1,
    "dealer": "alice",
    "bids": {"alice": 3, "bob": 4},
    "tricks": [{"leader", "plays", "winner"}, ...],  # same shape as trick_history
    "tricks_won": {"alice": 6, "bob": 7},
    "round_scores": {"alice": 60, "bob": -40},
    "bags_after": {"alice": 0, "bob": 0},
    "scores_after": {"alice": 60, "bob": -40},
}
```

### `lead` vs `turn`

| Field | Meaning |
|-------|---------|
| `turn` | Who must act **right now** (bid or play a card) |
| `lead` | Who led the **current** trick (play phase only; `None` in bid phase) |

When `current_trick` is empty, `lead` is the player about to lead (same as `turn`). When you are following, `lead` is the opponent who played first.

### Kitty

`kitty_remaining` is an `int` (always `24` at the start of a round). You are not told which cards are in the kitty.

## Legal moves

### Bidding

Any integer `0`–`13`.

### Playing

Your returned card must:

1. Be in `your_hand`.
2. **Follow suit** when possible (match the led suit if you have it).
3. **Leading:** not lead spades unless spades are broken **or** you hold only spades.

The engine enforces these rules. Do not reimplement legality checks for submission, but you will need them internally to choose good moves.

## Minimal template

```python
def nextMove(gameState):
    if gameState.phase == "bid":
        return 3  # replace with your bidding logic

    hand = gameState.your_hand
    trick = gameState.current_trick

    if trick:
        lead_suit = trick[0][1][0]
        same_suit = [c for c in hand if c[0] == lead_suit]
        if same_suit:
            return same_suit[0]

    if not gameState.spades_broken:
        non_spades = [c for c in hand if c[0] != "S"]
        if non_spades:
            return non_spades[0]

    return hand[0]
```

See `players/example_player.py` for a commented reference and `players/basic_player.py` / `players/smart_player.py` for working examples.

## Scoring reminders

- Made bid: `bid × 10`, plus `+1` per overtrick (also adds a bag).
- Missed bid: `−(bid × 10)`.
- Nil made: `+100`. Nil failed: `−100`.
- At **10 bags**: `−100` penalty and bags reset to `0`.
- Match ends at **500** points or **−200** (instant loss).

Overtricks matter — avoid collecting bags when you are already close to 10.

## Tips

- Branch on `gameState.phase` first; bidding and play need different logic.
- Use `trick_history` to infer what suits remain and when spades were trumped.
- When following, read the lead card from `current_trick[0][1]`.
- Keep `nextMove` deterministic if you want reproducible debugging from logs in `spades/logs/`.
- Test locally by adding your file to `players/` and running `python main.py` with at least two bots present.

For full rules, see `SPADES.md`. For engine internals, see `engine.py`.
