from __future__ import annotations

from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.database.base import (
    MlDatasetRow,
    MlEvaluationRow,
    MlFeatureSnapshotRow,
    MlModelRow,
    MlOutcomeRow,
    MlPredictionRow,
    SessionLocal,
    SignalAuditRow,
    WorkerStateRow,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")
HORIZONS = ("15m", "30m", "60m", "120m", "EOD", "NEXT_DAY")


def _local_day(value: datetime) -> date:
    return value.astimezone(ISTANBUL).date()


def _minutes(start: datetime, end: datetime | None) -> int | None:
    return round((end - start).total_seconds() / 60) if end else None


class SignalIntelligence:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def records(
        self,
        *,
        symbol: str | None = None,
        day: date | None = None,
        score_bucket: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        size = min(max(page_size, 1), 100)
        selected_page = max(page, 1)
        with self.session_factory() as session:
            query = select(MlFeatureSnapshotRow)
            if symbol:
                query = query.where(MlFeatureSnapshotRow.symbol == symbol.upper())
            if day:
                start = datetime.combine(day, datetime.min.time(), tzinfo=ISTANBUL)
                query = query.where(
                    MlFeatureSnapshotRow.signal_time >= start,
                    MlFeatureSnapshotRow.signal_time < start + timedelta(days=1),
                )
            database_page = not score_bucket and not status
            total = (
                session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
                or 0
            )
            if database_page:
                query = query.offset((selected_page - 1) * size).limit(size)
            rows = session.scalars(query.order_by(MlFeatureSnapshotRow.signal_time.desc())).all()
            signal_ids = [row.signal_id for row in rows]
            if not signal_ids:
                return [], 0
            outcomes = session.scalars(
                select(MlOutcomeRow).where(MlOutcomeRow.signal_id.in_(signal_ids))
            ).all()
            audits = {
                row.signal_id: row
                for row in session.scalars(
                    select(SignalAuditRow).where(SignalAuditRow.signal_id.in_(signal_ids))
                ).all()
            }
            predictions: dict[str, MlPredictionRow] = {}
            for prediction in session.scalars(
                select(MlPredictionRow)
                .where(MlPredictionRow.signal_id.in_(signal_ids))
                .order_by(MlPredictionRow.created_at.desc())
            ).all():
                predictions.setdefault(prediction.signal_id, prediction)
        by_signal: dict[str, dict[str, MlOutcomeRow]] = {}
        for outcome in outcomes:
            by_signal.setdefault(outcome.signal_id, {})[outcome.horizon] = outcome
        result: list[dict[str, Any]] = []
        for row in rows:
            features = dict(row.features)
            score = int(features.get("radar_score", 0))
            bucket = "90+" if score >= 90 else "80-89" if score >= 80 else "70-79"
            if score_bucket and bucket != score_bucket:
                continue
            metrics: dict[str, object] = {}
            for horizon, outcome in by_signal.get(row.signal_id, {}).items():
                metrics[horizon] = dict(outcome.outcome)
            audit = audits.get(row.signal_id)
            audit_payload: dict[str, object] = {
                "ordering": audit.ordering if audit else "NONE",
                "result_classification": audit.result_classification if audit else "PENDING",
            }
            if audit:
                for name in (
                    "entry_hit_at",
                    "stop_hit_at",
                    "target1_hit_at",
                    "target2_hit_at",
                    "target3_hit_at",
                    "terminal_at",
                ):
                    stamp = getattr(audit, name)
                    audit_payload[name] = stamp
                    audit_payload[name.replace("_at", "_minutes")] = _minutes(
                        row.signal_time, stamp
                    )
                audit_payload |= {
                    "audit_version": audit.audit_version,
                    "entry_price": float(audit.entry_price)
                    if audit.entry_price is not None
                    else None,
                    "highest_target": audit.highest_target,
                    "bars_to_entry": audit.bars_to_entry,
                    "bars_after_entry": audit.bars_after_entry,
                }
            prediction = predictions.get(row.signal_id)
            record = features | {
                "signal_id": row.signal_id,
                "signal_timestamp": row.signal_time,
                "reference_price": features.get("price"),
                "radar_class": features.get("classification"),
                "lifecycle": row.lifecycle,
                "score_bucket": bucket,
                "outcomes": metrics,
                "audit": audit_payload,
                "shadow_prediction": dict(prediction.predictions) if prediction else None,
                "has_trade_plan_snapshot": isinstance(features.get("trade_plan_snapshot"), dict),
            }
            if status and status not in {
                row.lifecycle,
                str(audit_payload["result_classification"]),
            }:
                continue
            result.append(record)
        if database_page:
            return result, total
        total = len(result)
        start_index = (selected_page - 1) * size
        return result[start_index : start_index + size], total

    def symbol_results(self, symbol: str) -> list[dict[str, Any]]:
        return self.records(symbol=symbol, page_size=100)[0]

    def daily(self, days: int = 7) -> list[dict[str, object]]:
        records, _ = self.records(page_size=100)
        # Analytics is intentionally bounded by fetching pages, not an unbounded UI response.
        page = 2
        while True:
            chunk, _ = self.records(page=page, page_size=100)
            if not chunk:
                break
            records.extend(chunk)
            page += 1
        grouped: dict[date, list[dict[str, Any]]] = {}
        for row in records:
            grouped.setdefault(_local_day(row["signal_timestamp"]), []).append(row)
        output = []
        for day, members in sorted(grouped.items(), reverse=True)[:days]:
            output.append(
                {
                    "date": day,
                    "total": len(members),
                    "very_strong": sum(
                        x.get("radar_class") == "VERY_STRONG_CANDIDATE" for x in members
                    ),
                    "strong": sum(x.get("radar_class") == "STRONG_CANDIDATE" for x in members),
                    "candidate": sum(x.get("radar_class") == "CANDIDATE" for x in members),
                    "completed": sum(x.get("lifecycle") == "FULLY_LABELED" for x in members),
                    "pending": sum(x.get("lifecycle") == "OUTCOME_PENDING" for x in members),
                    "partial": sum(x.get("lifecycle") == "PARTIALLY_LABELED" for x in members),
                    "h1_hits": sum(x["audit"].get("target1_hit_at") is not None for x in members),
                    "h2_hits": sum(x["audit"].get("target2_hit_at") is not None for x in members),
                    "h3_hits": sum(x["audit"].get("target3_hit_at") is not None for x in members),
                    "entered": sum(x["audit"].get("entry_hit_at") is not None for x in members),
                    "no_entry": sum(
                        x["audit"].get("result_classification") == "NO_ENTRY" for x in members
                    ),
                    "stopped": sum(
                        x["audit"].get("result_classification") == "STOPPED" for x in members
                    ),
                }
            )
        return output

    def analytics(self, group: str = "score") -> list[dict[str, object]]:
        records: list[dict[str, Any]] = []
        page = 1
        while True:
            chunk, _ = self.records(page=page, page_size=100)
            if not chunk:
                break
            records.extend(chunk)
            page += 1
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in records:
            if group == "score":
                key = str(row["score_bucket"])
            elif group == "rvol":
                value = float(row.get("rvol", 0))
                key = (
                    "<1"
                    if value < 1
                    else "1-2"
                    if value < 2
                    else "2-3"
                    if value < 3
                    else "3-5"
                    if value < 5
                    else "5+"
                )
            else:
                value = int(row.get("early_momentum_score", 0))
                key = (
                    "<60"
                    if value < 60
                    else "60-79"
                    if value < 80
                    else "80-89"
                    if value < 90
                    else "90+"
                )
            buckets.setdefault(key, []).append(row)
        output = []
        for key, members in sorted(buckets.items()):
            mature = [
                x
                for x in members
                if isinstance(x["outcomes"], dict)
                and x["outcomes"].get("120m", {}).get("status") == "LABEL_AVAILABLE"
            ]

            def values(field: str, mature_rows: list[dict[str, Any]] = mature) -> list[float]:
                return [
                    float(x["outcomes"]["120m"][field])
                    for x in mature_rows
                    if isinstance(x["outcomes"]["120m"].get(field), (int, float))
                ]

            mfe, mae = values("maximum_favorable_excursion"), values("maximum_adverse_excursion")
            output.append(
                {
                    "bucket": key,
                    "unique_signals": len(members),
                    "mature_signals": len(mature),
                    "h1_hit_rate": sum(x["audit"].get("target1_hit_at") is not None for x in mature)
                    / len(mature)
                    if mature
                    else None,
                    "h2_hit_rate": sum(x["audit"].get("target2_hit_at") is not None for x in mature)
                    / len(mature)
                    if mature
                    else None,
                    "h3_hit_rate": sum(x["audit"].get("target3_hit_at") is not None for x in mature)
                    / len(mature)
                    if mature
                    else None,
                    "stop_first_rate": sum(
                        x["audit"].get("ordering") == "STOP_FIRST" for x in mature
                    )
                    / len(mature)
                    if mature
                    else None,
                    "average_mfe": sum(mfe) / len(mfe) if mfe else None,
                    "median_mfe": median(mfe) if mfe else None,
                    "average_mae": sum(mae) / len(mae) if mae else None,
                    "median_mae": median(mae) if mae else None,
                }
            )
        return output

    def shadow_status(self, symbol: str | None = None) -> dict[str, object]:
        with self.session_factory() as session:
            condition = (
                MlFeatureSnapshotRow.symbol == symbol.upper()
                if symbol
                else MlFeatureSnapshotRow.signal_id.is_not(None)
            )
            observations = (
                session.scalar(
                    select(func.count()).select_from(MlFeatureSnapshotRow).where(condition)
                )
                or 0
            )
            labeled = (
                session.scalar(
                    select(func.count())
                    .select_from(MlFeatureSnapshotRow)
                    .where(condition, MlFeatureSnapshotRow.lifecycle == "FULLY_LABELED")
                )
                or 0
            )
            models = session.scalars(
                select(MlModelRow).order_by(MlModelRow.created_at.desc())
            ).all()
            datasets = session.scalars(
                select(MlDatasetRow).order_by(MlDatasetRow.created_at.desc())
            ).all()
            evaluations = session.scalar(select(func.count()).select_from(MlEvaluationRow)) or 0
            predictions = session.scalar(select(func.count()).select_from(MlPredictionRow)) or 0
            training = session.get(WorkerStateRow, "shadow_training")
            eligible = (
                session.scalar(
                    select(func.count())
                    .select_from(SignalAuditRow)
                    .where(
                        SignalAuditRow.audit_version == 2,
                        SignalAuditRow.result_classification.in_(
                            (
                                "NO_ENTRY",
                                "STOPPED",
                                "H3_REACHED",
                                "EXPIRED_H0",
                                "EXPIRED_H1",
                                "EXPIRED_H2",
                            )
                        ),
                    )
                )
                or 0
            )
            latest_model = models[0] if models else None
            latest_evaluation = (
                session.scalar(
                    select(MlEvaluationRow)
                    .where(MlEvaluationRow.model_id == latest_model.model_id)
                    .order_by(MlEvaluationRow.created_at.desc())
                    .limit(1)
                )
                if latest_model
                else None
            )
        threshold = 200
        state = (
            "MODEL_READY"
            if models
            else "EĞİTİM_BEKLİYOR"
            if eligible >= threshold
            else "VERİ_TOPLANIYOR"
        )
        reasons: list[str] = []
        if symbol and not observations:
            reasons.append("Radar sinyali yok")
        if observations and not labeled:
            reasons.append("Henüz mature outcome yok")
        if not models:
            reasons.append("Training model henüz yok")
        return {
            "mode": "SHADOW",
            "allow_ml_to_change_radar": False,
            "observations": observations,
            "labeled": labeled,
            "training_eligible": eligible,
            "excluded": observations - eligible,
            "training_threshold": threshold,
            "progress_percent": min(100, round(eligible / threshold * 100, 1)),
            "remaining": max(0, threshold - eligible),
            "status": state,
            "reasons": reasons,
            "datasets": len(datasets),
            "evaluations": evaluations,
            "predictions": predictions,
            "current_model": models[0].model_id if models else None,
            "model_type": latest_model.model_type if latest_model else None,
            "sample_maturity": latest_model.metadata_json.get("maturity") if latest_model else None,
            "evaluation": latest_evaluation.metrics if latest_evaluation else None,
            "last_dataset_update": datasets[0].created_at if datasets else None,
            "last_training_attempt": training.last_started_at if training else None,
            "last_successful_training": training.last_success_at if training else None,
        }

    def latest_shadow_prediction(self, symbol: str) -> dict[str, object]:
        """Return advisory output for the latest persisted signal only."""
        with self.session_factory() as session:
            signal = session.scalar(
                select(MlFeatureSnapshotRow)
                .where(MlFeatureSnapshotRow.symbol == symbol.upper())
                .order_by(
                    MlFeatureSnapshotRow.signal_time.desc(),
                    MlFeatureSnapshotRow.signal_id.desc(),
                )
                .limit(1)
            )
            prediction = (
                session.scalar(
                    select(MlPredictionRow)
                    .where(MlPredictionRow.signal_id == signal.signal_id)
                    .order_by(MlPredictionRow.created_at.desc(), MlPredictionRow.id.desc())
                    .limit(1)
                )
                if signal
                else None
            )
            model = session.get(MlModelRow, prediction.model_id) if prediction else None
        raw_maturity = (
            str(model.metadata_json.get("maturity", "INSUFFICIENT")).upper()
            if model
            else "INSUFFICIENT"
        )
        maturity = next(
            (
                state
                for state in ("MATURE", "MODERATE", "EARLY", "EXPERIMENTAL")
                if state in raw_maturity
            ),
            "INSUFFICIENT",
        )
        return {
            "mode": "SHADOW",
            "radar_decision_effect": "NONE",
            "allow_ml_to_change_radar": False,
            "symbol": symbol.upper(),
            "signal_id": signal.signal_id if signal else None,
            "signal_time": signal.signal_time if signal else None,
            "status": "AVAILABLE" if prediction else "LEARNING",
            "model_id": prediction.model_id if prediction else None,
            "model_maturity": maturity,
            "prediction_created_at": prediction.created_at if prediction else None,
            "prediction": dict(prediction.predictions) if prediction else None,
        }
