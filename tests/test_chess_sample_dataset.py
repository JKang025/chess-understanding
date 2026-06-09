from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data import ChessSampleDataset, Game, MoveSelectionMode, SQLiteGameDataset


SCHEMA = """
CREATE TABLE games (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NULL,
    source_file TEXT NOT NULL,
    byte_offset_start INTEGER NOT NULL,
    byte_offset_end INTEGER NOT NULL,
    event TEXT,
    site TEXT,
    date TEXT,
    round TEXT,
    white TEXT,
    black TEXT,
    result TEXT,
    utc_date TEXT,
    utc_time TEXT,
    white_elo TEXT,
    black_elo TEXT,
    white_rating_diff TEXT,
    black_rating_diff TEXT,
    eco TEXT,
    opening TEXT,
    time_control TEXT,
    termination TEXT,
    variant TEXT,
    movetext TEXT
);
"""


def _game(game_id: str = "game-1", movetext: str | None = None) -> Game:
    if movetext is None:
        movetext = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"
    parsed_pgn = chess.pgn.read_game(io.StringIO(movetext))
    if parsed_pgn is None:
        raise AssertionError("test PGN did not parse")

    return Game(
        row_id=1,
        game_id=game_id,
        source_file="source.pgn",
        byte_offset_start=0,
        byte_offset_end=100,
        event="Rated Blitz game",
        site="https://lichess.org/game-1",
        round="-",
        white="Alice",
        black="Bob",
        result="1-0",
        eco="C60",
        opening="Ruy Lopez",
        time_control="180+0",
        termination="Normal",
        variant="Standard",
        movetext=movetext,
        parsed_pgn=parsed_pgn,
        game_date=date(2026, 4, 1),
        utc_date=date(2026, 4, 1),
        utc_time=time(0, 0, 20),
        white_elo=2100,
        black_elo=2050,
    )


def _insert_game(conn: sqlite3.Connection, *, game_id: str = "game-1") -> None:
    conn.execute(
        """
        INSERT INTO games (
            game_id, source_file, byte_offset_start, byte_offset_end, event, site, date,
            round, white, black, result, utc_date, utc_time, white_elo, black_elo,
            white_rating_diff, black_rating_diff, eco, opening, time_control,
            termination, variant, movetext
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            "source.pgn",
            0,
            100,
            "Rated Blitz game",
            f"https://lichess.org/{game_id}",
            "2026.04.01",
            "-",
            "Alice",
            "Bob",
            "1-0",
            "2026.04.01",
            "00:00:20",
            "2100",
            "2050",
            "+5",
            "-6",
            "C60",
            "Ruy Lopez",
            "180+0",
            "Normal",
            "Standard",
            "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0",
        ),
    )


class TestChessSampleDataset(unittest.TestCase):
    def test_complete_selection_emits_every_ply(self) -> None:
        samples = list(ChessSampleDataset([_game()], move_selection=MoveSelectionMode.COMPLETE))

        self.assertEqual([sample.ply_index for sample in samples], [0, 1, 2, 3, 4, 5])
        self.assertEqual(
            [sample.move.uci() for sample in samples],
            ["e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"],
        )
        self.assertEqual(samples[0].board.fen(), chess.Board().fen())

        board_after_first_move = chess.Board()
        board_after_first_move.push_uci("e2e4")
        self.assertEqual(samples[1].board.fen(), board_after_first_move.fen())

    def test_random_selection_is_deterministic_per_game(self) -> None:
        dataset_a = ChessSampleDataset(
            [_game()],
            move_selection="random",
            random_moves_per_game=2,
            random_seed=123,
        )
        dataset_b = ChessSampleDataset(
            [_game()],
            move_selection="random",
            random_moves_per_game=2,
            random_seed=123,
        )

        indexes_a = [sample.ply_index for sample in dataset_a]
        indexes_b = [sample.ply_index for sample in dataset_b]

        self.assertEqual(indexes_a, indexes_b)
        self.assertEqual(len(indexes_a), 2)
        self.assertEqual(indexes_a, sorted(indexes_a))

    def test_random_selection_caps_at_game_length(self) -> None:
        samples = list(
            ChessSampleDataset(
                [_game()],
                move_selection=MoveSelectionMode.RANDOM,
                random_moves_per_game=100,
                random_seed=123,
            )
        )

        self.assertEqual(len(samples), 6)

    def test_empty_game_emits_no_samples(self) -> None:
        samples = list(ChessSampleDataset([_game(movetext="1-0")]))

        self.assertEqual(samples, [])

    def test_random_selection_requires_sample_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "random_moves_per_game is required"):
            ChessSampleDataset([_game()], move_selection=MoveSelectionMode.RANDOM)

    def test_random_selection_requires_positive_sample_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "random_moves_per_game must be >= 1"):
            ChessSampleDataset(
                [_game()],
                move_selection=MoveSelectionMode.RANDOM,
                random_moves_per_game=0,
            )

    def test_complete_selection_rejects_random_sample_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "only valid for random"):
            ChessSampleDataset([_game()], random_moves_per_game=2)

    def test_composes_with_sqlite_game_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, game_id="sqlite-game")
                conn.commit()

            games = SQLiteGameDataset(db_path)
            samples = list(ChessSampleDataset(games, move_selection=MoveSelectionMode.COMPLETE))

            self.assertEqual(len(samples), 6)
            self.assertEqual(samples[0].game.game_id, "sqlite-game")
            self.assertEqual(samples[0].ply_index, 0)
            self.assertEqual(samples[0].move.uci(), "e2e4")


if __name__ == "__main__":
    unittest.main()
