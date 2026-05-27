from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

import chess.pgn


@dataclass(frozen=True)
class Game:
    row_id: int
    game_id: str
    source_file: str
    byte_offset_start: int
    byte_offset_end: int
    event: str
    site: str
    round: str
    white: str
    black: str
    result: str
    eco: str | None
    opening: str
    time_control: str
    termination: str
    variant: str | None
    movetext: str
    parsed_pgn: chess.pgn.Game
    game_date: date
    utc_date: date
    utc_time: time
    white_elo: int
    black_elo: int
