import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from numbers import Real

from app.backtest.replay_models import Timeframe


class DataMode(StrEnum):
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    EOD = "EOD"
    FIXTURE = "FIXTURE"
    RESEARCH = "RESEARCH"


class QualityFlag(StrEnum):
    CALENDAR_UNVERIFIED = "CALENDAR_UNVERIFIED"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    UNVERIFIED_SOURCE = "UNVERIFIED_SOURCE"
    CLOCK_ANOMALY = "CLOCK_ANOMALY"
    POSSIBLE_CORPORATE_ACTION = "POSSIBLE_CORPORATE_ACTION"
    SURVIVORSHIP_BIAS_POSSIBLE = "SURVIVORSHIP_BIAS_POSSIBLE"
    DATA_RANGE_INCOMPLETE = "DATA_RANGE_INCOMPLETE"
    UNVERIFIED_CORPORATE_ACTION = "UNVERIFIED_CORPORATE_ACTION"
    ASSUMED_COST_MODEL = "ASSUMED_COST_MODEL"


class SessionState(StrEnum):
    PRE_MARKET = "PRE_MARKET"
    OPEN = "OPEN"
    BREAK = "BREAK"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProviderCapabilities:
    historical_bars: bool = False
    intraday_bars: bool = False
    quotes: bool = False
    indices: bool = False
    sector_indices: bool = False
    corporate_actions: bool = False
    streaming: bool = False
    delayed: bool = False
    realtime: bool = False
    market_calendar: bool = False


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    provider_name: str
    data_mode: DataMode
    timezone: str
    source_timestamp: datetime | None = None
    received_timestamp: datetime | None = None
    license_type: str | None = None
    dataset_version: str | None = None
    verified: bool = False


@dataclass(frozen=True)
class CanonicalBar:
    symbol: str
    timestamp: datetime
    timeframe: Timeframe
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    provider: str
    received_at: datetime
    is_adjusted: bool = False
    adjustment_type: str | None = None
    quality_flags: tuple[QualityFlag, ...] = field(default_factory=tuple)

    @property
    def identity(self) -> tuple[str, str, Timeframe, datetime]:
        return self.provider, self.symbol, self.timeframe, self.timestamp

    def values(self) -> tuple[Decimal, ...]:
        return self.open, self.high, self.low, self.close, self.volume


def decimal_from_vendor(value: object) -> Decimal:
    if isinstance(value, Real) and not isinstance(value, bool):
        value = repr(float(value))
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite():
        raise ValueError("non-finite decimal")
    return result


def normalize_timestamp(value: object, *, epoch: bool = False) -> datetime:
    if epoch:
        if not isinstance(value, (str, int, float)):
            raise ValueError("invalid epoch timestamp")
        return datetime.fromtimestamp(float(value), UTC)
    if not isinstance(value, (str, datetime)):
        raise ValueError("invalid timestamp")
    parsed = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if parsed.tzinfo is None:
        raise ValueError("naive timestamp rejected")
    return parsed.astimezone(UTC)


class SymbolMapper:
    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def map(self, vendor_symbol: str) -> str:
        try:
            return self.mapping[vendor_symbol]
        except KeyError as exc:
            raise ValueError("SYMBOL_MAPPING_FAILED") from exc


def dataset_hash(bars: list[CanonicalBar]) -> str:
    digest = hashlib.sha256()
    for bar in sorted(bars, key=lambda b: b.identity):
        row = {
            "symbol": bar.symbol,
            "timestamp": bar.timestamp.isoformat(),
            "timeframe": bar.timeframe.value,
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "volume": str(bar.volume),
            "provider": bar.provider,
            "is_adjusted": bar.is_adjusted,
            "adjustment_type": bar.adjustment_type,
            "quality_flags": [flag.value for flag in bar.quality_flags],
        }
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def validate_canonical(bar: CanonicalBar) -> list[str]:
    errors = []
    if min(bar.open, bar.high, bar.low, bar.close) <= 0:
        errors.append("non-positive price")
    if bar.volume < 0:
        errors.append("negative volume")
    if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
        errors.append("invalid OHLC")
    if bar.received_at < bar.timestamp:
        errors.append("clock anomaly")
    return errors
