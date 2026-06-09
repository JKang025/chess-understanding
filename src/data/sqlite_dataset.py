from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

from torch.utils.data import IterableDataset, get_worker_info

from .game import Game
from .sqlite_extractor import iter_games, row_id_bounds


@dataclass(frozen=True)
class _RowRange:
    min_row_id: int
    max_row_id: int


def _split_limit(limit: int | None, worker_id: int, num_workers: int) -> int | None:
    if limit is None:
        return None

    base_limit = limit // num_workers
    extra = 1 if worker_id < limit % num_workers else 0
    return base_limit + extra


def _split_row_range(
    min_row_id: int,
    max_row_id: int,
    worker_id: int,
    num_workers: int,
) -> _RowRange | None:
    row_count = max_row_id - min_row_id + 1
    base_rows = row_count // num_workers
    extra = 1 if worker_id < row_count % num_workers else 0
    worker_rows = base_rows + extra
    if worker_rows == 0:
        return None

    start_offset = worker_id * base_rows + min(worker_id, row_count % num_workers)
    worker_min_row_id = min_row_id + start_offset
    worker_max_row_id = worker_min_row_id + worker_rows - 1
    return _RowRange(worker_min_row_id, worker_max_row_id)


class SQLiteGameDataset(IterableDataset[Game]):
    def __init__(
        self,
        db_path: str | Path,
        *,
        where: str | None = None,
        params: Sequence[object] = (),
        limit: int | None = None,
        min_row_id: int | None = None,
        max_row_id: int | None = None,
        skip_errors: bool = True,
    ) -> None:
        if limit is not None and limit < 1:
            raise ValueError("limit must be >= 1")
        if min_row_id is not None and max_row_id is not None and min_row_id > max_row_id:
            raise ValueError("min_row_id must be <= max_row_id")

        self.db_path = Path(db_path)
        self.where = where
        self.params = tuple(params)
        self.limit = limit
        self.min_row_id = min_row_id
        self.max_row_id = max_row_id
        self.skip_errors = skip_errors

    def __iter__(self) -> Iterator[Game]:
        worker = get_worker_info()
        if worker is None:
            yield from iter_games(
                self.db_path,
                where=self.where,
                params=self.params,
                limit=self.limit,
                min_row_id=self.min_row_id,
                max_row_id=self.max_row_id,
                skip_errors=self.skip_errors,
            )
            return

        local_limit = _split_limit(self.limit, worker.id, worker.num_workers)
        if local_limit == 0:
            return

        bounds = row_id_bounds(
            self.db_path,
            where=self.where,
            params=self.params,
            min_row_id=self.min_row_id,
            max_row_id=self.max_row_id,
        )
        if bounds is None:
            return

        worker_range = _split_row_range(*bounds, worker.id, worker.num_workers)
        if worker_range is None:
            return

        yield from iter_games(
            self.db_path,
            where=self.where,
            params=self.params,
            limit=local_limit,
            min_row_id=worker_range.min_row_id,
            max_row_id=worker_range.max_row_id,
            skip_errors=self.skip_errors,
        )
