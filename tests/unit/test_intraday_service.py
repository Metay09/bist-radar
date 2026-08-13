from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.data.research_repository import ResearchRepository
from app.database.base import Base, MarketBarRow
from app.intraday.repository import IntradayRepository
from app.intraday.service import IntradayResearchService, safe_intraday_cycle


def service_fixture() -> tuple[IntradayResearchService, IntradayRepository]:
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    sessions = sessionmaker(bind=db, expire_on_commit=False)
    start = datetime(2026, 1, 1, 7, tzinfo=UTC)
    with sessions.begin() as session:
        for index in range(80):
            close = 100 + index * 0.2
            session.add(
                MarketBarRow(
                    symbol="ASELS",
                    timestamp=start + timedelta(minutes=15 * index),
                    open=close - 0.1,
                    high=close + 0.5,
                    low=close - 0.5,
                    close=close,
                    volume=float(1000 + index * 100),
                    timeframe="15m",
                    provider_id="yfinance-research",
                    received_at=start + timedelta(minutes=15 * index + 20),
                )
            )
    repository = IntradayRepository(sessions)
    return IntradayResearchService(sessions, repository, ResearchRepository(sessions)), repository


def test_scan_and_restart_outcome_tracking() -> None:
    service, repository = service_fixture()
    now = datetime(2026, 1, 2, 3, 15, tzinfo=UTC)
    result = service.run(now)
    assert result["evaluated_symbols"] == 1
    assert result["candidates"]
    assert repository.signals()
    assert service.update_outcomes(now + timedelta(hours=3)) == 1
    restarted = IntradayResearchService(
        repository.session_factory,
        IntradayRepository(repository.session_factory),
        ResearchRepository(repository.session_factory),
    )
    assert restarted.update_outcomes(now + timedelta(hours=4)) == 1


def test_stale_symbol_is_audited_and_not_scored() -> None:
    service, _ = service_fixture()
    result = service.run(datetime(2026, 1, 2, 8, tzinfo=UTC))
    assert result["candidates"] == []
    assert result["stage_a_rejections"] == {"STALE": 1}


def test_empty_service_and_safe_failure(monkeypatch: object) -> None:
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    sessions = sessionmaker(bind=db)
    service = IntradayResearchService(
        sessions, IntradayRepository(sessions), ResearchRepository(sessions)
    )
    assert service.run(datetime(2026, 1, 1, tzinfo=UTC))["candidates"] == []
    # The production wrapper deliberately absorbs research-only failures.
    safe_intraday_cycle()
