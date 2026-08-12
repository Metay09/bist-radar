from datetime import datetime
from decimal import Decimal

import pandas as pd
import pytest

from app.backtest.replay import (
    HistoricalReplayEngine,
    daily_analytics,
    possible_corporate_action,
    replay_performance,
    stable_config_hash,
)
from app.backtest.replay_models import ExecutionOrder, ExecutionState, Timeframe
from app.data.historical import HistoricalProvider, SymbolMetadata
from app.paper.execution import ExecutionConfig


class MemoryProvider(HistoricalProvider):
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        return self.frame.copy()


def bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    times = pd.date_range("2025-01-01", periods=len(rows), freq="D", tz="UTC")
    return pd.DataFrame(
        [
            {
                "symbol": "TEST",
                "timestamp": t,
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 1000,
            }
            for t, (o, h, low, c) in zip(times, rows, strict=True)
        ]
    )


def once_strategy(seen_lengths: list[int]):
    def strategy(symbol: str, visible: pd.DataFrame) -> ExecutionOrder | None:
        seen_lengths.append(len(visible))
        if len(visible) != 1:
            return None
        t = visible.iloc[-1].timestamp.to_pydatetime()
        return ExecutionOrder(
            "sig-1",
            "radar-v1:TEST:" + t.isoformat(),
            "paper-default",
            "radar-v1",
            symbol,
            t,
            Decimal("10"),
            Decimal("9"),
            Decimal("11"),
            Decimal("12"),
            90,
            100,
        )

    return strategy


def run(rows: list[tuple[float, float, float, float]], config: ExecutionConfig | None = None):
    seen: list[int] = []
    engine = HistoricalReplayEngine(
        MemoryProvider(bars(rows)),
        {"TEST": SymbolMetadata("TEST")},
        once_strategy(seen),
        config or ExecutionConfig(),
    )
    return engine.run(["TEST"], Timeframe.D1, None, None, Decimal("10000")), seen


def test_sequential_future_inaccessible_next_open_and_target() -> None:
    result, seen = run([(10, 10.5, 9.5, 10), (10, 10.8, 9.8, 10.5), (10.5, 12.5, 10, 12)])
    assert seen == [1, 2, 3]
    trade = result.trades[0]
    assert trade.entry_time == bars([(1, 1, 1, 1), (1, 1, 1, 1)]).timestamp.iloc[1].to_pydatetime()
    assert trade.exit_reason == "TARGET_2" and trade.state == ExecutionState.CLOSED
    assert result.final_equity == trade.equity_after


def test_entry_gap_rejection() -> None:
    result, _ = run(
        [(10, 10, 10, 10), (20, 20, 20, 20)],
        ExecutionConfig(reject_corporate_actions=False),
    )
    assert not result.trades and result.audits[-1]["result"] == "REJECTED_ENTRY_GAP"


@pytest.mark.parametrize(
    "row,reason,expected",
    [
        ((10, 11.5, 8.5, 10), "STOP_FIRST_AMBIGUITY", Decimal("9")),
        ((8, 9, 7, 8), "STOP_GAP", Decimal("8")),
        ((13, 13, 12, 13), "TARGET_2_GAP", Decimal("13")),
        ((10, 10, 8.5, 9), "STOP", Decimal("9")),
        ((10, 11.5, 9.5, 11), "TARGET_1", Decimal("11")),
    ],
)
def test_exit_policies(
    row: tuple[float, float, float, float], reason: str, expected: Decimal
) -> None:
    result, _ = run(
        [(10, 10, 10, 10), (10, 10.2, 9.8, 10), row], ExecutionConfig(slippage_bps=Decimal("0"))
    )
    trade = result.trades[0]
    assert trade.exit_reason == reason and trade.exit_price == expected


def test_portfolio_limits_and_idempotency() -> None:
    result, _ = run([(10, 10, 10, 10), (10, 10, 10, 10)], ExecutionConfig(max_open_positions=0))
    assert result.audits[-1]["result"] == "REJECTED_PORTFOLIO_RISK"
    result, _ = run(
        [(10, 10, 10, 10), (10, 10, 10, 10)],
        ExecutionConfig(max_total_open_risk_percent=Decimal("0")),
    )
    assert result.audits[-1]["result"] == "REJECTED_PORTFOLIO_RISK"


def test_corporate_action_and_unknown_symbol() -> None:
    assert possible_corporate_action(Decimal("10"), Decimal("20"))
    result, _ = run(
        [(10, 10, 10, 10), (20, 20, 20, 20)], ExecutionConfig(max_entry_gap_percent=Decimal("200"))
    )
    assert result.audits[-1]["result"] == "REJECTED_CORPORATE_ACTION"
    engine = HistoricalReplayEngine(MemoryProvider(bars([(1, 1, 1, 1)])), {}, lambda s, f: None)
    with pytest.raises(ValueError, match="unknown"):
        engine.run(["X"], Timeframe.D1, None, None, Decimal("1"))


def test_config_hash_stability_zero_trade_metrics_and_invariants() -> None:
    assert stable_config_hash(ExecutionConfig()) == stable_config_hash(ExecutionConfig())
    engine = HistoricalReplayEngine(
        MemoryProvider(bars([(1, 1, 1, 1)])), {"TEST": SymbolMetadata("TEST")}, lambda s, f: None
    )
    result = engine.run(["TEST"], Timeframe.D1, None, None, Decimal("100"))
    metrics = replay_performance(result)
    assert metrics["number_of_trades"] == 0 and metrics["final_equity"] == 100
    assert result.final_equity.is_finite()


def test_golden_replay_regression() -> None:
    result, _ = run([(10, 10.5, 9.5, 10), (10, 10.5, 9.5, 10), (10, 12.5, 8.5, 12)])
    trade = result.trades[0]
    metrics = replay_performance(result)
    assert len(result.trades) == 1
    assert trade.entry_price == Decimal("10.005")
    assert trade.exit_price == Decimal("8.9955")  # conservative stop-first
    assert trade.net_pnl == Decimal("-77.1375375")
    assert result.final_equity == Decimal("9922.8624625")
    assert metrics["max_drawdown"] < 0 and metrics["win_rate"] == 0
    assert daily_analytics(result, {"TEST": "Metal"})[0]["sector"] == "Metal"


def test_all_winning_and_all_losing_metrics() -> None:
    winning, _ = run([(10, 10, 10, 10), (10, 10, 10, 10), (10, 13, 10, 12)])
    losing, _ = run([(10, 10, 10, 10), (10, 10, 10, 10), (10, 10, 8, 9)])
    assert replay_performance(winning)["profit_factor"] == float("inf")
    assert replay_performance(winning)["win_rate"] == 1
    assert replay_performance(losing)["win_rate"] == 0
