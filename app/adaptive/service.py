from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.adaptive.engine import AdaptiveConfig, evaluate_adaptive_setup
from app.backtest.repository import jsonable
from app.database.base import (
    AdaptiveEventRow,
    AdaptivePlanVersionRow,
    AdaptiveSetupRow,
    MlFeatureSnapshotRow,
    SessionLocal,
)
from app.intraday.service import IntradayResearchService
from app.operations.jobs import mark_job


class AdaptiveDecisionService:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def update(self, now: datetime | None = None, *, ttl: int = 8, holding: int = 16) -> int:
        current = now or datetime.now(UTC)
        mark_job("adaptive_lifecycle", True, {"phase": "STARTED"})
        frames = IntradayResearchService(self.session_factory)._frames()
        config = AdaptiveConfig(entry_ttl_bars=ttl, max_holding_bars=holding)
        with self.session_factory() as session:
            signals = session.scalars(
                select(MlFeatureSnapshotRow).order_by(MlFeatureSnapshotRow.signal_time)
            ).all()
        updated = 0
        skipped_missing_plan = 0
        for signal in signals:
            plan = signal.features.get("trade_plan_snapshot")
            if not isinstance(plan, dict) or signal.symbol not in frames:
                continue
            setup_id = f"{config.policy_version}:{signal.signal_id}"
            with self.session_factory() as session:
                existing = session.get(AdaptiveSetupRow, setup_id)
                if existing is not None and existing.outcome is not None:
                    continue
            try:
                result = evaluate_adaptive_setup(
                    signal.signal_time,
                    frames[signal.symbol],
                    dict(signal.features),
                    plan,
                    current,
                    config=config,
                )
            except ValueError as exc:
                if str(exc) != "complete immutable trade plan required":
                    raise
                skipped_missing_plan += 1
                continue
            with self.session_factory.begin() as session:
                row = session.get(AdaptiveSetupRow, setup_id)
                if row is None:
                    row = AdaptiveSetupRow(
                        setup_id=setup_id,
                        signal_id=signal.signal_id,
                        symbol=signal.symbol,
                        policy_version=config.policy_version,
                        state=result.state,
                        health=result.health,
                        current_plan_version=len(result.plans),
                        signal_time=signal.signal_time,
                        action=jsonable(result.action),
                        metrics=jsonable(result.metrics),
                        config={
                            "entry_ttl_bars": ttl,
                            "max_holding_bars": holding,
                            "min_risk_reward": config.min_risk_reward,
                            "profit_policy": config.profit_policy,
                        },
                        updated_at=current,
                    )
                    session.add(row)
                row.state, row.health = result.state, result.health
                row.entry_time, row.entry_price = result.entry_time, _decimal(result.entry_price)
                row.initial_stop, row.active_stop = (
                    _decimal(result.initial_stop),
                    _decimal(result.active_stop),
                )
                row.exit_time, row.exit_price = result.exit_time, _decimal(result.exit_price)
                row.outcome, row.highest_target = result.outcome, result.highest_target
                row.action, row.metrics, row.updated_at = (
                    jsonable(result.action),
                    jsonable(result.metrics),
                    current,
                )
                existing_events = (
                    session.scalar(
                        select(func.count())
                        .select_from(AdaptiveEventRow)
                        .where(AdaptiveEventRow.setup_id == setup_id)
                    )
                    or 0
                )
                for item in result.events[existing_events:]:
                    normalized = dict(item)
                    normalized["payload"] = jsonable(normalized["payload"])
                    session.add(AdaptiveEventRow(setup_id=setup_id, **normalized))
                existing_plans = (
                    session.scalar(
                        select(func.count())
                        .select_from(AdaptivePlanVersionRow)
                        .where(AdaptivePlanVersionRow.setup_id == setup_id)
                    )
                    or 0
                )
                for item in result.plans[existing_plans:]:
                    session.add(AdaptivePlanVersionRow(setup_id=setup_id, **item))
            updated += 1
        mark_job(
            "adaptive_lifecycle",
            True,
            {
                "phase": "COMPLETED",
                "updated": updated,
                "skipped_missing_plan": skipped_missing_plan,
                "coverage_degraded": skipped_missing_plan > 0,
            },
        )
        return updated

    def detail(self, symbol: str) -> dict[str, object] | None:
        with self.session_factory() as session:
            setup = session.scalar(
                select(AdaptiveSetupRow)
                .where(AdaptiveSetupRow.symbol == symbol.upper())
                .order_by(AdaptiveSetupRow.signal_time.desc())
                .limit(1)
            )
            if setup is None:
                return None
            events = session.scalars(
                select(AdaptiveEventRow)
                .where(AdaptiveEventRow.setup_id == setup.setup_id)
                .order_by(AdaptiveEventRow.sequence)
            ).all()
            plans = session.scalars(
                select(AdaptivePlanVersionRow)
                .where(AdaptivePlanVersionRow.setup_id == setup.setup_id)
                .order_by(AdaptivePlanVersionRow.version)
            ).all()
        return {
            "setup_id": setup.setup_id,
            "signal_id": setup.signal_id,
            "symbol": setup.symbol,
            "policy_version": setup.policy_version,
            "state": setup.state,
            "health": setup.health,
            "action": setup.action,
            "entry_time": setup.entry_time,
            "entry_price": float(setup.entry_price) if setup.entry_price is not None else None,
            "initial_stop": float(setup.initial_stop) if setup.initial_stop is not None else None,
            "active_stop": float(setup.active_stop) if setup.active_stop is not None else None,
            "exit_time": setup.exit_time,
            "exit_price": float(setup.exit_price) if setup.exit_price is not None else None,
            "outcome": setup.outcome,
            "highest_target": setup.highest_target,
            "metrics": setup.metrics,
            "config": setup.config,
            "plans": [
                {
                    "version": x.version,
                    "created_at": x.created_at,
                    "effective_at": x.effective_at,
                    "reason": x.reason,
                    "plan": x.plan,
                }
                for x in plans
            ],
            "events": [
                {
                    "sequence": x.sequence,
                    "event_time": x.event_time,
                    "event_type": x.event_type,
                    "state_from": x.state_from,
                    "state_to": x.state_to,
                    "payload": x.payload,
                }
                for x in events
            ],
        }

    def analytics(self) -> dict[str, object]:
        with self.session_factory() as session:
            rows = session.scalars(select(AdaptiveSetupRow)).all()
            events = session.scalars(select(AdaptiveEventRow)).all()
        entered = [x for x in rows if x.entry_time is not None]
        terminal = [x for x in rows if x.outcome is not None]
        values = [
            float(x.metrics["realized_r_after_cost"])
            for x in terminal
            if isinstance(x.metrics.get("realized_r_after_cost"), (int, float))
        ]
        outcomes: dict[str, int] = {}
        for row in terminal:
            outcomes[str(row.outcome)] = outcomes.get(str(row.outcome), 0) + 1
        by_setup: dict[str, list[AdaptiveEventRow]] = {}
        for item in events:
            by_setup.setdefault(item.setup_id, []).append(item)
        entry_minutes: list[float] = []
        h1_minutes: list[float] = []
        for row in rows:
            if row.entry_time is not None:
                entry_minutes.append((row.entry_time - row.signal_time).total_seconds() / 60)
                h1 = next(
                    (
                        item
                        for item in by_setup.get(row.setup_id, [])
                        if item.event_type == "H1_TOUCHED"
                    ),
                    None,
                )
                if h1 is not None:
                    h1_minutes.append((h1.event_time - row.entry_time).total_seconds() / 60)
        return {
            "policy_version": "adaptive-v1-h1-partial-trailing",
            "planned": len(rows),
            "entry_activated": len(entered),
            "activation_rate": len(entered) / len(rows) if rows else None,
            "outcomes": outcomes,
            "median_realized_r": sorted(values)[len(values) // 2] if values else None,
            "expected_r": sum(values) / len(values) if values else None,
            "median_time_to_entry_minutes": _median(entry_minutes),
            "median_time_to_h1_minutes": _median(h1_minutes),
            "static_vs_adaptive_oos": {
                "status": "INSUFFICIENT_COMPARABLE_OOS",
                "adaptive_is_better": False,
                "reason": "Static v2 ve adaptive-v1 için ortak terminal OOS pencere henüz yok",
            },
        }


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
