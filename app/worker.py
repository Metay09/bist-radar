import logging
import time

from app.api.service import service
from app.core.logging import configure_logging


def run() -> None:
    configure_logging()
    log = logging.getLogger(__name__)
    while True:
        log.info("market_scan_started")
        results = service.scan()
        log.info("market_scan_finished count=%d", len(results))
        time.sleep(300)


if __name__ == "__main__":
    run()
