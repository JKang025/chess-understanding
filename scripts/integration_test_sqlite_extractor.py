from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Example usage:
# uv run python scripts/integration_test_sqlite_extractor.py
# uv run python scripts/integration_test_sqlite_extractor.py --limit 20
# uv run python scripts/integration_test_sqlite_extractor.py --db /Users/jkang/repos/chess-understanding/data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db --limit 5

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data import load_games

DEFAULT_DB = ROOT / "data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quick integration check for src/data SQLite extractor."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to SQLite DB")
    parser.add_argument("--limit", type=int, default=10, help="Rows to validate (default: 10)")
    args = parser.parse_args()

    if args.limit < 1:
        parser.error("--limit must be >= 1")

    return args


def main() -> int:
    args = parse_args()

    if not args.db.exists():
        print(f"FAIL: DB not found: {args.db}", file=sys.stderr)
        return 1

    games = load_games(args.db, limit=args.limit)
    if len(games) != args.limit:
        print(f"FAIL: expected {args.limit} rows, got {len(games)}", file=sys.stderr)
        return 1

    for idx, game in enumerate(games, start=1):
        move_count = len(list(game.parsed_pgn.mainline_moves()))
        if move_count < 1:
            print(f"FAIL: row {idx} row_id={game.row_id} parsed with zero moves", file=sys.stderr)
            return 1

    first = games[0]
    print("PASS")
    print(f"db: {args.db}")
    print(f"validated_rows: {len(games)}")
    print(f"sample_row_id: {first.row_id}")
    print(f"sample_game_id: {first.game_id}")
    print(f"sample_white_black: {first.white} vs {first.black}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
