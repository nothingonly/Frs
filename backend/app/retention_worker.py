from __future__ import annotations

import argparse
import logging
import signal
import time
from typing import Any

from app.core.logging_config import setup_logging
from app.core.metrics import get_metrics
from app.database import SessionLocal, create_schema
from app.services.retention import run_retention_purge

setup_logging()
logger = logging.getLogger("frs.retention_worker")


class RetentionPurgeDaemon:
    """Scheduled background worker for executing biometric retention policies and auditing."""

    def __init__(self, retention_days: int = 30, interval_seconds: float = 86400.0) -> None:
        self.retention_days = retention_days
        self.interval_seconds = interval_seconds
        self._shutdown_requested = False

    def request_shutdown(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Retention worker shutdown signal received (%s); exiting...", sig_name)
        self._shutdown_requested = True

    def run_sweep(self) -> dict[str, Any]:
        """Execute one retention purge sweep."""
        logger.info("Executing retention purge sweep (retention_days=%d)...", self.retention_days)
        start_time = time.perf_counter()
        with SessionLocal() as db:
            result = run_retention_purge(
                db,
                retention_days=self.retention_days,
                operator_id="scheduled-retention-worker",
            )

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        purged_count = result.get("purged_payloads", 0)

        get_metrics().inc_counter("frs_retention_purges_total")
        get_metrics().inc_counter("frs_retention_payloads_purged_total", value=float(purged_count))

        logger.info(
            "Retention sweep completed in %.1fms: %d capture payloads purged.",
            elapsed_ms,
            purged_count,
        )
        return result

    def start(self, once: bool = False) -> None:
        """Run the retention schedule loop."""
        logger.info(
            "FRS retention daemon started (retention_days=%d, interval=%.0fs)",
            self.retention_days,
            self.interval_seconds,
        )

        while not self._shutdown_requested:
            self.run_sweep()
            if once:
                logger.info("Retention sweep executed with --once flag; stopping.")
                break

            # Sleep in 1-second slices so shutdown signals are responsive
            sleep_slices = int(self.interval_seconds)
            for _ in range(sleep_slices):
                if self._shutdown_requested:
                    break
                time.sleep(1)

        logger.info("FRS retention daemon stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="FRS Scheduled Biometric Retention Purge Worker")
    parser.add_argument("--once", action="store_true", help="Execute single retention purge sweep and exit.")
    parser.add_argument("--retention-days", type=int, default=30, help="Days to retain raw biometric frames (default: 30).")
    parser.add_argument("--interval-hours", type=float, default=24.0, help="Interval between sweeps in hours (default: 24.0).")
    args = parser.parse_args()

    create_schema()
    worker = RetentionPurgeDaemon(
        retention_days=args.retention_days,
        interval_seconds=args.interval_hours * 3600.0,
    )

    signal.signal(signal.SIGINT, worker.request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, worker.request_shutdown)

    worker.start(once=args.once)


if __name__ == "__main__":
    main()
