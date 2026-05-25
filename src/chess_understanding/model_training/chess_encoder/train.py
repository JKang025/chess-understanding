import torch
from torch import nn

from chess_understanding.model_training.chess_encoder.model import ChessEncoder


def main() -> None:
    model = ChessEncoder()
    optimizer = torch.optim.Adam(model.parameters())

    for epoch in range(3):
        board_planes = torch.randn(8, 12, 8, 8)
        targets = torch.randn(8)

        loss = nn.functional.mse_loss(model(board_planes), targets)
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        print(f"epoch {epoch + 1} loss={loss.item():.4f}")


if __name__ == "__main__":
    main()
