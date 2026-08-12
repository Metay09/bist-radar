from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import sleep

import pandas as pd

from app.models.domain import DataStatus


class ProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderResult:
    status: DataStatus
    bars: pd.DataFrame | None
    error: str | None = None


def fetch_with_retry(
    provider: "MarketDataProvider",
    symbol: str,
    attempts: int = 3,
    backoff_seconds: float = 0.1,
    sleeper: Callable[[float], None] = sleep,
) -> ProviderResult:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            return ProviderResult(DataStatus.OK, provider.get_daily_bars(symbol))
        except (ProviderError, TimeoutError) as exc:
            if attempt + 1 < attempts:
                sleeper(backoff_seconds * (2**attempt))
            else:
                return ProviderResult(DataStatus.PROVIDER_DOWN, None, type(exc).__name__)
    raise AssertionError("unreachable")


class MarketDataProvider(ABC):
    @abstractmethod
    def get_daily_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame: ...

    def get_quote(self, symbol: str) -> float:
        bars = self.get_daily_bars(symbol, 1)
        if bars.empty:
            raise ProviderError(f"No quote for {symbol}")
        return float(bars.iloc[-1].close)

    def get_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        return self.get_daily_bars(symbol, limit)

    def get_index_data(self, symbol: str = "XU100", limit: int = 300) -> pd.DataFrame:
        return self.get_daily_bars(symbol, limit)


class CsvProvider(MarketDataProvider):
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_daily_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        path = self.root / f"{symbol.lower()}.csv"
        if not path.exists():
            raise ProviderError(f"Fixture unavailable: {symbol}")
        frame = pd.read_csv(path, parse_dates=["timestamp"])
        return frame.tail(limit).reset_index(drop=True)


class MockProvider(MarketDataProvider):
    def __init__(self, data: dict[str, pd.DataFrame]) -> None:
        self.data = data

    def get_daily_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        try:
            return self.data[symbol].tail(limit).copy()
        except KeyError as exc:
            raise ProviderError(symbol) from exc


class FutureLicensedProvider(MarketDataProvider):
    def get_daily_bars(self, symbol: str, limit: int = 300) -> pd.DataFrame:
        raise ProviderError("No licensed provider configured")


def compare_latest_prices(
    primary: pd.DataFrame, secondary: pd.DataFrame, tolerance_percent: float
) -> bool:
    if primary.empty or secondary.empty:
        return False
    a, b = float(primary.iloc[-1].close), float(secondary.iloc[-1].close)
    return abs(a - b) / max(abs(a), abs(b)) * 100 <= tolerance_percent
