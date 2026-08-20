import logging
from datetime import UTC, datetime, time
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import desc, func, select

from app.core.config import get_settings
from app.data.research import load_universe
from app.data.research_repository import ResearchRepository
from app.database.base import (
    MarketBarRow,
    MlFeatureSnapshotRow,
    MlOutcomeRow,
    NotificationEventRow,
    PaperTradeRow,
    SessionLocal,
    UniverseSymbolRow,
    WorkerStateRow,
)
from app.intraday.repository import IntradayRepository
from app.market.bist import canonical_bist_symbol
from app.risk.trade_plan_view import build_research_trade_plan

log = logging.getLogger(__name__)

ACTION_PRIORITY = {
    "BREAKOUT_ONAYI": 0,
    "GIRIS_BOLGESINDE": 1,
    "GIRIS_BEKLENIYOR": 2,
    "KACMIS_KOVALAMA": 3,
    "GECERSIZ": 4,
}


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
    report = ResearchRepository().latest_report("intraday_scan", require_candidates=True) or {}
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
    with SessionLocal() as session:
        data_job = session.get(WorkerStateRow, "intraday_data_update")
        scan_job = session.get(WorkerStateRow, "intraday_radar_scan")
    return {
        "provider": "Yahoo Finance via yfinance",
        "provider_health": (
            "RESEARCH_ONLY" if data_job is None or data_job.status == "HEALTHY" else "DEGRADED"
        ),
        "paper_mode": True,
        "research_only": True,
        "market_open": market_open(),
        "data_timestamp": timestamp,
        "freshness": freshness(timestamp),
        "counts": counts | {"PENDING_OUTCOMES": ml["pending"]},
        "last_data_update": data_job.last_success_at if data_job else None,
        "last_provider_attempt": data_job.last_started_at if data_job else None,
        "last_scan": scan_job.last_success_at if scan_job else None,
    }


def candidates() -> list[dict[str, object]]:
    report = ResearchRepository().latest_report("intraday_scan", require_candidates=True) or {}
    return _candidates_from_report(report)


def _candidates_from_report(report: dict[str, object]) -> list[dict[str, object]]:
    rows = report.get("candidates", [])
    if not isinstance(rows, list):
        return []
    bist100 = {
        member.symbol
        for member in load_universe(Path("config/universes/bist100.csv")).members
        if member.active
    }
    return [row | {"bist100_member": row["symbol"] in bist100} for row in _unique_candidates(rows)]


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
        symbol = canonical_bist_symbol(row.get("symbol", ""))
        if not symbol:
            continue
        row["symbol"] = symbol
        strategies = row.get("matched_strategies")
        strategy = row.get("strategy_id")
        matched = set(strategies if isinstance(strategies, list) else [])
        if strategy:
            matched.add(str(strategy))
        current = newest.get(symbol)
        if current is not None:
            current_matched = current.get("matched_strategies")
            matched.update(current_matched if isinstance(current_matched, list) else [])
            current_strategy = current.get("strategy_id")
            if current_strategy:
                matched.add(str(current_strategy))

        # Newest observation wins; ties use score then confidence, never input order.
        def preference(item: dict[str, object]) -> tuple[int, datetime, float, float]:
            score = item.get("radar_score", 0)
            confidence = item.get("confidence", item.get("data_quality", 0))
            return (
                -ACTION_PRIORITY.get(str(item.get("action_state", "")), 5),
                _candidate_timestamp(item),
                float(score) if isinstance(score, (int, float)) else 0,
                float(confidence) if isinstance(confidence, (int, float)) else 0,
            )

        winner = row if current is None or preference(row) > preference(current) else current
        winner["matched_strategies"] = sorted(matched)
        newest[symbol] = winner
        if current is not None:
            log.debug("duplicate_symbol_merged symbol=%s strategies=%s", symbol, sorted(matched))

    def rank(row: dict[str, object]) -> tuple[int, float, float, int, str]:
        value = row.get("radar_score", 0)
        score = int(value) if isinstance(value, (int, float, str)) else 0
        distance = row.get("breakout_distance", float("inf"))
        return (
            ACTION_PRIORITY.get(str(row.get("action_state", "")), 5),
            abs(float(distance)) if isinstance(distance, (int, float)) else float("inf"),
            -_candidate_timestamp(row).timestamp(),
            -score,
            str(row["symbol"]),
        )

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
    return list(_plans_for_candidates(candidates()).values())


def _plans_for_candidates(
    candidate_rows: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Build every plan from one candidate snapshot and one bounded bar query."""
    if not candidate_rows:
        return {}
    symbols = [str(row["symbol"]) for row in candidate_rows]
    ranked = (
        select(
            MarketBarRow.symbol.label("symbol"),
            MarketBarRow.low.label("low"),
            func.row_number()
            .over(partition_by=MarketBarRow.symbol, order_by=MarketBarRow.timestamp.desc())
            .label("rank"),
        )
        .where(MarketBarRow.symbol.in_(symbols), MarketBarRow.timeframe == "15m")
        .subquery()
    )
    with SessionLocal() as session:
        low_rows = session.execute(
            select(ranked.c.symbol, ranked.c.low)
            .where(ranked.c.rank <= 10)
            .order_by(ranked.c.symbol, ranked.c.rank.desc())
        ).all()
    lows: dict[str, list[object]] = {symbol: [] for symbol in symbols}
    for symbol, low in low_rows:
        lows[str(symbol)].append(low)
    settings = get_settings()
    closed = not market_open()
    result: dict[str, dict[str, object]] = {}
    for candidate in candidate_rows:
        symbol = str(candidate["symbol"])
        plan = build_research_trade_plan(
            candidate,
            lows[symbol],
            account_equity=Decimal(str(settings.paper_default_account_equity)),
            risk_percent=Decimal(str(settings.max_risk_per_trade_percent)),
            max_position_percent=Decimal(str(settings.max_position_percent)),
            stale_minutes=settings.intraday_stale_minutes,
        )
        plan["market_closed"] = closed
        result[symbol] = plan
    return result


def dashboard_opportunities() -> dict[str, object]:
    """Coherent candidate + backend-owned plan view from a single completed scan."""
    report = ResearchRepository().latest_report("intraday_scan", require_candidates=True) or {}
    candidate_rows = _candidates_from_report(report)
    plans = _plans_for_candidates(candidate_rows)
    data_timestamp = report.get("data_timestamp")
    if data_timestamp is None and candidate_rows:
        data_timestamp = max(_candidate_timestamp(row) for row in candidate_rows)
    identity = "|".join(
        [str(data_timestamp)]
        + [
            f"{row['symbol']}:{row.get('signal_id', row.get('timestamp', ''))}"
            for row in candidate_rows
        ]
    )
    snapshot_id = sha256(identity.encode()).hexdigest()[:24]
    return {
        "snapshot_id": snapshot_id,
        "data_timestamp": data_timestamp,
        "opportunities": [
            {
                "candidate": row,
                "plan": plans[str(row["symbol"])],
                "snapshot_id": snapshot_id,
                "data_timestamp": data_timestamp,
            }
            for row in candidate_rows
        ],
    }


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
        universe = session.get(UniverseSymbolRow, canonical)
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
        "universe_metadata": (
            {
                "universe": "BIST Tüm",
                "company_name": universe.company_name,
                "market": universe.market,
                "provider": "Yahoo Research",
                "provider_status": universe.provider_status,
                "validation_status": universe.validation_status,
            }
            if universe is not None
            else None
        ),
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
