from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.backtest.portfolio_accounting import (
    accounting_report,
    daily_risk_metrics,
    portfolio_equity_curve,
)
from app.backtest.replay_models import ExecutedTrade, ExecutionState, ReplayResult

D = Decimal
DAY = datetime(2024, 1, 2, tzinfo=UTC)


def trade(*, closed: bool = False) -> ExecutedTrade:
    item = ExecutedTrade(
        "signal",
        "trade",
        "key",
        "paper-default",
        "radar-v1-frozen",
        "AAA",
        DAY,
        DAY,
        D("100"),
        D("90"),
        D("120"),
        D("130"),
        D("10"),
        D("100000"),
        "NEXT_BAR_OPEN",
        initial_risk=D("100"),
    )
    if closed:
        item.state = ExecutionState.CLOSED
        item.exit_time = DAY + timedelta(days=2)
        item.exit_price = D("110")
        item.net_pnl = D("100")
        item.equity_after = D("100100")
    return item


def frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": [DAY + timedelta(days=i) for i in range(len(closes))],
            "close": closes,
        }
    )


def test_total_return_identity_and_open_position_mtm() -> None:
    result = ReplayResult("run", D("100000"), D("100100"), trades=[trade(closed=True), trade()])
    result.trades[1].trade_id = "open"
    result.trades[1].idempotency_key = "open"
    report = accounting_report(
        result,
        {"AAA": frame([100, 105, 110])},
        DAY,
        DAY + timedelta(days=2),
        DAY,
        D("0"),
        D("0"),
    )
    realized = report["realized_only"]
    mtm = report["mark_to_market"]
    assert realized["total_return"] == pytest.approx(100100 / 100000 - 1)  # type: ignore[index]
    assert mtm["unrealized_pnl"] == 100  # type: ignore[index]
    assert mtm["final_equity"] == 100200  # type: ignore[index]


def test_cagr_multi_year_periods_are_explicit() -> None:
    end = datetime(2026, 1, 1, tzinfo=UTC)
    result = ReplayResult("run", D("100000"), D("121000"))
    report = accounting_report(
        result,
        {},
        datetime(2024, 1, 1, tzinfo=UTC),
        end,
        datetime(2024, 1, 1, tzinfo=UTC),
        D("0"),
        D("0"),
    )
    dataset = report["periods"]["dataset"]  # type: ignore[index]
    assert dataset["start"] == "2024-01-01T00:00:00+00:00"
    assert dataset["end"] == "2026-01-01T00:00:00+00:00"
    assert dataset["cagr"] == pytest.approx(0.1, abs=0.0002)


def test_daily_equity_drawdown_and_exposure_semantics() -> None:
    result = ReplayResult("run", D("100000"), D("100000"), trades=[trade()])
    timeline = [DAY + timedelta(days=i) for i in range(3)]
    curve = portfolio_equity_curve(result, {"AAA": frame([100, 80, 110])}, timeline, D("0"), D("0"))
    assert [point.mtm_equity for point in curve] == [100000, 99800, 100100]
    assert curve[1].drawdown == pytest.approx(-0.002)
    report = accounting_report(
        result, {"AAA": frame([100, 80, 110])}, DAY, timeline[-1], DAY, D("0"), D("0")
    )
    exposure = report["exposure"]
    assert exposure["time_invested_percent"] == 100  # type: ignore[index]
    assert exposure["average_open_positions"] == 1  # type: ignore[index]
    assert exposure["peak_gross_exposure_percent"] > 0  # type: ignore[index]


def test_sharpe_and_sortino_use_daily_returns() -> None:
    equities = [100.0, 101.0, 99.0, 102.0]
    metrics = daily_risk_metrics(equities)
    returns = np.asarray(equities[1:]) / np.asarray(equities[:-1]) - 1
    expected_sharpe = returns.mean() / returns.std(ddof=1) * np.sqrt(252)
    downside = np.minimum(returns, 0)
    expected_sortino = returns.mean() / np.sqrt(np.mean(downside**2)) * np.sqrt(252)
    assert metrics["sharpe_ratio"] == pytest.approx(expected_sharpe)
    assert metrics["sortino_ratio"] == pytest.approx(expected_sortino)


def test_zero_length_daily_series_is_safe() -> None:
    assert daily_risk_metrics([]) == {
        "max_drawdown": 0,
        "sharpe_ratio": 0,
        "sortino_ratio": 0,
    }
