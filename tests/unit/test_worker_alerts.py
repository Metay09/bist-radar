from datetime import UTC, datetime
from types import SimpleNamespace

from app import worker


def test_worker_dispatches_valid_candidates_and_skips_invalid(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[object] = []
    monkeypatch.setattr(
        worker,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token=None,
            telegram_chat_id=None,
            telegram_enabled=False,
            max_alert_data_age_minutes=45,
            telegram_cooldown_minutes=60,
            telegram_upgrade_points=5,
        ),
    )

    class Dispatcher:
        def dispatch(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            calls.append((args, kwargs))

    monkeypatch.setattr(worker, "AlertDispatcher", Dispatcher)
    now = datetime(2026, 8, 13, 10, tzinfo=UTC)
    row = {
        "symbol": "ASELS",
        "radar_score": 90,
        "classification": "VERY_STRONG_CANDIDATE",
        "price": 100,
        "rvol": 2,
        "early_momentum_score": 80,
        "timestamp": now,
    }
    assert (
        worker.dispatch_report_alerts({"candidates": [row, "bad", row | {"timestamp": "bad"}]}, now)
        == 1
    )
    assert len(calls) == 1
    assert worker.dispatch_report_alerts({"candidates": "bad"}, now) == 0
