-- FRS migration 0005: complete group-photo attendance workflow and academic departments.
-- Supports multi-face group photography, session-level deduplication, provisional attendance,
-- lab sessions, mixed class sessions, and the 7 college engineering departments.

ALTER TABLE class_groups ADD COLUMN IF NOT EXISTS semester INTEGER;
ALTER TABLE class_groups ADD COLUMN IF NOT EXISTS is_lab BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE class_groups ADD COLUMN IF NOT EXISTS lab_name VARCHAR(160);

ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS session_type VARCHAR(20) NOT NULL DEFAULT 'SPECIFIC';
ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS lab_name VARCHAR(160);
ALTER TABLE attendance_sessions ADD COLUMN IF NOT EXISTS semester INTEGER;

CREATE TABLE IF NOT EXISTS session_class_groups (
    session_id VARCHAR(36) NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE CASCADE,
    class_group_id VARCHAR(36) NOT NULL REFERENCES class_groups(class_group_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (session_id, class_group_id)
);
CREATE INDEX IF NOT EXISTS ix_session_class_groups_group ON session_class_groups (class_group_id);

CREATE TABLE IF NOT EXISTS session_group_captures (
    capture_id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL,
    photo_index INTEGER NOT NULL,
    image_sha256 VARCHAR(64) NOT NULL,
    faces_detected_count INTEGER NOT NULL DEFAULT 0,
    faces_matched_count INTEGER NOT NULL DEFAULT 0,
    faces_uncertain_count INTEGER NOT NULL DEFAULT 0,
    faces_unknown_count INTEGER NOT NULL DEFAULT 0,
    duplicates_ignored_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_session_captures_session_idx ON session_group_captures (session_id, photo_index);

CREATE TABLE IF NOT EXISTS session_provisional_attendance (
    provisional_id VARCHAR(36) PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL REFERENCES attendance_sessions(session_id) ON DELETE CASCADE,
    student_id VARCHAR(36) NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    person_id VARCHAR(36) REFERENCES persons(person_id) ON DELETE SET NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'PRESENT',
    similarity_score FLOAT NOT NULL DEFAULT 0.0,
    first_capture_id VARCHAR(36),
    notes VARCHAR(255),
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_session_provisional_student UNIQUE (session_id, student_id)
);
CREATE INDEX IF NOT EXISTS ix_session_provisional_session_status ON session_provisional_attendance (session_id, status);

-- Seed standard engineering college departments
INSERT INTO departments (department_id, code, name, is_active, created_at, updated_at)
VALUES
    ('dept-cse-auto-seed', 'CSE', 'Computer Science and Engineering', TRUE, NOW(), NOW()),
    ('dept-csd-auto-seed', 'CSD', 'Computer Science and Data Science', TRUE, NOW(), NOW()),
    ('dept-mech-auto-seed', 'MECH', 'Mechanical Engineering', TRUE, NOW(), NOW()),
    ('dept-civil-auto-seed', 'CIVIL', 'Civil Engineering', TRUE, NOW(), NOW()),
    ('dept-it-auto-seed', 'IT', 'Information Technology', TRUE, NOW(), NOW()),
    ('dept-ece-auto-seed', 'ECE', 'Electronics and Communication Engineering', TRUE, NOW(), NOW()),
    ('dept-eee-auto-seed', 'EEE', 'Electrical and Electronics Engineering', TRUE, NOW(), NOW())
ON CONFLICT (code) DO NOTHING;

ALTER TABLE session_class_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_group_captures ENABLE ROW LEVEL SECURITY;
ALTER TABLE session_provisional_attendance ENABLE ROW LEVEL SECURITY;
