from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import sleep
from typing import Any

import pandas as pd

from app.backtest.replay_models import Timeframe
from app.data.canonical import (
    CanonicalBar,
    DataMode,
    ProviderCapabilities,
    ProviderMetadata,
    QualityFlag,
    decimal_from_vendor,
)
from app.data.readiness import retry_delay
from app.data.research import ResearchCache, SymbolQuality

Downloader = Callable[..., pd.DataFrame]


class ResearchProviderError(RuntimeError):
    pass


class SymbolDataUnavailable(ResearchProviderError):
    pass


@dataclass(frozen=True)
class ResearchDownload:
    bars: tuple[CanonicalBar, ...]
    quality: SymbolQuality
    requested_start: date
    requested_end: date


class YFinanceResearchProvider:
    metadata = ProviderMetadata(
        "yfinance-research",
        "Yahoo Finance via yfinance",
        DataMode.RESEARCH,
        "UTC",
        license_type="UNVERIFIED_RESEARCH",
        verified=False,
    )
    capabilities = ProviderCapabilities(
        historical_bars=True,
        intraday_bars=True,
        indices=True,
        corporate_actions=True,
        delayed=True,
    )
    mandatory_flags = (
        QualityFlag.RESEARCH_ONLY,
        QualityFlag.UNVERIFIED_SOURCE,
        QualityFlag.CALENDAR_UNVERIFIED,
    )

    def __init__(
        self,
        downloader: Downloader | None = None,
        cache: ResearchCache | None = None,
        *,
        price_mode: str = "adjusted",
        attempts: int = 3,
    ) -> None:
        if price_mode not in {"adjusted", "unadjusted"}:
            raise ValueError("PRICE_MODE must be adjusted or unadjusted")
        if attempts < 1:
            raise ValueError("attempts must be positive")
        self._downloader = downloader
        self.cache = cache
        self.price_mode = price_mode
        self.attempts = attempts

    @staticmethod
    def vendor_symbol(symbol: str) -> str:
        canonical = symbol.strip().upper()
        if canonical == "XU100":
            return "XU100.IS"
        if not canonical or not canonical.isascii() or not canonical.isalnum():
            raise ValueError("SYMBOL_MAPPING_FAILED")
        return f"{canonical}.IS"

    @staticmethod
    def canonical_symbol(vendor: str) -> str:
        if vendor == "XU100.IS":
            return "XU100"
        if not vendor.endswith(".IS") or not vendor[:-3].isalnum():
            raise ValueError("SYMBOL_MAPPING_FAILED")
        return vendor[:-3]

    def _download(self, **kwargs: Any) -> pd.DataFrame:
        if self._downloader is not None:
            return self._downloader(**kwargs)
        try:
            import yfinance as yf
        except ImportError as exc:  # isolated optional vendor failure
            raise ResearchProviderError("yfinance dependency unavailable") from exc
        return yf.download(**kwargs)

    def _fetch(self, vendor: str, start: date, end: date, interval: str = "1d") -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(self.attempts):
            try:
                return self._download(
                    tickers=vendor,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    interval=interval,
                    auto_adjust=self.price_mode == "adjusted",
                    actions=True,
                    progress=False,
                    threads=False,
                    group_by="column",
                )
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.attempts:
                    sleep(retry_delay(attempt))
        raise ResearchProviderError(type(last_error).__name__) from last_error

    @staticmethod
    def _flatten(frame: pd.DataFrame, vendor: str) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise ResearchProviderError("invalid payload")
        if isinstance(frame.columns, pd.MultiIndex):
            if vendor in frame.columns.get_level_values(-1):
                frame = frame.xs(vendor, axis=1, level=-1)
            elif len(set(frame.columns.get_level_values(-1))) == 1:
                frame = frame.droplevel(-1, axis=1)
            else:
                raise ResearchProviderError("unexpected MultiIndex layout")
        normalized = frame.rename(
            columns={str(c): str(c).strip().lower().replace(" ", "_") for c in frame.columns}
        )
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(normalized.columns):
            raise ResearchProviderError("invalid payload columns")
        return normalized

    def download(self, symbol: str, start: date, end: date) -> ResearchDownload:
        if start >= end:
            raise ValueError("start must precede end")
        vendor = self.vendor_symbol(symbol)
        frame = self.cache.load(symbol, start, end, self.price_mode) if self.cache else None
        if frame is None:
            frame = self._fetch(vendor, start, end)
            if frame.empty:
                raise SymbolDataUnavailable("SYMBOL_DATA_UNAVAILABLE")
            if self.cache:
                try:
                    self.cache.save(symbol, start, end, self.price_mode, frame)
                except OSError:
                    pass
        return self._convert(symbol, start, end, frame)

    def download_intraday(
        self, symbol: str, start: date, end: date, timeframe: Timeframe
    ) -> ResearchDownload:
        intervals = {
            Timeframe.M5: "5m",
            Timeframe.M15: "15m",
            Timeframe.M30: "30m",
            Timeframe.M60: "60m",
        }
        if timeframe not in intervals:
            raise ValueError("unsupported intraday timeframe")
        vendor = self.vendor_symbol(symbol)
        frame = self._fetch(vendor, start, end, intervals[timeframe])
        if frame.empty:
            raise SymbolDataUnavailable("SYMBOL_DATA_UNAVAILABLE")
        return self._convert(symbol, start, end, frame, timeframe=timeframe)

    def download_many_intraday(
        self,
        symbols: list[str],
        start: date,
        end: date,
        timeframe: Timeframe = Timeframe.M15,
        batch_size: int = 25,
    ) -> tuple[dict[str, ResearchDownload], dict[str, str]]:
        intervals = {
            Timeframe.M5: "5m",
            Timeframe.M15: "15m",
            Timeframe.M30: "30m",
            Timeframe.M60: "60m",
        }
        if timeframe not in intervals or batch_size < 1:
            raise ValueError("unsupported timeframe or batch size")
        results: dict[str, ResearchDownload] = {}
        failures: dict[str, str] = {}
        ordered = sorted(dict.fromkeys(symbols))
        for offset in range(0, len(ordered), batch_size):
            batch = ordered[offset : offset + batch_size]
            try:
                vendors = " ".join(self.vendor_symbol(symbol) for symbol in batch)
                raw = self._fetch(vendors, start, end, intervals[timeframe])
                for symbol in batch:
                    try:
                        individual = self._flatten(raw, self.vendor_symbol(symbol))
                        results[symbol] = self._convert(
                            symbol, start, end, individual, timeframe=timeframe
                        )
                    except ResearchProviderError as exc:
                        failures[symbol] = str(exc)
            except ResearchProviderError:
                for symbol in batch:
                    try:
                        results[symbol] = self.download_intraday(symbol, start, end, timeframe)
                    except ResearchProviderError as exc:
                        failures[symbol] = str(exc)
        return results, failures

    def _convert(
        self,
        symbol: str,
        start: date,
        end: date,
        frame: pd.DataFrame,
        timeframe: Timeframe = Timeframe.D1,
    ) -> ResearchDownload:
        vendor = self.vendor_symbol(symbol)
        frame = self._flatten(frame, vendor)
        received = datetime.now(UTC)
        quality = SymbolQuality(symbol=symbol, bars_received=len(frame))
        quality.duplicates = int(frame.index.duplicated(keep="first").sum())
        frame = frame.loc[~frame.index.duplicated(keep="first")].sort_index()
        bars: list[CanonicalBar] = []
        for stamp, row in frame.iterrows():
            try:
                timestamp = pd.Timestamp(stamp)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.tz_localize("Europe/Istanbul")
                timestamp = timestamp.tz_convert("UTC")
                fields = ("open", "high", "low", "close", "volume")
                if any(pd.isna(row[c]) for c in ("open", "high", "low", "close", "volume")):
                    quality.invalid_reason("NAN_OHLCV")
                    continue
                try:
                    values = [decimal_from_vendor(row[c]) for c in fields]
                except ValueError:
                    quality.invalid_reason("INVALID_NUMERIC")
                    continue
                bar = CanonicalBar(
                    symbol=symbol,
                    timestamp=timestamp.to_pydatetime(),
                    timeframe=timeframe,
                    open=values[0],
                    high=values[1],
                    low=values[2],
                    close=values[3],
                    volume=values[4],
                    provider=self.metadata.provider_id,
                    received_at=received,
                    is_adjusted=self.price_mode == "adjusted",
                    adjustment_type=(
                        "YFINANCE_AUTO_ADJUST" if self.price_mode == "adjusted" else None
                    ),
                    quality_flags=self.mandatory_flags,
                )
                if min(bar.open, bar.high, bar.low, bar.close) <= Decimal("0"):
                    quality.invalid_reason("NON_POSITIVE_PRICE")
                    continue
                if bar.volume < 0:
                    quality.invalid_reason("NEGATIVE_VOLUME")
                    continue
                if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
                    quality.invalid_reason("OHLC_INCONSISTENCY")
                    continue
                bars.append(bar)
            except (TypeError, ValueError):
                quality.invalid_reason("TIMESTAMP_ERROR")
        quality.bars_valid = len(bars)
        quality.zero_volume = sum(bar.volume == 0 for bar in bars)
        quality.large_gaps = sum(
            abs(current.open / previous.close - 1) > Decimal("0.25")
            for previous, current in zip(bars, bars[1:], strict=False)
        )
        if bars:
            quality.first_timestamp, quality.last_timestamp = bars[0].timestamp, bars[-1].timestamp
            tolerance = timedelta(days=7)
            incomplete_start = bars[0].timestamp.date() > start + tolerance
            incomplete_end = bars[-1].timestamp.date() < end - tolerance
            if incomplete_start or incomplete_end:
                quality.flags.append(QualityFlag.DATA_RANGE_INCOMPLETE.value)
        else:
            raise SymbolDataUnavailable("SYMBOL_DATA_UNAVAILABLE")
        return ResearchDownload(tuple(bars), quality, start, end)

    def download_many(
        self, symbols: list[str], start: date, end: date, batch_size: int = 25
    ) -> tuple[dict[str, ResearchDownload], dict[str, str]]:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        results: dict[str, ResearchDownload] = {}
        failures: dict[str, str] = {}
        ordered = sorted(dict.fromkeys(symbols))
        uncached: list[str] = []
        for symbol in ordered:
            cached = self.cache.load(symbol, start, end, self.price_mode) if self.cache else None
            if cached is None:
                uncached.append(symbol)
            else:
                try:
                    results[symbol] = self._convert(symbol, start, end, cached)
                except ResearchProviderError:
                    uncached.append(symbol)
        for offset in range(0, len(uncached), batch_size):
            batch = uncached[offset : offset + batch_size]
            try:
                vendors = " ".join(self.vendor_symbol(symbol) for symbol in batch)
                raw = self._fetch(vendors, start, end) if len(batch) > 1 else None
                if len(batch) > 1 and (raw is None or not isinstance(raw.columns, pd.MultiIndex)):
                    raise ResearchProviderError("unexpected batch layout")
                for symbol in batch:
                    try:
                        if raw is not None:
                            individual = self._flatten(raw, self.vendor_symbol(symbol))
                            if self.cache:
                                try:
                                    self.cache.save(symbol, start, end, self.price_mode, individual)
                                except OSError:
                                    pass
                            results[symbol] = self._convert(symbol, start, end, individual)
                        else:
                            individual = self._fetch(self.vendor_symbol(symbol), start, end)
                            if individual.empty:
                                raise SymbolDataUnavailable("SYMBOL_DATA_UNAVAILABLE")
                            results[symbol] = self._convert(symbol, start, end, individual)
                    except ResearchProviderError as exc:
                        failures[symbol] = str(exc)
            except ResearchProviderError:
                for symbol in batch:
                    try:
                        results[symbol] = self.download(symbol, start, end)
                    except ResearchProviderError as exc:
                        failures[symbol] = str(exc)
        return results, failures
