import chess

from chess_understanding.chess.stockfish import StockfishEngine, find_stockfish


def main() -> None:
    board = chess.Board()
    print(f"Using engine: {find_stockfish()}")
    print(f"Position:\n{board}\n")

    with StockfishEngine() as engine:
        analysis = engine.analyse(board, depth=12)
        move = engine.best_move(board, time_limit=0.1)

    print(f"Best move: {move.uci()}")
    print(f"Depth: {analysis.depth}")
    print(f"Score (cp): {analysis.score_cp}")
    print(f"Score (mate): {analysis.score_mate}")
    print(f"PV: {' '.join(m.uci() for m in analysis.pv[:5])}")


if __name__ == "__main__":
    main()
