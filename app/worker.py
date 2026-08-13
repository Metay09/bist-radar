import logging
import time
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.api.dashboard import market_open
from app.api.service import service
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.base import EventRow, SessionLocal
from app.intraday.ingestion import IntradayDataUpdater
from app.intraday.service import safe_intraday_cycle
from app.notifications.alerts import AlertCandidate, AlertDispatcher, TelegramClient
from app.operations.jobs import job_lock, mark_job


def dispatch_report_alerts(report: dict[str, object], now: datetime) -> int:
    settings = get_settings()
    client = TelegramClient(
        settings.telegram_bot_token, settings.telegram_chat_id, settings.telegram_enabled
    )
    dispatcher = AlertDispatcher()
    rows = report.get("candidates", [])
    dispatched = 0
    if not isinstance(rows, list):
        return 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        stamp = row.get("timestamp")
        if not isinstance(stamp, datetime):
            continue
        alert = AlertCandidate(
            symbol=str(row["symbol"]),
            score=int(row["radar_score"]),
            classification=str(row["classification"]),
            price=float(row["price"]),
            rvol=float(row["rvol"]),
            early_momentum=int(row["early_momentum_score"]),
            data_timestamp=stamp,
            disposition=str(row.get("disposition", "SIGNAL_CREATED")),
        )
        dispatcher.dispatch(
            alert,
            client,
            now,
            max_age_minutes=settings.max_alert_data_age_minutes,
            market_open=market_open(now),
            cooldown_minutes=settings.telegram_cooldown_minutes,
            upgrade_points=settings.telegram_upgrade_points,
        )
        dispatched += 1
    return dispatched


def run() -> None:
    configure_logging()
    log = logging.getLogger(__name__)
    next_scan = datetime.min.replace(tzinfo=UTC)
    while True:
        now = datetime.now(UTC)
        if now >= next_scan:
            with job_lock("autonomous_market_scan") as acquired:
                if acquired:
                    try:
                        log.info("market_scan_started")
                        results = service.scan()
                        with SessionLocal.begin() as session:
                            session.add(
                                EventRow(
                                    event="market_scan_finished",
                                    created_at=now,
                                    detail={"count": len(results)},
                                )
                            )
                        try:
                            update = IntradayDataUpdater().run(now)
                        except Exception as provider_exc:
                            mark_job(
                                "intraday_data_update",
                                False,
                                {"reason": type(provider_exc).__name__},
                            )
                            raise
                        mark_job(
                            "intraday_data_update",
                            update.provider_success,
                            {
                                "requested_symbols": update.requested_symbols,
                                "found_symbols": update.found_symbols,
                                "downloaded_bars": update.downloaded_bars,
                                "completed_bars": update.completed_bars,
                                "inserted_bars": update.inserted_bars,
                                "duplicate_bars": update.duplicate_bars,
                                "failures": update.failures,
                                "reason": update.reason,
                                "latest_provider_bar": (
                                    update.latest_provider_bar.isoformat()
                                    if update.latest_provider_bar
                                    else None
                                ),
                                "latest_persisted_bar": (
                                    update.latest_persisted_bar.isoformat()
                                    if update.latest_persisted_bar
                                    else None
                                ),
                            },
                            update.latest_persisted_bar,
                        )
                        if not update.provider_success and market_open(now):
                            raise RuntimeError(update.reason or "INTRADAY_DATA_UPDATE_FAILED")
                        report = safe_intraday_cycle()
                        if report is None:
                            raise RuntimeError("INTRADAY_SCAN_FAILED")
                        report_stamp = report.get("data_timestamp")
                        report_candidates = report.get("candidates", [])
                        mark_job(
                            "intraday_radar_scan",
                            True,
                            {
                                "candidates": (
                                    len(report_candidates)
                                    if isinstance(report_candidates, list)
                                    else 0
                                )
                            },
                            report_stamp if isinstance(report_stamp, datetime) else None,
                        )
                        if report:
                            dispatch_report_alerts(report, now)
                        mark_job("autonomous_market_scan", True, {"count": len(results)})
                        log.info("market_scan_finished count=%d", len(results))
                    except Exception as exc:
                        mark_job("autonomous_market_scan", False, {"error": type(exc).__name__})
                        log.warning("autonomous_cycle_failed error=%s", type(exc).__name__)
            # Provider-friendly: run after a 15m boundary plus a small availability buffer.
            local = now.astimezone(ZoneInfo("Europe/Istanbul"))
            minutes = 15 - (local.minute % 15)
            next_scan = now + timedelta(minutes=minutes, seconds=30 - local.second)
        time.sleep(30)


if __name__ == "__main__":
    run()
