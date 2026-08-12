import pandas as pd
import pytest

from app.backtest.metrics import NextBarExecution, calculate_metrics


def test_execution_uses_only_next_bar_open_not_signal_bar_ohlc() -> None:
    frame = pd.DataFrame(
        [
            {"open": 10, "high": 9999, "low": 0.01, "close": 8888},
            {"open": 11, "high": 12, "low": 10, "close": 11.5},
        ]
    )
    assert NextBarExecution.entry_open(frame, 0) == 11
    frame.loc[0, ["high", "low", "close"]] = [-999, 999999, -123]
    assert NextBarExecution.entry_open(frame, 0) == 11


def test_execution_requires_a_future_bar() -> None:
    with pytest.raises(IndexError):
        NextBarExecution.entry_open(pd.DataFrame([{"open": 1}]), 0)


def test_backtest_metric_boundaries() -> None:
    empty = calculate_metrics([])
    assert empty.number_of_trades == 0
    result = calculate_metrics([0.1, -0.05, 0.02], [1, 2, 3])
    assert result.number_of_trades == 3
    assert 0 <= result.win_rate <= 1 and result.max_drawdown <= 0
