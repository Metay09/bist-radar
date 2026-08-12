import logging
import time
from datetime import UTC, datetime

from app.api.service import service
from app.core.logging import configure_logging
from app.database.base import EventRow, SessionLocal


def run() -> None:
    configure_logging()
    log = logging.getLogger(__name__)
    while True:
        log.info("market_scan_started")
        results = service.scan()
        with SessionLocal.begin() as session:
            session.add(
                EventRow(
                    event="market_scan_finished",
                    created_at=datetime.now(UTC),
                    detail={"count": len(results)},
                )
            )
        log.info("market_scan_finished count=%d", len(results))
        time.sleep(300)


if __name__ == "__main__":
    run()
