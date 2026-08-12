import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc, select, text

from app import LIVE_TRADING
from app.api.service import service
from app.backtest.replay import HistoricalReplayEngine
from app.backtest.replay_models import ExecutionOrder, Timeframe
from app.backtest.repository import ReplayRepository
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.data.historical import CsvHistoricalProvider, SymbolMetadata
from app.data.research_repository import ResearchRepository
from app.data.vendor_mock import MockVendorA, MockVendorB
from app.data.yfinance_provider import YFinanceResearchProvider
from app.database.base import EventRow, HistoricalDatasetRow, SessionLocal
from app.intraday.outcomes import accuracy_buckets
from app.intraday.repository import IntradayRepository
from app.models.domain import SignalClass
from app.notifications.telegram import DISCLAIMER
from app.paper.ledger import PaperLedger
from app.paper.repository import PaperTradeRepository


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    with SessionLocal() as session:
        session.execute(text("SELECT 1"))
    yield


configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, description=DISCLAIMER, lifespan=lifespan)
ledger = PaperLedger()
paper_repository = PaperTradeRepository()
replay_repository = ReplayRepository()
research_repository = ResearchRepository()
intraday_repository = IntradayRepository()


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
    return [asdict(x) for x in paper_repository.list()]


@app.get("/paper/performance")
def paper_performance() -> dict[str, float | int]:
    return paper_repository.performance()


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
    }


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
    latest = research_repository.latest_report("intraday_scan")
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
    report = research_repository.latest_report("intraday_scan")
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
    return intraday_repository.outcomes()


@app.get("/analytics/signal-accuracy")
def signal_accuracy(group: str = "score") -> list[dict[str, object]]:
    return accuracy_buckets(intraday_repository.outcomes(), group)


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
