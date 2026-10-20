-- FRS migration 0002: college domain model.
-- Apply to Supabase PostgreSQL (or the institution's PostgreSQL instance) with a trusted
-- database administrator. Browser/mobile clients must not connect to these tables directly.
-- RLS is enabled without public/anon policies; use the protected FastAPI API for access.

CREATE TABLE IF NOT EXISTS departments (
    department_id VARCHAR(36) PRIMARY KEY,
    code VARCHAR(12) NOT NULL UNIQUE,
    name VARCHAR(160) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_departments_code ON departments (code);

CREATE TABLE IF NOT EXISTS class_groups (
    class_group_id VARCHAR(36) PRIMARY KEY,
    department_id VARCHAR(36) NOT NULL REFERENCES departments(department_id) ON DELETE RESTRICT,
    year_of_study INTEGER NOT NULL CHECK (year_of_study BETWEEN 1 AND 4),
    section VARCHAR(20) NOT NULL,
    academic_year VARCHAR(9) NOT NULL CHECK (academic_year ~ '^[0-9]{4}-[0-9]{4}$'),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_class_groups_cohort UNIQUE (department_id, year_of_study, section, academic_year)
);
CREATE INDEX IF NOT EXISTS ix_class_groups_department_id ON class_groups (department_id);

CREATE TABLE IF NOT EXISTS students (
    student_id VARCHAR(36) PRIMARY KEY,
    student_number VARCHAR(80) NOT NULL UNIQUE,
    full_name VARCHAR(200) NOT NULL,
    email VARCHAR(254),
    person_id VARCHAR(36) UNIQUE REFERENCES persons(person_id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_students_student_number ON students (student_number);

CREATE TABLE IF NOT EXISTS class_enrollments (
    enrollment_id VARCHAR(36) PRIMARY KEY,
    student_id VARCHAR(36) NOT NULL REFERENCES students(student_id) ON DELETE RESTRICT,
    class_group_id VARCHAR(36) NOT NULL REFERENCES class_groups(class_group_id) ON DELETE RESTRICT,
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'WITHDRAWN')),
    enrolled_at TIMESTAMPTZ NOT NULL,
    withdrawn_at TIMESTAMPTZ,
    CONSTRAINT uq_class_enrollments_student_group UNIQUE (student_id, class_group_id)
);
CREATE INDEX IF NOT EXISTS ix_class_enrollments_student_id ON class_enrollments (student_id);
CREATE INDEX IF NOT EXISTS ix_class_enrollments_class_group_id ON class_enrollments (class_group_id);
CREATE INDEX IF NOT EXISTS ix_class_enrollments_group_status ON class_enrollments (class_group_id, status);

CREATE TABLE IF NOT EXISTS attendance_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    class_group_id VARCHAR(36) NOT NULL REFERENCES class_groups(class_group_id) ON DELETE RESTRICT,
    subject_code VARCHAR(40),
    subject_name VARCHAR(160) NOT NULL,
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'CLOSED', 'CANCELLED')),
    idempotency_key VARCHAR(120) UNIQUE,
    created_by VARCHAR(120) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attendance_sessions_class_group_id ON attendance_sessions (class_group_id);
CREATE INDEX IF NOT EXISTS ix_attendance_sessions_group_started ON attendance_sessions (class_group_id, starts_at);

ALTER TABLE attendance_events
    ADD COLUMN IF NOT EXISTS attendance_session_id VARCHAR(36)
    REFERENCES attendance_sessions(session_id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS ix_attendance_events_attendance_session_id
    ON attendance_events (attendance_session_id);

ALTER TABLE departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE students ENABLE ROW LEVEL SECURITY;
ALTER TABLE class_enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_sessions ENABLE ROW LEVEL SECURITY;

-- Intentionally no anon/authenticated policies are created here. Browser/mobile code must
-- call FastAPI; use a server-only database credential and add audited organization-specific
-- policies only after the institution's Auth/role model has been designed.
