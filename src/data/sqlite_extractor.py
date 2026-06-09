from __future__ import annotations

import io
import logging
import sqlite3
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterator, Sequence

import chess.pgn

from .game import Game

logger = logging.getLogger(__name__)


class GameExtractionError(Exception):
    """Base exception for SQLite extraction failures."""


class GameValidationError(GameExtractionError):
    """Row validation error while coercing DB values to typed fields."""


class GameParseError(GameExtractionError):
    """PGN parse error while constructing a Game from row data."""


def _parse_required_string(field: str, value: str | None, row_id: int, game_id: str | None) -> str:
    if value is None or value.strip() == "":
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: required string field '{field}' is empty"
        )
    return value


def _parse_required_int(field: str, value: str | None, row_id: int, game_id: str | None) -> int:
    if value is None or value == "":
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: required int field '{field}' is empty"
        )
    try:
        return int(value)
    except ValueError as exc:
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: invalid int for '{field}': {value!r}"
        ) from exc


def _parse_required_date(field: str, value: str | None, row_id: int, game_id: str | None) -> date:
    if value is None or value == "":
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: required date field '{field}' is empty"
        )
    try:
        return datetime.strptime(value, "%Y.%m.%d").date()
    except ValueError as exc:
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: invalid date for '{field}': {value!r}"
        ) from exc


def _parse_required_time(field: str, value: str | None, row_id: int, game_id: str | None) -> time:
    if value is None or value == "":
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: required time field '{field}' is empty"
        )
    try:
        return datetime.strptime(value, "%H:%M:%S").time()
    except ValueError as exc:
        raise GameValidationError(
            f"row_id={row_id} game_id={game_id}: invalid time for '{field}': {value!r}"
        ) from exc


def _parse_pgn(movetext: str, row_id: int, game_id: str | None) -> chess.pgn.Game:
    pgn_text = movetext.strip()
    if not pgn_text:
        raise GameParseError(f"row_id={row_id} game_id={game_id}: movetext is empty")

    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if game is None:
        raise GameParseError(f"row_id={row_id} game_id={game_id}: unable to parse movetext as PGN")

    return game


def _row_to_game(row: sqlite3.Row) -> Game:
    row_id = int(row["row_id"])
    game_id = _parse_required_string("game_id", row["game_id"], row_id, None)

    movetext = _parse_required_string("movetext", row["movetext"], row_id, game_id)
    parsed_pgn = _parse_pgn(movetext, row_id, game_id)

    return Game(
        row_id=row_id,
        game_id=game_id,
        source_file=row["source_file"],
        byte_offset_start=int(row["byte_offset_start"]),
        byte_offset_end=int(row["byte_offset_end"]),
        event=_parse_required_string("event", row["event"], row_id, game_id),
        site=_parse_required_string("site", row["site"], row_id, game_id),
        round=_parse_required_string("round", row["round"], row_id, game_id),
        white=_parse_required_string("white", row["white"], row_id, game_id),
        black=_parse_required_string("black", row["black"], row_id, game_id),
        result=_parse_required_string("result", row["result"], row_id, game_id),
        eco=row["eco"],
        opening=_parse_required_string("opening", row["opening"], row_id, game_id),
        time_control=_parse_required_string("time_control", row["time_control"], row_id, game_id),
        termination=_parse_required_string("termination", row["termination"], row_id, game_id),
        variant=row["variant"],
        movetext=movetext,
        parsed_pgn=parsed_pgn,
        game_date=_parse_required_date("date", row["date"], row_id, game_id),
        utc_date=_parse_required_date("utc_date", row["utc_date"], row_id, game_id),
        utc_time=_parse_required_time("utc_time", row["utc_time"], row_id, game_id),
        white_elo=_parse_required_int("white_elo", row["white_elo"], row_id, game_id),
        black_elo=_parse_required_int("black_elo", row["black_elo"], row_id, game_id),
    )


def _append_row_id_filters(
    conditions: list[str],
    params: list[object],
    min_row_id: int | None,
    max_row_id: int | None,
) -> None:
    if min_row_id is not None:
        conditions.append("row_id >= ?")
        params.append(min_row_id)
    if max_row_id is not None:
        conditions.append("row_id <= ?")
        params.append(max_row_id)


def row_id_bounds(
    db_path: str | Path,
    *,
    where: str | None = None,
    params: Sequence[object] = (),
    min_row_id: int | None = None,
    max_row_id: int | None = None,
) -> tuple[int, int] | None:
    if min_row_id is not None and max_row_id is not None and min_row_id > max_row_id:
        return None

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"DB file not found: {path}")

    query = "SELECT MIN(row_id), MAX(row_id) FROM games"
    conditions: list[str] = []
    bound_params_list = list(params)
    if where:
        conditions.append(f"({where})")
    _append_row_id_filters(conditions, bound_params_list, min_row_id, max_row_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    bound_params = tuple(bound_params_list)

    with sqlite3.connect(path) as conn:
        try:
            min_row_id, max_row_id = conn.execute(query, bound_params).fetchone()
        except sqlite3.Error as exc:
            raise GameExtractionError(f"sqlite query failed: {exc}") from exc

    if min_row_id is None or max_row_id is None:
        return None
    return int(min_row_id), int(max_row_id)


def iter_games(
    db_path: str | Path,
    *,
    limit: int | None = None,
    where: str | None = None,
    params: Sequence[object] = (),
    min_row_id: int | None = None,
    max_row_id: int | None = None,
    skip_errors: bool = False,
) -> Iterator[Game]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be >= 1")
    if min_row_id is not None and max_row_id is not None and min_row_id > max_row_id:
        return

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"DB file not found: {path}")

    query = "SELECT * FROM games"
    conditions: list[str] = []
    bound_params_list = list(params)
    if where:
        conditions.append(f"({where})")
    _append_row_id_filters(conditions, bound_params_list, min_row_id, max_row_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY row_id"
    if limit is not None:
        query += " LIMIT ?"
        bound_params_list.append(limit)
    bound_params = tuple(bound_params_list)

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(query, bound_params)
        except sqlite3.Error as exc:
            raise GameExtractionError(f"sqlite query failed: {exc}") from exc

        for row in cursor:
            try:
                yield _row_to_game(row)
            except GameExtractionError:
                if not skip_errors:
                    raise
                logger.warning("skipping malformed game row", exc_info=True)
