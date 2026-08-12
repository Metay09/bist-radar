import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from app import LIVE_TRADING
from app.api.service import service
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.database.base import init_db
from app.models.domain import SignalClass
from app.notifications.telegram import DISCLAIMER
from app.paper.ledger import PaperLedger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


configure_logging()
settings = get_settings()
app = FastAPI(title=settings.app_name, description=DISCLAIMER, lifespan=lifespan)
ledger = PaperLedger()


@app.get("/health")
def health() -> dict[str, object]:
    usage = shutil.disk_usage(".")
    return {
        "status": "healthy",
        "database": "configured",
        "provider": "fixture",
        "worker": "in_process",
        "telegram": "mock" if not settings.telegram_bot_token else "configured",
        "disk_free_percent": round(usage.free / usage.total * 100, 2),
        "trading_mode": settings.trading_mode,
        "live_trading": LIVE_TRADING,
        "disclaimer": DISCLAIMER,
    }


@app.get("/ready")
def ready() -> dict[str, bool]:
    return {"ready": True}


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
    return [asdict(x) for x in ledger.trades]


@app.get("/paper/performance")
def paper_performance() -> dict[str, float | int]:
    return ledger.performance()


@app.get("/system/status")
def system_status() -> dict[str, object]:
    return {
        "last_scan": service.last_scan,
        "last_successful_scan": service.last_successful_scan,
        "last_error": service.last_error,
        "provider": "fixture",
        "takas": "TAKAS_DATA_UNAVAILABLE",
        "trading_mode": "paper",
    }
