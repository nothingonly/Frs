-- FRS migration 0003: encrypted, restart-recoverable attendance capture queue.
-- Camera burst payloads are AES-GCM encrypted with FRS_DATA_ENCRYPTION_KEY and expire after 24h.
-- Payload bytes are deleted after accepted/rejected terminal outcomes. Apply as trusted DB admin.

CREATE TABLE IF NOT EXISTS capture_batch_jobs (
    batch_id VARCHAR(36) PRIMARY KEY,
    attendance_session_id VARCHAR(36) NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE RESTRICT,
    class_group_id VARCHAR(36) NOT NULL REFERENCES class_groups(class_group_id) ON DELETE RESTRICT,
    device_actor_id VARCHAR(120) NOT NULL,
    client_device_id VARCHAR(120) NOT NULL,
    idempotency_key VARCHAR(120) NOT NULL,
    request_sha256 VARCHAR(64) NOT NULL,
    frame_count INTEGER NOT NULL,
    punch_type VARCHAR(20) NOT NULL CHECK (punch_type IN ('CHECK_IN', 'CHECK_OUT')),
    status VARCHAR(20) NOT NULL DEFAULT 'QUEUED'
      CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED')),
    encrypted_payload BYTEA,
    payload_nonce BYTEA,
    payload_expires_at TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    next_attempt_at TIMESTAMPTZ,
    result_json TEXT,
    error_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT uq_capture_batch_device_idempotency UNIQUE (device_actor_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS ix_capture_batch_status_created ON capture_batch_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS ix_capture_batch_session_created ON capture_batch_jobs (attendance_session_id, created_at);
CREATE INDEX IF NOT EXISTS ix_capture_batch_jobs_class_group_id ON capture_batch_jobs (class_group_id);
CREATE INDEX IF NOT EXISTS ix_capture_batch_jobs_device_actor_id ON capture_batch_jobs (device_actor_id);
CREATE INDEX IF NOT EXISTS ix_capture_batch_jobs_status ON capture_batch_jobs (status);
ALTER TABLE capture_batch_jobs ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies: kiosk and admin clients must access data via protected FastAPI.
