from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings
from app.core.logging_config import set_correlation_id, setup_logging
from app.core.metrics import get_metrics
from app.database import SessionLocal, create_schema, engine
from app.db.entities import CaptureBatchJob
from app.services.capture_batches import (
    _claim_next_capture_batch,
    as_utc,
    process_claimed_capture_batch,
)
from app.services.pipeline import AttendancePipeline
from app.vision.engine import VisionEngine

setup_logging()
logger = logging.getLogger("frs.worker")


class FRSWorkerDaemon:
    """Standalone out-of-process capture queue worker daemon with graceful shutdown."""

    def __init__(self, pipeline: AttendancePipeline, poll_interval: float = 0.5) -> None:
        self.pipeline = pipeline
        self.poll_interval = poll_interval
        self._shutdown_requested = False
        self._current_batch_id: str | None = None

    def request_shutdown(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Shutdown signal received (%s); finishing active batch...", sig_name)
        self._shutdown_requested = True

    def process_one(self) -> bool:
        """Attempt to claim and process a single batch job. Returns True if a job was processed."""
        claim = _claim_next_capture_batch()
        if not claim:
            return False

        batch_id, claimed_attempt = claim
        self._current_batch_id = batch_id
        set_correlation_id(f"batch-{batch_id[:8]}")
        start_time = time.perf_counter()

        # Measure queue wait time
        queue_wait_ms = 0.0
        try:
            with SessionLocal() as db:
                job = db.get(CaptureBatchJob, batch_id)
                if job:
                    created_at_utc = as_utc(job.created_at)
                    now_utc = datetime.now(timezone.utc)
                    queue_wait_ms = max(0.0, (now_utc - created_at_utc).total_seconds() * 1000)
                    get_metrics().observe_histogram("frs_queue_wait_duration_seconds", queue_wait_ms / 1000.0)
        except Exception:
            pass

        logger.info(
            "Worker claimed batch; batch_id=%s attempt=%d queue_wait=%.1fms",
            batch_id, claimed_attempt, queue_wait_ms,
        )

        try:
            process_claimed_capture_batch(batch_id, self.pipeline, claimed_attempt)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            get_metrics().observe_histogram("frs_batch_processing_duration_seconds", elapsed_ms / 1000.0)
            get_metrics().inc_counter("frs_worker_batches_processed_total")
            logger.info("Batch completed; batch_id=%s duration=%.1fms", batch_id, elapsed_ms)
        finally:
            self._current_batch_id = None

        return True

    def run(self, once: bool = False, max_batches: int | None = None) -> int:
        """Run the worker loop until shutdown or queue exhaustion (if once=True)."""
        logger.info("FRS standalone worker daemon started (poll_interval=%.2fs)", self.poll_interval)
        processed_count = 0

        while not self._shutdown_requested:
            had_job = self.process_one()
            if had_job:
                processed_count += 1
                if max_batches and processed_count >= max_batches:
                    logger.info("Worker reached batch limit (%d); exiting.", max_batches)
                    break
            else:
                if once:
                    logger.info("Queue is empty and --once specified; exiting.")
                    break
                time.sleep(self.poll_interval)

        logger.info("FRS standalone worker stopped cleanly. Total batches processed: %d", processed_count)
        return processed_count


def create_worker(poll_interval: float = 0.5) -> FRSWorkerDaemon:
    """Initialize dependencies and instantiate the worker daemon."""
    settings = get_settings()
    settings.validate_startup_security()
    create_schema()
    from app.db.migrator import assert_production_schema_ready
    assert_production_schema_ready(engine)

    vision = VisionEngine(settings)
    pipeline = AttendancePipeline(settings, vision)
    return FRSWorkerDaemon(pipeline=pipeline, poll_interval=poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="FRS Standalone Capture Batch Worker Daemon")
    parser.add_argument("--once", action="store_true", help="Process until queue is empty, then exit.")
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of batches to process.")
    args = parser.parse_args()

    worker = create_worker(poll_interval=args.interval)

    # Attach signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, worker.request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, worker.request_shutdown)

    try:
        worker.run(once=args.once, max_batches=args.limit)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
