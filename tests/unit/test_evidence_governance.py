from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.database.base import (
    Base,
    DailyResearchSnapshotRow,
    DataFreshnessObservationRow,
    MlExperimentRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlPredictionRow,
    ResearchCycleRow,
    ResearchDatasetVersionRow,
    ResearchLabelRow,
    SignalAuditRow,
    WeeklyResearchReportRow,
    WorkerStateRow,
)
from app.research.cycle import AutonomousResearchCycle
from app.research.governance import (
    EvidenceRepository,
    evidence_maturity,
    promotion_candidate,
)


def _sessions():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _terminal_signal(sessions, now: datetime) -> None:
    with sessions.begin() as session:
        session.add(
            MlFeatureSnapshotRow(
                signal_id="THYAO:15m:20260814T1000",
                symbol="THYAO",
                timeframe="15m",
                signal_time=now - timedelta(hours=3),
                lifecycle="FULLY_LABELED",
                feature_schema_version="intraday-v1",
                features={"radar_score": 91, "momentum_15m": 0.02},
            )
        )
        session.add(
            SignalAuditRow(
                signal_id="THYAO:15m:20260814T1000",
                audit_version=2,
                entry_hit_at=now - timedelta(hours=2),
                target1_hit_at=now - timedelta(hours=1),
                ordering="TARGET_FIRST",
                result_classification="EXPIRED_H1",
                highest_target=1,
                bars_to_entry=4,
                bars_after_entry=8,
                terminal_at=now,
                updated_at=now,
            )
        )


def test_feature_label_dataset_and_scorecard_are_restart_persistent() -> None:
    sessions = _sessions()
    now = datetime(2026, 8, 14, 15, tzinfo=UTC)
    _terminal_signal(sessions, now)
    repository = EvidenceRepository(sessions)
    assert repository.persist_feature_truth() > 0
    assert repository.persist_feature_truth() == 0
    assert repository.mature_labels(now) == 1
    assert repository.mature_labels(now) == 0
    with sessions.begin() as session:
        session.get(ResearchLabelRow, "THYAO:15m:20260814T1000").cost_adjusted_r = 0.5
        session.add(
            MlPredictionRow(
                signal_id="THYAO:15m:20260814T1000",
                model_id="shadow-test",
                created_at=now,
                predictions={
                    "entry_probability": 0.8,
                    "suggestion": "NO_TRADE",
                    "expected_r": -0.2,
                },
            )
        )
        for offset in (30, 60):
            close = now - timedelta(minutes=offset)
            session.add(
                DataFreshnessObservationRow(
                    provider_id="yfinance-research",
                    symbol="THYAO",
                    timeframe="5m",
                    bar_close_time=close,
                    provider_available_time=close + timedelta(seconds=45),
                    persist_time=close + timedelta(seconds=50),
                    metadata_json={"research_only": True},
                )
            )
    dataset_id = repository.version_dataset(now)
    assert dataset_id is not None
    assert repository.version_dataset(now + timedelta(minutes=1)) is None
    daily = repository.daily_snapshot(date(2026, 8, 14), now)
    weekly = repository.weekly_report(date(2026, 8, 14), now)
    assert daily["signals"] == 1
    assert daily["mature_outcomes"] == 1
    assert weekly["new_mature_outcomes"] == 1
    latency = repository.latency_evidence()
    assert latency["maturity"] == "OBSERVING"
    assert latency["provider_latency_seconds"]["p95"] == 45
    matrix = repository.disagreement_matrix()
    assert matrix["RADAR_HIGH_ML_HIGH"]["N"] == 1
    assert matrix["RADAR_HIGH_ML_HIGH"]["H1"] == 1
    abstention = repository.abstention_evidence()
    assert abstention["no_trade_rate"] == 1
    assert abstention["radar_decision_effect"] == "NONE"
    restarted = EvidenceRepository(sessions)
    assert restarted.evidence_status(now)["mature_labels"] == 1
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ResearchLabelRow)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchDatasetVersionRow)) == 1
        assert session.scalar(select(func.count()).select_from(DailyResearchSnapshotRow)) == 1
        assert session.scalar(select(func.count()).select_from(WeeklyResearchReportRow)) == 1


