from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import chess


@dataclass
class AnalysisResult:
    score_cp: int | None
    score_mate: int | None
    depth: int | None
    pv: list[chess.Move]
    best_move: chess.Move | None


class ChessEngine(Protocol):
    def analyse(
        self,
        board: chess.Board,
        *,
        time_limit: float | None = 0.1,
        depth: int | None = None,
    ) -> AnalysisResult: ...

    def best_move(
        self,
        board: chess.Board,
        *,
        time_limit: float = 0.1,
        depth: int | None = None,
    ) -> chess.Move: ...

    def close(self) -> None: ...


class EngineContextMixin:
    def __enter__(self) -> EngineContextMixin:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
