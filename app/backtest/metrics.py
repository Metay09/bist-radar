from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    cagr: float
    win_rate: float
    loss_rate: float
    average_win: float
    average_loss: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    number_of_trades: int
    average_trade_duration: float
    max_consecutive_losses: int
    max_consecutive_wins: int


def _max_streak(values: list[float], winning: bool) -> int:
    best = current = 0
    for value in values:
        current = current + 1 if (value > 0) == winning else 0
        best = max(best, current)
    return best


def calculate_metrics(
    returns: list[float], durations: list[float] | None = None, years: float = 1
) -> BacktestMetrics:
    if not returns:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    arr = np.asarray(returns)
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    equity = np.cumprod(1 + arr)
    peaks = np.maximum.accumulate(equity)
    downside = arr[arr < 0].std() if np.any(arr < 0) else 0
    total = float(equity[-1] - 1)
    std = arr.std()
    return BacktestMetrics(
        total,
        float((1 + total) ** (1 / years) - 1) if total > -1 else -1,
        len(wins) / len(arr),
        len(losses) / len(arr),
        float(wins.mean()) if len(wins) else 0,
        float(losses.mean()) if len(losses) else 0,
        float(arr.mean()),
        float(wins.sum() / abs(losses.sum())) if losses.sum() else float("inf"),
        float(np.min(equity / peaks - 1)),
        float(arr.mean() / std * np.sqrt(252)) if std else 0,
        float(arr.mean() / downside * np.sqrt(252)) if downside else 0,
        len(arr),
        float(np.mean(durations or [0])),
        _max_streak(returns, False),
        _max_streak(returns, True),
    )


class NextBarExecution:
    """Signals computed at close t execute at open t+1, preventing same-bar leakage."""

    @staticmethod
    def entry_open(frame: pd.DataFrame, signal_index: int) -> float:
        if signal_index + 1 >= len(frame):
            raise IndexError("no next bar")
        return float(frame.iloc[signal_index + 1].open)
