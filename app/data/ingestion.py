from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from app.data.canonical import CanonicalBar, dataset_hash, validate_canonical
from app.data.readiness import QualityMetrics


@dataclass(frozen=True)
class DataRevision:
    old_value: CanonicalBar
    new_value: CanonicalBar
    received_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class DatasetManifest:
    dataset_id: str
    provider: str
    symbols: tuple[str, ...]
    timeframe: str
    start: datetime
    end: datetime
    rows: int
    hash: str
    imported_at: datetime
    adjusted: bool
    quality_score: float
    revision: int = 1


class BarStore(Protocol):
    def get(self, identity: tuple[object, ...]) -> CanonicalBar | None: ...
    def insert(self, bar: CanonicalBar) -> None: ...
    def revision(self, item: DataRevision) -> None: ...
    def quarantine(self, payload: object, errors: list[str]) -> None: ...


class MemoryBarStore:
    def __init__(self) -> None:
        self.bars: dict[tuple[object, ...], CanonicalBar] = {}
        self.revisions: list[DataRevision] = []
        self.quarantined: list[tuple[object, list[str]]] = []

    def get(self, identity: tuple[object, ...]) -> CanonicalBar | None:
        return self.bars.get(identity)

    def insert(self, bar: CanonicalBar) -> None:
        self.bars[bar.identity] = bar

    def revision(self, item: DataRevision) -> None:
        self.revisions.append(item)

    def quarantine(self, payload: object, errors: list[str]) -> None:
        self.quarantined.append((payload, errors))


class IngestionPipeline:
    """Adapter→schema→symbol→timestamp→canonical→quality→dedupe→persistence."""

    def __init__(self, store: BarStore) -> None:
        self.store = store

    def ingest(
        self, bars: list[CanonicalBar], dry_run: bool = False
    ) -> tuple[DatasetManifest | None, QualityMetrics]:
        metrics = QualityMetrics()
        valid = []
        for bar in bars:
            metrics.bars_received += 1
            errors = validate_canonical(bar)
            if errors:
                metrics.invalid_bars += 1
                if not dry_run:
                    self.store.quarantine(asdict(bar), errors)
                continue
            metrics.bars_valid += 1
            latency = (bar.received_at - bar.timestamp).total_seconds() * 1000
            metrics.latencies_ms.append(latency)
            old = self.store.get(bar.identity)
            if old:
                if old.values() == bar.values():
                    metrics.duplicate_bars += 1
                else:
                    metrics.revised_bars += 1
                    if not dry_run:
                        self.store.revision(
                            DataRevision(old, bar, bar.received_at, "DATA_REVISION")
                        )
                continue
            valid.append(bar)
            if not dry_run:
                self.store.insert(bar)
        if not valid:
            return None, metrics
        manifest = DatasetManifest(
            str(uuid4()),
            valid[0].provider,
            tuple(sorted({b.symbol for b in valid})),
            valid[0].timeframe.value,
            min(b.timestamp for b in valid),
            max(b.timestamp for b in valid),
            len(valid),
            dataset_hash(valid),
            datetime.now(UTC),
            all(b.is_adjusted for b in valid),
            metrics.quality_percent,
        )
        return manifest, metrics


def compare_bars(
    a: CanonicalBar, b: CanonicalBar, price_tolerance: float = 0.001, volume_tolerance: float = 0.01
) -> bool:
    if a.symbol != b.symbol or a.timestamp != b.timestamp or a.timeframe != b.timeframe:
        return False
    return (
        all(
            abs(float(x - y)) / max(abs(float(x)), abs(float(y)), 1) <= price_tolerance
            for x, y in zip(a.values()[:4], b.values()[:4], strict=True)
        )
        and abs(float(a.volume - b.volume)) / max(float(a.volume), float(b.volume), 1)
        <= volume_tolerance
    )
