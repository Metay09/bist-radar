import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from app.data.canonical import QualityFlag


@dataclass(frozen=True)
class UniverseMember:
    symbol: str
    name: str | None
    sector: str | None
    active: bool
    source: str
    source_date: date


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_id: str
    members: tuple[UniverseMember, ...]
    snapshot_hash: str
    flags: tuple[QualityFlag, ...] = (QualityFlag.SURVIVORSHIP_BIAS_POSSIBLE,)


def load_universe(path: Path, universe_id: str = "bist100-current") -> UniverseSnapshot:
    frame = pd.read_csv(path, dtype=str).fillna("")
    required = {"symbol", "name", "sector", "active", "source", "source_date"}
    if set(frame.columns) != required:
        raise ValueError("invalid universe schema")
    members: list[UniverseMember] = []
    for row in frame.itertuples(index=False):
        symbol = str(row.symbol).strip().upper()
        if not symbol or not symbol.isascii() or not symbol.replace("_", "").isalnum():
            raise ValueError("invalid universe symbol")
        members.append(
            UniverseMember(
                symbol,
                str(row.name) or None,
                str(row.sector) or None,
                str(row.active).lower() in {"1", "true", "yes"},
                str(row.source),
                date.fromisoformat(str(row.source_date)),
            )
        )
    if len({m.symbol for m in members}) != len(members):
        raise ValueError("duplicate universe symbol")
    canonical = [
        vars(member) | {"source_date": member.source_date.isoformat()} for member in members
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return UniverseSnapshot(universe_id, tuple(members), digest)


@dataclass(frozen=True)
class CacheManifest:
    provider: str
    symbol: str
    start: str
    end: str
    price_mode: str
    downloaded_at: str
    data_hash: str


class ResearchCache:
    def __init__(self, root: Path, ttl: timedelta = timedelta(hours=24)) -> None:
        self.root, self.ttl = root, ttl

    def _paths(self, symbol: str, start: date, end: date, mode: str) -> tuple[Path, Path]:
        key = f"{symbol}_{start.isoformat()}_{end.isoformat()}_{mode}"
        return self.root / f"{key}.csv", self.root / f"{key}.json"

    def load(self, symbol: str, start: date, end: date, mode: str) -> pd.DataFrame | None:
        data_path, manifest_path = self._paths(symbol, start, end, mode)
        if not data_path.exists() or not manifest_path.exists():
            return None
        manifest = json.loads(manifest_path.read_text())
        downloaded = datetime.fromisoformat(manifest["downloaded_at"])
        if datetime.now(UTC) - downloaded > self.ttl:
            return None
        payload = data_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest["data_hash"]:
            return None
        return pd.read_csv(data_path, index_col=0, parse_dates=True)

    def save(
        self, symbol: str, start: date, end: date, mode: str, frame: pd.DataFrame
    ) -> CacheManifest:
        self.root.mkdir(parents=True, exist_ok=True)
        data_path, manifest_path = self._paths(symbol, start, end, mode)
        frame.to_csv(data_path)
        data_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
        manifest = CacheManifest(
            "yfinance-research",
            symbol,
            start.isoformat(),
            end.isoformat(),
            mode,
            datetime.now(UTC).isoformat(),
            data_hash,
        )
        manifest_path.write_text(json.dumps(vars(manifest), sort_keys=True))
        return manifest


@dataclass
class SymbolQuality:
    symbol: str
    bars_received: int = 0
    bars_valid: int = 0
    invalid: int = 0
    duplicates: int = 0
    missing: str = "unknown"
    zero_volume: int = 0
    large_gaps: int = 0
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None
    flags: list[str] = field(default_factory=list)

    @property
    def quality_score(self) -> float:
        if not self.bars_received:
            return 0
        penalties = self.invalid + self.duplicates
        return max(0.0, min(100.0, (self.bars_received - penalties) / self.bars_received * 100))


def liquidity_rejection(
    frame: pd.DataFrame,
    *,
    min_value: float = 0,
    min_volume: float = 0,
    min_bars: int = 0,
    min_price: float = 0,
) -> str | None:
    normalized = frame.rename(columns={str(c): str(c).lower() for c in frame.columns})
    if not {"close", "volume"}.issubset(normalized.columns):
        return "REJECTED_LOW_LIQUIDITY"
    if len(normalized) < min_bars or normalized.volume.mean() < min_volume:
        return "REJECTED_LOW_LIQUIDITY"
    if (normalized.close * normalized.volume).mean() < min_value:
        return "REJECTED_LOW_LIQUIDITY"
    if float(normalized.close.iloc[-1]) < min_price:
        return "REJECTED_PRICE_FLOOR"
    return None
