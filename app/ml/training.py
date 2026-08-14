from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.database.base import (
    MlDatasetRow,
    MlEvaluationRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlOutcomeRow,
    SessionLocal,
)
from app.ml.shadow import base_rate_predictor, calibration, classification_metrics, temporal_split
from app.operations.jobs import mark_job


def run_shadow_training(*, force: bool = False) -> bool:
    """Train a diagnostic baseline at the threshold; it has no Radar execution path."""
    settings = get_settings()
    now = datetime.now(UTC)
    mark_job("shadow_training", True, {"phase": "STARTED"})
    try:
        with SessionLocal() as session:
            rows = session.execute(
                select(MlFeatureSnapshotRow, MlOutcomeRow)
                .join(MlOutcomeRow, MlOutcomeRow.signal_id == MlFeatureSnapshotRow.signal_id)
                .where(
                    MlFeatureSnapshotRow.lifecycle == "FULLY_LABELED",
                    MlOutcomeRow.horizon == "120m",
                    MlOutcomeRow.status == "LABEL_AVAILABLE",
                )
                .order_by(MlFeatureSnapshotRow.signal_time)
            ).all()
            prior = session.scalar(
                select(MlModelRow).order_by(MlModelRow.created_at.desc()).limit(1)
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
        if prior and not force and isinstance(prior_count, int) and prior_count == len(rows):
            mark_job("shadow_training", True, {"phase": "UP_TO_DATE", "eligible": len(rows)})
            return False
        labels = [int(bool(outcome.outcome.get("hit_plus_1_percent"))) for _, outcome in rows]
        train, validation, test = temporal_split(len(labels))
        training_labels = [labels[index] for index in train]
        test_labels = [labels[index] for index in test]
        probabilities = base_rate_predictor(training_labels, len(test_labels))
        metrics: dict[str, Any] = classification_metrics(test_labels, probabilities)
        metrics["calibration"] = calibration(test_labels, probabilities)
        dataset_id = str(uuid4())
        model_id = f"shadow-baseline-{now.strftime('%Y%m%d%H%M%S')}"
        with SessionLocal.begin() as session:
            session.add(
                MlDatasetRow(
                    dataset_id=dataset_id,
                    created_at=now,
                    metadata_json={
                        "sample_count": len(rows),
                        "eligible": len(rows),
                        "excluded": 0,
                        "split": {
                            "train": len(train),
                            "validation": len(validation),
                            "test": len(test),
                        },
                        "label": "120m_hit_plus_1_percent",
                        "synthetic": False,
                    },
                )
            )
            session.add(
                MlModelRow(
                    model_id=model_id,
                    created_at=now,
                    model_type="BASE_RATE_DIAGNOSTIC",
                    metadata_json={
                        "model_id": model_id,
                        "dataset_id": dataset_id,
                        "sample_count": len(rows),
                        "artifact": {"type": "BASE_RATE", "probability": probabilities[0]},
                        "shadow_only": True,
                        "created_at": now.isoformat(),
                    },
                )
            )
            session.add(MlEvaluationRow(model_id=model_id, created_at=now, metrics=metrics))
        mark_job(
            "shadow_training",
            True,
            {
                "phase": "COMPLETED",
                "model_id": model_id,
                "dataset_id": dataset_id,
                "eligible": len(rows),
            },
        )
        return True
    except Exception as exc:
        mark_job("shadow_training", False, {"phase": "FAILED", "reason": type(exc).__name__})
        raise
