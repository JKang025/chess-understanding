import argparse
import io
import subprocess
import sys
from pathlib import Path

import chess.pgn

# Examples:
# uv run python scripts/read_lichess_sample.py --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn.zst
# uv run python scripts/read_lichess_sample.py --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn.zst --mode bytes --num-bytes 4096
# uv run python scripts/read_lichess_sample.py --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn.zst --game-index 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read a sample from a compressed Lichess PGN (.pgn.zst) without full decompression."
    )
    parser.add_argument("--input", required=True, help="Path to .pgn.zst file")
    parser.add_argument(
        "--mode",
        choices=["game", "bytes"],
        default="game",
        help="Read one parsed game or raw decompressed bytes.",
    )
    parser.add_argument(
        "--game-index",
        type=int,
        default=1,
        help="1-based game index to read when --mode game (default: 1).",
    )
    parser.add_argument(
        "--num-bytes",
        type=int,
        default=2048,
        help="Byte count to read when --mode bytes (default: 2048).",
    )
    return parser.parse_args()


def open_zstd_stream(path: Path) -> subprocess.Popen[bytes]:
    # Stream decompressed data so we never load the full file in memory.
    return subprocess.Popen(
        ["zstd", "-dc", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_game(path: Path, game_index: int) -> int:
    if game_index < 1:
        raise ValueError("--game-index must be >= 1")

    proc = open_zstd_stream(path)
    assert proc.stdout is not None

    try:
        text_stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace")

        game = None
        for _ in range(game_index):
            game = chess.pgn.read_game(text_stream)
            if game is None:
                break

        if game is None:
            print(f"No game found at index {game_index}")
            return 1

        print(f"Game #{game_index}")
        for key, value in game.headers.items():
            print(f"{key}: {value}")

        moves = list(game.mainline_moves())
        print(f"Move count: {len(moves)}")
        print("First 20 SAN moves:")

        board = game.board()
        san_moves: list[str] = []
        for move in moves[:20]:
            san_moves.append(board.san(move))
            board.push(move)
        print(" ".join(san_moves) if san_moves else "(no moves)")

        return 0
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()


def read_bytes(path: Path, num_bytes: int) -> int:
    if num_bytes < 1:
        raise ValueError("--num-bytes must be >= 1")

    proc = open_zstd_stream(path)
    assert proc.stdout is not None

    try:
        chunk = proc.stdout.read(num_bytes)
        if not chunk:
            print("No bytes read (empty stream)")
            return 1

        text = chunk.decode("utf-8", errors="replace")
        print(text)
        return 0
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 1

    if args.mode == "game":
        return read_game(input_path, args.game_index)

    return read_bytes(input_path, args.num_bytes)


if __name__ == "__main__":
    raise SystemExit(main())
