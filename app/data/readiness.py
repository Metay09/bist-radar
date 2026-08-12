import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from app.backtest.replay_models import Timeframe
from app.data.canonical import CanonicalBar, DataMode


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class BarSequence(StrEnum):
    OK = "BAR_SEQUENCE_OK"
    MISSING = "BAR_MISSING"
    UNKNOWN = "BAR_SEQUENCE_UNKNOWN"


@dataclass
class QualityMetrics:
    bars_received: int = 0
    bars_valid: int = 0
    invalid_bars: int = 0
    duplicate_bars: int = 0
    revised_bars: int = 0
    missing_bars: int = 0
    stale_bars: int = 0
    symbol_mapping_errors: int = 0
    timestamp_errors: int = 0
    provider_errors: int = 0
    latencies_ms: list[float] = field(default_factory=list)

    @property
    def quality_percent(self) -> float:
        return self.bars_valid / self.bars_received * 100 if self.bars_received else 0

    def latency(self) -> dict[str, float]:
        values = sorted(self.latencies_ms)
        if not values:
            return {k: 0 for k in ("latest", "average", "p50", "p95", "p99", "maximum")}

        def percentile(p: float) -> float:
            return values[min(len(values) - 1, round((len(values) - 1) * p))]

        return {
            "latest": values[-1],
            "average": statistics.mean(values),
            "p50": percentile(0.5),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "maximum": max(values),
        }


class ProviderHealthTracker:
    def __init__(self, failure_threshold: int = 3, recovery_threshold: int = 2) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.failures = 0
        self.successes = 0
        self.state = ProviderHealth.UNKNOWN

    def failure(self) -> ProviderHealth:
        self.failures += 1
        self.successes = 0
        self.state = (
            ProviderHealth.DOWN
            if self.failures >= self.failure_threshold
            else ProviderHealth.DEGRADED
        )
        return self.state

    def success(self) -> ProviderHealth:
        self.successes += 1
        self.failures = 0
        if self.successes >= self.recovery_threshold:
            self.state = ProviderHealth.HEALTHY
        return self.state


class CircuitBreaker:
    def __init__(self, threshold: int = 3, cooldown: timedelta = timedelta(seconds=30)) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.opened_at: datetime | None = None

    def allow(self, now: datetime) -> bool:
        if (
            self.state == CircuitState.OPEN
            and self.opened_at
            and now - self.opened_at >= self.cooldown
        ):
            self.state = CircuitState.HALF_OPEN
        return self.state != CircuitState.OPEN

    def failure(self, now: datetime) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.state = CircuitState.OPEN
            self.opened_at = now

    def success(self) -> None:
        self.failures = 0
        self.state = CircuitState.CLOSED


def retry_delay(attempt: int, base: float = 0.25, jitter: float = 0.1) -> float:
    return float(base * (2**attempt) + random.uniform(0, jitter))


STALE_LIMITS = {
    Timeframe.M5: timedelta(minutes=10),
    Timeframe.M15: timedelta(minutes=30),
    Timeframe.M60: timedelta(hours=2),
    Timeframe.D1: timedelta(days=2),
}


def is_stale(bar: CanonicalBar, now: datetime, mode: DataMode) -> bool:
    allowance = timedelta(minutes=20) if mode == DataMode.DELAYED else timedelta(0)
    return now - bar.timestamp > STALE_LIMITS[bar.timeframe] + allowance


def detect_missing(bars: list[CanonicalBar], calendar_verified: bool) -> BarSequence:
    if not calendar_verified:
        return BarSequence.UNKNOWN
    if len(bars) < 2:
        return BarSequence.OK
    expected = {
        Timeframe.M5: timedelta(minutes=5),
        Timeframe.M15: timedelta(minutes=15),
        Timeframe.M60: timedelta(hours=1),
        Timeframe.D1: timedelta(days=1),
    }[bars[0].timeframe]
    return (
        BarSequence.MISSING
        if any(b.timestamp - a.timestamp > expected for a, b in zip(bars, bars[1:], strict=False))
        else BarSequence.OK
    )


def assert_environment_compatible(
    environment: str, mode: DataMode, provider_verified: bool, calendar_verified: bool
) -> None:
    if environment == "production" and (
        mode == DataMode.FIXTURE or not provider_verified or not calendar_verified
    ):
        raise ValueError("provider is not approved for production")
