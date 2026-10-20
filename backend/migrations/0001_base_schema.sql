-- FRS migration 0001: base biometrics schema for a fresh PostgreSQL/Supabase project.
-- Apply this before 0002_college_domain.sql. No example people or biometric data are seeded.
-- Direct browser/mobile table access remains disabled; use the protected FastAPI service.

CREATE TABLE IF NOT EXISTS persons (
    person_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    employee_id VARCHAR(80) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    department VARCHAR(160),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    enrollment_version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_persons_employee_id ON persons (employee_id);

CREATE TABLE IF NOT EXISTS embedding_records (
    embedding_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    person_id VARCHAR(36) NOT NULL REFERENCES persons(person_id) ON DELETE CASCADE,
    enrollment_version INTEGER NOT NULL,
    recognizer_id VARCHAR(80) NOT NULL,
    model_version VARCHAR(120) NOT NULL,
    preprocessing_id VARCHAR(120) NOT NULL,
    embedding_dim INTEGER NOT NULL,
    ciphertext BYTEA NOT NULL,
    nonce BYTEA NOT NULL,
    sample_sha256 VARCHAR(64) NOT NULL,
    quality_json TEXT NOT NULL,
    accepted BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_embedding_records_person_id ON embedding_records (person_id);
CREATE INDEX IF NOT EXISTS ix_embedding_records_recognizer_id ON embedding_records (recognizer_id);
CREATE INDEX IF NOT EXISTS ix_embedding_records_sample_sha256 ON embedding_records (sample_sha256);
CREATE INDEX IF NOT EXISTS ix_embedding_person_model ON embedding_records (person_id, recognizer_id, model_version);

CREATE TABLE IF NOT EXISTS attendance_events (
    attendance_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    person_id VARCHAR(36) NOT NULL REFERENCES persons(person_id) ON DELETE RESTRICT,
    employee_id VARCHAR(80) NOT NULL,
    punch_type VARCHAR(20) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    similarity_score DOUBLE PRECISION NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,
    client_device_id VARCHAR(120) NOT NULL,
    pipeline_version VARCHAR(120) NOT NULL,
    evidence_id VARCHAR(36) NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attendance_events_person_id ON attendance_events (person_id);
CREATE INDEX IF NOT EXISTS ix_attendance_events_employee_id ON attendance_events (employee_id);
CREATE INDEX IF NOT EXISTS ix_attendance_events_timestamp ON attendance_events (timestamp);
CREATE INDEX IF NOT EXISTS ix_attendance_person_time ON attendance_events (person_id, timestamp);
CREATE INDEX IF NOT EXISTS ix_attendance_employee_time ON attendance_events (employee_id, timestamp);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    session_id VARCHAR(36) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type VARCHAR(40) NOT NULL,
    actor_id VARCHAR(120) NOT NULL,
    action VARCHAR(120) NOT NULL,
    decision_state VARCHAR(40) NOT NULL,
    reason_codes_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_events_session_id ON audit_events (session_id);
CREATE INDEX IF NOT EXISTS ix_audit_events_occurred_at ON audit_events (occurred_at);

CREATE TABLE IF NOT EXISTS model_registry (
    registry_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    model_id VARCHAR(80) NOT NULL,
    model_version VARCHAR(120) NOT NULL,
    artifact_sha256 VARCHAR(64) NOT NULL,
    artifact_path TEXT NOT NULL,
    license_name VARCHAR(200) NOT NULL,
    source_url TEXT NOT NULL DEFAULT '',
    permitted_use VARCHAR(240) NOT NULL DEFAULT 'UNVERIFIED LEGACY RECORD',
    preprocessing_id VARCHAR(120) NOT NULL,
    input_contract_json TEXT NOT NULL,
    output_contract_json TEXT NOT NULL,
    benchmark_json TEXT NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT TRUE,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_model_registry_version UNIQUE (model_id, model_version)
);
CREATE INDEX IF NOT EXISTS ix_model_registry_model_id ON model_registry (model_id);

ALTER TABLE persons ENABLE ROW LEVEL SECURITY;
ALTER TABLE embedding_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE model_registry ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies are granted in this baseline. Keep the database URL only
-- on the server. Do not put Supabase service-role credentials in Next.js or Flutter.
