from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select

from app.database.base import MlExperimentRow, ResearchBaselineRow, SessionLocal
from app.ml.research_lab import CHAMPION_BASELINE_ID, champion_manifest


def freeze_champion(session_factory: Any = SessionLocal) -> str:
    """Insert once; historical baselines are never updated or overwritten."""
    with session_factory.begin() as session:
        if session.get(ResearchBaselineRow, CHAMPION_BASELINE_ID) is None:
            session.add(
                ResearchBaselineRow(
                    baseline_id=CHAMPION_BASELINE_ID,
                    created_at=datetime.now(UTC),
                    immutable=True,
                    manifest=champion_manifest(),
                )
            )
    return CHAMPION_BASELINE_ID


def register_experiment(
    *,
    data_hash: str,
    feature_schema: str,
    policy_version: str,
    model: str,
    hyperparameters: dict[str, object],
    date_ranges: dict[str, object],
    metrics: dict[str, object],
    session_factory: Any = SessionLocal,
) -> str:
    with session_factory.begin() as session:
        prior = (
            session.scalar(
                select(func.count())
                .select_from(MlExperimentRow)
                .where(MlExperimentRow.data_hash == data_hash)
            )
            or 0
        )
        experiment_id = f"exp-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        session.add(
            MlExperimentRow(
                experiment_id=experiment_id,
                created_at=datetime.now(UTC),
                data_hash=data_hash,
                feature_schema=feature_schema,
                policy_version=policy_version,
                model=model,
                hyperparameters=hyperparameters,
                date_ranges=date_ranges,
                prior_trials=int(prior),
                metrics=metrics,
            )
        )
    return experiment_id


def promotion_allowed(_: dict[str, object]) -> bool:
    """Milestone hard boundary: challengers can never auto-promote."""
    return False