class _NoopBackfill:
    def active_5m_universe(self, _: list[str]) -> list[str]:
        return []


def test_controlled_autonomous_cycle_is_idempotent_end_to_end() -> None:
    sessions = _sessions()
    now = datetime(2026, 8, 14, 15, tzinfo=UTC)
    _terminal_signal(sessions, now)
    calls: list[bool] = []

    def trainer(*, force: bool) -> bool:
        calls.append(force)
        return False

    cycle = AutonomousResearchCycle(
        sessions,
        EvidenceRepository(sessions),
        _NoopBackfill(),  # type: ignore[arg-type]
        trainer,
        lambda *_args: None,
    )
    first = cycle.run(now, now)
    restarted = AutonomousResearchCycle(
        sessions,
        EvidenceRepository(sessions),
        _NoopBackfill(),  # type: ignore[arg-type]
        trainer,
        lambda *_args: None,
    )
    second = restarted.run(now, now + timedelta(minutes=1))
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert calls == [False]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(ResearchCycleRow)) == 1
        assert session.scalar(select(func.count()).select_from(ResearchLabelRow)) == 1


class _FailingBackfill:
    def active_5m_universe(self, _: list[str]) -> list[str]:
        raise RuntimeError("provider down")


def test_cycle_persists_failed_checkpoint_and_rejects_naive_time() -> None:
    sessions = _sessions()
    marked: list[bool] = []
    cycle = AutonomousResearchCycle(
        sessions,
        EvidenceRepository(sessions),
        _FailingBackfill(),  # type: ignore[arg-type]
        lambda **_: False,
        lambda _name, success, *_args: marked.append(success),
    )
    aware = datetime(2026, 8, 14, 15, tzinfo=UTC)
    try:
        cycle.run(aware, aware)
    except RuntimeError:
        pass
    else:
        raise AssertionError("failure must propagate")
    assert marked == [False]
    with sessions() as session:
        row = session.get(ResearchCycleRow, f"research-v1:{aware.isoformat()}")
        assert row is not None and row.status == "FAILED"
    try:
        cycle.run(datetime(2026, 8, 14), aware)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive timestamp must fail")


def test_retrain_policy_maturity_and_multi_metric_promotion_gate() -> None:
    repository = EvidenceRepository(_sessions())
    decision = repository.retrain_decision(datetime(2026, 8, 14, tzinfo=UTC))
    assert decision.eligible is False
    assert decision.reason == "MINIMUM_TOTAL_LABELS"
    assert evidence_maturity(10, 1) == "INSUFFICIENT_DATA"
    assert evidence_maturity(150, 2) == "EARLY"
    assert evidence_maturity(500, 3) == "DEVELOPING"
    assert evidence_maturity(1500, 5) == "MATURE"
    passing = {
        "oos_sample": 600,
        "folds": 4,
        "winning_fold_ratio": 0.75,
        "expected_r": 0.2,
        "economic_improvement": 0.1,
        "max_drawdown_r": 5,
        "calibrated": True,
        "no_leakage": True,
        "severe_regime_instability": False,
    }
    assert promotion_candidate(passing) is True
    assert promotion_candidate(passing | {"calibrated": False}) is False


