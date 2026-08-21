"""Bounded yfinance intraday backfill and 5m freshness research.

This is deliberately separate from operational 15m ingestion. Provider output
is research-only, unverified and fails closed on any availability problem.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.backtest.replay_models import Timeframe
from app.core.config import get_settings
from app.data.research_repository import ResearchRepository
from app.data.yfinance_provider import YFinanceResearchProvider
from app.database.base import (
    AdaptiveSetupRow,
    DataFreshnessObservationRow,
    MarketBarRow,
    MlFeatureSnapshotRow,
    SessionLocal,
)


@dataclass(frozen=True)
class BackfillResult:
    timeframe: str
    requested_symbols: int
    found_symbols: int
    inserted_bars: int
    duplicate_bars: int
    failures: dict[str, str]
    provider_seconds: float
    persistence_seconds: float
    provider: str = "yfinance-research"
    status: str = "RESEARCH_ONLY_UNVERIFIED"


def prioritized_5m_symbols(
    liquid_symbols: Sequence[str],
    shortlist: Sequence[str],
    active_setups: Sequence[str],
    limit: int = 30,
) -> list[str]:
    """Union priorities without silently expanding 5m ingestion to all BIST."""
    if limit < 1:
        raise ValueError("positive limit required")
    ordered: list[str] = []
    for group in (active_setups, shortlist, liquid_symbols):
        for raw in group:
            symbol = raw.strip().upper()
            if symbol and symbol not in ordered:
                ordered.append(symbol)
    return ordered[:limit]


class IntradayResearchBackfill:
    def __init__(
        self, provider: YFinanceResearchProvider | None = None, session_factory: Any = SessionLocal
    ) -> None:
        settings = get_settings()
        self.provider = provider or YFinanceResearchProvider(
            price_mode=settings.research_price_mode, attempts=settings.research_download_attempts
        )
        self.repository = ResearchRepository(session_factory)
        self.session_factory = session_factory

    def active_5m_universe(
        self, liquid_symbols: Sequence[str], limit: int | None = None
    ) -> list[str]:
        with self.session_factory() as session:
            shortlist = session.scalars(
                select(MlFeatureSnapshotRow.symbol)
                .order_by(MlFeatureSnapshotRow.signal_time.desc())
                .limit(100)
            ).all()
            active = session.scalars(
                select(AdaptiveSetupRow.symbol).where(AdaptiveSetupRow.outcome.is_(None)).limit(100)
            ).all()
        return prioritized_5m_symbols(
            liquid_symbols, shortlist, active, limit or get_settings().research_5m_liquid_symbols
        )

    def run(
        self, symbols: Sequence[str], timeframe: Timeframe, *, now: datetime | None = None
    ) -> BackfillResult:
        if timeframe not in {Timeframe.M5, Timeframe.M15}:
            raise ValueError("research backfill supports 5m and 15m only")
        current = now or datetime.now(UTC)
        settings = get_settings()
        lookback = (
            settings.research_5m_lookback_days
            if timeframe == Timeframe.M5
            else settings.research_15m_lookback_days
        )
        # Stay just inside the configured/probed provider window. Empty or rejected
        # responses are persisted as failures; older data is never fabricated.
        end: date = current.date() + timedelta(days=1)
        start: date = end - timedelta(days=lookback)
        provider_start = monotonic()
        results, failures = self.provider.download_many_intraday(
            list(symbols), start, end, timeframe, settings.research_batch_size
        )
        provider_seconds = monotonic() - provider_start
        bars = [
            bar for result in results.values() for bar in result.bars if bar.timestamp <= current
        ]
        persistence_start = monotonic()
        inserted = duplicates = 0
        if bars:
            manifest: dict[str, object] = {
                "provider": self.provider.metadata.provider_id,
                "flags": ["RESEARCH_ONLY", "UNVERIFIED_SOURCE", "PROVIDER_RANGE_LIMITED"],
                "timeframe": timeframe.value,
                "requested_start": start.isoformat(),
                "requested_end": end.isoformat(),
                "actual_start": min(bar.timestamp for bar in bars),
                "actual_end": max(bar.timestamp for bar in bars),
                "requested_symbols": len(symbols),
                "found_symbols": len(results),
                "failures": failures,
            }
            _, inserted, duplicates = self.repository.import_dataset(bars, manifest, manifest)
            if timeframe == Timeframe.M5:
                persisted_at = datetime.now(UTC)
                self.record_many_5m_availability(bars, persisted_at)
        return BackfillResult(
            timeframe.value,
            len(symbols),
            len(results),
            inserted,
            duplicates,
            failures,
            round(provider_seconds, 3),
            round(monotonic() - persistence_start, 3),
        )

    def record_5m_availability(
        self,
        symbol: str,
        bar_close_time: datetime,
        provider_available_time: datetime,
        persist_time: datetime,
    ) -> bool:
        if not (bar_close_time <= provider_available_time <= persist_time):
            raise ValueError("freshness timestamps must be monotonic")
        try:
            with self.session_factory.begin() as session:
                session.add(
                    DataFreshnessObservationRow(
                        provider_id=self.provider.metadata.provider_id,
                        symbol=symbol.upper(),
                        timeframe="5m",
                        bar_close_time=bar_close_time,
                        provider_available_time=provider_available_time,
                        persist_time=persist_time,
                        metadata_json={"source": "observed", "research_only": True},
                    )
                )
            return True
        except IntegrityError:
            return False

    def record_many_5m_availability(self, bars: Sequence[Any], persist_time: datetime) -> int:
        max_age = timedelta(minutes=get_settings().research_latency_max_observation_age_minutes)
        with self.session_factory() as session:
            keys = {
                (symbol, stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp)
                for symbol, stamp in session.execute(
                    select(
                        DataFreshnessObservationRow.symbol,
                        DataFreshnessObservationRow.bar_close_time,
                    ).where(DataFreshnessObservationRow.timeframe == "5m")
                ).all()
            }
        inserted = 0
        with self.session_factory.begin() as session:
            for bar in bars:
                close_time = bar.timestamp + timedelta(minutes=5)
                observation_age = bar.received_at - close_time
                if (
                    (bar.symbol, close_time) in keys
                    or observation_age < timedelta(0)
                    or observation_age > max_age
                ):
                    continue
                session.add(
                    DataFreshnessObservationRow(
                        provider_id=self.provider.metadata.provider_id,
                        symbol=bar.symbol,
                        timeframe="5m",
                        bar_close_time=close_time,
                        provider_available_time=bar.received_at,
                        persist_time=max(persist_time, bar.received_at),
                        metadata_json={
                            "source": "provider_observation",
                            "research_only": True,
                            "provider_latency_seconds": (
                                bar.received_at - close_time
                            ).total_seconds(),
                            "total_latency_seconds": (
                                max(persist_time, bar.received_at) - close_time
                            ).total_seconds(),
                        },
                    )
                )
                inserted += 1
        return inserted

    def latency_report(self) -> dict[str, object]:
        with self.session_factory() as session:
            rows = session.scalars(
                select(DataFreshnessObservationRow).where(
                    DataFreshnessObservationRow.timeframe == "5m"
                )
            ).all()
        provider = [
            (row.provider_available_time - row.bar_close_time).total_seconds() for row in rows
        ]
        persist = [(row.persist_time - row.bar_close_time).total_seconds() for row in rows]
        symbols = {row.symbol for row in rows}
        minimum = get_settings().research_latency_min_symbols

        def percentile(values: list[float], q: float) -> float | None:
            return round(float(np.percentile(values, q)), 3) if values else None

        mature = len(symbols) >= minimum and len(rows) >= len(symbols) * 20
        return {
            "status": "MATURE" if mature else "INSUFFICIENT_SESSION_OBSERVATIONS",
            "symbols": len(symbols),
            "observations": len(rows),
            "provider_latency_seconds": {
                "p50": percentile(provider, 50),
                "p95": percentile(provider, 95),
            },
            "end_to_end_latency_seconds": {
                "p50": percentile(persist, 50),
                "p95": percentile(persist, 95),
            },
            "production_dependency_allowed": False,
            "reason": "5m remains research-only until full-session maturity and reliability review",
        }


def latest_liquidity_symbols(session_factory: Any = SessionLocal, limit: int = 30) -> list[str]:
    """Rank from observed 15m traded value; no fabricated liquidity metadata."""
    with session_factory() as session:
        rows = session.scalars(select(MarketBarRow).where(MarketBarRow.timeframe == "15m")).all()
    totals: dict[str, float] = {}
    for row in rows:
        totals[row.symbol] = totals.get(row.symbol, 0.0) + float(row.close) * float(row.volume)
    return [
        symbol for symbol, _ in sorted(totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]
