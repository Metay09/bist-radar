import logging
import shutil
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select, text

from app import LIVE_TRADING
from app.adaptive.service import AdaptiveDecisionService
from app.api.dashboard import (
    candidates as dashboard_candidates,
)
from app.api.dashboard import (
    dashboard_opportunities,
    dashboard_snapshot_status,
    dashboard_summary,
    dashboard_trade_plans,
    symbol_detail,
    system_overview,
    trade_plan,
)
from app.api.dashboard import (
    performance_summary as dashboard_performance,
)
from app.api.service import service
from app.backtest.replay import HistoricalReplayEngine
from app.backtest.replay_models import ExecutionOrder, Timeframe
from app.backtest.repository import ReplayRepository
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.data.historical import CsvHistoricalProvider, SymbolMetadata
from app.data.intraday_research import IntradayResearchBackfill
from app.data.research_repository import ResearchRepository
from app.data.vendor_mock import MockVendorA, MockVendorB
from app.data.yfinance_provider import YFinanceResearchProvider
from app.database.base import EventRow, HistoricalDatasetRow, SessionLocal
from app.intraday.intelligence import SignalIntelligence
from app.intraday.outcomes import accuracy_buckets
from app.intraday.repository import IntradayRepository
from app.ml.registry import freeze_champion
from app.ml.research_lab import champion_manifest
from app.models.domain import SignalClass
from app.notifications.telegram import DISCLAIMER
from app.paper.ledger import PaperLedger
from app.paper.repository import PaperTradeRepository
from app.research.governance import EvidenceRepository
from app.universe.service import UniverseRepository


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    freeze_champion()
    yield


configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, description=DISCLAIMER, lifespan=lifespan)
request_log = logging.getLogger("app.api.latency")
dashboard_latencies: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))


