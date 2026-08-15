from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import numpy as np
from sqlalchemy import select

from app.core.config import get_settings
from app.database.base import (
    MlDatasetRow,
    MlEvaluationRow,
    MlExperimentRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlPredictionRow,
    SessionLocal,
    SignalAuditRow,
)
from app.ml.research_lab import (
    FEATURE_SCHEMA_VERSION,
    data_hash,
    serializable_fold,
    walk_forward_folds,
)
from app.ml.shadow import (
    calibration,
    classification_metrics,
    fit_logistic_artifact,
    predict_logistic_artifact,
    sample_maturity,
    temporal_split,
)
from app.operations.jobs import mark_job
from app.research.governance import code_commit_sha

FEATURES = (
    "radar_score",
    "rsi",
    "macd",
    "macd_histogram",
    "rvol",
    "atr",
    "vwap_distance",
    "ema9_distance",
    "ema20_distance",
    "ema50_distance",
    "breakout_distance",
    "relative_strength",
    "volume_acceleration",
    "price_acceleration",
    "data_quality",
    "early_momentum_score",
)
HEADS = ("entry", "stop", "h1", "h2", "h3")
TERMINAL_RESULTS = {"NO_ENTRY", "STOPPED", "H3_REACHED", "EXPIRED_H0", "EXPIRED_H1", "EXPIRED_H2"}
EMBARGO_SAMPLES = 16


def _vector(row: MlFeatureSnapshotRow) -> list[float]:
    return [
        float(value) if isinstance((value := row.features.get(name)), (int, float)) else 0.0
        for name in FEATURES
    ]


def _labels(audit: SignalAuditRow) -> dict[str, int]:
    entered = audit.entry_hit_at is not None
    return {
        "entry": int(entered),
        "stop": int(audit.result_classification == "STOPPED"),
        "h1": int(audit.highest_target >= 1),
        "h2": int(audit.highest_target >= 2),
        "h3": int(audit.highest_target >= 3),
    }


def _metrics(actual: list[int], probability: list[float]) -> dict[str, Any]:
    result: dict[str, Any] = classification_metrics(actual, probability)
    result["calibration"] = calibration(actual, probability)
    result["base_rate"] = sum(actual) / len(actual)
    return result


def _probability_quality(metrics: dict[str, Any]) -> dict[str, object]:
    bins = metrics.get("calibration", [])
    populated = [
        item for item in bins if isinstance(item, dict) and int(item.get("count", 0)) >= 10
    ]
    sample = sum(int(item.get("count", 0)) for item in bins if isinstance(item, dict))
    gaps = [abs(float(item["mean_probability"]) - float(item["hit_rate"])) for item in populated]
    base_rate = float(metrics.get("base_rate", 0))
    beats_base = float(metrics.get("brier_score", 1)) < base_rate * (1 - base_rate)
    calibrated = (
        sample >= 50 and len(populated) >= 2 and beats_base and max(gaps, default=1) <= 0.15
    )
    return {
        "status": "CALIBRATED" if calibrated else "UNCALIBRATED",
        "display": "PROBABILITY" if calibrated else "SHADOW_SCORE",
        "sample": sample,
        "max_calibration_gap": max(gaps, default=None),
        "beats_base_rate_brier": beats_base,
    }


