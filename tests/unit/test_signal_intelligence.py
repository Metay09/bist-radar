from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.base import Base, MlFeatureSnapshotRow, MlOutcomeRow, SignalAuditRow
from app.intraday.intelligence import SignalIntelligence
from app.intraday.repository import IntradayRepository
from app.ml import training


def database():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def seed(factory, count: int = 3) -> None:  # type: ignore[no-untyped-def]
    start = datetime(2026, 8, 13, 7, tzinfo=UTC)
    with factory.begin() as session:
        offset = session.query(MlFeatureSnapshotRow).count()
        for index in range(count):
            item = offset + index
            stamp = start + timedelta(minutes=item * 15)
            signal_id = f"s-{item}"
            session.add(
                MlFeatureSnapshotRow(
                    signal_id=signal_id,
                    symbol="ASELS" if item < 2 else "THYAO",
                    timeframe="15m",
                    signal_time=stamp,
                    lifecycle="FULLY_LABELED",
                    feature_schema_version="v1",
                    features={
                        "signal_id": signal_id,
                        "symbol": "ASELS" if item < 2 else "THYAO",
                        "timestamp": stamp.isoformat(),
                        "price": 100.0,
                        "radar_score": 75 + item * 10,
                        "classification": "CANDIDATE",
                        "rvol": 0.5 + item * 2,
                        "early_momentum_score": 55 + item * 20,
                        "trade_plan_snapshot": {
                            "stop_price": 98.0,
                            "targets": [{"price": 101.0}, {"price": 102.0}, {"price": 103.0}],
                        },
                    },
                )
            )
            session.add(
                MlOutcomeRow(
                    signal_id=signal_id,
                    horizon="120m",
                    status="LABEL_AVAILABLE",
                    outcome={
                        "horizon": "120m",
                        "status": "LABEL_AVAILABLE",
                        "forward_return": item / 100,
                        "maximum_favorable_excursion": (item + 1) / 100,
                        "maximum_adverse_excursion": -0.01,
                        "hit_plus_1_percent": item > 0,
                    },
                )
            )
            session.add(
                SignalAuditRow(
                    signal_id=signal_id,
                    audit_version=2,
                    entry_hit_at=stamp + timedelta(minutes=15),
                    entry_price=100,
                    ordering="TARGET1_FIRST",
                    result_classification=f"EXPIRED_H{min(item % 4, 2)}"
                    if item % 4 < 3
                    else "H3_REACHED",
                    highest_target=item % 4,
                    bars_to_entry=1,
                    bars_after_entry=16,
                    terminal_at=stamp + timedelta(hours=4),
                    updated_at=stamp + timedelta(hours=4),
                )
            )


def test_signal_read_models_filters_analytics_and_shadow() -> None:
    factory = database()
    seed(factory)
    repo = IntradayRepository(factory)
    now = datetime(2026, 8, 13, 12, tzinfo=UTC)
    repo.save_audit(
        "s-0",
        {
            "stop_hit_at": None,
            "target1_hit_at": now,
            "target2_hit_at": None,
            "target3_hit_at": None,
            "ordering": "TARGET1_FIRST",
            "result_classification": "H1_SUCCESS",
        },
        now,
    )
    # A later recomputation cannot rewrite the first hit.
    repo.save_audit(
        "s-0",
        {
            "stop_hit_at": None,
            "target1_hit_at": now + timedelta(hours=1),
            "target2_hit_at": None,
            "target3_hit_at": None,
            "ordering": "TARGET1_FIRST",
            "result_classification": "H1_SUCCESS",
        },
        now,
    )
    intelligence = SignalIntelligence(factory)
    rows, total = intelligence.records(symbol="ASELS", score_bucket="70-79")
    assert total == 1 and rows[0]["audit"]["target1_hit_minutes"] == 300
    assert intelligence.records(day=datetime(2020, 1, 1).date())[1] == 0
    assert intelligence.records(status="H1_SUCCESS")[1] == 1
    assert intelligence.symbol_results("ASELS")
    assert intelligence.daily()[0]["total"] == 3
    assert len(intelligence.analytics("score")) == 3
    assert len(intelligence.analytics("rvol")) == 3
    assert len(intelligence.analytics("momentum")) == 3
    status = intelligence.shadow_status("ASELS")
    assert status["observations"] == 2
    assert status["allow_ml_to_change_radar"] is False
    assert intelligence.shadow_status("MISSING")["reasons"]


def test_training_threshold_trigger_and_persistence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    factory = database()
    events: list[tuple[str, bool]] = []
    monkeypatch.setattr(training, "SessionLocal", factory)
    monkeypatch.setattr(
        training, "mark_job", lambda name, success, detail: events.append((name, success))
    )
    monkeypatch.setattr(training, "get_settings", lambda: SimpleNamespace(ml_training_threshold=20))
    seed(factory, 19)
    assert training.run_shadow_training() is False
    seed(factory, 1)
    assert training.run_shadow_training() is True
    assert training.run_shadow_training() is False
    with factory() as session:
        assert session.query(training.MlDatasetRow).count() == 1
        assert session.query(training.MlModelRow).count() == 1
        assert session.query(training.MlEvaluationRow).count() == 1
    assert events
