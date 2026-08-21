from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.data.intraday_research import IntradayResearchBackfill, prioritized_5m_symbols
from app.database.base import Base, DataFreshnessObservationRow


def test_5m_priority_is_bounded_and_prefers_active_then_shortlist() -> None:
    selected = prioritized_5m_symbols(
        ["THYAO", "AKBNK", "EREGL"], ["EREGL", "TUPRS"], ["ASELS"], limit=4
    )
    assert selected == ["ASELS", "EREGL", "TUPRS", "THYAO"]


def test_5m_priority_rejects_unbounded_request() -> None:
    with pytest.raises(ValueError):
        prioritized_5m_symbols([], [], [], limit=0)


def test_latency_timestamps_must_be_monotonic() -> None:
    close = datetime(2026, 8, 14, 10, tzinfo=UTC)
    available = close + timedelta(seconds=30)
    persisted = available + timedelta(seconds=2)
    assert close <= available <= persisted


def test_historical_backfill_is_never_counted_as_live_latency() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    provider = SimpleNamespace(metadata=SimpleNamespace(provider_id="yfinance-research"))
    service = IntradayResearchBackfill(provider=provider, session_factory=sessions)
    received = datetime(2026, 8, 14, 15, tzinfo=UTC)
    historical = SimpleNamespace(
        symbol="THYAO",
        timestamp=received - timedelta(days=2, minutes=5),
        received_at=received,
    )
    recent = SimpleNamespace(
        symbol="THYAO",
        timestamp=received - timedelta(minutes=10),
        received_at=received,
    )
    assert service.record_many_5m_availability([historical, recent], received) == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(DataFreshnessObservationRow)) == 1