@app.middleware("http")
async def observe_dashboard_latency(request: Request, call_next: Any) -> Any:
    started = perf_counter()
    response = await call_next(request)
    if request.url.path in {
        "/dashboard/candidates",
        "/dashboard/trade-plans",
        "/dashboard/opportunities",
        "/dashboard/snapshot-status",
    }:
        elapsed_ms = (perf_counter() - started) * 1000
        dashboard_latencies[request.url.path].append(elapsed_ms)
        response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
        request_log.info(
            "dashboard_request path=%s status=%d latency_ms=%.1f",
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response


ledger = PaperLedger()
paper_repository = PaperTradeRepository()
replay_repository = ReplayRepository()
research_repository = ResearchRepository()
intraday_repository = IntradayRepository()
signal_intelligence = SignalIntelligence()
adaptive_decisions = AdaptiveDecisionService()
intraday_research = IntradayResearchBackfill()
evidence_repository = EvidenceRepository()
universe_repository = UniverseRepository()


class ReplayRequest(BaseModel):
    symbols: list[str] = ["RALLY"]
    timeframe: Timeframe = Timeframe.D1
    initial_equity: Decimal = Decimal("100000")


def demo_strategy(symbol: str, visible: Any) -> ExecutionOrder | None:
    if len(visible) != 220:
        return None
    bar = visible.iloc[-1]
    timestamp = bar.timestamp.to_pydatetime()
    entry = Decimal(str(bar.close))
    return ExecutionOrder(
        f"{symbol}-{timestamp.isoformat()}",
        f"radar-v1:{symbol}:{timestamp.isoformat()}",
        "paper-default",
        "radar-v1",
        symbol,
        timestamp,
        entry,
        entry * Decimal("0.97"),
        entry * Decimal("1.05"),
        entry * Decimal("1.10"),
        85,
        100,
    )


def database_ok() -> bool:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def last_worker_scan() -> object | None:
    try:
        with SessionLocal() as session:
            event = session.scalar(
                select(EventRow)
                .where(EventRow.event == "market_scan_finished")
                .order_by(desc(EventRow.created_at))
                .limit(1)
            )
            return event.created_at if event else None
    except Exception:
        return None


@app.get("/health")
def health() -> dict[str, object]:
    usage = shutil.disk_usage(".")
    return {
        "status": "healthy",
        "database": "ok" if database_ok() else "down",
        "provider": "fixture",
        "worker": "ok" if last_worker_scan() else "awaiting_first_scan",
        "telegram": "mock" if not settings.telegram_bot_token else "configured",
        "disk_free_percent": round(usage.free / usage.total * 100, 2),
        "trading_mode": settings.trading_mode,
        "live_trading": LIVE_TRADING,
        "disclaimer": DISCLAIMER,
    }


@app.get("/ready")
def ready() -> dict[str, bool]:
    return {"ready": database_ok()}


@app.get("/symbols")
def symbols() -> list[str]:
    return service.symbols


@app.get("/universe")
def universe() -> list[str]:
    return universe_repository.active_symbols()


@app.get("/universe/summary")
def universe_summary() -> dict[str, object]:
    summary = universe_repository.summary(settings.intraday_stale_minutes)
    report = research_repository.latest_report("intraday_scan", require_candidates=True) or {}
    scanned = report.get("stage_b_symbols")
    actually_scanned = scanned if isinstance(scanned, int) else None
    active = summary.get("total_active_equities")
    summary["pre_scan_eligible"] = summary.get("eligible_for_radar")
    summary["actually_scanned"] = actually_scanned
    summary["scan_coverage_percent"] = (
        round(actually_scanned / active * 100, 2)
        if actually_scanned is not None and isinstance(active, int) and active
        else None
    )
    if actually_scanned is not None:
        summary["eligible_for_radar"] = actually_scanned
        summary["coverage_percent"] = summary["scan_coverage_percent"]
    return summary


@app.get("/universe/failures")
def universe_failures() -> list[dict[str, object]]:
    from app.database.base import UniverseSymbolRow

    with SessionLocal() as session:
        rows = session.scalars(
            select(UniverseSymbolRow)
            .where(
                UniverseSymbolRow.active.is_(True),
                UniverseSymbolRow.provider_status != "AVAILABLE",
            )
            .order_by(UniverseSymbolRow.symbol)
        ).all()
        return [
            {
                "symbol": row.symbol,
                "provider_symbol": row.provider_symbol,
                "status": row.provider_status,
                "validation_status": row.validation_status,
                "last_probed_at": row.last_probed_at,
            }
            for row in rows
        ]


@app.get("/radar")
def radar() -> list[dict[str, object]]:
    return [asdict(item) for item in service.scan()]


@app.get("/radar/{symbol}")
def radar_symbol(symbol: str) -> dict[str, object]:
    result = next((x for x in service.scan() if x.symbol == symbol.upper()), None)
    if not result:
        raise HTTPException(404, "symbol not found")
    return asdict(result)


@app.get("/signals")
def signals() -> list[dict[str, object]]:
    return [asdict(x) for x in service.scan() if x.signal_class != SignalClass.NO_SIGNAL]


@app.get("/paper/trades")
def paper_trades() -> list[dict[str, object]]:
    return [
        asdict(x)
        for x in paper_repository.list(
            portfolio_id="paper-default", strategy_id="radar-intraday-v1"
        )
    ]


@app.get("/paper/performance")
def paper_performance() -> dict[str, float | int]:
    return paper_repository.performance("paper-default", "radar-intraday-v1")


@app.get("/system/status")
def system_status() -> dict[str, object]:
    return {
        "last_scan": service.last_scan,
        "last_successful_scan": service.last_successful_scan,
        "last_error": service.last_error,
        "worker_last_scan": last_worker_scan(),
        "provider": "fixture",
        "takas": "TAKAS_DATA_UNAVAILABLE",
        "trading_mode": "paper",
    }


@app.post("/replay")
def create_replay(request: ReplayRequest) -> dict[str, object]:
    metadata = {
        symbol: SymbolMetadata(symbol) for symbol in service.symbols if symbol != "BAD_DATA"
    }
    engine = HistoricalReplayEngine(
        CsvHistoricalProvider(service.provider.root), metadata, demo_strategy
    )
    try:
        result = engine.run(request.symbols, request.timeframe, None, None, request.initial_equity)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    replay_repository.save(
        result,
        {"timeframe": request.timeframe.value, "initial_equity": str(request.initial_equity)},
    )
    return {"run_id": result.run_id, "status": "COMPLETED"}


@app.get("/replay/{run_id}")
def get_replay(run_id: str) -> dict[str, object]:
    result = replay_repository.run(run_id)
    if result is None:
        raise HTTPException(404, "replay not found")
    return result


@app.get("/replay/{run_id}/trades")
def replay_trades(run_id: str) -> list[dict[str, object]]:
    return replay_repository.trades(run_id)


@app.get("/replay/{run_id}/performance")
def replay_performance_endpoint(run_id: str) -> dict[str, object]:
    result = get_replay(run_id)
    return result["performance"]  # type: ignore[return-value]


@app.get("/replay/{run_id}/equity")
def replay_equity(run_id: str) -> list[dict[str, object]]:
    return replay_repository.equity(run_id)


def provider_payload(provider: Any) -> dict[str, object]:
    return {
        "provider_id": provider.metadata.provider_id,
        "provider_name": provider.metadata.provider_name,
        "data_mode": provider.metadata.data_mode.value,
        "timezone": provider.metadata.timezone,
        "verified": provider.metadata.verified,
        "capabilities": vars(provider.capabilities),
    }


@app.get("/providers")
def providers() -> list[dict[str, object]]:
    return [provider_payload(p) for p in (MockVendorA(), MockVendorB(), YFinanceResearchProvider())]


@app.get("/providers/health")
def providers_health() -> list[dict[str, object]]:
    return [
        {
            "provider_id": p.metadata.provider_id,
            "health": "HEALTHY",
            "data_mode": p.metadata.data_mode.value,
        }
        for p in (MockVendorA(), MockVendorB())
    ]


@app.get("/research/status")
def research_status() -> dict[str, object]:
    provider = YFinanceResearchProvider()
    return {
        **provider_payload(provider),
        "health": "UNKNOWN",
        "network_dependency": True,
        "production_approved": False,
        "flags": [flag.value for flag in provider.mandatory_flags],
        "champion": champion_manifest(),
        "ml_mode": "shadow",
        "allow_ml_to_change_radar": False,
        "auto_promotion": False,
        "five_minute_latency": intraday_research.latency_report(),
        "notice": "Bu bölüm Radar kararını etkilemez.",
    }


@app.get("/research/evidence")
def research_evidence() -> dict[str, object]:
    return evidence_repository.evidence_status()


@app.get("/research/daily")
def research_daily(limit: int = 30) -> list[dict[str, object]]:
    from app.database.base import DailyResearchSnapshotRow

    with SessionLocal() as session:
        rows = session.scalars(
            select(DailyResearchSnapshotRow)
            .order_by(DailyResearchSnapshotRow.session_date.desc())
            .limit(min(max(limit, 1), 100))
        ).all()
    return [
        {"session_date": row.session_date, "metrics": row.metrics, "deltas": row.deltas}
        for row in rows
    ]


@app.get("/research/weekly")
def research_weekly(limit: int = 12) -> list[dict[str, object]]:
    from app.database.base import WeeklyResearchReportRow

    with SessionLocal() as session:
        rows = session.scalars(
            select(WeeklyResearchReportRow)
            .order_by(WeeklyResearchReportRow.week_start.desc())
            .limit(min(max(limit, 1), 52))
        ).all()
    return [dict(row.payload) for row in rows]


@app.get("/research/scan")
def latest_research_scan() -> dict[str, object]:
    report = research_repository.latest_report("scan")
    if report is None:
        raise HTTPException(404, "research scan not available")
    return report


@app.get("/research/scan/{symbol}")
def research_scan_symbol(symbol: str) -> dict[str, object]:
    report = latest_research_scan()
    candidates = report.get("candidates", [])
    if not isinstance(candidates, list):
        raise HTTPException(500, "invalid research report")
    candidate = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("symbol") == symbol.upper()
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(404, "research symbol not available")
    return {str(key): value for key, value in candidate.items()}


@app.get("/research/replay/latest")
def latest_research_replay() -> dict[str, object]:
    report = research_repository.latest_report("replay")
    if report is None:
        raise HTTPException(404, "research replay not available")
    return report


@app.get("/intraday/status")
def intraday_status() -> dict[str, object]:
    latest = research_repository.latest_report("intraday_scan", require_candidates=True)
    return {
        "strategy_id": "radar-intraday-v1",
        "provider": "yfinance-research",
        "timeframes": ["5m", "15m", "30m", "60m"],
        "cadence_minutes": settings.intraday_scan_minutes,
        "research_only": True,
        "latest_scan": latest,
    }


@app.get("/intraday/scan")
def intraday_scan() -> dict[str, object]:
    report = research_repository.latest_report("intraday_scan", require_candidates=True)
    if report is None:
        return {"strategy_id": "radar-intraday-v1", "candidates": [], "status": "NO_SCAN"}
    return report


@app.get("/intraday/scan/{symbol}")
def intraday_scan_symbol(symbol: str) -> dict[str, object]:
    candidates = intraday_scan().get("candidates", [])
    if not isinstance(candidates, list):
        raise HTTPException(500, "invalid intraday report")
    match = next(
        (
            row
            for row in candidates
            if isinstance(row, dict) and row.get("symbol") == symbol.upper()
        ),
        None,
    )
    if match is None:
        raise HTTPException(404, "intraday symbol not available")
    return {str(key): value for key, value in match.items()}


@app.get("/signals/outcomes")
def signal_outcomes() -> list[dict[str, object]]:
    return intraday_repository.outcome_summaries()


@app.get("/analytics/signal-accuracy")
def signal_accuracy(group: str = "score", horizon: str = "120m") -> list[dict[str, object]]:
    allowed = {"15m", "30m", "60m", "120m", "EOD", "NEXT_DAY"}
    if horizon not in allowed:
        raise HTTPException(422, "invalid outcome horizon")
    rows = [row for row in intraday_repository.outcomes() if row.get("horizon") == horizon]
    return accuracy_buckets(rows, group)


@app.get("/ml/status")
def ml_status() -> dict[str, object]:
    return intraday_repository.status()


@app.get("/ml/models")
def ml_models() -> list[dict[str, object]]:
    return intraday_repository.models()


@app.get("/ml/predictions")
def ml_predictions() -> list[dict[str, object]]:
    return intraday_repository.predictions()


@app.get("/ml/evaluation")
def ml_evaluation() -> list[dict[str, object]]:
    return intraday_repository.evaluations()


@app.get("/data/quality")
def data_quality() -> list[dict[str, object]]:
    return [
        {
            "provider_id": "mock-a",
            "bars_received": 0,
            "bars_valid": 0,
            "invalid_bars": 0,
            "duplicate_bars": 0,
            "revised_bars": 0,
            "missing_bars": "unknown",
            "quality_percent": 0,
            "p50_latency_ms": 0,
            "p95_latency_ms": 0,
            "p99_latency_ms": 0,
        }
    ]


@app.get("/datasets")
def datasets() -> list[dict[str, object]]:
    with SessionLocal() as session:
        return [row.manifest for row in session.scalars(select(HistoricalDatasetRow)).all()]


@app.get("/datasets/{dataset_id}")
def dataset(dataset_id: str) -> dict[str, object]:
    with SessionLocal() as session:
        row = session.get(HistoricalDatasetRow, dataset_id)
    if row is None:
        raise HTTPException(404, "dataset not found")
    return row.manifest


@app.get("/dashboard/summary")
def dashboard_summary_endpoint() -> dict[str, object]:
    return dashboard_summary()


@app.get("/dashboard/candidates")
def dashboard_candidates_endpoint() -> list[dict[str, object]]:
    return dashboard_candidates()


@app.get("/dashboard/trade-plans")
def dashboard_trade_plans_endpoint() -> list[dict[str, object]]:
    return dashboard_trade_plans()


@app.get("/dashboard/opportunities")
def dashboard_opportunities_endpoint() -> dict[str, object]:
    return dashboard_opportunities()


@app.get("/dashboard/snapshot-status")
def dashboard_snapshot_status_endpoint() -> dict[str, object]:
    return dashboard_snapshot_status()


@app.get("/dashboard/latency")
def dashboard_latency_endpoint() -> dict[str, dict[str, float | int | None]]:
    def stats(values: deque[float]) -> dict[str, float | int | None]:
        ordered = sorted(values)
        if not ordered:
            return {"count": 0, "p50_ms": None, "p95_ms": None}
        return {
            "count": len(ordered),
            "p50_ms": round(ordered[(len(ordered) - 1) // 2], 1),
            "p95_ms": round(ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)], 1),
        }

    return {path.rsplit("/", 1)[-1]: stats(values) for path, values in dashboard_latencies.items()}


@app.get("/symbols/{symbol}/trade-plan")
def symbol_trade_plan_endpoint(symbol: str) -> dict[str, object]:
    return trade_plan(symbol)


@app.get("/symbols/{symbol}/detail")
def symbol_detail_endpoint(symbol: str, limit: int = 160) -> dict[str, object]:
    result = symbol_detail(symbol, limit)
    if result is None:
        raise HTTPException(404, "symbol detail not found")
    return result


@app.get("/signals/history")
def signal_history_endpoint(
    limit: int = 50,
    symbol: str | None = None,
    date: str | None = None,
    score_bucket: str | None = None,
    status: str | None = None,
    page: int = 1,
) -> list[dict[str, object]]:
    try:
        selected_date = datetime.fromisoformat(date).date() if date else None
    except ValueError as exc:
        raise HTTPException(422, "invalid date") from exc
    return signal_intelligence.records(
        symbol=symbol,
        day=selected_date,
        score_bucket=score_bucket,
        status=status,
        page=page,
        page_size=limit,
    )[0]


@app.get("/signals/daily-summary")
def signal_daily_summary(days: int = 7) -> list[dict[str, object]]:
    return signal_intelligence.daily(min(max(days, 1), 60))


@app.get("/symbols/{symbol}/results")
def symbol_results(symbol: str) -> list[dict[str, object]]:
    return signal_intelligence.symbol_results(symbol)


@app.get("/symbols/{symbol}/shadow-status")
def symbol_shadow_status(symbol: str) -> dict[str, object]:
    return signal_intelligence.shadow_status(symbol)


@app.get("/symbols/{symbol}/latest-shadow-prediction")
def symbol_latest_shadow_prediction(symbol: str) -> dict[str, object]:
    return signal_intelligence.latest_shadow_prediction(symbol)


@app.get("/shadow/status")
def shadow_status() -> dict[str, object]:
    return signal_intelligence.shadow_status()


@app.get("/symbols/{symbol}/adaptive-decision")
def adaptive_decision(symbol: str) -> dict[str, object]:
    result = adaptive_decisions.detail(symbol)
    if result is None:
        raise HTTPException(404, "adaptive setup not found")
    return result


@app.get("/analytics/adaptive")
def adaptive_analytics() -> dict[str, object]:
    return adaptive_decisions.analytics()


@app.get("/analytics/scores")
def score_performance() -> list[dict[str, object]]:
    return signal_intelligence.analytics("score")


@app.get("/analytics/rvol")
def rvol_performance() -> list[dict[str, object]]:
    return signal_intelligence.analytics("rvol")


@app.get("/analytics/momentum")
def momentum_performance() -> list[dict[str, object]]:
    return signal_intelligence.analytics("momentum")


@app.get("/performance/summary")
def dashboard_performance_endpoint() -> dict[str, object]:
    return dashboard_performance()


@app.get("/system/overview")
def system_overview_endpoint() -> dict[str, object]:
    return system_overview()
