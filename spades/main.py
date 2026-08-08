# This file runs the tournament between all the files in the /players folder.
# It is game-agnostic in spirit: it delegates all rule logic to engine.playGame.

import os
import sys
import importlib.util
import threading
from itertools import combinations

from engine import GameLogger, playGame

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GAMES_PER_MATCHUP = 300
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
    """Scan *players_dir* for .py files and import their nextMove functions.

    Returns a dict  {player_name: nextMove_function}.
    Files starting with '_' or named 'example_player.py' are skipped.
    Each nextMove is wrapped with with_move_timeout.
    """
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
    """Run a full round-robin tournament and print the leaderboard."""

    os.makedirs(LOGS_DIR, exist_ok=True)

    players = load_players(PLAYERS_DIR)

    if len(players) < 2:
        print("Need at least 2 players in the /players folder to run a tournament.")
        sys.exit(1)

    scores = {name: 0.0 for name in players}
    matchups = list(combinations(sorted(players.keys()), 2))
    total_matchups = len(matchups)

    for idx, (nameA, nameB) in enumerate(matchups, start=1):
        funcA = players[nameA]
        funcB = players[nameB]

        log_path = os.path.join(LOGS_DIR, f"{nameA}_vs_{nameB}.log")
        logger = GameLogger(log_path)

        print(f"\nMatchup {idx}/{total_matchups}: {nameA} vs {nameB}")

        a_wins = 0
        b_wins = 0
        draws = 0

        for game_num in range(1, GAMES_PER_MATCHUP + 1):
            logger.start_game(game_num)

            if game_num % 2 == 1:
                result = playGame(nameA, funcA, nameB, funcB, logger)
                if result == 1:
                    a_wins += 1
                elif result == 2:
                    b_wins += 1
                else:
                    draws += 1
            else:
                result = playGame(nameB, funcB, nameA, funcA, logger)
                if result == 1:
                    b_wins += 1
                elif result == 2:
                    a_wins += 1
                else:
                    draws += 1

        logger.flush()

        scores[nameA] += a_wins + 0.5 * draws
        scores[nameB] += b_wins + 0.5 * draws

        print(f"  {nameA} wins: {a_wins}  |  {nameB} wins: {b_wins}  |  Draws: {draws}")

    print("\n" + "=" * 40)
    print("         FINAL LEADERBOARD")
    print("=" * 40)

    ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (name, score) in enumerate(ranking, start=1):
        print(f"  {rank}. {name:<20} {score:>7.1f} pts")

    print("=" * 40)

    csv_path = os.path.join(LOGS_DIR, "leaderboard.csv")
    GameLogger.write_leaderboard_csv(csv_path, scores)
    print(f"Leaderboard CSV: {csv_path}")


if __name__ == "__main__":
    run_tournament()
