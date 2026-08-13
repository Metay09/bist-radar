from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from app.backtest.replay_models import Timeframe
from app.data.canonical import CanonicalBar
from app.data.intraday_cache import merge_incremental, next_incremental_start
from app.intraday.core import (
    completed_frame,
    completed_intraday_bar,
    early_momentum_score,
    intraday_features,
    intraday_radar_score,
    provider_latency,
    scan_symbol,
    slot_relative_volume,
    stage_a_eligible,
)


def frame(size: int = 240) -> pd.DataFrame:
    index = pd.date_range("2026-01-05 07:00", periods=size, freq="15min", tz="UTC")
    close = np.linspace(100, 112, size) + np.sin(np.arange(size) / 4) * 0.2
    return pd.DataFrame(
        {
            "open": close - 0.05,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": np.resize(np.arange(1, 17) * 1000, size),
        },
        index=index,
    )


def bar(timestamp: datetime, close: str = "10") -> CanonicalBar:
    price = Decimal(close)
    return CanonicalBar(
        "ASELS",
        timestamp,
        Timeframe.M15,
        price,
        price + 1,
        price - 1,
        price,
        Decimal("100"),
        "yfinance-research",
        timestamp + timedelta(minutes=20),
    )


def test_partial_and_completed_intraday_bars() -> None:
    stamp = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert not completed_intraday_bar(stamp, 15, stamp + timedelta(minutes=14))
    assert completed_intraday_bar(stamp, 15, stamp + timedelta(minutes=15))
    data = frame(2)
    filtered = completed_frame(data, 15, data.index[0].to_pydatetime() + timedelta(minutes=15))
    assert len(filtered) == 1
    try:
        completed_intraday_bar(stamp.replace(tzinfo=None), 15, stamp)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)


def test_provider_latency_statistics_and_anomaly_visibility() -> None:
    received = datetime(2026, 1, 1, 10, tzinfo=UTC)
    result = provider_latency(
        [received - timedelta(seconds=60), received - timedelta(seconds=30)], received
    )
    assert result["latest"] == 30
    assert result["p95"] > result["p50"]
    assert provider_latency([], received)["p99"] == 0


def test_stage_a_quality_and_early_mover_override() -> None:
    data = frame(60)
    assert stage_a_eligible(data) == (True, "ELIGIBLE")
    assert stage_a_eligible(data.head(20)) == (False, "LIMITED_HISTORY")
    illiquid = data.copy()
    illiquid.loc[illiquid.index[-20:], "volume"] = 0
    assert stage_a_eligible(illiquid) == (False, "LIQUIDITY_FILTER")
    illiquid.loc[illiquid.index[-2], ["close", "volume"]] = [100, 100]
    illiquid.loc[illiquid.index[-1], ["close", "volume"]] = [103, 1000]
    assert stage_a_eligible(illiquid) == (True, "EARLY_MOVER_OVERRIDE")


def test_incremental_update_duplicate_and_revision() -> None:
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    original = bar(stamp)
    update = merge_incremental(
        [original], [original, bar(stamp, "11"), bar(stamp + timedelta(minutes=15))]
    )
    assert (update.inserted, update.duplicates, update.revisions) == (1, 1, 1)
    assert len(update.bars) == 2  # revision is audited, never silently used
    assert next_incremental_start(list(update.bars), stamp) == stamp + timedelta(minutes=15)
    assert next_incremental_start([], stamp) == stamp


def test_slot_rvol_and_fallback() -> None:
    data = frame(480)
    rvol, method = slot_relative_volume(data, 3)
    assert method == "HISTORICAL_BAR_SLOT"
    assert rvol.notna().any()
    _, short_method = slot_relative_volume(data.iloc[:10], 20)
    assert short_method == "ROLLING_FALLBACK"


def test_15m_scan_features_and_scores_are_bounded() -> None:
    data = frame()
    features = intraday_features(data)
    assert 0 <= early_momentum_score(features) <= 100
    assert 0 <= intraday_radar_score(features) <= 100
    received = data.index[-1].to_pydatetime() + timedelta(minutes=20)
    snapshot = scan_symbol("ASELS", data, received, daily_trend="UPTREND")
    assert snapshot.strategy_id == "radar-intraday-v1"
    assert snapshot.timeframe == "15m"
    assert snapshot.provider_latency_seconds == 1200
    assert snapshot.daily_trend == "UPTREND"
    assert scan_symbol("ASELS", data, received, data_quality=89).radar_score == 0


def test_warmup_and_naive_timestamp_fail_closed() -> None:
    try:
        intraday_features(frame(49))
    except ValueError as exc:
        assert str(exc) == "WARMUP_INCOMPLETE"
    naive = frame()
    naive.index = naive.index.tz_localize(None)
    try:
        scan_symbol("ASELS", naive, datetime.now(UTC))
    except ValueError as exc:
        assert "naive timestamp" in str(exc)
