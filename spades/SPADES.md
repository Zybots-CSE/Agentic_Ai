# Spades (two-player) — implementation specification

## Overview

Spades is a trick-taking card game in which the spade suit is permanently
trump. A game is played over multiple rounds until one player reaches **500
points** or falls to **−200 points**. Each round consists of a bidding phase
followed by 13 tricks.

---

## Deck

Use a standard 52-card deck with the **2♣ and 2♦ removed**, leaving **50 cards**. Each round:

- Deal **13 cards** to each player (alternating, starting with the non-dealer).
- Place the remaining **24 cards** face-down in a **kitty**. Kitty cards are not played and are not visible to either player; bots only know the kitty size.

### Card ranks (high to low within each suit)

```
A  K  Q  J  10  9  8  7  6  5  4  3  2
```

Suits have no rank relative to each other except that **spades are trump** (see below).

---

## Game flow

Each round proceeds in three phases:

1. Deal
2. Bid
3. Play (13 tricks)
4. Score

---

## Phase 1: Deal

Shuffle the 50-card deck. Deal 13 cards to each player one at a time, alternating (non-dealer receives the first card). The remaining 24 cards form the kitty and are set aside unseen. The dealer alternates each round.

---

## Phase 2: Bidding

After receiving their hand, each player states a **bid**: an integer from 0 to 13 representing the number of tricks they expect to win this round.

- Bids are made in turn: **non-dealer bids first**, then the dealer.
- Both bids are **public information** for the rest of the round.
- A bid of **0** is called a **nil bid** and is governed by special rules (see Nil Bids).
- There is no auction; each player bids once and the bid is final.

---

## Phase 3: Play

### Leading

- The **non-dealer leads** the first trick.
- The winner of each trick leads the next.
- **Spades may not be led** until the suit has been "broken" — i.e. at least one spade has been played as a discard or trump on a previous trick in this round — **unless the leading player holds nothing but spades**.

### Following

- A player **must follow suit** if they hold any card in the led suit.
- If a player is **void** in the led suit, they may play any card, including a spade.

### Winning a trick

- If **no spade** was played: the **highest card of the led suit** wins.
- If **one or more spades** were played: the **highest spade** wins.
- The trick winner takes all cards in the trick (for counting purposes) and leads the next trick.

---

## Phase 4: Scoring

### Making or missing your bid

Let `B` = a player's bid and `T` = tricks actually won by that player.

| Outcome | Score |
|---|---|
| `T >= B` and `B > 0` | `B × 10` points, plus `(T − B)` overtrick points (see Bags) |
| `T < B` and `B > 0` | `−(B × 10)` points (called being "set") |
| Nil bid succeeded (`T == 0`) | `+100` points |
| Nil bid failed (`T > 0`) | `−100` points |

Nil bid scoring is **independent** of the other player's bid and result. Each player's score is calculated separately.

### Bags (overtrick penalty)

Each overtrick (a trick won above the player's bid) scores **+1 point** but also increments that player's **bag counter**.

- Each player has a persistent bag counter that carries across rounds.
- When a player's bag counter reaches **10**, they lose **100 points** and their bag counter resets to **0**.
- Bag counter and bag penalty are tracked separately from the round score.

**Example:** A player bids 4 and wins 6 tricks. They score `4 × 10 = 40` points plus `2` overtrick points = **42 points**, and gain **2 bags**.

### Nil bids

A nil bid means the player commits to winning **zero tricks** this round.

- If the nil bidder wins **no tricks**: `+100` points.
- If the nil bidder wins **any trick**: `−100` points.
- The nil bidder's score from the nil is added to (or subtracted from) their running total independently of the other player's score.
- The non-nil player is scored normally against their own bid.

> **Optional — Blind nil:** A player may declare nil *before* looking at their cards. Success scores `+200`; failure scores `−200`. Implement as a variant flag.

### End-of-round scoring procedure

1. Count each player's tricks won.
2. Score each player's bid outcome (including nil if applicable).
3. Add overtricks to bags; apply bag penalty if bags ≥ 10.
4. Add round scores to cumulative totals.

---

## Game end conditions

- A player reaching **500 points or more** wins. If both players cross 500 in the same round, the higher score wins; if tied, play another round.
- A player reaching **−200 points** loses immediately (optional — implement as a configurable threshold).

---

## State representation

The following information must be tracked and made available:

### Per game
- Cumulative score for each player
- Bag count for each player
- Which player is dealer this round

### Per round
- Each player's hand (private to that player)
- Kitty size (24 cards; identities not revealed)
- Each player's bid
- Whether spades have been broken this round
- Tricks won by each player so far
- Full trick history (cards played, who led, who won)
- Current trick in progress (cards played so far, who led)

### Per trick
- Who led
- Cards played (indexed by player)
- Who won

---

## Legal moves

### Bidding phase

- Any integer from 0 to 13 is a legal bid.
- 0 triggers nil bid rules.

### Play phase

A card is legal to play if and only if:

1. The card is in the player's hand.
2. **If following:** the card matches the led suit, OR the player holds no cards of the led suit.
3. **If leading:** the card is not a spade, OR spades have been broken, OR the player holds only spades.

---

## Edge cases

- **All spades hand:** A player holding only spades may lead spades freely regardless of whether spades have been broken.
- **Void in led suit:** A player void in the led suit may play any card, including discarding a low spade, playing an off-suit card, or trumping high — all are legal.
- **Nil bid + winning a trick:** The nil bidder's round score is −100 regardless of how many tricks they win. Overtrick/bag rules do not apply to a failed nil bidder's won tricks (they do not score or bag the tricks won while failing nil).
- **Both players bid nil:** Both are scored independently. Each tries to avoid winning tricks.
- **Bag overflow across rounds:** Bags are cumulative. A player with 8 bags who earns 3 more in a round incurs the −100 penalty and carries over 1 bag.

---

## Bot interface

A bot receives the following inputs at each decision point:

### At bidding time
- Own hand (list of 13 cards)
- Kitty size (24; card identities unknown)
- Opponent's bid (if bidding in turn and opponent has already bid; otherwise unknown)

### At play time (each trick)

- Own hand (remaining cards)
- Kitty size (unchanged for the round; card identities unknown)
- Both bids
- Spades broken (boolean)
- Tricks won so far by each player
- Both players' current scores and bag counts
- Full history of completed tricks
- Cards played so far in the current trick (empty if bot is leading)

### Bot outputs
- **Bidding:** an integer 0–13
- **Playing:** a single card from the legal moves set

---

## Scoring example

**Round setup:** Player A bids 5, Player B bids nil.

**Result:** Player A wins 7 tricks, Player B wins 0 tricks.

| Player | Calculation | Score |
|---|---|---|
| A | Made bid (7 ≥ 5): `5 × 10 = 50`, plus 2 bags = `+52` | +52 |
| B | Nil succeeded (0 tricks): | +100 |

Player A also gains 2 bags. If A already had 8 bags, the total reaches 10, applying a −100 penalty: A's round score becomes `52 − 100 = −48`, and A's bag count resets to 0.
