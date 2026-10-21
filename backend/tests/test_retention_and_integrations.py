from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    CaptureBatchJob,
    ClassEnrollment,
    ClassGroup,
    Department,
    EmbeddingRecord,
    Person,
    Student,
)
from app.services.integrations import AbsenteeAlertService, CsvExportService, WebhookDispatcher
from app.services.retention import de_enroll_student_biometrics, purge_expired_capture_payloads


def setup_in_memory_db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_purge_expired_capture_payloads() -> None:
    session = setup_in_memory_db()
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=45)

    # 1. Old job with encrypted payload
    old_job = CaptureBatchJob(
        batch_id="batch-old",
        attendance_session_id="session-1",
        class_group_id="cg-1",
        device_actor_id="actor-1",
        client_device_id="kiosk-1",
        idempotency_key="idemp-old",
        request_sha256="a" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="SUCCEEDED",
        encrypted_payload=b"encrypted_burst_bytes",
        payload_nonce=b"123456789012",
        created_at=old_time,
        updated_at=old_time,
        payload_expires_at=now + timedelta(days=1),
    )
    # 2. Fresh job
    fresh_job = CaptureBatchJob(
        batch_id="batch-fresh",
        attendance_session_id="session-1",
        class_group_id="cg-1",
        device_actor_id="actor-1",
        client_device_id="kiosk-1",
        idempotency_key="idemp-fresh",
        request_sha256="b" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="SUCCEEDED",
        encrypted_payload=b"encrypted_burst_bytes",
        payload_nonce=b"123456789012",
        created_at=now,
        updated_at=now,
        payload_expires_at=now + timedelta(days=1),
    )
    session.add_all([old_job, fresh_job])
    session.commit()

    purged = purge_expired_capture_payloads(session, retention_days=30)
    assert purged == 1

    reloaded_old = session.get(CaptureBatchJob, "batch-old")
    assert reloaded_old.encrypted_payload is None
    assert reloaded_old.payload_nonce is None
    assert "retention_purged" in reloaded_old.error_json

    reloaded_fresh = session.get(CaptureBatchJob, "batch-fresh")
    assert reloaded_fresh.encrypted_payload is not None


def test_de_enroll_student_biometrics() -> None:
    session = setup_in_memory_db()
    person = Person(person_id="p-1", employee_id="EMP-001", full_name="Alice Student", is_active=True)
    student = Student(student_id="s-1", student_number="STU-001", full_name="Alice Student", person_id="p-1", is_active=True)
    emb1 = EmbeddingRecord(
        embedding_id="emb-1",
        person_id="p-1",
        enrollment_version=1,
        recognizer_id="ArcFace",
        model_version="v1.0",
        preprocessing_id="insightface_112",
        embedding_dim=512,
        ciphertext=b"enc1",
        nonce=b"nonce1234567",
        sample_sha256="c" * 64,
        quality_json="{}",
        accepted=True,
    )
    emb2 = EmbeddingRecord(
        embedding_id="emb-2",
        person_id="p-1",
        enrollment_version=1,
        recognizer_id="ArcFace",
        model_version="v1.0",
        preprocessing_id="insightface_112",
        embedding_dim=512,
        ciphertext=b"enc2",
        nonce=b"nonce1234568",
        sample_sha256="d" * 64,
        quality_json="{}",
        accepted=True,
    )

    session.add_all([person, student, emb1, emb2])
    session.commit()

    result = de_enroll_student_biometrics(session, "s-1", operator_id="admin-user-99")
    assert result["status"] == "DE_ENROLLED"
    assert result["deleted_embeddings_count"] == 2
    assert len(result["deletion_certificate"]) == 64

    # Verify embeddings are deleted
    assert session.get(EmbeddingRecord, "emb-1") is None
    assert session.get(EmbeddingRecord, "emb-2") is None
    assert session.get(Person, "p-1").is_active is False


