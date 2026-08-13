from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.intraday.core import IntradaySnapshot
from app.intraday.outcomes import HorizonOutcome, LabelStatus
from app.intraday.repository import IntradayRepository


@pytest.fixture
def repository() -> IntradayRepository:
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    return IntradayRepository(sessionmaker(bind=db, expire_on_commit=False))


def snapshot(stamp: datetime, score: int = 75) -> IntradaySnapshot:
    return IntradaySnapshot(
        f"radar-intraday-v1:ASELS:{stamp.isoformat()}",
        "ASELS",
        stamp,
        "15m",
        100,
        score,
        "CANDIDATE",
        55,
        1,
        0.2,
        1.8,
        "HISTORICAL_BAR_SLOT",
        2,
        1,
        1,
        1,
        1,
        -0.2,
        None,
        0.5,
        0.01,
        "NEUTRAL",
        "UPTREND",
        100,
        900,
        75,
    )


def test_signal_cooldown_upgrade_and_immutability(repository: IntradayRepository) -> None:
    stamp = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert repository.save_signal(snapshot(stamp), 60, 5) == "SIGNAL_CREATED"
    assert repository.save_signal(snapshot(stamp), 60, 5) == "REJECTED_COOLDOWN"
    assert (
        repository.save_signal(snapshot(stamp + timedelta(minutes=15), 84), 60, 5)
        == "SIGNAL_UPGRADED"
    )
    stored = repository.signals()
    assert len(stored) == 2
    assert stored[0]["radar_score"] == 84
    assert stored[1]["radar_score"] == 75
    assert repository.save_signal(snapshot(stamp), -1, 5) == "REJECTED_DUPLICATE"


def test_outcome_persistence_update_and_restart(repository: IntradayRepository) -> None:
    stamp = datetime(2026, 1, 1, 10, tzinfo=UTC)
    signal = snapshot(stamp)
    repository.save_signal(signal, 60, 5)
    repository.save_outcomes(
        signal.signal_id, {"15m": HorizonOutcome("15m", LabelStatus.LABEL_PENDING)}
    )
    assert repository.status()["pending"] == 1
    restarted = IntradayRepository(repository.session_factory)
    restarted.save_outcomes(
        signal.signal_id,
        {"15m": HorizonOutcome("15m", LabelStatus.LABEL_AVAILABLE, forward_return=0.01)},
    )
    assert restarted.outcomes()[0]["forward_return"] == 0.01
    summary = restarted.outcome_summaries()[0]
    assert summary["forward_return_15m"] == 0.01
    assert summary.get("maximum_favorable_excursion") is None
    assert restarted.status()["fully_labeled"] == 1
    with pytest.raises(ValueError, match="unknown signal"):
        restarted.save_outcomes("missing", {})


def test_empty_shadow_persistence_views(repository: IntradayRepository) -> None:
    assert repository.models() == []
    assert repository.predictions() == []
    assert repository.evaluations() == []
