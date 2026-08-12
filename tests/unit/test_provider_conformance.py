from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.replay_models import Timeframe
from app.data.canonical import (
    CanonicalBar,
    DataMode,
    QualityFlag,
    SymbolMapper,
    dataset_hash,
    decimal_from_vendor,
    normalize_timestamp,
    validate_canonical,
)
from app.data.ingestion import IngestionPipeline, MemoryBarStore, compare_bars
from app.data.readiness import (
    BarSequence,
    CircuitBreaker,
    CircuitState,
    ProviderHealth,
    ProviderHealthTracker,
    QualityMetrics,
    assert_environment_compatible,
    detect_missing,
    is_stale,
    retry_delay,
)
from app.data.vendor_mock import CapabilityUnavailable, MockVendorA, MockVendorB

NOW = datetime(2025, 1, 2, tzinfo=UTC)
TS = datetime(2025, 1, 1, tzinfo=UTC)
PAYLOAD_A = {
    "ticker": "BIST:THYAO",
    "time": "2025-01-01T00:00:00Z",
    "interval": "1d",
    "o": "10.10",
    "h": "11",
    "l": "9.5",
    "c": "10.5",
    "v": "1000",
}
PAYLOAD_B = {
    "instrument": "THYAO.IS",
    "ts": TS.timestamp(),
    "tf": "1d",
    "openPrice": "10.10",
    "highPrice": "11",
    "lowPrice": "9.5",
    "lastPrice": "10.5",
    "totalVolume": "1000",
}


@pytest.mark.parametrize(
    "provider,payload", [(MockVendorA(), PAYLOAD_A), (MockVendorB(), PAYLOAD_B)]
)
def test_provider_contract_canonical_sorted_identity(
    provider: object, payload: dict[str, object]
) -> None:
    bar = provider.normalize(payload, NOW)  # type: ignore[attr-defined]
    assert bar.symbol == "THYAO" and bar.timestamp == TS and bar.open == Decimal("10.10")
    assert bar.provider == provider.metadata.provider_id  # type: ignore[attr-defined]
    assert provider.capabilities.historical_bars  # type: ignore[attr-defined]
    assert not validate_canonical(bar)


def test_vendor_formats_have_equivalent_market_values() -> None:
    a = MockVendorA().normalize(PAYLOAD_A, NOW)
    b = MockVendorB().normalize(PAYLOAD_B, NOW)
    assert a.symbol == b.symbol and a.timestamp == b.timestamp and a.values() == b.values()
    assert compare_bars(a, b)


def test_capability_mapping_decimal_and_timestamp_fail_closed() -> None:
    with pytest.raises(CapabilityUnavailable, match="CAPABILITY"):
        MockVendorA().require("streaming")
    with pytest.raises(ValueError, match="SYMBOL_MAPPING_FAILED"):
        SymbolMapper({}).map("UNKNOWN")
    with pytest.raises(ValueError):
        decimal_from_vendor("NaN")
    with pytest.raises(ValueError, match="naive"):
        normalize_timestamp("2025-01-01T00:00:00")
    assert normalize_timestamp("2025-01-01T03:00:00+03:00") == TS


def bar(**changes: object) -> CanonicalBar:
    values = dict(
        symbol="THYAO",
        timestamp=TS,
        timeframe=Timeframe.D1,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        provider="mock-a",
        received_at=NOW,
        quality_flags=(QualityFlag.RESEARCH_ONLY,),
    )
    values.update(changes)
    return CanonicalBar(**values)  # type: ignore[arg-type]


def test_ingestion_duplicate_revision_quarantine_and_dry_run() -> None:
    store = MemoryBarStore()
    pipeline = IngestionPipeline(store)
    manifest, metrics = pipeline.ingest([bar()])
    assert manifest and metrics.bars_valid == 1 and len(store.bars) == 1
    _, duplicate = pipeline.ingest([bar()])
    assert duplicate.duplicate_bars == 1 and len(store.bars) == 1
    _, revision = pipeline.ingest([bar(close=Decimal("10.6"))])
    assert revision.revised_bars == 1 and len(store.revisions) == 1
    _, invalid = pipeline.ingest([bar(low=Decimal("12"))])
    assert invalid.invalid_bars == 1 and len(store.quarantined) == 1
    fresh = MemoryBarStore()
    dry_manifest, _ = IngestionPipeline(fresh).ingest([bar()], dry_run=True)
    assert dry_manifest and not fresh.bars


def test_dataset_hash_reproducible_and_sensitive() -> None:
    assert dataset_hash([bar()]) == dataset_hash([bar()])
    assert dataset_hash([bar()]) != dataset_hash([bar(close=Decimal("10.6"))])


def test_quality_latency_health_stale_sequence_and_circuit() -> None:
    metrics = QualityMetrics(bars_received=2, bars_valid=1, latencies_ms=[10, 20, 30])
    assert metrics.quality_percent == 50 and metrics.latency()["p95"] == 30
    tracker = ProviderHealthTracker(2, 2)
    assert tracker.failure() == ProviderHealth.DEGRADED
    assert tracker.failure() == ProviderHealth.DOWN
    tracker.success()
    assert tracker.success() == ProviderHealth.HEALTHY
    assert is_stale(bar(), TS + timedelta(days=3), DataMode.EOD)
    assert detect_missing([bar()], False) == BarSequence.UNKNOWN
    assert (
        detect_missing([bar(), bar(timestamp=TS + timedelta(days=2))], True) == BarSequence.MISSING
    )
    breaker = CircuitBreaker(2, timedelta(seconds=1))
    breaker.failure(TS)
    breaker.failure(TS)
    assert breaker.state == CircuitState.OPEN and not breaker.allow(TS)
    assert breaker.allow(TS + timedelta(seconds=2)) and breaker.state == CircuitState.HALF_OPEN
    breaker.success()
    assert breaker.state == CircuitState.CLOSED
    assert 0.25 <= retry_delay(0, jitter=0) <= 0.25


def test_cross_provider_conflict_and_validation_flags() -> None:
    assert not compare_bars(bar(), bar(timestamp=TS + timedelta(days=1)))
    assert not compare_bars(bar(), bar(close=Decimal("20")))
    errors = validate_canonical(
        bar(open=Decimal("-1"), volume=Decimal("-1"), received_at=TS - timedelta(seconds=1))
    )
    assert {"non-positive price", "negative volume", "invalid OHLC", "clock anomaly"}.issubset(
        errors
    )


def test_production_rejects_fixture_unverified_provider() -> None:
    with pytest.raises(ValueError, match="not approved"):
        assert_environment_compatible("production", DataMode.FIXTURE, False, False)
    assert_environment_compatible("research", DataMode.FIXTURE, False, False)
