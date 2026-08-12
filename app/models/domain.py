from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class DataStatus(StrEnum):
    OK = "DATA_OK"
    STALE = "DATA_STALE"
    CONFLICT = "DATA_CONFLICT"
    MISSING = "DATA_MISSING"
    INVALID = "DATA_INVALID"
    PROVIDER_DOWN = "PROVIDER_DOWN"


class SignalClass(StrEnum):
    NO_SIGNAL = "NO_SIGNAL"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    STRONG_CANDIDATE = "STRONG_CANDIDATE"
    VERY_STRONG_CANDIDATE = "VERY_STRONG_CANDIDATE"


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class ValidationResult:
    status: DataStatus
    quality_score: float
    errors: list[str] = field(default_factory=list)


@dataclass
class TradePlan:
    entry: Decimal
    stop: Decimal
    target_1: Decimal
    target_2: Decimal
    risk_reward: Decimal
    reason: str
