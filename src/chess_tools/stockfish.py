from __future__ import annotations

import os
import shutil
from typing import Any

from .stockfish_binary import ensure_stockfish, stockfish_binary_path
from .uci import UciEngine


def find_stockfish(*, download: bool = True) -> str:
    if path := os.environ.get("STOCKFISH_PATH"):
        return path

    local_path = stockfish_binary_path()
    if local_path.is_file() and os.access(local_path, os.X_OK):
        return str(local_path)

    if download:
        try:
            return str(ensure_stockfish())
        except RuntimeError:
            if found := shutil.which("stockfish"):
                return found
            raise

    if found := shutil.which("stockfish"):
        return found

    raise FileNotFoundError(
        "Stockfish not found. Run with download=True (default), set STOCKFISH_PATH, "
        "or install stockfish on PATH."
    )


class StockfishEngine(UciEngine):
    def __init__(
        self,
        path: str | None = None,
        *,
        options: dict[str, Any] | None = None,
        download: bool = True,
    ) -> None:
        super().__init__(path or find_stockfish(download=download), options=options)
