import math
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.backtest.replay import replay_performance
from app.backtest.replay_models import ReplayResult
from app.database.base import ReplayEquityRow, ReplayRunRow, ReplayTradeRow, SessionLocal


def jsonable(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


class ReplayRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def save(self, result: ReplayResult, config_snapshot: dict[str, object]) -> None:
        summary = jsonable(replay_performance(result))
        with self.session_factory() as session:
            with session.begin():
                existing = session.get(ReplayRunRow, result.run_id)
                if existing:
                    existing.last_processed_timestamp = result.last_processed_timestamp
                    existing.status = "COMPLETED"
                    existing.result = summary
                else:
                    session.add(
                        ReplayRunRow(
                            run_id=result.run_id,
                            started_at=datetime.now(UTC),
                            last_processed_timestamp=result.last_processed_timestamp,
                            status="COMPLETED",
                            config_hash=result.config_hash,
                            config_snapshot=jsonable(config_snapshot),
                            result=summary,
                        )
                    )
                for trade in result.trades:
                    if not session.scalar(
                        select(ReplayTradeRow.id).where(
                            ReplayTradeRow.idempotency_key == trade.idempotency_key
                        )
                    ):
                        session.add(
                            ReplayTradeRow(
                                run_id=result.run_id,
                                idempotency_key=trade.idempotency_key,
                                portfolio_id=trade.portfolio_id,
                                strategy_id=trade.strategy_id,
                                symbol=trade.symbol,
                                payload=jsonable(asdict(trade)),
                            )
                        )
                if not session.scalar(
                    select(ReplayEquityRow.id).where(ReplayEquityRow.run_id == result.run_id)
                ):
                    for point in result.equity_curve:
                        session.add(
                            ReplayEquityRow(
                                run_id=result.run_id,
                                timestamp=point.timestamp,
                                equity=point.equity,
                                peak_equity=point.peak_equity,
                                drawdown=point.drawdown,
                            )
                        )

    def run(self, run_id: str) -> dict[str, object] | None:
        with self.session_factory() as session:
            row = session.get(ReplayRunRow, run_id)
            return (
                None
                if row is None
                else {
                    "run_id": row.run_id,
                    "status": row.status,
                    "config_hash": row.config_hash,
                    "last_processed_timestamp": row.last_processed_timestamp,
                    "performance": row.result,
                }
            )

    def trades(self, run_id: str) -> list[dict[str, object]]:
        with self.session_factory() as session:
            return [
                r.payload
                for r in session.scalars(
                    select(ReplayTradeRow).where(ReplayTradeRow.run_id == run_id)
                ).all()
            ]

    def equity(self, run_id: str) -> list[dict[str, object]]:
        with self.session_factory() as session:
            return [
                {
                    "timestamp": r.timestamp,
                    "equity": str(r.equity),
                    "peak_equity": str(r.peak_equity),
                    "drawdown": str(r.drawdown),
                }
                for r in session.scalars(
                    select(ReplayEquityRow)
                    .where(ReplayEquityRow.run_id == run_id)
                    .order_by(ReplayEquityRow.timestamp)
                ).all()
            ]
