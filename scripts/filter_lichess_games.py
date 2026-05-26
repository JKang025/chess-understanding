import argparse
import io
import subprocess
import sys
from pathlib import Path

import chess.pgn

# Examples:
# uv run python scripts/filter_lichess_games.py \
#   --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn.zst \
#   --max-games 10000
#
# uv run python scripts/filter_lichess_games.py \
#   --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn.zst \
#   --min-elo 1800 --min-speed blitz --variant Standard
#
# uv run python scripts/filter_lichess_games.py \
#   --input data/lichess_open_database/lichess_db_standard_rated_2024-01.pgn \
#   --result 1-0 --opening-contains "Sicilian" --max-games 50000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filter Lichess PGN games and write matching games to a new PGN file."
    )

    parser.add_argument("--input", required=True, help="Input .pgn or .pgn.zst file")
    parser.add_argument(
        "--out-dir",
        default="data/filtered_lichess",
        help="Directory to store filtered PGN output.",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help="Optional output filename. Default: <input_stem>.filtered.pgn",
    )
    parser.add_argument(
        "--max-games",
        type=int,
        default=None,
        help="Stop after writing this many matched games.",
    )

    parser.add_argument("--min-elo", type=int, default=None)
    parser.add_argument("--max-elo", type=int, default=None)
    parser.add_argument("--time-control-prefix", default=None)
    parser.add_argument(
        "--min-speed",
        choices=["bullet", "blitz", "rapid", "classical"],
        default=None,
        help="Keep games at this speed or slower (e.g. blitz keeps blitz/rapid/classical).",
    )
    parser.add_argument("--variant", default=None)
    parser.add_argument("--result", choices=["1-0", "0-1", "1/2-1/2"], default=None)
    parser.add_argument("--opening-contains", default=None)

    args = parser.parse_args()

    if args.min_elo is not None and args.max_elo is not None and args.min_elo > args.max_elo:
        parser.error("--min-elo must be <= --max-elo")

    if args.max_games is not None and args.max_games < 1:
        parser.error("--max-games must be >= 1")

    return args


def open_input_text_stream(path: Path):
    if path.suffix == ".zst":
        proc = subprocess.Popen(
            ["zstd", "-dc", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None
        text_stream = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace")
        return text_stream, proc

    text_stream = path.open("r", encoding="utf-8", errors="replace")
    return text_stream, None


def parse_elo(headers: chess.pgn.Headers, key: str) -> int | None:
    value = headers.get(key)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def parse_time_control_seconds(value: str) -> tuple[int, int] | None:
    # Expected format is "<base>+<increment>", for example "180+2".
    if "+" not in value:
        return None
    left, right = value.split("+", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None


def speed_rank(headers: chess.pgn.Headers) -> int | None:
    tc = headers.get("TimeControl", "")
    parsed = parse_time_control_seconds(tc)
    if parsed is None:
        return None

    base_seconds, increment_seconds = parsed
    estimated_seconds = base_seconds + (40 * increment_seconds)

    # Lichess-style speed buckets based on estimated game duration.
    # bullet: <3m, blitz: 3m-<8m, rapid: 8m-<25m, classical: >=25m
    if estimated_seconds < 180:
        return 0
    if estimated_seconds < 480:
        return 1
    if estimated_seconds < 1500:
        return 2
    return 3


def matches_filters(game: chess.pgn.Game, args: argparse.Namespace) -> bool:
    headers = game.headers

    if args.variant and headers.get("Variant") != args.variant:
        return False

    if args.result and headers.get("Result") != args.result:
        return False

    if args.time_control_prefix:
        tc = headers.get("TimeControl", "")
        if not tc.startswith(args.time_control_prefix):
            return False

    if args.min_speed:
        rank = speed_rank(headers)
        if rank is None:
            return False
        required_rank = {"bullet": 0, "blitz": 1, "rapid": 2, "classical": 3}[args.min_speed]
        if rank < required_rank:
            return False

    if args.opening_contains:
        opening = headers.get("Opening", "")
        if args.opening_contains.lower() not in opening.lower():
            return False

    if args.min_elo is not None or args.max_elo is not None:
        white_elo = parse_elo(headers, "WhiteElo")
        black_elo = parse_elo(headers, "BlackElo")
        if white_elo is None or black_elo is None:
            return False
        min_player_elo = min(white_elo, black_elo)
        max_player_elo = max(white_elo, black_elo)

        if args.min_elo is not None and min_player_elo < args.min_elo:
            return False
        if args.max_elo is not None and max_player_elo > args.max_elo:
            return False

    return True


def default_output_name(input_path: Path) -> str:
    if input_path.name.endswith(".pgn.zst"):
        base = input_path.name[:-8]
    else:
        base = input_path.stem
    return f"{base}.filtered.pgn"


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        return 1

    output_dir = Path(args.out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_name = args.output_name or default_output_name(input_path)
    output_path = output_dir / out_name

    games_seen = 0
    games_written = 0

    in_stream, zstd_proc = open_input_text_stream(input_path)

    try:
        with output_path.open("w", encoding="utf-8") as out_f:
            while True:
                game = chess.pgn.read_game(in_stream)
                if game is None:
                    break

                games_seen += 1

                if not matches_filters(game, args):
                    continue

                print(game, file=out_f, end="\n\n")
                games_written += 1

                if args.max_games is not None and games_written >= args.max_games:
                    break

                if games_seen % 10000 == 0:
                    print(f"progress: seen={games_seen} written={games_written}")
    finally:
        in_stream.close()
        if zstd_proc is not None:
            zstd_proc.wait()

    print(f"done: seen={games_seen} written={games_written}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
