from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, _upgrade_attendance_session_link, _upgrade_model_registry_provenance
from app.db.entities import (
    AttendanceSession,
    CaptureBatchJob,
    ClassEnrollment,
    ClassGroup,
    Department,
    Person,
    Student,
)


def test_model_registry_provenance_columns_are_added_to_existing_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE model_registry (
                    registry_id VARCHAR(36) PRIMARY KEY,
                    model_id VARCHAR(80) NOT NULL,
                    model_version VARCHAR(120) NOT NULL,
                    artifact_sha256 VARCHAR(64) NOT NULL,
                    artifact_path TEXT NOT NULL,
                    license_name VARCHAR(200) NOT NULL,
                    preprocessing_id VARCHAR(120) NOT NULL,
                    input_contract_json TEXT NOT NULL,
                    output_contract_json TEXT NOT NULL,
                    benchmark_json TEXT DEFAULT '{}',
                    active BOOLEAN NOT NULL DEFAULT 1,
                    registered_at DATETIME NOT NULL
                )
            """))
            connection.execute(text("""
                INSERT INTO model_registry (
                    registry_id, model_id, model_version, artifact_sha256, artifact_path,
                    license_name, preprocessing_id, input_contract_json, output_contract_json,
                    benchmark_json, active, registered_at
                ) VALUES (
                    'legacy', 'ArcFace', 'old-version', 'sha256', '/models/old.onnx',
                    'UNVERIFIED', 'legacy-preprocessing', '{}', '{}', '{}', 1, CURRENT_TIMESTAMP
                )
            """))

        _upgrade_model_registry_provenance(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("model_registry")}
        assert "source_url" in columns
        assert "permitted_use" in columns
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT source_url, permitted_use FROM model_registry WHERE registry_id='legacy'"
            )).one()
        assert row.source_url == ""
        assert row.permitted_use == "UNVERIFIED LEGACY RECORD"

        # The migration is idempotent and does not fail on the already upgraded table.
        _upgrade_model_registry_provenance(engine)
    finally:
        engine.dispose()



def test_attendance_session_link_is_added_to_an_existing_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE attendance_sessions (session_id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(text(
                "CREATE TABLE attendance_events (attendance_id VARCHAR(36) PRIMARY KEY, employee_id VARCHAR(80) NOT NULL)"
            ))

        _upgrade_attendance_session_link(engine)
        columns = {column["name"] for column in inspect(engine).get_columns("attendance_events")}
        assert "attendance_session_id" in columns
        indexes = {index["name"] for index in inspect(engine).get_indexes("attendance_events")}
        assert "ix_attendance_events_attendance_session_id" in indexes

        # Re-running the compatibility migration is safe.
        _upgrade_attendance_session_link(engine)
    finally:
        engine.dispose()


def test_migration_sql_files_exist_and_match_entity_schema() -> None:
    migration_dir = Path(__file__).resolve().parent.parent / "migrations"
    expected_files = [
        "0001_base_schema.sql",
        "0002_college_domain.sql",
        "0003_capture_batches.sql",
    ]
    for filename in expected_files:
        path = migration_dir / filename
        assert path.is_file(), f"Migration file missing: {path}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, f"Migration file {filename} is unexpectedly empty"
        assert "ENABLE ROW LEVEL SECURITY" in content, f"RLS must be enabled in {filename}"

    expected_tables = {
        "persons",
        "embedding_records",
        "attendance_events",
        "audit_events",
        "model_registry",
        "departments",
        "class_groups",
        "students",
        "class_enrollments",
        "attendance_sessions",
        "capture_batch_jobs",
    }
    entity_tables = set(Base.metadata.tables.keys())
    assert expected_tables.issubset(entity_tables)


def test_schema_constraints_and_foreign_keys_enforced() -> None:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        Base.metadata.create_all(engine)
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            # 1. Department uniqueness
            d1 = Department(department_id="dept-1", code="CSE", name="Computer Science")
            session.add(d1)
            session.commit()

            d2 = Department(department_id="dept-2", code="CSE", name="Duplicate Dept")
            session.add(d2)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 2. Class group FK to non-existent department
            cg_bad_fk = ClassGroup(
                class_group_id="cg-bad",
                department_id="non-existent",
                year_of_study=2,
                section="A",
                academic_year="2026-2027",
            )
            session.add(cg_bad_fk)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 3. Class group check constraint on year_of_study (1..4)
            cg_bad_year = ClassGroup(
                class_group_id="cg-bad-year",
                department_id="dept-1",
                year_of_study=5,
                section="A",
                academic_year="2026-2027",
            )
            session.add(cg_bad_year)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 4. Valid class group & duplicate cohort uniqueness
            cg1 = ClassGroup(
                class_group_id="cg-1",
                department_id="dept-1",
                year_of_study=2,
                section="A",
                academic_year="2026-2027",
            )
            session.add(cg1)
            session.commit()

            cg1_dup = ClassGroup(
                class_group_id="cg-2",
                department_id="dept-1",
                year_of_study=2,
                section="A",
                academic_year="2026-2027",
            )
            session.add(cg1_dup)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 5. Restrict deletion of department with class group
            dept_to_delete = session.get(Department, "dept-1")
            session.delete(dept_to_delete)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 6. Student uniqueness on student_number
            p1 = Person(person_id="p-1", employee_id="STU001", full_name="Student One")
            s1 = Student(student_id="s-1", student_number="STU001", full_name="Student One", person_id="p-1")
            session.add_all([p1, s1])
            session.commit()

            s1_dup = Student(student_id="s-2", student_number="STU001", full_name="Student One Duplicate")
            session.add(s1_dup)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 7. Class enrollment check constraint on status
            e_bad = ClassEnrollment(
                enrollment_id="e-bad",
                student_id="s-1",
                class_group_id="cg-1",
                status="INVALID_STATUS",
                enrolled_at=now,
            )
            session.add(e_bad)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 8. Unique class enrollment per student and class group
            e1 = ClassEnrollment(
                enrollment_id="e-1",
                student_id="s-1",
                class_group_id="cg-1",
                status="ACTIVE",
                enrolled_at=now,
            )
            session.add(e1)
            session.commit()

            e1_dup = ClassEnrollment(
                enrollment_id="e-2",
                student_id="s-1",
                class_group_id="cg-1",
                status="ACTIVE",
                enrolled_at=now,
            )
            session.add(e1_dup)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 9. Attendance session check constraint on status
            sess_bad = AttendanceSession(
                session_id="sess-bad",
                class_group_id="cg-1",
                subject_name="Test",
                starts_at=now,
                status="UNKNOWN_STATUS",
                created_by="admin",
            )
            session.add(sess_bad)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            sess1 = AttendanceSession(
                session_id="sess-1",
                class_group_id="cg-1",
                subject_name="Networks",
                starts_at=now,
                status="OPEN",
                idempotency_key="sess-key-01",
                created_by="admin",
            )
            session.add(sess1)
            session.commit()

            # 10. CaptureBatchJob unique constraint on (device_actor_id, idempotency_key)
            job1 = CaptureBatchJob(
                batch_id="batch-1",
                attendance_session_id="sess-1",
                class_group_id="cg-1",
                device_actor_id="device:001",
                client_device_id="kiosk-1",
                idempotency_key="idemp-key-1",
                request_sha256="a" * 64,
                frame_count=3,
                punch_type="CHECK_IN",
                status="QUEUED",
                payload_expires_at=now + timedelta(hours=24),
            )
            session.add(job1)
            session.commit()

            job1_dup = CaptureBatchJob(
                batch_id="batch-2",
                attendance_session_id="sess-1",
                class_group_id="cg-1",
                device_actor_id="device:001",
                client_device_id="kiosk-1",
                idempotency_key="idemp-key-1",
                request_sha256="b" * 64,
                frame_count=3,
                punch_type="CHECK_IN",
                status="QUEUED",
                payload_expires_at=now + timedelta(hours=24),
            )
            session.add(job1_dup)
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()

            # 11. Student SET NULL on Person deletion
            person = session.get(Person, "p-1")
            session.delete(person)
            session.commit()

            student = session.get(Student, "s-1")
            assert student is not None
            assert student.person_id is None
    finally:
        engine.dispose()

