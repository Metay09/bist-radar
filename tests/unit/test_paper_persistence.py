from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.database.base import Base
from app.paper.ledger import PaperLedger
from app.paper.repository import (
    DuplicateOpenTradeError,
    PaperTradePersistenceError,
    PaperTradeRepository,
)


@pytest.fixture
def repository(tmp_path: object) -> PaperTradeRepository:
    db_path = tmp_path / "paper.db"  # type: ignore[operator]
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    return PaperTradeRepository(sessionmaker(bind=engine, expire_on_commit=False))


def values() -> tuple[datetime, Decimal, Decimal, Decimal, Decimal, Decimal]:
    return (
        datetime.now(UTC),
        Decimal("10"),
        Decimal("100"),
        Decimal("9"),
        Decimal("11.5"),
        Decimal("12.5"),
    )


def test_open_and_closed_trade_survive_repository_restart(repository: PaperTradeRepository) -> None:
    ledger = PaperLedger()
    when, entry, size, stop, target_1, target_2 = values()
    opened = repository.open(ledger, "TEST", when, entry, size, stop, target_1, target_2)
    restarted = PaperTradeRepository(repository.session_factory)
    assert restarted.list()[0].trade_id == opened.trade_id
    restarted.close(ledger, opened.trade_id, when + timedelta(days=1), Decimal("12"), "target")
    closed = PaperTradeRepository(repository.session_factory).list()[0]
    assert closed.exit_reason == "target" and closed.net_return > 0


def test_duplicate_open_trade_is_atomically_rejected(repository: PaperTradeRepository) -> None:
    ledger = PaperLedger()
    args = values()
    repository.open(ledger, "TEST", *args)
    with pytest.raises(DuplicateOpenTradeError):
        repository.open(ledger, "TEST", *args)
    assert len(repository.list()) == 1


def test_repository_close_errors_and_performance(repository: PaperTradeRepository) -> None:
    ledger = PaperLedger()
    with pytest.raises(KeyError):
        repository.close(ledger, "missing", datetime.now(UTC), Decimal("10"), "none")
    when, entry, size, stop, target_1, target_2 = values()
    opened = repository.open(ledger, "PERF", when, entry, size, stop, target_1, target_2)
    repository.close(ledger, opened.trade_id, when + timedelta(days=1), Decimal("12"), "target")
    performance = repository.performance()
    assert performance["number_of_trades"] == 1 and performance["win_rate"] == 1
    with pytest.raises(ValueError):
        repository.close(ledger, opened.trade_id, when + timedelta(days=2), Decimal("12"), "again")


def test_invalid_exit_boundaries() -> None:
    ledger = PaperLedger()
    when, entry, size, stop, t1, t2 = values()
    trade = ledger.open("EXIT", when, entry, size, stop, t1, t2)
    with pytest.raises(ValueError):
        ledger.close(trade.trade_id, when - timedelta(seconds=1), Decimal("10"), "early")
    with pytest.raises(ValueError):
        ledger.close(trade.trade_id, when, Decimal("0"), "zero")


def test_transaction_failure_leaves_no_partial_trade(tmp_path: object) -> None:
    db_path = tmp_path / "broken.db"  # type: ignore[operator]
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    @event.listens_for(Session, "before_flush")
    def fail_flush(session: Session, flush_context: object, instances: object) -> None:
        if session.bind is engine:
            raise OperationalError("insert", {}, Exception("forced"))

    repository = PaperTradeRepository(factory)
    ledger = PaperLedger()
    with pytest.raises(PaperTradePersistenceError):
        repository.open(ledger, "FAIL", *values())
    event.remove(Session, "before_flush", fail_flush)
    assert repository.list() == []


@pytest.mark.parametrize(("commission", "slippage"), [("0", "0"), ("10000", "0"), ("0", "10000")])
def test_commission_and_slippage_edges(commission: str, slippage: str) -> None:
    ledger = PaperLedger(Decimal(commission), Decimal(slippage))
    when, entry, size, stop, t1, t2 = values()
    trade = ledger.open("EDGE", when, entry, size, stop, t1, t2)
    closed = ledger.close(trade.trade_id, when + timedelta(seconds=1), Decimal("12"), "test")
    assert closed.fees >= 0 and closed.slippage >= 0


def test_negative_cost_configuration_rejected() -> None:
    ledger = PaperLedger(Decimal("-1"), Decimal("0"))
    with pytest.raises(ValueError):
        ledger.open("BAD", *values())
