import argparse
import sqlite3
from pathlib import Path

# Example usage:
# uv run python scripts/show_sqlite_head.py
# uv run python scripts/show_sqlite_head.py --db /Users/jkang/repos/chess-understanding/data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db
# uv run python scripts/show_sqlite_head.py --rows 3

DEFAULT_DB = Path(
    "/Users/jkang/repos/chess-understanding/data/sqlite_db/lichess_standard_rated_2026-04_minelo2000_minspeedblitz.sqlite.db"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Print table schemas and a small row sample from a SQLite DB."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"Path to SQLite DB (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=5,
        help="Number of rows to show per table (default: 5)",
    )
    args = parser.parse_args()

    if args.rows < 1:
        parser.error("--rows must be >= 1")

    return args


def fetch_table_names(conn: sqlite3.Connection) -> list[str]:
    cursor = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    )
    return [row[0] for row in cursor.fetchall()]


def main() -> int:
    args = parse_args()

    if not args.db.exists():
        raise FileNotFoundError(f"DB file not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    try:
        table_names = fetch_table_names(conn)
        if not table_names:
            print("No user tables found.")
            return 0

        print(f"DB: {args.db}")
        print(f"Tables ({len(table_names)}): {', '.join(table_names)}")

        for table_name in table_names:
            print(f"\n=== {table_name} ===")

            columns = conn.execute(f"PRAGMA table_info('{table_name}')").fetchall()
            if not columns:
                print("(no columns)")
                continue

            print("Columns:")
            for col in columns:
                notnull = " NOT NULL" if col[3] else ""
                pk = " PRIMARY KEY" if col[5] else ""
                print(f"- {col[1]}: {col[2]}{notnull}{pk}")

            rows = conn.execute(
                f"SELECT * FROM \"{table_name}\" LIMIT ?", (args.rows,)
            ).fetchall()

            if not rows:
                print("Rows: (empty table)")
                continue

            print(f"Rows (up to {args.rows}):")
            for row in rows:
                print(dict(row))
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
