# ADR-0002: Session-Scoped Durable Database Queue and Dead-Letter Isolation

## Status
Accepted

## Context
High-volume attendance sessions in university lecture halls require processing bursts of 3–8 camera frames per student within a narrow time window (e.g. 10 minutes before class). Synchronous HTTP execution on the API web server risks thread exhaustion, request timeouts, and dropped punches under network fluctuations. Furthermore, adding third-party message brokers like Redis or RabbitMQ adds stateful operational overhead and multi-system failover complexity.

## Decision
FRS implements a durable, database-backed capture batch queue (`capture_batch_jobs`) using atomic lease semantics:
- Kiosk clients submit encrypted multi-frame capture payloads with client-generated UUID idempotency keys.
- Processing workers acquire batches atomically via `SELECT ... FOR UPDATE SKIP LOCKED` (PostgreSQL) or atomic updates (SQLite).
- Leases expire after a configurable duration (`_STALE_AFTER = 45 minutes`), allowing automatic recovery if a worker dies mid-batch.
- Retry policy enforces exponential backoff up to `max_attempts` (default: 3).
- Poison messages or repeatedly exhausted batches transition to `DEAD_LETTER` state for operator triage, preventing endless retry loops while preserving payloads until retention expiry.
- The worker can run in-process for development or out-of-process via `FRS_WORKER_IN_PROCESS=false` and the standalone `app.worker:FRSWorkerDaemon` CLI.

## Consequences
- **Positive:** Zero additional infrastructure needed; identical ACID semantics across PostgreSQL and SQLite; full auditability of queued, processing, succeeded, failed, and dead-lettered batches.
- **Positive:** Poison messages are quarantined into `DEAD_LETTER` without blocking subsequent student check-ins.
- **Negative:** Heavy database write volume during peak attendance windows requires index optimization and timely retention purging.
