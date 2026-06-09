from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable, Iterator

import chess
from torch.utils.data import IterableDataset

from .game import Game


class MoveSelectionMode(StrEnum):
    COMPLETE = "complete"
    RANDOM = "random"


@dataclass(frozen=True)
class ChessSample:
    game: Game
    ply_index: int
    board: chess.Board
    move: chess.Move


def _stable_random(game_id: str, seed: int) -> random.Random:
    seed_bytes = f"{seed}:{game_id}".encode("utf-8")
    seed_int = int.from_bytes(hashlib.sha256(seed_bytes).digest(), byteorder="big")
    return random.Random(seed_int)


def _selected_ply_indexes(
    total_plies: int,
    *,
    game_id: str,
    move_selection: MoveSelectionMode,
    random_moves_per_game: int | None,
    random_seed: int,
) -> set[int]:
    if total_plies == 0:
        return set()

    if move_selection == MoveSelectionMode.COMPLETE:
        return set(range(total_plies))

    assert random_moves_per_game is not None
    sample_size = min(random_moves_per_game, total_plies)
    rng = _stable_random(game_id, random_seed)
    return set(rng.sample(range(total_plies), k=sample_size))


class ChessSampleDataset(IterableDataset[ChessSample]):
    def __init__(
        self,
        games: Iterable[Game],
        *,
        move_selection: MoveSelectionMode | str = MoveSelectionMode.COMPLETE,
        random_moves_per_game: int | None = None,
        random_seed: int = 0,
    ) -> None:
        selection_mode = MoveSelectionMode(move_selection)
        if selection_mode == MoveSelectionMode.COMPLETE and random_moves_per_game is not None:
            raise ValueError("random_moves_per_game is only valid for random move selection")
        if selection_mode == MoveSelectionMode.RANDOM:
            if random_moves_per_game is None:
                raise ValueError("random_moves_per_game is required for random move selection")
            if random_moves_per_game < 1:
                raise ValueError("random_moves_per_game must be >= 1")

        self.games = games
        self.move_selection = selection_mode
        self.random_moves_per_game = random_moves_per_game
        self.random_seed = random_seed

    def __iter__(self) -> Iterator[ChessSample]:
        for game in self.games:
            moves = list(game.parsed_pgn.mainline_moves())
            selected_indexes = _selected_ply_indexes(
                len(moves),
                game_id=game.game_id,
                move_selection=self.move_selection,
                random_moves_per_game=self.random_moves_per_game,
                random_seed=self.random_seed,
            )

            board = game.parsed_pgn.board()
            for ply_index, move in enumerate(moves):
                if ply_index in selected_indexes:
                    yield ChessSample(
                        game=game,
                        ply_index=ply_index,
                        board=board.copy(stack=False),
                        move=move,
                    )
                board.push(move)
