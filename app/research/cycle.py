from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.data.intraday_research import IntradayResearchBackfill, latest_liquidity_symbols
from app.database.base import ResearchCycleRow, SessionLocal
from app.ml.training import run_shadow_training
from app.operations.jobs import mark_job
from app.research.governance import EvidenceRepository

ISTANBUL = ZoneInfo("Europe/Istanbul")


class AutonomousResearchCycle:
    """Idempotent post-Radar evidence cycle; never returns an execution decision."""

    def __init__(
        self,
        session_factory: Any = SessionLocal,
        evidence: EvidenceRepository | None = None,
        backfill: IntradayResearchBackfill | None = None,
        trainer: Callable[..., bool] = run_shadow_training,
        job_marker: Callable[..., None] = mark_job,
    ) -> None:
        self.session_factory = session_factory
        self.evidence = evidence or EvidenceRepository(session_factory)
        self.backfill = backfill or IntradayResearchBackfill(session_factory=session_factory)
        self.trainer = trainer
        self.job_marker = job_marker

    def run(self, completed_bar_at: datetime, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        if completed_bar_at.tzinfo is None or current.tzinfo is None:
            raise ValueError("timezone-aware cycle timestamps required")
        cycle_id = f"research-v1:{completed_bar_at.astimezone(UTC).isoformat()}"
        with self.session_factory() as session:
            prior = session.get(ResearchCycleRow, cycle_id)
            if prior is not None and prior.status == "COMPLETED":
                return dict(prior.metrics) | {"cycle_id": cycle_id, "idempotent_replay": True}
        checkpoints: dict[str, object] = {}
        metrics: dict[str, object] = {}
        try:
            liquid = latest_liquidity_symbols(self.session_factory)
            selected = self.backfill.active_5m_universe(liquid)
            if selected:
                from app.backtest.replay_models import Timeframe

                result = self.backfill.run(selected, Timeframe.M5, now=current)
                metrics["5m_bars_added"] = result.inserted_bars
                metrics["5m_failures"] = len(result.failures)
                checkpoints["5m_ingest"] = "PASS" if result.found_symbols else "DEGRADED"
            else:
                metrics["5m_bars_added"] = 0
                checkpoints["5m_ingest"] = "NO_ELIGIBLE_SYMBOLS"
            features = self.evidence.persist_feature_truth()
            checkpoints["feature_persistence"] = "PASS"
            metrics["features_added"] = features
            labels = self.evidence.mature_labels(current)
            checkpoints["label_maturation"] = "PASS"
            metrics["labels_added"] = labels
            dataset_id = self.evidence.version_dataset(current)
            checkpoints["dataset_update"] = "PASS"
            metrics["dataset_id"] = dataset_id
            retrain = self.evidence.retrain_decision(current)
            metrics["retrain"] = {
                "eligible": retrain.eligible,
                "reason": retrain.reason,
                "total_labels": retrain.total_labels,
                "new_labels": retrain.new_labels,
                "elapsed_hours": retrain.elapsed_hours,
                "policy": retrain.policy,
            }
            trained = self.trainer(force=True) if retrain.eligible else self.trainer(force=False)
            checkpoints["shadow_inference"] = "PASS"
            checkpoints["retraining"] = "TRAINED" if trained else retrain.reason
            metrics["model_trained"] = trained
            session_day = current.astimezone(ISTANBUL).date()
            metrics["daily"] = self.evidence.daily_snapshot(session_day, current)
            metrics["weekly"] = self.evidence.weekly_report(session_day, current)
            metrics["latency"] = self.evidence.latency_evidence()
            checkpoints["health"] = "PASS"
            status = "COMPLETED"
        except Exception as exc:
            status = "FAILED"
            metrics["error"] = type(exc).__name__
            checkpoints["failure"] = type(exc).__name__
            self._save(cycle_id, completed_bar_at, current, status, checkpoints, metrics)
            self.job_marker("research_cycle", False, metrics, completed_bar_at)
            raise
        self._save(cycle_id, completed_bar_at, current, status, checkpoints, metrics)
        self.job_marker("research_cycle", True, metrics, completed_bar_at)
        return metrics | {"cycle_id": cycle_id, "idempotent_replay": False}

    def _save(
        self,
        cycle_id: str,
        completed_bar_at: datetime,
        now: datetime,
        status: str,
        checkpoints: dict[str, object],
        metrics: dict[str, object],
    ) -> None:
        with self.session_factory.begin() as session:
            row = session.get(ResearchCycleRow, cycle_id)
            if row is None:
                session.add(
                    ResearchCycleRow(
                        cycle_id=cycle_id,
                        completed_bar_at=completed_bar_at,
                        created_at=now,
                        status=status,
                        checkpoints=checkpoints,
                        metrics=metrics,
                    )
                )
            else:
                row.created_at, row.status = now, status
                row.checkpoints, row.metrics = checkpoints, metrics
