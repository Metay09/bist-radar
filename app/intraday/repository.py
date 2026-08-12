from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.backtest.repository import jsonable
from app.database.base import (
    MlEvaluationRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlOutcomeRow,
    MlPredictionRow,
    SessionLocal,
)
from app.intraday.core import IntradaySnapshot
from app.intraday.outcomes import HorizonOutcome, lifecycle


class IntradayRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def save_signal(
        self, snapshot: IntradaySnapshot, cooldown_minutes: int, upgrade_points: int
    ) -> str:
        with self.session_factory() as session:
            previous = session.scalar(
                select(MlFeatureSnapshotRow)
                .where(
                    MlFeatureSnapshotRow.symbol == snapshot.symbol,
                    MlFeatureSnapshotRow.timeframe == snapshot.timeframe,
                    MlFeatureSnapshotRow.signal_time
                    >= snapshot.timestamp - timedelta(minutes=cooldown_minutes),
                )
                .order_by(MlFeatureSnapshotRow.signal_time.desc())
                .limit(1)
            )
            if previous is not None:
                old_score = int(previous.features.get("radar_score", 0))
                return (
                    "SIGNAL_UPGRADED"
                    if snapshot.radar_score >= old_score + upgrade_points
                    else "REJECTED_COOLDOWN"
                )
            try:
                session.add(
                    MlFeatureSnapshotRow(
                        signal_id=snapshot.signal_id,
                        symbol=snapshot.symbol,
                        timeframe=snapshot.timeframe,
                        signal_time=snapshot.timestamp,
                        lifecycle="OUTCOME_PENDING",
                        feature_schema_version=snapshot.feature_schema_version,
                        features=jsonable(snapshot.payload()),
                    )
                )
                session.commit()
            except IntegrityError:
                session.rollback()
                return "REJECTED_DUPLICATE"
        return "SIGNAL_CREATED"

    def signals(self, symbol: str | None = None) -> list[dict[str, object]]:
        with self.session_factory() as session:
            query = select(MlFeatureSnapshotRow)
            if symbol:
                query = query.where(MlFeatureSnapshotRow.symbol == symbol)
            rows = session.scalars(query.order_by(MlFeatureSnapshotRow.signal_time.desc())).all()
            return [dict(row.features) | {"lifecycle": row.lifecycle} for row in rows]

    def save_outcomes(self, signal_id: str, outcomes: dict[str, HorizonOutcome]) -> None:
        with self.session_factory.begin() as session:
            signal = session.get(MlFeatureSnapshotRow, signal_id)
            if signal is None:
                raise ValueError("unknown signal")
            for horizon, item in outcomes.items():
                row = session.scalar(
                    select(MlOutcomeRow).where(
                        MlOutcomeRow.signal_id == signal_id, MlOutcomeRow.horizon == horizon
                    )
                )
                payload = jsonable(asdict(item))
                if row is None:
                    session.add(
                        MlOutcomeRow(
                            signal_id=signal_id,
                            horizon=horizon,
                            status=item.status.value,
                            outcome=payload,
                        )
                    )
                else:
                    row.status, row.outcome = item.status.value, payload
            signal.lifecycle = lifecycle(outcomes)

    def outcomes(self) -> list[dict[str, object]]:
        with self.session_factory() as session:
            rows = session.scalars(select(MlOutcomeRow).order_by(MlOutcomeRow.id)).all()
            output = []
            for row in rows:
                signal = session.get(MlFeatureSnapshotRow, row.signal_id)
                features = {} if signal is None else dict(signal.features)
                output.append(features | dict(row.outcome) | {"signal_id": row.signal_id})
            return output

    def models(self) -> list[dict[str, object]]:
        with self.session_factory() as session:
            return [dict(row.metadata_json) for row in session.scalars(select(MlModelRow)).all()]

    def predictions(self) -> list[dict[str, object]]:
        with self.session_factory() as session:
            return [
                dict(row.predictions) | {"signal_id": row.signal_id, "model_id": row.model_id}
                for row in session.scalars(select(MlPredictionRow)).all()
            ]

    def evaluations(self) -> list[dict[str, object]]:
        with self.session_factory() as session:
            return [
                dict(row.metrics) | {"model_id": row.model_id}
                for row in session.scalars(select(MlEvaluationRow)).all()
            ]

    def status(self) -> dict[str, object]:
        signals = self.signals()
        return {
            "mode": "SHADOW",
            "allow_ml_to_change_radar": False,
            "observations": len(signals),
            "fully_labeled": sum(row["lifecycle"] == "FULLY_LABELED" for row in signals),
            "pending": sum(row["lifecycle"] != "FULLY_LABELED" for row in signals),
            "checked_at": datetime.now(UTC),
        }
