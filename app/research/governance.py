from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func, select

from app.adaptive.engine import POLICY_VERSION
from app.core.config import get_settings
from app.database.base import (
    AdaptiveSetupRow,
    DailyResearchSnapshotRow,
    DataFreshnessObservationRow,
    FeatureDefinitionRow,
    FeatureObservationRow,
    MarketBarRow,
    MlExperimentRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlPredictionRow,
    ResearchDatasetVersionRow,
    ResearchLabelRow,
    SessionLocal,
    SignalAuditRow,
    WeeklyResearchReportRow,
    WorkerStateRow,
)
from app.ml.research_lab import FEATURE_MANIFEST, FEATURE_SCHEMA_VERSION, data_hash

ISTANBUL = ZoneInfo("Europe/Istanbul")
TERMINAL_RESULTS = {
    "NO_ENTRY",
    "STOPPED",
    "H3_REACHED",
    "EXPIRED_H0",
    "EXPIRED_H1",
    "EXPIRED_H2",
}


@dataclass(frozen=True)
class RetrainDecision:
    eligible: bool
    reason: str
    total_labels: int
    new_labels: int
    elapsed_hours: float | None
    policy: dict[str, int]


def _aware(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _rate(
    members: list[tuple[ResearchLabelRow, dict[str, object]]], label_name: str
) -> float | None:
    return (
        sum(bool(row.labels.get(label_name)) for row, _ in members) / len(members)
        if members
        else None
    )


def code_commit_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


class EvidenceRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def persist_feature_truth(self) -> int:
        """Copy only signal-time features; target/outcome values never enter this table."""
        with self.session_factory.begin() as session:
            for spec in FEATURE_MANIFEST:
                if session.get(FeatureDefinitionRow, spec.name) is None:
                    session.add(
                        FeatureDefinitionRow(
                            name=spec.name,
                            schema_version=FEATURE_SCHEMA_VERSION,
                            source_timeframe=spec.source_timeframe,
                            formula=spec.formula,
                            missing_policy=spec.missing_policy,
                            metadata_json={
                                "authoritative_only": spec.authoritative_only,
                                "future_derived": False,
                            },
                        )
                    )
            signals = session.scalars(select(MlFeatureSnapshotRow)).all()
            existing = {
                (signal_id, name)
                for signal_id, name in session.execute(
                    select(FeatureObservationRow.signal_id, FeatureObservationRow.feature_name)
                ).all()
            }
            inserted = 0
            for signal in signals:
                for spec in FEATURE_MANIFEST:
                    key = (signal.signal_id, spec.name)
                    if key in existing:
                        continue
                    value = signal.features.get(spec.name)
                    if value is None and spec.name == "radar_score_15m":
                        value = signal.features.get("radar_score")
                    session.add(
                        FeatureObservationRow(
                            signal_id=signal.signal_id,
                            feature_name=spec.name,
                            source_timestamp=signal.signal_time,
                            availability_timestamp=signal.signal_time,
                            value_json={"value": value, "missing": value is None},
                        )
                    )
                    inserted += 1
        return inserted

    def mature_labels(self, now: datetime) -> int:
        settings = get_settings()
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(SignalAuditRow, MlFeatureSnapshotRow)
                .join(
                    MlFeatureSnapshotRow, MlFeatureSnapshotRow.signal_id == SignalAuditRow.signal_id
                )
                .where(
                    SignalAuditRow.result_classification.in_(TERMINAL_RESULTS),
                    SignalAuditRow.terminal_at.is_not(None),
                )
            ).all()
            existing = set(session.scalars(select(ResearchLabelRow.signal_id)).all())
            setups = {row.signal_id: row for row in session.scalars(select(AdaptiveSetupRow)).all()}
            inserted = 0
            for audit, signal in rows:
                if signal.signal_id in existing or audit.terminal_at is None:
                    continue
                setup = setups.get(signal.signal_id)
                realized = None
                if setup is not None and isinstance(
                    setup.metrics.get("realized_r_after_cost"), (int, float)
                ):
                    realized = float(setup.metrics["realized_r_after_cost"])
                session.add(
                    ResearchLabelRow(
                        signal_id=signal.signal_id,
                        policy_version=setup.policy_version if setup else POLICY_VERSION,
                        terminal_at=audit.terminal_at,
                        created_at=now,
                        cost_adjusted_r=realized,
                        labels={
                            "entry": audit.entry_hit_at is not None,
                            "stop_before_h1": audit.result_classification == "STOPPED"
                            and audit.highest_target == 0,
                            "h1": audit.highest_target >= 1,
                            "h2_given_h1": audit.highest_target >= 2,
                            "h3_given_h2": audit.highest_target >= 3,
                            "result": audit.result_classification,
                            "time_to_entry_bars": audit.bars_to_entry,
                        },
                        trace={
                            "signal_time": signal.signal_time.isoformat(),
                            "terminal_at": audit.terminal_at.isoformat(),
                            "audit_version": audit.audit_version,
                            "feature_schema": signal.feature_schema_version,
                            "commission_bps": settings.commission_bps,
                            "slippage_bps": settings.slippage_bps,
                            "feature_truth": "SIGNAL_TIME",
                            "outcome_truth": "FUTURE_TERMINAL",
                        },
                    )
                )
                inserted += 1
        return inserted

    def version_dataset(self, now: datetime) -> str | None:
        with self.session_factory.begin() as session:
            labels = session.scalars(
                select(ResearchLabelRow).order_by(ResearchLabelRow.signal_id)
            ).all()
            records = [
                {
                    "signal_id": row.signal_id,
                    "policy": row.policy_version,
                    "terminal": row.terminal_at.isoformat(),
                    "r": row.cost_adjusted_r,
                    "labels": row.labels,
                }
                for row in labels
            ]
            digest = data_hash(records)
            prior = session.scalar(
                select(ResearchDatasetVersionRow)
                .order_by(ResearchDatasetVersionRow.created_at.desc())
                .limit(1)
            )
            if prior is not None and prior.data_hash == digest:
                return None
            dataset_id = f"research-{now.strftime('%Y%m%d%H%M%S')}-{digest[:10]}"
            session.add(
                ResearchDatasetVersionRow(
                    dataset_id=dataset_id,
                    created_at=now,
                    data_hash=digest,
                    label_count=len(labels),
                    feature_schema=FEATURE_SCHEMA_VERSION,
                    policy_version=POLICY_VERSION,
                    manifest={
                        "code_commit_sha": code_commit_sha(),
                        "random_seed": 0,
                        "label_count": len(labels),
                        "append_only": True,
                    },
                )
            )
        return dataset_id

    def retrain_decision(self, now: datetime) -> RetrainDecision:
        settings = get_settings()
        with self.session_factory() as session:
            total = session.scalar(select(func.count()).select_from(ResearchLabelRow)) or 0
            model = session.scalar(
                select(MlModelRow).order_by(MlModelRow.created_at.desc()).limit(1)
            )
        prior_count = int(model.metadata_json.get("sample_count", 0)) if model else 0
        created = _aware(model.created_at) if model else None
        elapsed = (now - created).total_seconds() / 3600 if created else None
        new = int(total) - prior_count
        policy = {
            "minimum_new_labels_since_previous_model": settings.research_retrain_min_new_labels,
            "minimum_total_labels": settings.research_retrain_min_total_labels,
            "minimum_elapsed_time_hours": settings.research_retrain_min_elapsed_hours,
        }
        if total < settings.research_retrain_min_total_labels:
            return RetrainDecision(False, "MINIMUM_TOTAL_LABELS", int(total), new, elapsed, policy)
        if new < settings.research_retrain_min_new_labels:
            return RetrainDecision(False, "MINIMUM_NEW_LABELS", int(total), new, elapsed, policy)
        if elapsed is not None and elapsed < settings.research_retrain_min_elapsed_hours:
            return RetrainDecision(False, "MINIMUM_ELAPSED_TIME", int(total), new, elapsed, policy)
        return RetrainDecision(True, "ELIGIBLE", int(total), new, elapsed, policy)

    def daily_snapshot(self, session_day: date, now: datetime) -> dict[str, object]:
        start = datetime.combine(session_day, datetime.min.time(), tzinfo=ISTANBUL).astimezone(UTC)
        end = start + timedelta(days=1)
        with self.session_factory.begin() as session:
            bars15 = (
                session.scalar(
                    select(func.count())
                    .select_from(MarketBarRow)
                    .where(
                        MarketBarRow.timeframe == "15m",
                        MarketBarRow.timestamp >= start,
                        MarketBarRow.timestamp < end,
                    )
                )
                or 0
            )
            bars5 = (
                session.scalar(
                    select(func.count())
                    .select_from(MarketBarRow)
                    .where(
                        MarketBarRow.timeframe == "5m",
                        MarketBarRow.timestamp >= start,
                        MarketBarRow.timestamp < end,
                    )
                )
                or 0
            )
            signals = session.scalars(
                select(MlFeatureSnapshotRow).where(
                    MlFeatureSnapshotRow.signal_time >= start,
                    MlFeatureSnapshotRow.signal_time < end,
                )
            ).all()
            signal_ids = [row.signal_id for row in signals]
            setups = session.scalars(
                select(AdaptiveSetupRow).where(
                    AdaptiveSetupRow.signal_time >= start, AdaptiveSetupRow.signal_time < end
                )
            ).all()
            audits = (
                session.scalars(
                    select(SignalAuditRow).where(SignalAuditRow.signal_id.in_(signal_ids))
                ).all()
                if signal_ids
                else []
            )
            day_labels = session.scalars(
                select(ResearchLabelRow).where(
                    ResearchLabelRow.terminal_at >= start, ResearchLabelRow.terminal_at < end
                )
            ).all()
            mature_r = [
                row.cost_adjusted_r for row in day_labels if row.cost_adjusted_r is not None
            ]
            metrics: dict[str, object] = {
                "15m_bars_added": int(bars15),
                "5m_bars_added": int(bars5),
                "signals": len(signals),
                "planned_setups": len(setups),
                "entries": sum(row.entry_time is not None for row in setups),
                "no_entries": sum(
                    row.entry_time is None and row.outcome is not None for row in setups
                ),
                "cancelled_decay": sum(row.outcome == "NO_ENTRY_DECAY" for row in setups),
                "cancelled_structure": sum(row.outcome == "NO_ENTRY_STRUCTURE" for row in setups),
                "chased": sum(row.outcome == "CHASED" for row in setups),
                "hard_stops": sum(row.outcome == "STOPPED" for row in setups),
                "time_exits": sum(row.outcome == "TIME_EXIT" for row in setups),
                "thesis_invalidations": sum(row.outcome == "THESIS_INVALIDATED" for row in setups),
                "h1": sum(row.highest_target >= 1 for row in audits),
                "h2": sum(row.highest_target >= 2 for row in audits),
                "h3": sum(row.highest_target >= 3 for row in audits),
                "shadow_predictions": session.scalar(
                    select(func.count())
                    .select_from(MlPredictionRow)
                    .where(MlPredictionRow.signal_id.in_(signal_ids))
                )
                or 0
                if signal_ids
                else 0,
                "mature_outcomes": sum(
                    row.result_classification in TERMINAL_RESULTS for row in audits
                ),
                "training_eligible": session.scalar(
                    select(func.count()).select_from(ResearchLabelRow)
                )
                or 0,
                "research_eligible": len(signal_ids),
                "radar_average_r": float(np.mean(mature_r)) if mature_r else None,
                "adaptive_average_r": float(np.mean(mature_r)) if mature_r else None,
                "ml_veto_shadow_average_r": None,
                "expected_r_ranking_shadow_average_r": None,
                "economic_denominator_mature_only": len(mature_r),
            }
            previous = session.scalar(
                select(DailyResearchSnapshotRow)
                .where(DailyResearchSnapshotRow.session_date < session_day.isoformat())
                .order_by(DailyResearchSnapshotRow.session_date.desc())
                .limit(1)
            )
            deltas = {
                key: int(value) - int(previous.metrics.get(key, 0) if previous else 0)
                for key, value in metrics.items()
                if isinstance(value, int)
            }
            row = session.get(DailyResearchSnapshotRow, session_day.isoformat())
            if row is None:
                session.add(
                    DailyResearchSnapshotRow(
                        session_date=session_day.isoformat(),
                        created_at=now,
                        metrics=metrics,
                        deltas=deltas,
                    )
                )
            else:
                row.created_at, row.metrics, row.deltas = now, metrics, deltas
        return metrics | {"deltas": deltas}

    def latency_evidence(self) -> dict[str, object]:
        settings = get_settings()
        with self.session_factory() as session:
            rows = session.scalars(
                select(DataFreshnessObservationRow).where(
                    DataFreshnessObservationRow.timeframe == "5m"
                )
            ).all()
        latencies = [
            (row.provider_available_time - row.bar_close_time).total_seconds() for row in rows
        ]
        totals = [(row.persist_time - row.bar_close_time).total_seconds() for row in rows]
        sessions = {row.bar_close_time.astimezone(ISTANBUL).date() for row in rows}
        symbols = {row.symbol for row in rows}
        expected = max(1, len(sessions) * len(symbols) * 96)
        completeness = min(1.0, len(rows) / expected)
        p95 = float(np.percentile(latencies, 95)) if latencies else None
        if not rows:
            maturity = "INSUFFICIENT"
        elif p95 is not None and p95 > settings.research_latency_degraded_p95_seconds:
            maturity = "DEGRADED"
        elif (
            len(sessions) < settings.research_latency_min_sessions
            or completeness < settings.research_latency_min_completeness
        ):
            maturity = "OBSERVING"
        elif p95 is not None and p95 <= settings.research_latency_ready_p95_seconds:
            maturity = "RESEARCH_READY"
        else:
            maturity = "DEGRADED"

        def percentile(values: list[float], value: int) -> float | None:
            return round(float(np.percentile(values, value)), 3) if values else None

        return {
            "policy_version": settings.research_latency_policy_version,
            "maturity": maturity,
            "sample": len(rows),
            "sessions": len(sessions),
            "symbols": len(symbols),
            "coverage": completeness,
            "missing": max(0, expected - len(rows)),
            "provider_latency_seconds": {
                f"p{q}": percentile(latencies, q) for q in (50, 90, 95, 99)
            },
            "total_latency_seconds": {f"p{q}": percentile(totals, q) for q in (50, 90, 95, 99)},
            "production_dependency": "NONE",
        }

    def evidence_status(self, now: datetime | None = None) -> dict[str, object]:
        current = now or datetime.now(UTC)
        settings = get_settings()
        with self.session_factory() as session:
            counts = {
                "15m_observations": session.scalar(
                    select(func.count())
                    .select_from(MarketBarRow)
                    .where(MarketBarRow.timeframe == "15m")
                )
                or 0,
                "5m_observations": session.scalar(
                    select(func.count())
                    .select_from(MarketBarRow)
                    .where(MarketBarRow.timeframe == "5m")
                )
                or 0,
                "mature_labels": session.scalar(select(func.count()).select_from(ResearchLabelRow))
                or 0,
                "oos_sample": 0,
                "walk_forward_folds": 0,
            }
            experiments = session.scalars(
                select(MlExperimentRow).order_by(MlExperimentRow.created_at.desc())
            ).all()
            models = session.scalars(
                select(MlModelRow).order_by(MlModelRow.created_at.desc())
            ).all()
            jobs = {row.job_name: row for row in session.scalars(select(WorkerStateRow)).all()}
            recent_days = session.scalars(
                select(DailyResearchSnapshotRow)
                .order_by(DailyResearchSnapshotRow.session_date.desc())
                .limit(2)
            ).all()
        for experiment in experiments:
            counts["oos_sample"] = max(
                counts["oos_sample"], int(experiment.metrics.get("oos_sample", 0))
            )
            counts["walk_forward_folds"] = max(
                counts["walk_forward_folds"], int(experiment.metrics.get("folds", 0))
            )
        folds = counts["walk_forward_folds"]
        sample = counts["oos_sample"]
        predictive = (
            "INSUFFICIENT"
            if sample < settings.research_governance_min_oos
            or folds < settings.research_governance_min_folds
            else "NO"
        )
        economic = (
            "INSUFFICIENT"
            if counts["mature_labels"] < settings.research_governance_min_oos
            or sample < settings.research_governance_min_oos
            or folds < settings.research_governance_min_folds
            else "NO"
        )
        health: list[dict[str, object]] = []
        for name in (
            "intraday_radar_scan",
            "shadow_training",
            "adaptive_lifecycle",
            "research_cycle",
        ):
            job = jobs.get(name)
            stamp = _aware(job.last_success_at) if job else None
            stale = stamp is None or current - stamp > timedelta(
                hours=settings.research_health_stale_hours
            )
            health.append(
                {
                    "component": name,
                    "status": "STALE" if stale or job is None else job.status,
                    "last_success": stamp,
                }
            )
        if len(recent_days) == 2:
            newest, older = recent_days
            signals_growing = int(newest.metrics.get("signals", 0)) > int(
                older.metrics.get("signals", 0)
            )
            labels_growing = int(newest.metrics.get("mature_outcomes", 0)) > int(
                older.metrics.get("mature_outcomes", 0)
            )
            if signals_growing and not labels_growing:
                health.append(
                    {
                        "component": "label_growth",
                        "status": "DEGRADED",
                        "reason": "SIGNALS_GROWING_LABELS_NOT_GROWING",
                    }
                )
        model_status = "INSUFFICIENT_DATA" if not models else "SHADOW"
        if experiments:
            latest_expected = experiments[0].metrics.get("expected_r")
            latest_drawdown = experiments[0].metrics.get("max_drawdown_r")
            economic_failure = isinstance(latest_expected, (int, float)) and latest_expected < 0
            drawdown_failure = (
                isinstance(latest_drawdown, (int, float))
                and latest_drawdown > settings.research_governance_max_drawdown_r
            )
            if economic_failure or drawdown_failure:
                model_status = "MODEL_DEGRADED"
                health.append(
                    {
                        "component": "model_degradation",
                        "status": "MODEL_DEGRADED",
                        "reason": "RECENT_OOS_ECONOMIC_OR_DRAWDOWN_FAILURE",
                    }
                )
        return {
            **counts,
            "latency": self.latency_evidence(),
            "predictive_edge": predictive,
            "economic_edge": economic,
            "current_champion": f"Radar + {POLICY_VERSION}",
            "best_challenger": models[0].model_id if models else None,
            "challenger_vs_champion": "INSUFFICIENT_OOS",
            "expected_r_improvement": None,
            "drawdown_difference": None,
            "model_status": model_status,
            "radar_decision_effect": "NONE",
            "auto_promotion": False,
            "health": health,
            "disagreement_matrix": self.disagreement_matrix(),
            "abstention_research": self.abstention_evidence(),
        }

    def disagreement_matrix(self) -> dict[str, dict[str, object]]:
        with self.session_factory() as session:
            labels = session.scalars(select(ResearchLabelRow)).all()
            signals = {
                row.signal_id: row for row in session.scalars(select(MlFeatureSnapshotRow)).all()
            }
            predictions: dict[str, MlPredictionRow] = {}
            for row in session.scalars(
                select(MlPredictionRow).order_by(MlPredictionRow.created_at.desc())
            ).all():
                predictions.setdefault(row.signal_id, row)
        grouped: dict[str, list[tuple[ResearchLabelRow, dict[str, object]]]] = {
            f"RADAR_{radar}_ML_{ml}": [] for radar in ("HIGH", "LOW") for ml in ("HIGH", "LOW")
        }
        for label in labels:
            signal, prediction = signals.get(label.signal_id), predictions.get(label.signal_id)
            if signal is None or prediction is None:
                continue
            radar_score = signal.features.get("radar_score")
            ml_score = prediction.predictions.get("entry_probability")
            if not isinstance(radar_score, (int, float)) or not isinstance(ml_score, (int, float)):
                continue
            radar_group = "HIGH" if radar_score >= 80 else "LOW"
            ml_group = "HIGH" if ml_score >= 0.5 else "LOW"
            key = f"RADAR_{radar_group}_ML_{ml_group}"
            grouped[key].append((label, prediction.predictions))
        output: dict[str, dict[str, object]] = {}
        for key, members in grouped.items():
            values = [row.cost_adjusted_r for row, _ in members if row.cost_adjusted_r is not None]
            output[key] = {
                "N": len(members),
                "entry_rate": _rate(members, "entry"),
                "H1": _rate(members, "h1"),
                "H2": _rate(members, "h2_given_h1"),
                "H3": _rate(members, "h3_given_h2"),
                "stop": _rate(members, "stop_before_h1"),
                "time_exit": sum(row.labels.get("result") == "TIME_EXIT" for row, _ in members)
                / len(members)
                if members
                else None,
                "mean_r": float(np.mean(values)) if values else None,
                "median_r": median(values) if values else None,
            }
        return output

    def abstention_evidence(self) -> dict[str, object]:
        with self.session_factory() as session:
            labels = {row.signal_id: row for row in session.scalars(select(ResearchLabelRow)).all()}
            predictions: dict[str, MlPredictionRow] = {}
            for row in session.scalars(
                select(MlPredictionRow).order_by(MlPredictionRow.created_at.desc())
            ).all():
                predictions.setdefault(row.signal_id, row)
        paired = [
            (labels[signal_id], prediction.predictions)
            for signal_id, prediction in predictions.items()
            if signal_id in labels and labels[signal_id].cost_adjusted_r is not None
        ]
        radar = [float(row.cost_adjusted_r) for row, _ in paired if row.cost_adjusted_r is not None]
        traded = [
            float(row.cost_adjusted_r)
            for row, prediction in paired
            if row.cost_adjusted_r is not None and prediction.get("suggestion") != "NO_TRADE"
        ]
        vetoed = sum(prediction.get("suggestion") == "NO_TRADE" for _, prediction in paired)
        return {
            "mode": "SHADOW_ONLY",
            "radar_trade_assumption_mean_r": float(np.mean(radar)) if radar else None,
            "ml_veto_simulation_mean_r": float(np.mean(traded)) if traded else None,
            "no_trade_rate": vetoed / len(paired) if paired else None,
            "sample": len(paired),
            "radar_decision_effect": "NONE",
        }

    def weekly_report(self, session_day: date, now: datetime) -> dict[str, object]:
        week_start = session_day - timedelta(days=session_day.weekday())
        status = self.evidence_status(now)
        with self.session_factory.begin() as session:
            labels = session.scalars(
                select(ResearchLabelRow).where(
                    ResearchLabelRow.terminal_at
                    >= datetime.combine(week_start, datetime.min.time(), tzinfo=ISTANBUL)
                )
            ).all()
            values = [row.cost_adjusted_r for row in labels if row.cost_adjusted_r is not None]
            payload = {
                "week_start": week_start.isoformat(),
                "new_mature_outcomes": len(labels),
                "new_samples": len(labels),
                "data_quality": "RESEARCH_ONLY_UNVERIFIED",
                "5m_latency": status["latency"],
                "models_trained": 0,
                "oos_evaluation": {
                    "sample": status["oos_sample"],
                    "folds": status["walk_forward_folds"],
                },
                "champion_challenger": status["challenger_vs_champion"],
                "economic_metrics": {
                    "mean_r": float(np.mean(values)) if values else None,
                    "median_r": median(values) if values else None,
                },
                "drift": status["model_status"],
                "edge_verdict": {
                    "predictive": status["predictive_edge"],
                    "economic": status["economic_edge"],
                },
            }
            row = session.get(WeeklyResearchReportRow, week_start.isoformat())
            if row is None:
                session.add(
                    WeeklyResearchReportRow(
                        week_start=week_start.isoformat(), created_at=now, payload=payload
                    )
                )
            else:
                row.created_at, row.payload = now, payload
        return payload


def evidence_maturity(oos_sample: int, independent_folds: int) -> str:
    if oos_sample < 100 or independent_folds < 2:
        return "INSUFFICIENT_DATA"
    if oos_sample < 300 or independent_folds < 3:
        return "EARLY"
    if oos_sample < 1000 or independent_folds < 5:
        return "DEVELOPING"
    return "MATURE"


def promotion_candidate(metrics: dict[str, object]) -> bool:
    settings = get_settings()

    def number(name: str, default: float) -> float:
        value = metrics.get(name)
        return float(value) if isinstance(value, (int, float)) else default

    required = (
        number("oos_sample", 0) >= settings.research_governance_min_oos,
        number("folds", 0) >= settings.research_governance_min_folds,
        number("winning_fold_ratio", 0) >= settings.research_governance_min_winning_fold_ratio,
        number("expected_r", -1) > 0,
        number("economic_improvement", -1) > 0,
        number("max_drawdown_r", float("inf")) <= settings.research_governance_max_drawdown_r,
        bool(metrics.get("calibrated", False)),
        bool(metrics.get("no_leakage", False)),
        not bool(metrics.get("severe_regime_instability", True)),
    )
    return all(required)
