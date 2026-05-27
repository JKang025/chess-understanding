from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Example usage:
# .venv/bin/python scripts/print_extracted_games.py --rows 3
# .venv/bin/python scripts/print_extracted_games.py --rows 2 --compact
# .venv/bin/python scripts/print_extracted_games.py --db /Users/jkang/repos/chess-understanding/data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db --rows 5

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data import iter_games

DEFAULT_DB = ROOT / "data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract N games from SQLite and print the Game objects."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite DB path")
    parser.add_argument("--rows", type=int, default=3, help="Rows to print (default: 3)")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact summary instead of full dataclass repr.",
    )
    args = parser.parse_args()

    if args.rows < 1:
        parser.error("--rows must be >= 1")

    return args


def main() -> int:
    args = parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1

    for game in iter_games(args.db, limit=args.rows):
        if args.compact:
            move_count = len(list(game.parsed_pgn.mainline_moves()))
            print(
                f"row_id={game.row_id} game_id={game.game_id} "
                f"players={game.white} vs {game.black} "
                f"elos={game.white_elo}/{game.black_elo} moves={move_count}"
            )
        else:
            print(game)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
