from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.backtest.repository import jsonable
from app.data.canonical import CanonicalBar, dataset_hash
from app.database.base import (
    DataQualityRow,
    HistoricalDatasetRow,
    MarketBarRow,
    ProviderRow,
    ResearchReportRow,
    SessionLocal,
)


class ResearchRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def import_dataset(
        self,
        bars: list[CanonicalBar],
        manifest: dict[str, object],
        quality: dict[str, object],
    ) -> tuple[str, int, int]:
        if not bars:
            raise ValueError("empty dataset")
        dataset_id = str(manifest.get("dataset_id") or uuid4())
        digest = dataset_hash(bars)
        inserted = duplicates = 0
        with self.session_factory() as session:
            frozen = session.scalar(
                select(HistoricalDatasetRow).where(HistoricalDatasetRow.dataset_hash == digest)
            )
            if frozen is not None:
                return frozen.dataset_id, 0, len(bars)
        with self.session_factory() as session:
            with session.begin():
                provider = session.get(ProviderRow, "yfinance-research")
                if provider is None:
                    session.add(
                        ProviderRow(
                            provider_id="yfinance-research",
                            name="Yahoo Finance via yfinance",
                            data_mode="RESEARCH",
                            health="HEALTHY",
                            capabilities={"historical_bars": True, "indices": True},
                        )
                    )
                if session.get(HistoricalDatasetRow, dataset_id) is None:
                    stored_manifest = jsonable(
                        manifest
                        | {
                            "dataset_id": dataset_id,
                            "hash": digest,
                            "flags": ["RESEARCH_ONLY", "UNVERIFIED_SOURCE"],
                        }
                    )
                    session.add(
                        HistoricalDatasetRow(
                            dataset_id=dataset_id,
                            provider_id="yfinance-research",
                            manifest=stored_manifest,
                            dataset_hash=digest,
                        )
                    )
                    session.add(
                        DataQualityRow(
                            provider_id="yfinance-research",
                            day=datetime.now(UTC),
                            metrics=jsonable(quality),
                        )
                    )
                for bar in bars:
                    exists = session.scalar(
                        select(MarketBarRow.id).where(
                            MarketBarRow.provider_id == bar.provider,
                            MarketBarRow.symbol == bar.symbol,
                            MarketBarRow.timeframe == bar.timeframe.value,
                            MarketBarRow.timestamp == bar.timestamp,
                        )
                    )
                    if exists:
                        duplicates += 1
                        continue
                    session.add(
                        MarketBarRow(
                            symbol=bar.symbol,
                            timestamp=bar.timestamp,
                            open=float(bar.open),
                            high=float(bar.high),
                            low=float(bar.low),
                            close=float(bar.close),
                            volume=float(bar.volume),
                            timeframe=bar.timeframe.value,
                            provider_id=bar.provider,
                            dataset_id=dataset_id,
                            received_at=bar.received_at,
                            is_adjusted=bar.is_adjusted,
                            adjustment_type=bar.adjustment_type,
                            quality_flags=[flag.value for flag in bar.quality_flags],
                        )
                    )
                    inserted += 1
        return dataset_id, inserted, duplicates

    def bars(self, dataset_id: str, symbol: str | None = None) -> list[CanonicalBar]:
        from app.backtest.replay_models import Timeframe
        from app.data.canonical import QualityFlag

        with self.session_factory() as session:
            query = select(MarketBarRow).where(MarketBarRow.dataset_id == dataset_id)
            if symbol:
                query = query.where(MarketBarRow.symbol == symbol)
            rows = session.scalars(query.order_by(MarketBarRow.timestamp)).all()
            return [
                CanonicalBar(
                    symbol=row.symbol,
                    timestamp=row.timestamp,
                    timeframe=Timeframe(row.timeframe or "1d"),
                    open=Decimal(str(row.open)),
                    high=Decimal(str(row.high)),
                    low=Decimal(str(row.low)),
                    close=Decimal(str(row.close)),
                    volume=Decimal(str(row.volume)),
                    provider=row.provider_id or "yfinance-research",
                    received_at=row.received_at or row.timestamp,
                    is_adjusted=bool(row.is_adjusted),
                    adjustment_type=row.adjustment_type,
                    quality_flags=tuple(QualityFlag(flag) for flag in (row.quality_flags or [])),
                )
                for row in rows
            ]

    def save_report(self, report_type: str, dataset_id: str, payload: dict[str, object]) -> str:
        report_id = str(uuid4())
        with self.session_factory.begin() as session:
            session.add(
                ResearchReportRow(
                    report_id=report_id,
                    report_type=report_type,
                    dataset_id=dataset_id,
                    created_at=datetime.now(UTC),
                    payload=jsonable(payload),
                )
            )
        return report_id

    def latest_report(self, report_type: str) -> dict[str, object] | None:
        with self.session_factory() as session:
            row = session.scalar(
                select(ResearchReportRow)
                .where(ResearchReportRow.report_type == report_type)
                .order_by(ResearchReportRow.created_at.desc())
                .limit(1)
            )
            return None if row is None else row.payload
