from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from app.database.base import SessionLocal, WorkerStateRow


@contextmanager
def job_lock(job_name: str, session_factory: Any = SessionLocal) -> Iterator[bool]:
    """PostgreSQL advisory lock; SQLite test fallback uses persistent RUNNING state."""
    with session_factory() as session:
        dialect = session.bind.dialect.name
        if dialect == "postgresql":
            acquired = bool(
                session.scalar(
                    text("SELECT pg_try_advisory_lock(hashtext(:name))"), {"name": job_name}
                )
            )
        else:
            state = session.get(WorkerStateRow, job_name)
            acquired = state is None or state.status != "RUNNING"
        if not acquired:
            yield False
            return
        state = session.get(WorkerStateRow, job_name)
        if state is None:
            state = WorkerStateRow(job_name=job_name, status="RUNNING", detail={})
            session.add(state)
        state.status, state.last_started_at = "RUNNING", datetime.now(UTC)
        session.commit()
        try:
            yield True
        finally:
            state.status = "IDLE"
            session.commit()
            if dialect == "postgresql":
                session.execute(
                    text("SELECT pg_advisory_unlock(hashtext(:name))"), {"name": job_name}
                )


def mark_job(
    job_name: str,
    success: bool,
    detail: dict[str, object],
    last_bar: datetime | None = None,
    session_factory: Any = SessionLocal,
) -> None:
    now = datetime.now(UTC)
    with session_factory.begin() as session:
        state = session.get(WorkerStateRow, job_name)
        if state is None:
            state = WorkerStateRow(job_name=job_name, status="UNKNOWN", detail={})
            session.add(state)
        state.status = "HEALTHY" if success else "DEGRADED"
        state.last_success_at = now if success else state.last_success_at
        state.last_failure_at = now if not success else state.last_failure_at
        state.last_processed_bar = last_bar or state.last_processed_bar
        state.detail = detail
