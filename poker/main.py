# Single-table poker tournament — all players share every hand.

import os
import sys
import importlib.util
import threading

from engine import GameLogger, playHand, STARTING_STACK

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HANDS_PER_TOURNAMENT = 100
MIN_PLAYERS = 2
MAX_PLAYERS = 10
MOVE_TIMEOUT_SECONDS = 2.0
PLAYERS_DIR = os.path.join(os.path.dirname(__file__), "players")
LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")


# ---------------------------------------------------------------------------
# Move timeout
# ---------------------------------------------------------------------------
def with_move_timeout(next_move, timeout=MOVE_TIMEOUT_SECONDS):
    """Wrap nextMove so calls exceeding *timeout* seconds raise TimeoutError."""

    def timed_next_move(game_state):
        box = {}

        def runner():
            try:
                box["value"] = next_move(game_state)
            except BaseException as e:
                box["error"] = e

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(
                f"nextMove exceeded {timeout} second limit"
            )
        if "error" in box:
            raise box["error"]
        return box["value"]

    return timed_next_move


# ---------------------------------------------------------------------------
# Player loading
# ---------------------------------------------------------------------------
def load_players(players_dir):
    """Scan *players_dir* for .py files and import their nextMove functions."""
    players = {}

    for filename in sorted(os.listdir(players_dir)):
        if not filename.endswith(".py"):
            continue
        if filename.startswith("_"):
            continue
        if filename == "example_player.py":
            continue

        name = filename[:-3]
        filepath = os.path.join(players_dir, filename)

        spec = importlib.util.spec_from_file_location(name, filepath)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[WARNING] Could not load player '{name}': {e}")
            continue

        if not hasattr(module, "nextMove") or not callable(module.nextMove):
            print(f"[WARNING] Player '{name}' has no callable nextMove – skipped.")
            continue

        players[name] = with_move_timeout(module.nextMove)
        print(f"Loaded player: {name}")

    return players


# ---------------------------------------------------------------------------
# Tournament
# ---------------------------------------------------------------------------
def run_tournament():
    os.makedirs(LOGS_DIR, exist_ok=True)

    players = load_players(PLAYERS_DIR)
    count = len(players)

    if count < MIN_PLAYERS:
        print(f"Need at least {MIN_PLAYERS} players in /players to run a tournament.")
        sys.exit(1)
    if count > MAX_PLAYERS:
        print(f"At most {MAX_PLAYERS} players allowed; found {count}.")
        sys.exit(1)

    scores = {name: 0 for name in sorted(players)}
    log_path = os.path.join(LOGS_DIR, "tournament.log")
    logger = GameLogger(log_path)
    hand_history = []

    print(
        f"\nStarting tournament: {count} players, "
        f"{HANDS_PER_TOURNAMENT} hands, {STARTING_STACK} chips/hand\n"
    )

    for hand_num in range(1, HANDS_PER_TOURNAMENT + 1):
        logger.start_hand(hand_num)
        ending = playHand(players, logger, hand_num, hand_history=hand_history)
        for name, stack in ending.items():
            scores[name] += stack
        if hand_num % 10 == 0 or hand_num == HANDS_PER_TOURNAMENT:
            print(f"  Hand {hand_num}/{HANDS_PER_TOURNAMENT} complete")

    logger.flush()

    print("\n" + "=" * 40)
    print("         FINAL LEADERBOARD")
    print("=" * 40)

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(ranking, start=1):
        print(f"  {rank}. {name:<20} {score:>12.0f} chips")

    print("=" * 40)

    csv_path = os.path.join(LOGS_DIR, "leaderboard.csv")
    GameLogger.write_leaderboard_csv(csv_path, scores)
    print(f"Tournament log: {log_path}")
    print(f"Leaderboard CSV: {csv_path}")


if __name__ == "__main__":
    run_tournament()
