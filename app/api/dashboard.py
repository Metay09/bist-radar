from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select

from app.data.research_repository import ResearchRepository
from app.database.base import (
    MarketBarRow,
    MlFeatureSnapshotRow,
    MlOutcomeRow,
    NotificationEventRow,
    PaperTradeRow,
    SessionLocal,
    WorkerStateRow,
)
from app.intraday.repository import IntradayRepository


def market_open(now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo("Europe/Istanbul"))
    return local.weekday() < 5 and time(10, 0) <= local.time() <= time(18, 10)


def freshness(timestamp: datetime | None, stale_minutes: int = 45) -> dict[str, object]:
    if timestamp is None:
        return {"state": "UNKNOWN", "age_minutes": None, "label": "Veri yok"}
    age = max(0.0, (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds() / 60)
    if not market_open():
        state, label = "MARKET_CLOSED", "Piyasa kapalı — son tamamlanmış veri"
    elif age <= stale_minutes:
        state, label = "FRESH", f"Veri {age:.0f} dk yaşında"
    elif age <= stale_minutes * 3:
        state, label = "DELAYED", f"Veri {age:.0f} dk gecikmeli"
    else:
        state, label = "STALE", f"Veri eski: {age / 60:.1f} saat"
    return {"state": state, "age_minutes": age, "label": label}


def dashboard_summary() -> dict[str, object]:
    report = ResearchRepository().latest_report("intraday_scan") or {}
    candidates = report.get("candidates", [])
    if not isinstance(candidates, list):
        candidates = []
    timestamp_value = report.get("data_timestamp")
    timestamp: datetime | None = (
        datetime.fromisoformat(timestamp_value)
        if isinstance(timestamp_value, str)
        else timestamp_value
        if isinstance(timestamp_value, datetime)
        else None
    )
    counts = {
        name: 0 for name in ("VERY_STRONG_CANDIDATE", "STRONG_CANDIDATE", "CANDIDATE", "WATCH")
    }
    for row in candidates:
        if isinstance(row, dict) and row.get("classification") in counts:
            counts[str(row["classification"])] += 1
    ml = IntradayRepository().status()
    return {
        "provider": "Yahoo Finance via yfinance",
        "provider_health": "RESEARCH_ONLY",
        "paper_mode": True,
        "research_only": True,
        "market_open": market_open(),
        "data_timestamp": timestamp,
        "freshness": freshness(timestamp),
        "counts": counts | {"PENDING_OUTCOMES": ml["pending"]},
        "last_scan": report.get("data_timestamp"),
    }


def candidates() -> list[dict[str, object]]:
    report = ResearchRepository().latest_report("intraday_scan") or {}
    rows = report.get("candidates", [])
    if not isinstance(rows, list):
        return []
    return sorted(
        [{str(key): value for key, value in row.items()} for row in rows if isinstance(row, dict)],
        key=lambda row: (-int(row.get("radar_score", 0)), str(row.get("symbol", ""))),
    )


def symbol_detail(symbol: str, limit: int = 160) -> dict[str, object] | None:
    canonical = symbol.upper()
    candidate = next((row for row in candidates() if row.get("symbol") == canonical), None)
    with SessionLocal() as session:
        bars = session.scalars(
            select(MarketBarRow)
            .where(MarketBarRow.symbol == canonical, MarketBarRow.timeframe == "15m")
            .order_by(desc(MarketBarRow.timestamp))
            .limit(min(max(limit, 20), 500))
        ).all()
        progression = session.scalars(
            select(MlFeatureSnapshotRow)
            .where(MlFeatureSnapshotRow.symbol == canonical)
            .order_by(MlFeatureSnapshotRow.signal_time)
            .limit(200)
        ).all()
    if candidate is None and not bars:
        return None
    return {
        "symbol": canonical,
        "candidate": candidate,
        "bars": [
            {
                "timestamp": row.timestamp,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
            }
            for row in reversed(bars)
        ],
        "progression": [dict(row.features) | {"lifecycle": row.lifecycle} for row in progression],
        "freshness": freshness(bars[0].timestamp if bars else None),
    }


def signal_history(limit: int = 100, symbol: str | None = None) -> list[dict[str, object]]:
    with SessionLocal() as session:
        query = (
            select(MlFeatureSnapshotRow)
            .order_by(desc(MlFeatureSnapshotRow.signal_time))
            .limit(min(max(limit, 1), 500))
        )
        if symbol:
            query = query.where(MlFeatureSnapshotRow.symbol == symbol.upper())
        rows = session.scalars(query).all()
        return [dict(row.features) | {"lifecycle": row.lifecycle} for row in rows]


def performance_summary() -> dict[str, object]:
    with SessionLocal() as session:
        trades = session.scalars(select(PaperTradeRow)).all()
    realized = sum((trade.net_return for trade in trades if trade.exit_time), Decimal("0"))
    return {
        "paper_only": True,
        "trade_count": len(trades),
        "open_positions": sum(trade.exit_time is None for trade in trades),
        "closed_trades": sum(trade.exit_time is not None for trade in trades),
        "realized_pnl": float(realized),
        "unrealized_pnl": None,
        "mtm_equity": None,
        "message": "Güncel araştırma fiyatı yoksa unrealized P&L uydurulmaz.",
    }


def system_overview() -> dict[str, object]:
    with SessionLocal() as session:
        jobs = session.scalars(select(WorkerStateRow)).all()
        notifications = session.scalar(select(func.count()).select_from(NotificationEventRow)) or 0
        outcomes = session.scalar(select(func.count()).select_from(MlOutcomeRow)) or 0
    return {
        "database": "HEALTHY",
        "worker_jobs": [
            {
                "job_name": row.job_name,
                "status": row.status,
                "last_success": row.last_success_at,
                "last_failure": row.last_failure_at,
                "detail": row.detail,
            }
            for row in jobs
        ],
        "notifications": notifications,
        "outcome_labels": outcomes,
        "telegram": "CONFIGURED_EXTERNALLY_OR_DISABLED",
    }