def test_retrain_policy_enforces_new_label_and_elapsed_time_gates() -> None:
    sessions = _sessions()
    now = datetime(2026, 8, 14, 15, tzinfo=UTC)
    with sessions.begin() as session:
        session.add_all(
            ResearchLabelRow(
                signal_id=f"label-{index}",
                policy_version="adaptive-v1",
                terminal_at=now,
                created_at=now,
                cost_adjusted_r=0.1,
                labels={"entry": True},
                trace={},
            )
            for index in range(250)
        )
        session.add(
            MlModelRow(
                model_id="recent-model",
                created_at=now - timedelta(hours=1),
                model_type="logistic",
                metadata_json={"sample_count": 250},
            )
        )
    repository = EvidenceRepository(sessions)
    decision = repository.retrain_decision(now)
    assert decision.reason == "MINIMUM_NEW_LABELS"
    with sessions.begin() as session:
        model = session.get(MlModelRow, "recent-model")
        assert model is not None
        model.metadata_json = {"sample_count": 200}
    decision = repository.retrain_decision(now)
    assert decision.reason == "MINIMUM_ELAPSED_TIME"
    decision = repository.retrain_decision(now + timedelta(days=8))
    assert decision.eligible is True
    assert decision.reason == "ELIGIBLE"


def test_latency_maturity_ready_and_degraded_are_policy_driven(monkeypatch) -> None:
    sessions = _sessions()
    now = datetime(2026, 8, 14, 15, tzinfo=UTC)
    with sessions.begin() as session:
        for day, latency in ((0, 60), (1, 90), (2, 120)):
            close = now - timedelta(days=day)
            session.add(
                DataFreshnessObservationRow(
                    provider_id="yfinance-research",
                    symbol="THYAO",
                    timeframe="5m",
                    bar_close_time=close,
                    provider_available_time=close + timedelta(seconds=latency),
                    persist_time=close + timedelta(seconds=latency + 5),
                    metadata_json={"research_only": True},
                )
            )
    from app.core.config import get_settings

    settings = get_settings().model_copy(update={"research_latency_min_completeness": 0.001})
    monkeypatch.setattr("app.research.governance.get_settings", lambda: settings)
    repository = EvidenceRepository(sessions)
    assert repository.latency_evidence()["maturity"] == "RESEARCH_READY"
    with sessions.begin() as session:
        rows = session.scalars(select(DataFreshnessObservationRow)).all()
        for row in rows:
            row.provider_available_time = row.bar_close_time + timedelta(seconds=400)
    assert repository.latency_evidence()["maturity"] == "DEGRADED"


def test_evidence_health_flags_label_stall_and_recent_model_degradation() -> None:
    sessions = _sessions()
    now = datetime(2026, 8, 14, 15, tzinfo=UTC)
    with sessions.begin() as session:
        session.add(
            MlExperimentRow(
                experiment_id="degraded-oos",
                created_at=now,
                data_hash="a" * 64,
                feature_schema="intraday-v1",
                policy_version="adaptive-v1",
                model="logistic",
                hyperparameters={},
                date_ranges={},
                prior_trials=1,
                metrics={
                    "oos_sample": 600,
                    "folds": 4,
                    "expected_r": -0.2,
                    "max_drawdown_r": 20,
                },
            )
        )
        session.add(
            MlModelRow(
                model_id="shadow-degraded",
                created_at=now,
                model_type="logistic",
                metadata_json={"sample_count": 600},
            )
        )
        session.add_all(
            [
                DailyResearchSnapshotRow(
                    session_date="2026-08-14",
                    created_at=now,
                    metrics={"signals": 20, "mature_outcomes": 5},
                    deltas={},
                ),
                DailyResearchSnapshotRow(
                    session_date="2026-08-13",
                    created_at=now - timedelta(days=1),
                    metrics={"signals": 10, "mature_outcomes": 5},
                    deltas={},
                ),
                WorkerStateRow(
                    job_name="research_cycle",
                    last_started_at=now,
                    last_success_at=now,
                    status="HEALTHY",
                    detail={},
                ),
            ]
        )
    status = EvidenceRepository(sessions).evidence_status(now)
    assert status["oos_sample"] == 600
    assert status["walk_forward_folds"] == 4
    assert status["model_status"] == "MODEL_DEGRADED"
    health = {row["component"]: row for row in status["health"]}
    assert health["label_growth"]["reason"] == "SIGNALS_GROWING_LABELS_NOT_GROWING"
    assert health["model_degradation"]["status"] == "MODEL_DEGRADED"
    assert health["research_cycle"]["status"] == "HEALTHY"
