import sys
from datetime import UTC, date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from app.data.canonical import DataMode, QualityFlag
from app.data.readiness import assert_environment_compatible
from app.data.research import ResearchCache, liquidity_rejection, load_universe
from app.data.yfinance_provider import (
    ResearchProviderError,
    SymbolDataUnavailable,
    YFinanceResearchProvider,
)


def vendor_frame(rows: int = 3) -> pd.DataFrame:
    index = pd.date_range("2025-01-02", periods=rows, freq="B")
    return pd.DataFrame(
        {
            "Open": [10.0 + i for i in range(rows)],
            "High": [11.0 + i for i in range(rows)],
            "Low": [9.0 + i for i in range(rows)],
            "Close": [10.5 + i for i in range(rows)],
            "Volume": [1000 + i for i in range(rows)],
            "Dividends": [0.0] * rows,
            "Stock Splits": [0.0] * rows,
        },
        index=index,
    )


def test_metadata_mapping_and_production_rejection() -> None:
    provider = YFinanceResearchProvider(lambda **_: vendor_frame())
    assert provider.metadata.provider_id == "yfinance-research"
    assert provider.metadata.data_mode == DataMode.RESEARCH and not provider.metadata.verified
    assert set(provider.mandatory_flags) == {
        QualityFlag.RESEARCH_ONLY,
        QualityFlag.UNVERIFIED_SOURCE,
        QualityFlag.CALENDAR_UNVERIFIED,
    }
    assert provider.vendor_symbol("thyao") == "THYAO.IS"
    assert provider.vendor_symbol("XU100") == "XU100.IS"
    assert provider.canonical_symbol("THYAO.IS") == "THYAO"
    with pytest.raises(ValueError, match="MAPPING"):
        provider.vendor_symbol("THYAO.IS")
    with pytest.raises(ValueError, match="MAPPING"):
        provider.canonical_symbol("THYAO")
    with pytest.raises(ValueError, match="not approved"):
        assert_environment_compatible("production", DataMode.RESEARCH, False, False)


def test_download_normalizes_decimal_timezone_adjustment_and_range() -> None:
    provider = YFinanceResearchProvider(lambda **_: vendor_frame(), price_mode="adjusted")
    result = provider.download("THYAO", date(2025, 1, 1), date(2025, 1, 20))
    assert len(result.bars) == 3 and result.bars[0].symbol == "THYAO"
    assert result.bars[0].timestamp.tzinfo == UTC and result.bars[0].is_adjusted
    assert result.bars[0].provider == "yfinance-research"
    assert result.quality.bars_valid == 3 and result.quality.quality_score == 100
    assert QualityFlag.DATA_RANGE_INCOMPLETE.value in result.quality.flags


def test_unadjusted_mode_is_explicit_and_download_arguments() -> None:
    calls: list[dict[str, object]] = []

    def downloader(**kwargs: object) -> pd.DataFrame:
        calls.append(kwargs)
        return vendor_frame()

    bar = (
        YFinanceResearchProvider(downloader, price_mode="unadjusted")
        .download("ASELS", date(2025, 1, 1), date(2025, 1, 10))
        .bars[0]
    )
    assert not bar.is_adjusted and bar.adjustment_type is None
    assert calls[0]["auto_adjust"] is False and calls[0]["threads"] is False
    with pytest.raises(ValueError, match="PRICE_MODE"):
        YFinanceResearchProvider(downloader, price_mode="implicit")
    with pytest.raises(ValueError, match="attempts"):
        YFinanceResearchProvider(downloader, attempts=0)


def test_empty_missing_invalid_payload_and_bad_range() -> None:
    with pytest.raises(SymbolDataUnavailable, match="SYMBOL_DATA_UNAVAILABLE"):
        YFinanceResearchProvider(lambda **_: pd.DataFrame()).download(
            "MISSING", date(2025, 1, 1), date(2025, 2, 1)
        )
    with pytest.raises(ValueError, match="precede"):
        YFinanceResearchProvider(lambda **_: vendor_frame()).download(
            "THYAO", date(2025, 2, 1), date(2025, 1, 1)
        )
    with pytest.raises(ResearchProviderError, match="columns"):
        YFinanceResearchProvider(lambda **_: pd.DataFrame({"Bad": [1]})).download(
            "THYAO", date(2025, 1, 1), date(2025, 2, 1)
        )


