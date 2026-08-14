import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import select

from app.core.config import get_settings
from app.data.research_repository import ResearchRepository
from app.database.base import MarketBarRow, SessionLocal
from app.intraday.core import completed_frame, scan_symbol, stage_a_eligible
from app.intraday.outcomes import label_signal, level_audit
from app.intraday.repository import IntradayRepository
from app.risk.trade_plan_view import build_research_trade_plan
from app.universe.service import UniverseRepository


class IntradayResearchService:
    """Processes persisted canonical bars; network acquisition remains provider-isolated."""

    def __init__(
        self,
        session_factory: Any = SessionLocal,
        repository: IntradayRepository | None = None,
        reports: ResearchRepository | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.repository = repository or IntradayRepository(session_factory)
        self.reports = reports or ResearchRepository(session_factory)
        self.universe = UniverseRepository(session_factory)

    def _frames(self) -> dict[str, pd.DataFrame]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(MarketBarRow)
                .where(
                    MarketBarRow.provider_id == "yfinance-research",
                    MarketBarRow.timeframe == "15m",
                )
                .order_by(MarketBarRow.symbol, MarketBarRow.timestamp)
            ).all()
        grouped: dict[str, list[MarketBarRow]] = defaultdict(list)
        active = set(self.universe.active_symbols())
        for row in rows:
            if active and row.symbol not in active:
                continue
            grouped[row.symbol].append(row)
        frames: dict[str, pd.DataFrame] = {}
        for symbol, items in grouped.items():
            index = pd.DatetimeIndex([item.timestamp for item in items])
            if index.tz is None:
                index = index.tz_localize("UTC")
            frames[symbol] = pd.DataFrame(
                [
                    {
                        "open": row.open,
                        "high": row.high,
                        "low": row.low,
                        "close": row.close,
                        "volume": row.volume,
                    }
                    for row in items
                ],
                index=index,
            )
        return frames

    def run(self, now: datetime | None = None) -> dict[str, object]:
        settings = get_settings()
        current = now or datetime.now(UTC)
        candidates: list[dict[str, object]] = []
        stage_a_rejections: dict[str, int] = {}
        stage_b_symbols = 0
        frames = self._frames()
        for symbol, raw in frames.items():
            frame = completed_frame(raw, 15, current)
            if frame.empty:
                stage_a_rejections["NO_COMPLETED_DATA"] = (
                    stage_a_rejections.get("NO_COMPLETED_DATA", 0) + 1
                )
                continue
            latest = pd.Timestamp(frame.index[-1]).to_pydatetime()
            if current.astimezone(UTC) - latest.astimezone(UTC) > timedelta(
                minutes=settings.intraday_stale_minutes
            ):
                stage_a_rejections["STALE"] = stage_a_rejections.get("STALE", 0) + 1
                continue
            eligible, eligibility_reason = stage_a_eligible(frame)
            if not eligible:
                stage_a_rejections[eligibility_reason] = (
                    stage_a_rejections.get(eligibility_reason, 0) + 1
                )
                continue
            stage_b_symbols += 1
            received = current
            snapshot = scan_symbol(symbol, frame, received)
            if snapshot.radar_score >= 70:
                plan = build_research_trade_plan(
                    snapshot.payload(),
                    list(frame.low.tail(10)),
                    account_equity=Decimal(str(settings.paper_default_account_equity)),
                    risk_percent=Decimal(str(settings.max_risk_per_trade_percent)),
                    max_position_percent=Decimal(str(settings.max_position_percent)),
                    now=current,
                    stale_minutes=settings.intraday_stale_minutes,
                )
                disposition = self.repository.save_signal(
                    snapshot,
                    settings.intraday_signal_cooldown_minutes,
                    settings.intraday_signal_upgrade_points,
                    plan,
                )
                candidates.append(snapshot.payload() | {"disposition": disposition})

        def rank(row: dict[str, object]) -> tuple[int, str]:
            score = row["radar_score"]
            if not isinstance(score, int):
                raise ValueError("invalid radar score")
            return -score, str(row["symbol"])

        candidates.sort(key=rank)
        report: dict[str, object] = {
            "strategy_id": "radar-intraday-v1",
            "provider": "yfinance-research",
            "research_only": True,
            "data_timestamp": max(
                (row["timestamp"] for row in candidates),
                default=None,  # type: ignore[type-var]
            ),
            "candidates": candidates,
            "evaluated_symbols": len(frames),
            "stage_b_symbols": stage_b_symbols,
            "stage_a_rejections": stage_a_rejections,
        }
        self.reports.save_report("intraday_scan", "intraday-live", report)
        return report

    def update_outcomes(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        frames = self._frames()
        updated = 0
        for signal in self.repository.signals():
            symbol = str(signal["symbol"])
            if symbol not in frames:
                continue
            price = signal["price"]
            if not isinstance(price, (int, float)):
                raise ValueError("invalid signal price")
            plan = signal.get("trade_plan_snapshot")
            stop = (
                float(plan["stop_price"])
                if isinstance(plan, dict) and isinstance(plan.get("stop_price"), (int, float))
                else None
            )
            outcomes = label_signal(
                pd.Timestamp(signal["timestamp"]).to_pydatetime(),
                float(price),
                frames[symbol],
                current,
                stop=stop,
            )
            self.repository.save_outcomes(str(signal["signal_id"]), outcomes)
            if isinstance(plan, dict):
                completed = frames[symbol].loc[
                    frames[symbol].index <= current - timedelta(minutes=15)
                ]
                self.repository.save_audit(
                    str(signal["signal_id"]),
                    level_audit(pd.Timestamp(signal["timestamp"]).to_pydatetime(), completed, plan),
                    current,
                )
            updated += 1
        return updated


def safe_intraday_cycle() -> dict[str, object] | None:
    log = logging.getLogger(__name__)
    try:
        service = IntradayResearchService()
        report = service.run()
        updated = service.update_outcomes()
        from app.ml.training import run_shadow_training

        run_shadow_training()
        log.info(
            "intraday_scan_finished candidates=%d outcomes_updated=%d",
            len(report["candidates"]),  # type: ignore[arg-type]
            updated,
        )
        return report
    except Exception as exc:
        # Research provider/data failure must never take down the core worker/API.
        log.warning("intraday_research_unavailable error=%s", type(exc).__name__)
        return None
