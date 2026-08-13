from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.backtest.replay_models import Timeframe
from app.core.config import get_settings
from app.data.research import load_universe
from app.data.research_repository import ResearchRepository
from app.data.yfinance_provider import YFinanceResearchProvider
from app.database.base import MarketBarRow, SessionLocal
from app.intraday.core import completed_intraday_bar


@dataclass(frozen=True)
class IntradayUpdateResult:
    provider_success: bool
    requested_symbols: int
    found_symbols: int
    downloaded_bars: int
    completed_bars: int
    inserted_bars: int
    duplicate_bars: int
    latest_provider_bar: datetime | None
    latest_completed_bar: datetime | None
    latest_persisted_bar: datetime | None
    failures: int
    reason: str | None = None


class IntradayDataUpdater:
    """Acquire and persist canonical research bars before scanning persisted data."""

    def __init__(
        self,
        provider: YFinanceResearchProvider | None = None,
        repository: ResearchRepository | None = None,
        session_factory: Any = SessionLocal,
        universe_path: Path = Path("config/universes/bist100.csv"),
    ) -> None:
        settings = get_settings()
        self.provider = provider or YFinanceResearchProvider(
            price_mode=settings.research_price_mode,
            attempts=settings.research_download_attempts,
        )
        self.repository = repository or ResearchRepository(session_factory)
        self.session_factory = session_factory
        self.universe_path = universe_path

    def run(self, now: datetime | None = None) -> IntradayUpdateResult:
        current = now or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("timezone-aware now required")
        settings = get_settings()
        universe = load_universe(self.universe_path)
        symbols = [member.symbol for member in universe.members if member.active]
        local_day = current.astimezone(ZoneInfo("Europe/Istanbul")).date()
        start: date = local_day - timedelta(days=7)
        end: date = local_day + timedelta(days=1)
        results, failures = self.provider.download_many_intraday(
            symbols,
            start,
            end,
            Timeframe.M15,
            settings.research_batch_size,
        )
        downloaded = [bar for result in results.values() for bar in result.bars]
        completed = [
            bar
            for bar in downloaded
            if completed_intraday_bar(bar.timestamp, settings.intraday_scan_minutes, current)
        ]
        latest_provider = max((bar.timestamp for bar in downloaded), default=None)
        latest_completed = max((bar.timestamp for bar in completed), default=None)
        inserted = duplicates = 0
        if completed:
            report: dict[str, object] = {
                "provider": self.provider.metadata.provider_id,
                "flags": ["RESEARCH_ONLY", "UNVERIFIED_SOURCE", "INTRADAY_RANGE_LIMITED"],
                "timeframe": "15m",
                "requested_symbols": len(symbols),
                "found_symbols": len(results),
                "failures": failures,
                "bars": len(completed),
                "actual_start": min(bar.timestamp for bar in completed),
                "actual_end": latest_completed,
                "universe_hash": universe.snapshot_hash,
            }
            _, inserted, duplicates = self.repository.import_dataset(completed, report, report)
        with self.session_factory() as session:
            latest_persisted = session.scalar(
                select(MarketBarRow.timestamp)
                .where(
                    MarketBarRow.provider_id == self.provider.metadata.provider_id,
                    MarketBarRow.timeframe == "15m",
                )
                .order_by(MarketBarRow.timestamp.desc())
                .limit(1)
            )
        persisted_utc = (
            latest_persisted.replace(tzinfo=UTC)
            if latest_persisted is not None and latest_persisted.tzinfo is None
            else latest_persisted
        )
        fresh = persisted_utc is not None and (
            current.astimezone(UTC) - persisted_utc.astimezone(UTC)
        ) <= timedelta(minutes=settings.intraday_stale_minutes)
        reason = None
        if not results:
            reason = "PROVIDER_EMPTY"
        elif not completed:
            reason = "NO_COMPLETED_BARS"
        elif not fresh:
            reason = "PROVIDER_OLD_BARS_ONLY"
        return IntradayUpdateResult(
            fresh,
            len(symbols),
            len(results),
            len(downloaded),
            len(completed),
            inserted,
            duplicates,
            latest_provider,
            latest_completed,
            persisted_utc,
            len(failures),
            reason,
        )
