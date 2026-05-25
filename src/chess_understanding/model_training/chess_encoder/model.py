import torch
from torch import nn


class ChessEncoder(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(12 * 8 * 8, 1),
        )

    def forward(self, board_planes: torch.Tensor) -> torch.Tensor:
        return self.net(board_planes).squeeze(-1)
