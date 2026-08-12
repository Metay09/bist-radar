from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database.base import NotificationEventRow, SessionLocal
from app.notifications.telegram import DISCLAIMER


@dataclass(frozen=True)
class AlertCandidate:
    symbol: str
    score: int
    classification: str
    price: float
    rvol: float
    early_momentum: int
    data_timestamp: datetime
    disposition: str = "SIGNAL_CREATED"
    risk_reward: float | None = None


def format_candidate_alert(candidate: AlertCandidate, shadow_status: str) -> str:
    title = "ÇOK GÜÇLÜ ADAY" if candidate.score >= 90 else "GÜÇLÜ ADAY"
    age = max(
        0, (datetime.now(UTC) - candidate.data_timestamp.astimezone(UTC)).total_seconds() / 60
    )
    risk = "Veri yok" if candidate.risk_reward is None else f"1:{candidate.risk_reward:.1f}"
    return "\n".join(
        [
            f"🔥 BIST RADAR — {title}",
            "",
            candidate.symbol,
            f"Radar: {candidate.score}/100",
            f"Fiyat: {candidate.price:g}",
            f"15m RVOL: {candidate.rvol:.2f}x",
            f"Early Momentum: {candidate.early_momentum}",
            f"Risk/Getiri: {risk}",
            "",
            f"Veri zamanı: {candidate.data_timestamp.astimezone(UTC).isoformat()}",
            f"Veri yaşı: {age:.0f} dk",
            "",
            "Shadow:",
            shadow_status,
            "",
            "RESEARCH / PAPER ONLY",
            DISCLAIMER,
        ]
    )


def alert_eligibility(
    candidate: AlertCandidate,
    now: datetime,
    max_age_minutes: int,
    market_open: bool,
) -> tuple[bool, str | None]:
    if not market_open:
        return False, "ALERT_SUPPRESSED_MARKET_CLOSED"
    age = now.astimezone(UTC) - candidate.data_timestamp.astimezone(UTC)
    if age > timedelta(minutes=max_age_minutes) or age.total_seconds() < 0:
        return False, "ALERT_SUPPRESSED_STALE_DATA"
    if candidate.classification not in {"STRONG_CANDIDATE", "VERY_STRONG_CANDIDATE"}:
        return False, "ALERT_SUPPRESSED_CLASS"
    return True, None


class TelegramClient:
    def __init__(self, token: str | None, chat_id: str | None, enabled: bool) -> None:
        self.token, self.chat_id, self.enabled = token, chat_id, enabled

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.token and self.chat_id)

    def send(self, message: str) -> bool:
        if not self.configured:
            return False
        response = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": self.chat_id, "text": message, "disable_web_page_preview": True},
            timeout=10,
        )
        response.raise_for_status()
        return True


class AlertDispatcher:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def dispatch(
        self,
        candidate: AlertCandidate,
        client: TelegramClient,
        now: datetime,
        *,
        max_age_minutes: int,
        market_open: bool,
        cooldown_minutes: int,
        upgrade_points: int,
    ) -> str:
        allowed, reason = alert_eligibility(candidate, now, max_age_minutes, market_open)
        key = (
            f"{candidate.classification}:{candidate.symbol}:"
            f"{candidate.data_timestamp.isoformat()}:{candidate.score}"
        )
        with self.session_factory() as session:
            recent = session.scalar(
                select(NotificationEventRow)
                .where(
                    NotificationEventRow.symbol == candidate.symbol,
                    NotificationEventRow.status == "SENT",
                )
                .order_by(NotificationEventRow.created_at.desc())
                .limit(1)
            )
            recent_created = (
                recent.created_at.replace(tzinfo=UTC)
                if recent and recent.created_at.tzinfo is None
                else recent.created_at
                if recent
                else None
            )
            if (
                recent
                and recent.score is not None
                and recent_created is not None
                and now.astimezone(UTC) - recent_created.astimezone(UTC)
                < timedelta(minutes=cooldown_minutes)
                and candidate.score < recent.score + upgrade_points
            ):
                allowed, reason = False, "ALERT_SUPPRESSED_COOLDOWN"
            row = NotificationEventRow(
                dedup_key=key,
                alert_type=candidate.classification,
                symbol=candidate.symbol,
                signal_time=candidate.data_timestamp,
                score=candidate.score,
                status="PENDING" if allowed else "SUPPRESSED",
                reason=reason,
                created_at=now,
            )
            try:
                session.add(row)
                session.commit()
            except IntegrityError:
                session.rollback()
                return "ALERT_SUPPRESSED_DUPLICATE"
            if not allowed:
                return reason or "ALERT_SUPPRESSED"
            if not client.configured:
                row.status, row.reason = "SUPPRESSED", "TELEGRAM_UNCONFIGURED"
                session.commit()
                return "TELEGRAM_UNCONFIGURED"
            try:
                client.send(format_candidate_alert(candidate, "Henüz yeterli veri yok"))
                row.status, row.sent_at = "SENT", now
                session.commit()
                return "SENT"
            except (httpx.HTTPError, RuntimeError):
                row.status, row.reason = "FAILED", "TELEGRAM_SEND_FAILED"
                session.commit()
                return "TELEGRAM_SEND_FAILED"
