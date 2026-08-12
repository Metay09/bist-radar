from dataclasses import dataclass
from datetime import datetime

from app.data.canonical import CanonicalBar


@dataclass(frozen=True)
class IncrementalUpdate:
    bars: tuple[CanonicalBar, ...]
    inserted: int
    duplicates: int
    revisions: int


def merge_incremental(
    existing: list[CanonicalBar], incoming: list[CanonicalBar]
) -> IncrementalUpdate:
    """Merge without silently revising an existing provider bar."""
    merged = {bar.identity: bar for bar in existing}
    inserted = duplicates = revisions = 0
    for bar in incoming:
        old = merged.get(bar.identity)
        if old is None:
            merged[bar.identity] = bar
            inserted += 1
        elif old.values() == bar.values():
            duplicates += 1
        else:
            revisions += 1
    return IncrementalUpdate(
        tuple(sorted(merged.values(), key=lambda bar: (bar.timestamp, bar.symbol))),
        inserted,
        duplicates,
        revisions,
    )


def next_incremental_start(bars: list[CanonicalBar], fallback: datetime) -> datetime:
    return max((bar.timestamp for bar in bars), default=fallback)
