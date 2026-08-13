from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.backtest.replay_models import Timeframe
from app.data.canonical import CanonicalBar
from app.data.research import SymbolQuality
from app.data.research_repository import ResearchRepository
from app.data.yfinance_provider import ResearchDownload, YFinanceResearchProvider
from app.database.base import Base, MarketBarRow
from app.intraday.ingestion import IntradayDataUpdater


def bar(symbol: str, timestamp: datetime) -> CanonicalBar:
    return CanonicalBar(
        symbol=symbol,
        timestamp=timestamp,
        timeframe=Timeframe.M15,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1000"),
        provider="yfinance-research",
        received_at=timestamp + timedelta(minutes=20),
        is_adjusted=True,
    )


class Provider:
    metadata = YFinanceResearchProvider.metadata

    def __init__(self, bars: list[CanonicalBar]) -> None:
        self.bars = bars

    def download_many_intraday(self, symbols, start, end, timeframe, batch_size):  # type: ignore[no-untyped-def]
        quality = SymbolQuality("ASTOR", bars_received=len(self.bars), bars_valid=len(self.bars))
        return (
            {"ASTOR": ResearchDownload(tuple(self.bars), quality, start, end)} if self.bars else {},
            {} if self.bars else {"ASTOR": "SYMBOL_DATA_UNAVAILABLE"},
        )


def setup(tmp_path: Path, bars: list[CanonicalBar]) -> tuple[IntradayDataUpdater, object]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tmp_path.mkdir(parents=True, exist_ok=True)
    universe = tmp_path / "universe.csv"
    universe.write_text(
        "symbol,name,sector,active,source,source_date\nASTOR,Astor,,true,fixture,2026-08-13\n"
    )
    updater = IntradayDataUpdater(
        Provider(bars),
        ResearchRepository(sessions),
        sessions,
        universe,  # type: ignore[arg-type]
    )
    return updater, sessions


def test_today_completed_bar_persists_and_partial_bar_is_excluded(tmp_path: Path) -> None:
    # 12:10 Istanbul == 09:10 UTC. The 11:45 bar is complete; 12:00 is partial.
    now = datetime(2026, 8, 13, 9, 10, tzinfo=UTC)
    updater, sessions = setup(
        tmp_path,
        [
            bar("ASTOR", datetime(2026, 8, 13, 8, 45, tzinfo=UTC)),
            bar("ASTOR", datetime(2026, 8, 13, 9, 0, tzinfo=UTC)),
        ],
    )
    result = updater.run(now)
    assert result.provider_success is True
    assert result.downloaded_bars == 2 and result.completed_bars == 1
    assert result.latest_completed_bar == datetime(2026, 8, 13, 8, 45, tzinfo=UTC)
    with sessions() as session:  # type: ignore[operator]
        stored = session.scalars(select(MarketBarRow)).all()
    assert [row.timestamp.replace(tzinfo=UTC) for row in stored] == [result.latest_completed_bar]


def test_empty_and_old_provider_results_fail_closed(tmp_path: Path) -> None:
    now = datetime(2026, 8, 13, 9, 10, tzinfo=UTC)
    empty, _ = setup(tmp_path / "empty", [])
    assert empty.run(now).reason == "PROVIDER_EMPTY"
    old, _ = setup(tmp_path / "old", [bar("ASTOR", datetime(2026, 8, 12, 14, 45, tzinfo=UTC))])
    result = old.run(now)
    assert result.provider_success is False
    assert result.reason == "PROVIDER_OLD_BARS_ONLY"


def test_istanbul_completed_bar_boundary() -> None:
    from zoneinfo import ZoneInfo

    from app.intraday.core import completed_intraday_bar

    stamp = datetime(2026, 8, 13, 11, 45, tzinfo=ZoneInfo("Europe/Istanbul"))
    assert completed_intraday_bar(stamp, 15, datetime(2026, 8, 13, 9, tzinfo=UTC))
    assert not completed_intraday_bar(
        datetime(2026, 8, 13, 12, 0, tzinfo=ZoneInfo("Europe/Istanbul")),
        15,
        datetime(2026, 8, 13, 9, 10, tzinfo=UTC),
    )
