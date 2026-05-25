from __future__ import annotations

from typing import Any

import chess
import chess.engine

from .engine import AnalysisResult, EngineContextMixin


class UciEngine(EngineContextMixin):
    """Generic UCI chess engine wrapper."""

    def __init__(
        self,
        path: str,
        *,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.path = path
        self._engine = chess.engine.SimpleEngine.popen_uci(path)
        if options:
            self._engine.configure(options)

    def close(self) -> None:
        self._engine.quit()

    def analyse(
        self,
        board: chess.Board,
        *,
        time_limit: float | None = 0.1,
        depth: int | None = None,
    ) -> AnalysisResult:
        limit = _build_limit(time_limit=time_limit, depth=depth)
        info = self._engine.analyse(board, limit)
        score = info["score"].relative
        pv = info.get("pv") or []

        return AnalysisResult(
            score_cp=score.score(mate_score=100_000),
            score_mate=score.mate(),
            depth=info.get("depth"),
            pv=list(pv),
            best_move=pv[0] if pv else None,
        )

    def best_move(
        self,
        board: chess.Board,
        *,
        time_limit: float = 0.1,
        depth: int | None = None,
    ) -> chess.Move:
        limit = _build_limit(time_limit=time_limit, depth=depth)
        result = self._engine.play(board, limit)
        if result.move is None:
            raise chess.engine.EngineError("Engine returned no move.")
        return result.move


def _build_limit(
    *,
    time_limit: float | None,
    depth: int | None,
) -> chess.engine.Limit:
    if time_limit is None and depth is None:
        raise ValueError("Provide time_limit, depth, or both.")
    return chess.engine.Limit(
        time=time_limit,
        depth=depth,
    )
