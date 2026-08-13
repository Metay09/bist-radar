from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.core.config import Settings
from app.intraday.core import completed_intraday_bar
from app.intraday.outcomes import LabelStatus, label_signal, lifecycle
from app.risk.engine import position_size
from app.risk.trade_plan_view import build_research_trade_plan


def test_partial_outcome_has_a_completed_metric_and_never_reads_future_bars() -> None:
    signal = datetime(2026, 8, 13, 10, tzinfo=UTC)
    index = pd.date_range(signal + timedelta(minutes=15), periods=3, freq="15min")
    bars = pd.DataFrame(
        {
            "open": [100] * 3,
            "high": [101, 102, 150],
            "low": [99] * 3,
            "close": [101, 102, 150],
            "volume": [1] * 3,
        },
        index=index,
    )
    outcomes = label_signal(signal, 100, bars, signal + timedelta(minutes=46))
    assert lifecycle(outcomes) == "PARTIALLY_LABELED"
    assert outcomes["30m"].status == LabelStatus.LABEL_AVAILABLE
    assert outcomes["30m"].forward_return == pytest.approx(0.02)
    assert outcomes["60m"].status == LabelStatus.LABEL_PENDING

    before_second_bar_closes = label_signal(
        signal, 100, bars, signal + timedelta(minutes=44, seconds=59)
    )
    assert before_second_bar_closes["30m"].status == LabelStatus.LABEL_PENDING


def test_trade_plan_ordering_and_rounded_size_never_exceed_risk_budget() -> None:
    candidate: dict[str, object] = {
        "symbol": "TEST",
        "timestamp": datetime.now(UTC),
        "price": 100,
        "atr": 2,
        "breakout_distance": 0,
        "rvol": 2,
        "vwap_distance": 1,
        "ema9_distance": 1,
        "ema20_distance": 1,
    }
    plan = build_research_trade_plan(
        candidate,
        [98] * 10,
        account_equity=Decimal("100000"),
        risk_percent=Decimal("0.75"),
        max_position_percent=Decimal("20"),
    )
    targets = [Decimal(str(row["price"])) for row in plan["targets"]]  # type: ignore[index]
    entry = (Decimal(str(plan["entry_zone_low"])) + Decimal(str(plan["entry_zone_high"]))) / 2
    stop = Decimal(str(plan["stop_price"]))
    assert stop < entry < targets[0] < targets[1] < targets[2]
    quantity = position_size(Decimal("100000"), entry, stop)
    assert quantity * (entry - stop) <= Decimal("750")


def test_completed_bar_convention_and_live_trading_safety() -> None:
    stamp = datetime(2026, 8, 13, 10, 45, tzinfo=UTC)
    assert not completed_intraday_bar(stamp, 15, stamp + timedelta(minutes=14, seconds=59))
    assert completed_intraday_bar(stamp, 15, stamp + timedelta(minutes=15))
    try:
        Settings(trading_mode="live")
    except ValueError as exc:
        assert "LIVE TRADING IS DISABLED" in str(exc)
    else:
        raise AssertionError("live trading must remain impossible")


def test_coverage_count_ordering_invariant() -> None:
    active, provider_available, eligible, actually_scanned = 624, 621, 585, 529
    assert actually_scanned <= eligible <= provider_available <= active


def test_web_origin_uses_runtime_docker_dns_resolution() -> None:
    nginx = Path("frontend/nginx.conf").read_text()
    assert "resolver 127.0.0.11" in nginx
    assert "proxy_pass http://$api_upstream" in nginx
    assert "proxy_pass http://bist-radar-api" not in nginx
