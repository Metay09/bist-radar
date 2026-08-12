from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base, NotificationEventRow, WorkerStateRow
from app.notifications.alerts import (
    AlertCandidate,
    AlertDispatcher,
    TelegramClient,
    alert_eligibility,
    format_candidate_alert,
)
from app.operations.jobs import job_lock, mark_job


def sessions():  # type: ignore[no-untyped-def]
    db = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db)
    return sessionmaker(bind=db, expire_on_commit=False)


def candidate(now: datetime, score: int = 90) -> AlertCandidate:
    return AlertCandidate("ASELS", score, "VERY_STRONG_CANDIDATE", 200, 2.5, 88, now)


def test_formatting_and_stale_market_closed_suppression() -> None:
    now = datetime(2026, 8, 13, 10, tzinfo=UTC)
    text = format_candidate_alert(candidate(now), "Henüz yeterli veri yok")
    assert "BIST RADAR" in text and "RESEARCH / PAPER ONLY" in text and "2.50x" in text
    assert alert_eligibility(candidate(now - timedelta(hours=2)), now, 45, True) == (
        False,
        "ALERT_SUPPRESSED_STALE_DATA",
    )
    assert alert_eligibility(candidate(now), now, 45, False)[1] == "ALERT_SUPPRESSED_MARKET_CLOSED"
    weak = AlertCandidate("ASELS", 60, "WATCH", 1, 1, 1, now)
    assert alert_eligibility(weak, now, 45, True)[1] == "ALERT_SUPPRESSED_CLASS"


def test_notification_dedup_cooldown_and_persistence() -> None:
    factory = sessions()
    dispatch = AlertDispatcher(factory)
    now = datetime(2026, 8, 13, 10, tzinfo=UTC)
    client = TelegramClient(None, None, False)
    assert (
        dispatch.dispatch(
            candidate(now),
            client,
            now,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "TELEGRAM_UNCONFIGURED"
    )
    assert (
        dispatch.dispatch(
            candidate(now),
            client,
            now,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "ALERT_SUPPRESSED_DUPLICATE"
    )
    with factory() as session:
        row = session.query(NotificationEventRow).one()
        row.status, row.score = "SENT", 90
        session.commit()
    later = candidate(now + timedelta(minutes=15), 92)
    assert (
        dispatch.dispatch(
            later,
            client,
            later.data_timestamp,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "ALERT_SUPPRESSED_COOLDOWN"
    )
    assert len(AlertDispatcher(factory).session_factory().query(NotificationEventRow).all()) == 2

    # A new completed bar may alert again after the configured quiet period.
    after_cooldown = candidate(now + timedelta(minutes=61), 92)
    assert (
        dispatch.dispatch(
            after_cooldown,
            client,
            after_cooldown.data_timestamp,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "TELEGRAM_UNCONFIGURED"
    )


def test_telegram_send_and_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    client = TelegramClient("secret", "chat", True)
    called: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(
        httpx, "post", lambda url, **kwargs: called.update(url=url, kwargs=kwargs) or Response()
    )
    assert client.send("safe") and "secret" in str(called["url"])
    assert not TelegramClient(None, None, True).send("ignored")


def test_dispatch_send_success_and_network_failure(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    factory = sessions()
    now = datetime(2026, 8, 13, 10, tzinfo=UTC)
    client = TelegramClient("token", "chat", True)
    monkeypatch.setattr(client, "send", lambda message: bool(message))
    assert (
        AlertDispatcher(factory).dispatch(
            candidate(now),
            client,
            now,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "SENT"
    )
    failing = TelegramClient("token", "chat", True)

    def fail(_: str) -> bool:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(failing, "send", fail)
    later = candidate(now + timedelta(minutes=15), 96)
    assert (
        AlertDispatcher(factory).dispatch(
            later,
            failing,
            later.data_timestamp,
            max_age_minutes=45,
            market_open=True,
            cooldown_minutes=60,
            upgrade_points=5,
        )
        == "TELEGRAM_SEND_FAILED"
    )


def test_job_lock_restart_state_and_duplicate_lock() -> None:
    factory = sessions()
    with job_lock("scan", factory) as acquired:
        assert acquired
        with factory() as session:
            assert session.get(WorkerStateRow, "scan").status == "RUNNING"
        with job_lock("scan", factory) as duplicate:
            assert not duplicate
    mark_job("scan", True, {"bars": 10}, session_factory=factory)
    with factory() as session:
        state = session.get(WorkerStateRow, "scan")
        assert state.status == "HEALTHY" and state.last_success_at is not None
    with job_lock("scan", factory) as restarted:
        assert restarted
    mark_job("new-job", False, {"error": "timeout"}, session_factory=factory)
    with factory() as session:
        assert session.get(WorkerStateRow, "new-job").last_failure_at is not None
