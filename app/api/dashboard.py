from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select

from app.core.config import get_settings
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
from app.risk.trade_plan_view import build_research_trade_plan


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
    report_candidates = report.get("candidates", [])
    candidates = _unique_candidates(
        report_candidates if isinstance(report_candidates, list) else []
    )
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
    return _unique_candidates(rows)


def _candidate_timestamp(row: dict[str, object]) -> datetime:
    value = row.get("timestamp")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=UTC)


def _unique_candidates(rows: list[object]) -> list[dict[str, object]]:
    """Keep the newest canonical observation per symbol, then rank deterministically."""
    newest: dict[str, dict[str, object]] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        row = {str(key): value for key, value in raw.items()}
        symbol = str(row.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        row["symbol"] = symbol
        current = newest.get(symbol)
        if current is None or _candidate_timestamp(row) > _candidate_timestamp(current):
            newest[symbol] = row

    def rank(row: dict[str, object]) -> tuple[int, str]:
        value = row.get("radar_score", 0)
        score = int(value) if isinstance(value, (int, float, str)) else 0
        return -score, str(row["symbol"])

    return sorted(newest.values(), key=rank)


def trade_plan(symbol: str) -> dict[str, object]:
    canonical = symbol.upper()
    candidate = next((row for row in candidates() if row.get("symbol") == canonical), None)
    if candidate is None:
        return {
            "symbol": canonical,
            "status": "GECERSIZ",
            "research_only": True,
            "explanation": ["Henüz yeterli aday ve risk bağlamı yok."],
        }
    with SessionLocal() as session:
        lows = session.scalars(
            select(MarketBarRow.low)
            .where(MarketBarRow.symbol == canonical, MarketBarRow.timeframe == "15m")
            .order_by(desc(MarketBarRow.timestamp))
            .limit(10)
        ).all()
    settings = get_settings()
    plan = build_research_trade_plan(
        candidate,
        list(reversed(lows)),
        account_equity=Decimal(str(settings.paper_default_account_equity)),
        risk_percent=Decimal(str(settings.max_risk_per_trade_percent)),
        max_position_percent=Decimal(str(settings.max_position_percent)),
        stale_minutes=settings.intraday_stale_minutes,
    )
    plan["market_closed"] = not market_open()
    return plan


def dashboard_trade_plans() -> list[dict[str, object]]:
    return [trade_plan(str(row["symbol"])) for row in candidates()]


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
        "trade_plan": trade_plan(canonical),
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
        trades = session.scalars(
            select(PaperTradeRow).where(
                PaperTradeRow.portfolio_id == "paper-default",
                PaperTradeRow.strategy_id == "radar-intraday-v1",
            )
        ).all()
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
