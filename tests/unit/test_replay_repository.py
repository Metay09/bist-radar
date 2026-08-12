from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtest.replay_models import EquityPoint, ExecutedTrade, ExecutionState, ReplayResult
from app.backtest.repository import ReplayRepository, jsonable
from app.database.base import Base


def repository(tmp_path: Path) -> ReplayRepository:
    engine = create_engine(f"sqlite:///{tmp_path / 'replay.db'}")
    Base.metadata.create_all(engine)
    return ReplayRepository(sessionmaker(bind=engine, expire_on_commit=False))


def result() -> ReplayResult:
    now = datetime.now(UTC)
    trade = ExecutedTrade(
        "s",
        "t",
        "key",
        "paper-default",
        "radar-v1",
        "X",
        now,
        now,
        Decimal("10"),
        Decimal("9"),
        Decimal("11"),
        Decimal("12"),
        Decimal("1"),
        Decimal("100"),
        "NEXT_BAR_OPEN",
        ExecutionState.CLOSED,
        now,
        Decimal("11"),
        "TARGET",
        Decimal("1"),
        Decimal("0"),
        Decimal("0"),
        Decimal("1"),
        Decimal("101"),
        Decimal("1"),
    )
    return ReplayResult(
        "run",
        Decimal("100"),
        Decimal("101"),
        [trade],
        [],
        [EquityPoint(now, Decimal("101"), Decimal("101"), Decimal("0"))],
        "hash",
        now,
    )


def test_replay_repository_persistence_resume_and_idempotency(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    item = result()
    repo.save(item, {"risk": "0.75"})
    repo.save(item, {"risk": "changed"})
    stored = repo.run("run")
    assert stored and stored["status"] == "COMPLETED" and stored["config_hash"] == "hash"
    assert repo.run("missing") is None
    assert len(repo.trades("run")) == 1
    equity = repo.equity("run")
    assert equity[0]["equity"] == "101.00000000" and len(equity) == 1


def test_jsonable_types() -> None:
    now = datetime.now(UTC)
    converted = jsonable(
        {
            "decimal": Decimal("1.2"),
            "time": now,
            "state": ExecutionState.OPEN,
            "items": (Decimal("1"),),
            "infinite": float("inf"),
        }
    )
    assert converted == {
        "decimal": "1.2",
        "time": now.isoformat(),
        "state": "OPEN",
        "items": ["1"],
        "infinite": None,
    }
