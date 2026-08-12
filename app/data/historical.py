from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from app.backtest.replay_models import Timeframe
from app.data.validation import REQUIRED


@dataclass(frozen=True)
class SymbolMetadata:
    symbol: str
    exchange: str = "BIST"
    active: bool = True
    first_trade_date: date | None = None
    last_trade_date: date | None = None
    sector: str | None = None
    tick_size: Decimal | None = None
    lot_size: int = 1


class HistoricalDataError(ValueError):
    pass


class HistoricalProvider(ABC):
    @abstractmethod
    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame: ...


def validate_historical(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if frame.empty or not REQUIRED.issubset(frame.columns):
        raise HistoricalDataError("malformed historical data")
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result.timestamp, utc=True, errors="coerce")
    if result.timestamp.isna().any():
        raise HistoricalDataError("invalid timestamp")
    if not result.timestamp.is_monotonic_increasing:
        raise HistoricalDataError("unordered historical data")
    if result.timestamp.duplicated().any():
        raise HistoricalDataError("duplicate historical bar")
    if set(result.symbol) != {symbol}:
        raise HistoricalDataError("unexpected symbol")
    return result


class CsvHistoricalProvider(HistoricalProvider):
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        path = self.root / f"{symbol.lower()}.csv"
        if not path.exists():
            raise HistoricalDataError("unknown symbol")
        frame = validate_historical(pd.read_csv(path), symbol)
        if start:
            frame = frame[frame.timestamp >= start]
        if end:
            frame = frame[frame.timestamp <= end]
        return frame.reset_index(drop=True)


class ParquetHistoricalProvider(HistoricalProvider):
    def __init__(self, root: Path) -> None:
        self.root = root

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        path = self.root / f"{symbol.lower()}.parquet"
        if not path.exists():
            raise HistoricalDataError("unknown symbol")
        return validate_historical(pd.read_parquet(path), symbol)