def test_csv_export_service() -> None:
    session = setup_in_memory_db()
    dept = Department(department_id="d-1", code="CSE", name="Computer Science")
    cg = ClassGroup(class_group_id="cg-1", department_id="d-1", year_of_study=3, section="A", academic_year="2026-2027")
    person = Person(person_id="p-2", employee_id="EMP-100", full_name="Bob Builder", is_active=True)
    student = Student(student_id="s-1", student_number="STU-100", full_name="Bob Builder", person_id="p-2", is_active=True)
    enroll = ClassEnrollment(enrollment_id="e-1", student_id="s-1", class_group_id="cg-1", status="ACTIVE")
    att_session = AttendanceSession(
        session_id="sess-100",
        class_group_id="cg-1",
        subject_name="Math 101",
        status="OPEN",
        starts_at=datetime.now(timezone.utc),
        created_by="prof-1",
    )
    att_event = AttendanceEvent(
        attendance_id="evt-1",
        attendance_session_id="sess-100",
        person_id="p-2",
        employee_id="EMP-100",
        punch_type="CHECK_IN",
        similarity_score=0.88,
        threshold=0.60,
        client_device_id="kiosk-1",
        pipeline_version="v1.0",
        evidence_id="ev-1",
        timestamp=datetime.now(timezone.utc),
    )

    session.add_all([dept, cg, person, student, enroll, att_session, att_event])
    session.commit()

    csv_data = CsvExportService.export_attendance_csv(session, "sess-100")
    reader = csv.reader(io.StringIO(csv_data))
    rows = list(reader)

    assert len(rows) == 2  # Header + 1 student
    assert rows[0][0] == "Session ID"
    assert rows[1][4] == "STU-100"
    assert rows[1][6] == "PRESENT"


def test_absentee_alert_service() -> None:
    session = setup_in_memory_db()
    dept = Department(department_id="d-1", code="PHY", name="Physics Dept")
    cg = ClassGroup(class_group_id="cg-1", department_id="d-1", year_of_study=3, section="A", academic_year="2026-2027")
    p1 = Person(person_id="p-1", employee_id="EMP-101", full_name="Present Student", is_active=True)
    p2 = Person(person_id="p-2", employee_id="EMP-102", full_name="Absent Student", is_active=True)
    s1 = Student(student_id="s-1", student_number="STU-101", full_name="Present Student", person_id="p-1", is_active=True)
    s2 = Student(student_id="s-2", student_number="STU-102", full_name="Absent Student", person_id="p-2", is_active=True)
    e1 = ClassEnrollment(enrollment_id="e-1", student_id="s-1", class_group_id="cg-1", status="ACTIVE")
    e2 = ClassEnrollment(enrollment_id="e-2", student_id="s-2", class_group_id="cg-1", status="ACTIVE")
    att_session = AttendanceSession(
        session_id="sess-200",
        class_group_id="cg-1",
        subject_name="Physics",
        status="OPEN",
        starts_at=datetime.now(timezone.utc),
        created_by="prof-1",
    )
    evt = AttendanceEvent(
        attendance_id="evt-1",
        attendance_session_id="sess-200",
        person_id="p-1",
        employee_id="EMP-101",
        punch_type="CHECK_IN",
        similarity_score=0.85,
        threshold=0.60,
        client_device_id="kiosk-1",
        pipeline_version="v1.0",
        evidence_id="ev-1",
        timestamp=datetime.now(timezone.utc),
    )

    session.add_all([dept, cg, p1, p2, s1, s2, e1, e2, att_session, evt])
    session.commit()

    absentees = AbsenteeAlertService.find_absentees(session, "sess-200")
    assert len(absentees) == 1
    assert absentees[0]["student_number"] == "STU-102"

    alerts = AbsenteeAlertService.dispatch_mock_alerts(absentees)
    assert alerts["total_alerts"] == 1
    assert alerts["alerts"][0]["status"] == "SENT_MOCK"


def test_webhook_dispatcher_signing() -> None:
    secret = "webhook-signing-secret-123456"
    prepared = WebhookDispatcher.prepare_webhook_request(
        event_type="attendance.recorded",
        data={"session_id": "sess-1", "student_id": "stu-1"},
        secret=secret,
        target_url="https://campus.edu/api/webhook",
    )
    assert prepared["url"] == "https://campus.edu/api/webhook"
    assert "X-FRS-Signature" in prepared["headers"]
    sig_header = prepared["headers"]["X-FRS-Signature"]
    assert sig_header.startswith("sha256=")

    # Verify signature
    body_bytes = prepared["body"].encode("utf-8")
    expected_hash = WebhookDispatcher.sign_payload(body_bytes, secret)
    assert sig_header == f"sha256={expected_hash}"
