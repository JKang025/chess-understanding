from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from torch.utils.data import DataLoader

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from data import GameValidationError, SQLiteGameDataset, iter_games, row_id_bounds


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


def _insert_game(
    conn: sqlite3.Connection,
    *,
    game_id: str | None = "abc12345",
    white_elo: str = "2100",
    event: str = "Rated Blitz game",
    time_control: str = "180+0",
) -> None:
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
            event,
            "https://lichess.org/abc12345",
            "2026.04.01",
            "-",
            "Alice",
            "Bob",
            "1-0",
            "2026.04.01",
            "00:00:20",
            white_elo,
            "2050",
            "+5",
            "-6",
            "C00",
            "French Defense",
            time_control,
            "Normal",
            "Standard",
            "1. e4 e6 2. d4 d5 3. Nc3 Nf6 1-0",
        ),
    )


class TestSQLiteExtractor(unittest.TestCase):
    def test_happy_path_and_api_behaviors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn)
                _insert_game(conn)
                conn.commit()

            games_iter = list(iter_games(db_path, limit=1))
            self.assertEqual(len(games_iter), 1)
            game = games_iter[0]

            self.assertEqual(game.white_elo, 2100)
            self.assertEqual(game.black_elo, 2050)
            self.assertEqual(game.game_date.isoformat(), "2026-04-01")
            self.assertEqual(game.utc_time.isoformat(), "00:00:20")
            self.assertTrue(game.movetext.startswith("1. e4"))
            self.assertGreater(len(list(game.parsed_pgn.mainline_moves())), 0)

            games_list = list(iter_games(db_path, limit=2))
            self.assertEqual(len(games_list), 2)
            self.assertEqual(games_list[0].row_id, 1)
            self.assertEqual(games_list[1].row_id, 2)

    def test_row_id_bounds_respect_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, game_id="game-1", time_control="180+0")
                _insert_game(conn, game_id="game-2", time_control="300+0")
                _insert_game(conn, game_id="game-3", time_control="300+0")
                conn.commit()

            bounds = row_id_bounds(db_path, where="time_control = ?", params=("300+0",))
            self.assertEqual(bounds, (2, 3))
            bounded = row_id_bounds(
                db_path,
                where="time_control = ?",
                params=("300+0",),
                min_row_id=3,
                max_row_id=3,
            )
            self.assertEqual(bounded, (3, 3))
            self.assertIsNone(row_id_bounds(db_path, where="time_control = ?", params=("60+0",)))

    def test_strict_parse_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, white_elo="not-a-number")
                conn.commit()

            with self.assertRaises(GameValidationError) as ctx:
                list(iter_games(db_path))
            self.assertIn("row_id=1", str(ctx.exception))
            self.assertIn("white_elo", str(ctx.exception))

    def test_game_id_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, game_id="")
                conn.commit()

            with self.assertRaises(GameValidationError) as ctx:
                list(iter_games(db_path))
            self.assertIn("row_id=1", str(ctx.exception))
            self.assertIn("game_id", str(ctx.exception))

    def test_required_core_string_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, event="")
                conn.commit()

            with self.assertRaises(GameValidationError) as ctx:
                list(iter_games(db_path))
            self.assertIn("row_id=1", str(ctx.exception))
            self.assertIn("event", str(ctx.exception))

    def test_skip_errors_logs_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, white_elo="not-a-number")
                _insert_game(conn, game_id="valid-game")
                conn.commit()

            with self.assertLogs("data.sqlite_extractor", level="WARNING") as logs:
                games = list(iter_games(db_path, skip_errors=True))

            self.assertEqual([game.game_id for game in games], ["valid-game"])
            self.assertIn("skipping malformed game row", "\n".join(logs.output))


class TestSQLiteGameDataset(unittest.TestCase):
    def test_dataset_yields_games_with_filter_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, game_id="blitz-1", time_control="180+0")
                _insert_game(conn, game_id="rapid-1", time_control="600+0")
                _insert_game(conn, game_id="blitz-2", time_control="180+0")
                conn.commit()

            dataset = SQLiteGameDataset(
                db_path,
                where="time_control = ?",
                params=("180+0",),
                limit=1,
            )
            games = list(dataset)

            self.assertEqual(len(games), 1)
            self.assertEqual(games[0].game_id, "blitz-1")

    def test_dataset_applies_row_bounds_before_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                _insert_game(conn, game_id="game-1", time_control="180+0")
                _insert_game(conn, game_id="game-2", time_control="600+0")
                _insert_game(conn, game_id="game-3", time_control="180+0")
                _insert_game(conn, game_id="game-4", time_control="180+0")
                conn.commit()

            dataset = SQLiteGameDataset(
                db_path,
                where="time_control = ?",
                params=("180+0",),
                min_row_id=3,
                max_row_id=4,
                limit=1,
            )
            games = list(dataset)

            self.assertEqual([game.game_id for game in games], ["game-3"])

    def test_dataloader_workers_do_not_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                for idx in range(8):
                    _insert_game(conn, game_id=f"game-{idx}")
                conn.commit()

            dataset = SQLiteGameDataset(db_path, limit=8)
            loader = DataLoader(dataset, batch_size=None, num_workers=2)
            row_ids = [game.row_id for game in loader]

            self.assertEqual(len(row_ids), 8)
            self.assertEqual(sorted(row_ids), list(range(1, 9)))
            self.assertEqual(len(set(row_ids)), 8)

    def test_dataloader_workers_respect_row_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "games.db"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA)
                for idx in range(10):
                    _insert_game(conn, game_id=f"game-{idx}")
                conn.commit()

            dataset = SQLiteGameDataset(db_path, min_row_id=3, max_row_id=8)
            loader = DataLoader(dataset, batch_size=None, num_workers=2)
            row_ids = [game.row_id for game in loader]

            self.assertEqual(sorted(row_ids), list(range(3, 9)))
            self.assertEqual(len(set(row_ids)), 6)

    def test_real_db_smoke_if_present(self) -> None:
        real_db = ROOT / "data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db"
        if not real_db.exists():
            self.skipTest("real DB not available")

        games = list(iter_games(real_db, limit=2))
        self.assertEqual(len(games), 2)
        self.assertIsNotNone(games[0].parsed_pgn)
        self.assertGreater(len(list(games[0].parsed_pgn.mainline_moves())), 0)


if __name__ == "__main__":
    unittest.main()
