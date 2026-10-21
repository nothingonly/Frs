-- FRS migration 0004: add DEAD_LETTER status to capture_batch_jobs check constraint.
-- Forward-migration for existing PostgreSQL databases. Apply as trusted DB admin.

ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS ck_capture_batch_jobs_status;
ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS capture_batch_jobs_status_check;

ALTER TABLE capture_batch_jobs
    ADD CONSTRAINT ck_capture_batch_jobs_status
    CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'DEAD_LETTER'));

-- Verify row-level security remains active
ALTER TABLE capture_batch_jobs ENABLE ROW LEVEL SECURITY;