def test_network_timeout_retries_bounded_and_partial_many(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def downloader(**kwargs: object) -> pd.DataFrame:
        nonlocal attempts
        attempts += 1
        if kwargs["tickers"] == "BAD.IS" or attempts < 3:
            raise TimeoutError("network")
        return vendor_frame()

    monkeypatch.setattr("app.data.yfinance_provider.sleep", lambda _: None)
    provider = YFinanceResearchProvider(downloader, attempts=3)
    good = provider.download("THYAO", date(2025, 1, 1), date(2025, 2, 1))
    assert good.bars and attempts == 3
    results, failures = provider.download_many(["THYAO", "BAD"], date(2025, 1, 1), date(2025, 2, 1))
    assert "THYAO" in results and failures["BAD"] == "TimeoutError"


def test_duplicate_unordered_nan_invalid_numeric_zero_volume_and_large_gap() -> None:
    frame = vendor_frame(4).iloc[[2, 0, 0, 1]].copy()
    frame.iloc[1, frame.columns.get_loc("Open")] = float("nan")
    frame.iloc[3, frame.columns.get_loc("Volume")] = 0
    frame.iloc[0, frame.columns.get_loc("Open")] = 100
    frame.iloc[0, frame.columns.get_loc("High")] = 101
    frame.iloc[0, frame.columns.get_loc("Low")] = 99
    frame.iloc[0, frame.columns.get_loc("Close")] = 100
    result = YFinanceResearchProvider(lambda **_: frame).download(
        "THYAO", date(2025, 1, 1), date(2025, 2, 1)
    )
    assert result.quality.duplicates == 1
    assert result.quality.invalid == 1
    assert result.quality.zero_volume == 1
    assert result.quality.large_gaps == 1
    bad = vendor_frame(1).astype(object)
    bad.iloc[0, bad.columns.get_loc("Open")] = "not-a-number"
    with pytest.raises(SymbolDataUnavailable):
        YFinanceResearchProvider(lambda **_: bad).download(
            "THYAO", date(2025, 1, 1), date(2025, 2, 1)
        )


def test_multiindex_supported_and_unexpected_layout_rejected() -> None:
    frame = vendor_frame()
    frame.columns = pd.MultiIndex.from_product([frame.columns, ["THYAO.IS"]])
    assert (
        YFinanceResearchProvider(lambda **_: frame)
        .download("THYAO", date(2025, 1, 1), date(2025, 2, 1))
        .bars
    )
    mixed = vendor_frame()
    mixed.columns = pd.MultiIndex.from_tuples(
        [(column, "A.IS" if i % 2 else "B.IS") for i, column in enumerate(mixed.columns)]
    )
    with pytest.raises(ResearchProviderError, match="MultiIndex"):
        YFinanceResearchProvider(lambda **_: mixed).download(
            "THYAO", date(2025, 1, 1), date(2025, 2, 1)
        )


def test_batch_download_is_single_request_cached_and_deterministic(tmp_path: Path) -> None:
    calls: list[str] = []
    a, b = vendor_frame(), vendor_frame()
    batch = pd.concat({"THYAO.IS": a, "ASELS.IS": b}, axis=1).swaplevel(axis=1)

    def downloader(**kwargs: object) -> pd.DataFrame:
        calls.append(str(kwargs["tickers"]))
        return batch

    provider = YFinanceResearchProvider(downloader, ResearchCache(tmp_path), attempts=1)
    results, failures = provider.download_many(
        ["THYAO", "ASELS", "THYAO"], date(2025, 1, 1), date(2025, 2, 1)
    )
    assert set(results) == {"THYAO", "ASELS"} and not failures
    assert calls == ["ASELS.IS THYAO.IS"]
    assert len(list(tmp_path.glob("*.json"))) == 2
    cached, _ = provider.download_many(["THYAO", "ASELS"], date(2025, 1, 1), date(2025, 2, 1))
    assert set(cached) == {"THYAO", "ASELS"} and len(calls) == 1
    with pytest.raises(ValueError, match="batch_size"):
        provider.download_many(["THYAO"], date(2025, 1, 1), date(2025, 2, 1), 0)


def test_batch_failure_falls_back_per_symbol_and_cache_write_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def downloader(**kwargs: object) -> pd.DataFrame:
        ticker = str(kwargs["tickers"])
        calls.append(ticker)
        if " " in ticker:
            raise TimeoutError("batch failed")
        return vendor_frame()

    class ReadOnlyCache:
        def load(self, *args: object) -> None:
            return None

        def save(self, *args: object) -> None:
            raise PermissionError("read only")

    monkeypatch.setattr("app.data.yfinance_provider.sleep", lambda _: None)
    provider = YFinanceResearchProvider(
        downloader,
        ReadOnlyCache(),
        attempts=1,  # type: ignore[arg-type]
    )
    results, failures = provider.download_many(
        ["THYAO", "ASELS"], date(2025, 1, 1), date(2025, 2, 1)
    )
    assert set(results) == {"THYAO", "ASELS"} and not failures
    assert calls == ["ASELS.IS THYAO.IS", "ASELS.IS", "THYAO.IS"]


def test_invalid_cached_payload_is_refetched(tmp_path: Path) -> None:
    cache = ResearchCache(tmp_path)
    invalid = vendor_frame(1)
    invalid.loc[invalid.index[0], "Open"] = -1
    cache.save("THYAO", date(2025, 1, 1), date(2025, 2, 1), "adjusted", invalid)
    calls = 0

    def downloader(**_: object) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return vendor_frame()

    result, failures = YFinanceResearchProvider(downloader, cache).download_many(
        ["THYAO"], date(2025, 1, 1), date(2025, 2, 1)
    )
    assert result["THYAO"].bars
    assert calls == 1 and not failures


def test_vendor_boundary_misc_payload_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = YFinanceResearchProvider(attempts=1)
    monkeypatch.setitem(
        sys.modules, "yfinance", SimpleNamespace(download=lambda **_: vendor_frame())
    )
    assert provider.download("THYAO", date(2025, 1, 1), date(2025, 2, 1)).bars
    with pytest.raises(ResearchProviderError, match="invalid payload"):
        provider._flatten([], "THYAO.IS")  # type: ignore[arg-type]
    single = vendor_frame()
    single.columns = pd.MultiIndex.from_product([single.columns, ["ONLY.IS"]])
    assert not provider._flatten(single, "THYAO.IS").empty
    aware = vendor_frame()
    aware.index = aware.index.tz_localize("UTC")
    assert (
        YFinanceResearchProvider(lambda **_: aware)
        .download("THYAO", date(2025, 1, 1), date(2025, 2, 1))
        .bars[0]
        .timestamp.tzinfo
        == UTC
    )


@pytest.mark.parametrize(
    "column,value",
    [("Open", -1), ("High", 5)],
)
def test_invalid_prices_and_ohlc_are_rejected(column: str, value: float) -> None:
    frame = vendor_frame(1)
    frame.loc[frame.index[0], column] = value
    with pytest.raises(SymbolDataUnavailable):
        YFinanceResearchProvider(lambda **_: frame).download(
            "THYAO", date(2025, 1, 1), date(2025, 2, 1)
        )


def test_cache_hash_ttl_and_corruption(tmp_path: Path) -> None:
    cache = ResearchCache(tmp_path, timedelta(days=1))
    frame = vendor_frame()
    manifest = cache.save("THYAO", date(2025, 1, 1), date(2025, 2, 1), "adjusted", frame)
    assert len(manifest.data_hash) == 64
    assert cache.load("THYAO", date(2025, 1, 1), date(2025, 2, 1), "adjusted") is not None
    csv_path = next(tmp_path.glob("*.csv"))
    csv_path.write_text("corrupt")
    assert cache.load("THYAO", date(2025, 1, 1), date(2025, 2, 1), "adjusted") is None
    assert cache.load("ASELS", date(2025, 1, 1), date(2025, 2, 1), "adjusted") is None
    stale = ResearchCache(tmp_path, timedelta(seconds=-1))
    assert stale.load("THYAO", date(2025, 1, 1), date(2025, 2, 1), "adjusted") is None


def test_universe_hash_and_liquidity_filters(tmp_path: Path) -> None:
    universe = load_universe(Path("config/universes/bist100.csv"))
    assert len(universe.members) == 100 and len(universe.snapshot_hash) == 64
    assert QualityFlag.SURVIVORSHIP_BIAS_POSSIBLE in universe.flags
    frame = vendor_frame()
    assert liquidity_rejection(frame, min_bars=100) == "REJECTED_LOW_LIQUIDITY"
    assert liquidity_rejection(frame, min_volume=10_000) == "REJECTED_LOW_LIQUIDITY"
    assert liquidity_rejection(frame, min_value=1_000_000) == "REJECTED_LOW_LIQUIDITY"
    assert liquidity_rejection(frame, min_price=20) == "REJECTED_PRICE_FLOOR"
    assert liquidity_rejection(frame) is None
    invalid = tmp_path / "bad.csv"
    invalid.write_text("symbol,name\nTHYAO,THY")
    with pytest.raises(ValueError, match="schema"):
        load_universe(invalid)
    invalid.write_text("symbol,name,sector,active,source,source_date\n?.IS,x,,true,test,2025-01-01")
    with pytest.raises(ValueError, match="symbol"):
        load_universe(invalid)
    invalid.write_text(
        "symbol,name,sector,active,source,source_date\n"
        "AAA,x,,true,test,2025-01-01\nAAA,x,,true,test,2025-01-01"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_universe(invalid)
    assert liquidity_rejection(pd.DataFrame({"x": [1]})) == "REJECTED_LOW_LIQUIDITY"