def run_shadow_training(*, force: bool = False) -> bool:
    """Train entry-aware shadow probability heads and persist honest test metrics."""
    settings = get_settings()
    now = datetime.now(UTC)
    mark_job("shadow_training", True, {"phase": "STARTED"})
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(MlFeatureSnapshotRow, SignalAuditRow)
                .join(SignalAuditRow, SignalAuditRow.signal_id == MlFeatureSnapshotRow.signal_id)
                .where(
                    SignalAuditRow.audit_version == 2,
                    SignalAuditRow.result_classification.in_(TERMINAL_RESULTS),
                )
                .order_by(MlFeatureSnapshotRow.signal_time)
            ).all()
            all_signals = session.scalars(
                select(MlFeatureSnapshotRow).order_by(MlFeatureSnapshotRow.signal_time)
            ).all()
            prior = session.scalar(
                select(MlModelRow).order_by(MlModelRow.created_at.desc()).limit(1)
            )
            prior_predictions = (
                {
                    value
                    for value in session.scalars(
                        select(MlPredictionRow.signal_id).where(
                            MlPredictionRow.model_id == prior.model_id
                        )
                    ).all()
                }
                if prior
                else set()
            )
        threshold = settings.ml_training_threshold
        if len(rows) < threshold:
            mark_job(
                "shadow_training",
                True,
                {"phase": "BELOW_THRESHOLD", "eligible": len(rows), "threshold": threshold},
            )
            return False
        prior_count = prior.metadata_json.get("sample_count", 0) if prior else 0
        if (
            prior
            and not force
            and prior.model_type == "ENTRY_AWARE_LOGISTIC"
            and prior_count == len(rows)
        ):
            missing = [
                signal for signal in all_signals if signal.signal_id not in prior_predictions
            ]
            raw_artifacts = prior.metadata_json.get("artifacts")
            if missing and isinstance(raw_artifacts, dict):
                prior_artifacts = cast(dict[str, dict[str, object]], raw_artifacts)
                matrix = np.asarray([_vector(row) for row in missing], dtype=float)
                prior_predicted = {
                    head: predict_logistic_artifact(prior_artifacts[head], matrix)
                    for head in HEADS
                    if isinstance(prior_artifacts.get(head), dict)
                }
                if len(prior_predicted) == len(HEADS):
                    with SessionLocal.begin() as session:
                        for index, signal in enumerate(missing):
                            session.add(
                                MlPredictionRow(
                                    signal_id=signal.signal_id,
                                    model_id=prior.model_id,
                                    created_at=now,
                                    predictions={
                                        "entry_probability": prior_predicted["entry"][index],
                                        "stop_probability": prior_predicted["stop"][index],
                                        "h1_probability": prior_predicted["h1"][index],
                                        "h2_probability": prior_predicted["h2"][index],
                                        "h3_probability": prior_predicted["h3"][index],
                                        "sample_maturity": sample_maturity(len(rows)),
                                        "head_quality": prior.metadata_json.get("head_quality", {}),
                                        "mode": "SHADOW",
                                    },
                                )
                            )
            mark_job(
                "shadow_training",
                True,
                {"phase": "UP_TO_DATE", "eligible": len(rows), "scored": len(missing)},
            )
            return False

        values = np.asarray([_vector(row) for row, _ in rows], dtype=float)
        artifacts: dict[str, dict[str, object]] = {}
        evaluation: dict[str, Any] = {}
        head_splits: dict[str, dict[str, int]] = {}
        for head in HEADS:
            indices = [
                index
                for index, (_, audit) in enumerate(rows)
                if head == "entry"
                or (head in {"stop", "h1"} and audit.entry_hit_at is not None)
                or (head == "h2" and audit.highest_target >= 1)
                or (head == "h3" and audit.highest_target >= 2)
            ]
            head_values = values[indices]
            head_labels = np.asarray(
                [_labels(rows[index][1])[head] for index in indices], dtype=int
            )
            train_range, validation_range, test_range = temporal_split(len(indices))
            raw_train, raw_validation = list(train_range), list(validation_range)
            embargo = min(EMBARGO_SAMPLES, max(0, min(len(raw_train), len(raw_validation)) - 1))
            train = raw_train[:-embargo] if embargo else raw_train
            validation = raw_validation[:-embargo] if embargo else raw_validation
            test = list(test_range)
            if not train or not validation or not test:
                mark_job(
                    "shadow_training",
                    True,
                    {"phase": "INSUFFICIENT_SPLIT", "head": head, "eligible": len(indices)},
                )
                return False
            artifact = fit_logistic_artifact(head_values[train], head_labels[train])
            artifacts[head] = artifact
            validation_probability = predict_logistic_artifact(artifact, head_values[validation])
            test_probability = predict_logistic_artifact(artifact, head_values[test])
            evaluation[head] = {
                "task": {
                    "entry": "P(entry before setup expiry)",
                    "stop": "P(stop before H1 | entry)",
                    "h1": "P(H1 before time exit | entry)",
                    "h2": "P(H2 | H1)",
                    "h3": "P(H3 | H2)",
                }[head],
                "conditional_sample": len(indices),
                "validation": _metrics(head_labels[validation].tolist(), validation_probability),
                "test": _metrics(head_labels[test].tolist(), test_probability),
            }
            evaluation[head]["quality"] = _probability_quality(evaluation[head]["test"])
            if len(set(head_labels.tolist())) < 2:
                evaluation[head]["quality"]["status"] = "INSUFFICIENT_CLASS_VARIATION"
                evaluation[head]["quality"]["display"] = "SHADOW_SCORE"
            head_splits[head] = {
                "sample": len(indices),
                "train": len(train),
                "validation": len(validation),
                "test": len(test),
                "embargo": embargo,
            }

        dataset_id = str(uuid4())
        experiment_id = f"exp-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        model_id = f"shadow-entry-v2-{now.strftime('%Y%m%d%H%M%S')}"
        session_dates = sorted({row.signal_time.date() for row, _ in rows})
        folds = (
            walk_forward_folds(
                session_dates,
                train_sessions=max(3, len(session_dates) // 2),
                validation_sessions=max(1, len(session_dates) // 8),
                test_sessions=max(1, len(session_dates) // 8),
                purge_sessions=1,
                embargo_sessions=1,
            )
            if len(session_dates) >= 8
            else []
        )
        dataset_hash = data_hash(
            [
                {
                    "signal_id": signal.signal_id,
                    "signal_time": signal.signal_time.isoformat(),
                    "audit": audit.result_classification,
                    "highest_target": audit.highest_target,
                }
                for signal, audit in rows
            ]
        )
        matrix = np.asarray([_vector(row) for row in all_signals], dtype=float)
        predicted = {
            head: predict_logistic_artifact(artifact, matrix)
            for head, artifact in artifacts.items()
        }
        with SessionLocal.begin() as session:
            session.add(
                MlDatasetRow(
                    dataset_id=dataset_id,
                    created_at=now,
                    metadata_json={
                        "sample_count": len(rows),
                        "eligible": len(rows),
                        "conditional_splits": head_splits,
                        "labels": list(HEADS),
                        "features": list(FEATURES),
                        "audit_version": 2,
                        "synthetic": False,
                    },
                )
            )
            session.add(
                MlModelRow(
                    model_id=model_id,
                    created_at=now,
                    model_type="ENTRY_AWARE_LOGISTIC",
                    metadata_json={
                        "model_id": model_id,
                        "dataset_id": dataset_id,
                        "experiment_id": experiment_id,
                        "sample_count": len(rows),
                        "feature_names": list(FEATURES),
                        "heads": list(HEADS),
                        "artifacts": artifacts,
                        "head_quality": {head: evaluation[head]["quality"] for head in HEADS},
                        "shadow_only": True,
                        "maturity": sample_maturity(len(rows)),
                        "created_at": now.isoformat(),
                        "feature_schema": FEATURE_SCHEMA_VERSION,
                        "policy_version": "adaptive-v1-h1-partial-trailing",
                        "train_dates": [
                            item.isoformat() for item in (folds[-1].train_dates if folds else ())
                        ],
                        "validation_dates": [
                            item.isoformat()
                            for item in (folds[-1].validation_dates if folds else ())
                        ],
                        "test_dates": [
                            item.isoformat() for item in (folds[-1].test_dates if folds else ())
                        ],
                    },
                )
            )
            session.add(
                MlExperimentRow(
                    experiment_id=experiment_id,
                    created_at=now,
                    data_hash=dataset_hash,
                    feature_schema=FEATURE_SCHEMA_VERSION,
                    policy_version="adaptive-v1-h1-partial-trailing",
                    model="ENTRY_AWARE_LOGISTIC",
                    hyperparameters={"steps": 400, "l2": 0.01, "random_seed": 0},
                    date_ranges={"folds": [serializable_fold(fold) for fold in folds]},
                    prior_trials=0,
                    metrics={
                        "oos_sample": sum(split["test"] for split in head_splits.values()),
                        "folds": len(folds),
                        "heads": evaluation,
                        "code_commit_sha": code_commit_sha(),
                        "promotion_candidate": False,
                    },
                )
            )
            session.add(MlEvaluationRow(model_id=model_id, created_at=now, metrics=evaluation))
            for index, signal in enumerate(all_signals):
                session.add(
                    MlPredictionRow(
                        signal_id=signal.signal_id,
                        model_id=model_id,
                        created_at=now,
                        predictions={
                            "entry_probability": predicted["entry"][index],
                            "stop_probability": predicted["stop"][index],
                            "h1_probability": predicted["h1"][index],
                            "h2_probability": predicted["h2"][index],
                            "h3_probability": predicted["h3"][index],
                            "sample_maturity": sample_maturity(len(rows)),
                            "head_quality": {head: evaluation[head]["quality"] for head in HEADS},
                            "mode": "SHADOW",
                        },
                    )
                )
        mark_job(
            "shadow_training",
            True,
            {
                "phase": "COMPLETED",
                "model_id": model_id,
                "dataset_id": dataset_id,
                "eligible": len(rows),
                "predictions": len(all_signals),
            },
        )
        return True
    except Exception as exc:
        mark_job("shadow_training", False, {"phase": "FAILED", "reason": type(exc).__name__})
        raise
