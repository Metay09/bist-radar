from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.replay_models import Timeframe
from app.backtest.research_replay import (
    FrameHistoricalProvider,
    canonical_frames,
    research_scan,
    run_research_replay,
)
from app.data.canonical import CanonicalBar, QualityFlag
from app.market.analysis import feature_table, features


def research_bars(days: int = 220) -> list[CanonicalBar]:
    result: list[CanonicalBar] = []
    start = datetime(2025, 1, 1, tzinfo=UTC)
    for symbol, drift in (("THYAO", Decimal("0.10")), ("XU100", Decimal("0.04"))):
        for i in range(days):
            close = Decimal("100") + drift * i
            result.append(
                CanonicalBar(
                    symbol=symbol,
                    timestamp=start + timedelta(days=i),
                    timeframe=Timeframe.D1,
                    open=close - Decimal("0.1"),
                    high=close + Decimal("1"),
                    low=close - Decimal("1"),
                    close=close,
                    volume=Decimal("1000000"),
                    provider="yfinance-research",
                    received_at=start + timedelta(days=days + 1),
                    is_adjusted=True,
                    quality_flags=(QualityFlag.RESEARCH_ONLY,),
                )
            )
    return result


def test_canonical_frames_and_provider_range() -> None:
    frames = canonical_frames(research_bars(3))
    assert set(frames) == {"THYAO", "XU100"}
    provider = FrameHistoricalProvider(frames)
    start = frames["THYAO"].timestamp.iloc[1].to_pydatetime()
    assert len(provider.load("THYAO", Timeframe.D1, start, None)) == 2
    assert len(provider.load("THYAO", Timeframe.D1, None, start)) == 2


def test_vector_features_match_single_timestamp_calculation() -> None:
    frame = canonical_frames(research_bars())["THYAO"]
    vector = feature_table(frame).iloc[-1].to_dict()
    scalar = features(frame)
    for key in scalar:
        if isinstance(scalar[key], bool):
            assert bool(vector[key]) == scalar[key]
        else:
            assert float(vector[key]) == pytest.approx(float(scalar[key]))


def test_research_scan_warmup_and_missing_index_fail_closed() -> None:
    warmup = research_scan(research_bars(20), 200)
    assert warmup["candidates"] == []
    assert warmup["rejections"]["WARMUP_INCOMPLETE"] == 1  # type: ignore[index]
    with pytest.raises(ValueError, match="INDEX_DATA_UNAVAILABLE"):
        research_scan([bar for bar in research_bars() if bar.symbol != "XU100"])
    with pytest.raises(ValueError, match="INDEX_DATA_UNAVAILABLE"):
        run_research_replay(
            [bar for bar in research_bars() if bar.symbol != "XU100"], Decimal("100000")
        )


def test_research_scan_and_replay_are_labeled_and_deterministic() -> None:
    bars = research_bars()
    scan = research_scan(bars)
    assert "NOT REALTIME" in str(scan["warning"])
    assert "SURVIVORSHIP_BIAS_POSSIBLE" in scan["flags"]  # type: ignore[operator]
    first, report_a = run_research_replay(bars, Decimal("100000"))
    second, report_b = run_research_replay(bars, Decimal("100000"))
    assert first.final_equity == second.final_equity
    assert report_a["performance"] == report_b["performance"]
    assert report_a["strategy_id"] == "radar-v1-frozen"
    assert "ASSUMED_COST_MODEL" in report_a["flags"]  # type: ignore[operator]
    assert {"market_regimes", "yearly", "symbols_detail", "best_trades", "worst_trades"} <= set(
        report_a
    )


def test_benchmark_future_rows_do_not_change_current_signal() -> None:
    bars = research_bars()
    scan_before = research_scan(bars)
    future = CanonicalBar(
        symbol="XU100",
        timestamp=datetime(2030, 1, 1, tzinfo=UTC),
        timeframe=Timeframe.D1,
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        volume=Decimal("1"),
        provider="yfinance-research",
        received_at=datetime(2030, 1, 2, tzinfo=UTC),
    )
    assert research_scan(bars + [future]) == scan_before
