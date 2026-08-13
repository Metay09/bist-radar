import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select

from app.data.yfinance_provider import YFinanceResearchProvider
from app.database.base import (
    MarketBarRow,
    SessionLocal,
    UniverseMembershipRow,
    UniverseSnapshotRow,
    UniverseSymbolRow,
)

SOURCE_URL = "https://kap.org.tr/tr/Pazarlar"
ALLOWED_EQUITY_MARKETS = {
    "YILDIZ PAZAR",
    "ANA PAZAR",
    "ALT PAZAR",
    "YAKIN İZLEME PAZARI",
    "PİYASA ÖNCESİ İŞLEM PLATFORMU",
    "GÖZALTI PAZARI",
}
EXCLUDED_MARKETS = {
    "GİRİŞİM SERMAYESİ PAZARI": "FUND",
    "YAPILANDIRILMIŞ ÜRÜNLER VE FON PAZARI": "STRUCTURED_OR_FUND",
    "EMTİA PAZARI": "COMMODITY",
    "KESİN ALIM SATIM PAZARI": "DEBT_INSTRUMENT",
    "KESİN ALIM SATIM PAZARI-NİTELİKLİ YATIRIMCILAR ARASINDA": "DEBT_INSTRUMENT",
}


@dataclass(frozen=True)
class DiscoveredInstrument:
    symbol: str
    name: str
    market: str
    instrument_type: str
    accepted: bool


@dataclass(frozen=True)
class DiscoveryResult:
    source_timestamp: datetime
    instruments: tuple[DiscoveredInstrument, ...]

    @property
    def equities(self) -> tuple[DiscoveredInstrument, ...]:
        return tuple(item for item in self.instruments if item.accepted)

    @property
    def snapshot_id(self) -> str:
        payload = [(x.symbol, x.name, x.market, x.instrument_type) for x in self.instruments]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


class KapMarketUniverseSource:
    """KAP market registry linked by Borsa İstanbul; runtime refresh is daily, not per scan."""

    def __init__(self, client: Any | None = None) -> None:
        self.client = client

    def fetch(self) -> DiscoveryResult:
        response = (
            self.client.get(SOURCE_URL)
            if self.client is not None
            else httpx.get(SOURCE_URL, timeout=30, follow_redirects=True)
        )
        response.raise_for_status()
        return self.parse(response.text, datetime.now(UTC))

    @staticmethod
    def parse(payload: str, source_timestamp: datetime) -> DiscoveryResult:
        soup = BeautifulSoup(payload, "html.parser")
        market: str | None = None
        unique: dict[str, DiscoveredInstrument] = {}
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if not cells:
                continue
            heading = re.sub(r"\s+\d+\s+Şirket / Fon Bulundu$", "", cells[0]).strip()
            if heading in ALLOWED_EQUITY_MARKETS or heading in EXCLUDED_MARKETS:
                market = heading
                continue
            if market is None or len(cells) < 3 or not cells[0].isdigit():
                continue
            symbol, name = cells[1].strip().upper(), cells[2].strip()
            if not symbol or not symbol.isascii() or not symbol.isalnum():
                continue
            accepted = market in ALLOWED_EQUITY_MARKETS
            instrument_type = "EQUITY" if accepted else EXCLUDED_MARKETS[market]
            candidate = DiscoveredInstrument(symbol, name, market, instrument_type, accepted)
            previous = unique.get(symbol)
            if previous is None or (not previous.accepted and accepted):
                unique[symbol] = candidate
        if not unique:
            raise ValueError("EMPTY_OFFICIAL_UNIVERSE")
        return DiscoveryResult(
            source_timestamp, tuple(sorted(unique.values(), key=lambda x: x.symbol))
        )


class UniverseRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self.session_factory = session_factory

    def save(self, discovery: DiscoveryResult) -> dict[str, int]:
        now = datetime.now(UTC)
        accepted = {item.symbol: item for item in discovery.equities}
        new = inactive = 0
        with self.session_factory.begin() as session:
            existing = {row.symbol: row for row in session.scalars(select(UniverseSymbolRow))}
            snapshot = session.get(UniverseSnapshotRow, discovery.snapshot_id)
            if snapshot is None:
                session.add(
                    UniverseSnapshotRow(
                        snapshot_id=discovery.snapshot_id,
                        source=SOURCE_URL,
                        source_timestamp=discovery.source_timestamp,
                        created_at=now,
                        instrument_count=len(discovery.instruments),
                        equity_count=len(accepted),
                    )
                )
            for symbol, item in accepted.items():
                row = existing.get(symbol)
                event = "UNCHANGED"
                if row is None:
                    new += 1
                    event = "NEW_SYMBOL"
                    row = UniverseSymbolRow(
                        symbol=symbol,
                        canonical_symbol=symbol,
                        company_name=item.name,
                        market=item.market,
                        instrument_type="EQUITY",
                        source=SOURCE_URL,
                        first_seen=now,
                        last_seen=now,
                        active=True,
                        provider_symbol=YFinanceResearchProvider.vendor_symbol(symbol),
                        provider_status="UNKNOWN",
                        validation_status="PENDING",
                    )
                    session.add(row)
                else:
                    row.company_name, row.market, row.last_seen, row.active = (
                        item.name,
                        item.market,
                        now,
                        True,
                    )
                if snapshot is None:
                    session.add(
                        UniverseMembershipRow(
                            snapshot_id=discovery.snapshot_id,
                            symbol=symbol,
                            market=item.market,
                            active=True,
                            event=event,
                        )
                    )
            for symbol, row in existing.items():
                if row.active and symbol not in accepted:
                    row.active = False
                    inactive += 1
                    if snapshot is None:
                        session.add(
                            UniverseMembershipRow(
                                snapshot_id=discovery.snapshot_id,
                                symbol=symbol,
                                market=row.market,
                                active=False,
                                event="INACTIVE",
                            )
                        )
        return {"new": new, "inactive": inactive, "active": len(accepted)}

    def active_symbols(self, available_only: bool = False) -> list[str]:
        with self.session_factory() as session:
            query = select(UniverseSymbolRow.symbol).where(UniverseSymbolRow.active.is_(True))
            if available_only:
                query = query.where(UniverseSymbolRow.provider_status == "AVAILABLE")
            return list(session.scalars(query.order_by(UniverseSymbolRow.symbol)))

    def record_provider_results(
        self, results: dict[str, Any], failures: dict[str, str], probed_at: datetime
    ) -> None:
        with self.session_factory.begin() as session:
            for symbol, result in results.items():
                row = session.get(UniverseSymbolRow, symbol)
                if row is not None:
                    row.provider_status = "AVAILABLE"
                    row.validation_status = "VALID"
                    row.last_probed_at = probed_at
                    row.latest_provider_timestamp = result.quality.last_timestamp
            for symbol, reason in failures.items():
                row = session.get(UniverseSymbolRow, symbol)
                if row is not None:
                    row.provider_status = (
                        "PROVIDER_UNAVAILABLE"
                        if "UNAVAILABLE" in reason
                        else "TEMPORARILY_DEGRADED"
                    )
                    row.validation_status = "FAILED"
                    row.last_probed_at = probed_at

    def summary(self, stale_minutes: int = 45) -> dict[str, object]:
        now = datetime.now(UTC)
        with self.session_factory() as session:
            rows = session.scalars(
                select(UniverseSymbolRow).where(UniverseSymbolRow.active.is_(True))
            ).all()
            latest = session.scalar(
                select(UniverseSnapshotRow).order_by(UniverseSnapshotRow.created_at.desc()).limit(1)
            )
            bar_stats = {
                symbol: (stamp, count)
                for symbol, stamp, count in session.execute(
                    select(
                        MarketBarRow.symbol,
                        func.max(MarketBarRow.timestamp),
                        func.count(MarketBarRow.id),
                    )
                    .where(
                        MarketBarRow.timeframe == "15m",
                        MarketBarRow.provider_id == "yfinance-research",
                    )
                    .group_by(MarketBarRow.symbol)
                ).all()
            }
        fresh = {
            symbol
            for symbol, (stamp, _) in bar_stats.items()
            if stamp is not None
            and (
                now - (stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC))
            ).total_seconds()
            <= stale_minutes * 60
        }
        active = len(rows)
        available = sum(row.provider_status == "AVAILABLE" for row in rows)
        eligible = sum(
            row.provider_status == "AVAILABLE"
            and row.symbol in fresh
            and bar_stats.get(row.symbol, (None, 0))[1] >= 50
            for row in rows
        )
        return {
            "total_active_equities": active,
            "provider_available": available,
            "fresh": len(fresh & {row.symbol for row in rows}),
            "eligible_for_radar": eligible,
            "stale": sum(
                row.provider_status == "AVAILABLE" and row.symbol not in fresh for row in rows
            ),
            "provider_unavailable": sum(
                row.provider_status == "PROVIDER_UNAVAILABLE" for row in rows
            ),
            "limited_history": sum(
                row.provider_status == "AVAILABLE" and bar_stats.get(row.symbol, (None, 0))[1] < 50
                for row in rows
            ),
            "coverage_percent": round(eligible / active * 100, 2) if active else 0.0,
            "last_universe_refresh": latest.created_at if latest else None,
        }
