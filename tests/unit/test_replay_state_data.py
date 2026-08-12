from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.backtest.replay_models import ExecutionOrder, ExecutionState, Timeframe
from app.core.clock import ReplayClock
from app.data.historical import CsvHistoricalProvider, HistoricalDataError, validate_historical


def order() -> ExecutionOrder:
    now = datetime.now(UTC)
    return ExecutionOrder(
        "s",
        "k",
        "p",
        "st",
        "X",
        now,
        Decimal("10"),
        Decimal("9"),
        Decimal("11"),
        Decimal("12"),
        90,
        100,
    )


def test_invalid_state_transition() -> None:
    item = order()
    item.transition(ExecutionState.PENDING_ENTRY)
    item.transition(ExecutionState.OPEN)
    item.transition(ExecutionState.CLOSED)
    with pytest.raises(ValueError):
        item.transition(ExecutionState.OPEN)


def test_replay_clock_cannot_reverse() -> None:
    now = datetime.now(UTC)
    clock = ReplayClock(now)
    with pytest.raises(ValueError):
        clock.advance(now.replace(year=now.year - 1))


def base_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["X", "X"],
            "timestamp": ["2025-01-01", "2025-01-02"],
            "open": [1, 1],
            "high": [2, 2],
            "low": [0.5, 0.5],
            "close": [1, 1],
            "volume": [1, 1],
        }
    )


def test_malformed_unordered_duplicate_historical() -> None:
    with pytest.raises(HistoricalDataError, match="malformed"):
        validate_historical(pd.DataFrame(), "X")
    frame = base_frame().iloc[::-1]
    with pytest.raises(HistoricalDataError, match="unordered"):
        validate_historical(frame, "X")
    frame = base_frame()
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    with pytest.raises(HistoricalDataError, match="duplicate"):
        validate_historical(frame, "X")


def test_csv_unknown_symbol(tmp_path: Path) -> None:
    with pytest.raises(HistoricalDataError, match="unknown"):
        CsvHistoricalProvider(tmp_path).load("X", Timeframe.D1)
