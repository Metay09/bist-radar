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
from app.database.base import EventRow, SessionLocal
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
