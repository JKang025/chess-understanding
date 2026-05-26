import argparse
import io
import subprocess
from pathlib import Path

import chess.pgn

# Example usage:
# uv run python scripts/show_pgn_shape.py --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn --games 2
# uv run python scripts/show_pgn_shape.py --input data/lichess_open_database/lichess_db_standard_rated_2026-04.pgn.zst --games 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Display what PGN data looks like (raw snippet + parsed game fields)."
    )
    parser.add_argument("--input", required=True, help="Input .pgn or .pgn.zst file")
    parser.add_argument("--games", type=int, default=1, help="How many games to display")
    parser.add_argument(
        "--san-moves",
        type=int,
        default=16,
        help="How many SAN moves to print per game",
    )
    args = parser.parse_args()

    if args.games < 1:
        parser.error("--games must be >= 1")
    if args.san_moves < 1:
        parser.error("--san-moves must be >= 1")

    return args


def open_text_stream(path: Path):
    if path.suffix == ".zst":
        proc = subprocess.Popen(["zstd", "-dc", str(path)], stdout=subprocess.PIPE)
        assert proc.stdout is not None
        return io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace"), proc

    return path.open("r", encoding="utf-8", errors="replace"), None


def header_preview(game: chess.pgn.Game) -> str:
    headers = game.headers
    keys = [
        "Event",
        "Site",
        "Date",
        "White",
        "Black",
        "Result",
        "WhiteElo",
        "BlackElo",
        "TimeControl",
        "Opening",
    ]
    lines = [f"{k}: {headers.get(k, '?')}" for k in keys]
    return "\n".join(lines)


def san_preview(game: chess.pgn.Game, limit: int) -> str:
    board = game.board()
    out: list[str] = []
    for idx, move in enumerate(game.mainline_moves()):
        if idx >= limit:
            break
        out.append(board.san(move))
        board.push(move)
    return " ".join(out) if out else "(no moves)"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"File not found: {input_path}")

    stream, proc = open_text_stream(input_path)

    try:
        for game_num in range(1, args.games + 1):
            game = chess.pgn.read_game(stream)
            if game is None:
                print(f"Stopped early: only found {game_num - 1} game(s).")
                break

            print(f"\n=== Game {game_num} ===")
            print("[Headers]")
            print(header_preview(game))

            print("\n[PGN text sample]")
            game_text = str(game)
            print("\n".join(game_text.splitlines()[:20]))

            moves = list(game.mainline_moves())
            print("\n[Move summary]")
            print(f"plies: {len(moves)}")
            print(f"first {args.san_moves} SAN moves: {san_preview(game, args.san_moves)}")
    finally:
        stream.close()
        if proc is not None:
            proc.wait()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
