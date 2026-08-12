from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd


class ProviderError(RuntimeError):
    pass


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
