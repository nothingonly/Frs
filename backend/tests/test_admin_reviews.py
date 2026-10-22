from __future__ import annotations

from collections.abc import Generator
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import admin_actor
from app.api.routes.admin import router as admin_router
from app.api.routes.college import router as college_router
from app.database import Base, get_db
from app.db.entities import (
    AttendanceEvent,
    AuditEvent,
    CaptureBatchJob,
    EmbeddingRecord,
    Person,
)


@pytest.fixture
def client_and_sessions() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(college_router)
    app.include_router(admin_router)

    def override_db() -> Generator[Session, None, None]:
        session = testing_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[admin_actor] = lambda: "administrator:test"
    with TestClient(app) as client:
        yield client, testing_sessions
    engine.dispose()



def test_manual_attendance_entry_is_open_session_scoped_and_idempotent(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    department = client.post("/api/v1/admin/college/departments", json={
        "code": "MAN", "name": "Manual Attendance Test",
    }).json()
    group = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": department["department_id"],
        "year_of_study": 3,
        "section": "A",
        "academic_year": "2026-2027",
    }).json()
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "MAN3001",
        "full_name": "Manual Attendance Student",
        "class_group_id": group["class_group_id"],
    }).json()
    session = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": group["class_group_id"],
        "subject_name": "Demo Session",
    }).json()
    payload = {
        "student_id": student["student_id"],
        "attendance_session_id": session["session_id"],
        "punch_type": "CHECK_IN",
        "reason_code": "ID_DOCUMENT_VERIFIED",
        "justification": "Verified institutional ID at the desk.",
    }

    first = client.post("/api/v1/admin/attendance/manual-entry", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "success"
    assert first.json().get("idempotent_replay") is not True

    repeated = client.post("/api/v1/admin/attendance/manual-entry", json=payload)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["attendance_id"] == first.json()["attendance_id"]
    assert repeated.json()["idempotent_replay"] is True

    with sessions() as db:
        matching = db.query(AttendanceEvent).filter_by(
            attendance_session_id=session["session_id"],
            employee_id="MAN3001",
            punch_type="CHECK_IN",
        ).all()
        assert len(matching) == 1
        assert matching[0].pipeline_version == "manual-administrative-entry"
        assert matching[0].similarity_score == 0.0
        assert matching[0].threshold == 1.0

    closed = client.post(
        f"/api/v1/admin/college/attendance-sessions/{session['session_id']}/close"
    )
    assert closed.status_code == 200
    blocked = client.post("/api/v1/admin/attendance/manual-entry", json=payload)
    assert blocked.status_code == 409

def test_admin_stats_endpoint(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    # 1. Initially all zero
    response = client.get("/api/v1/admin/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["departments_count"] == 0
    assert data["classes_count"] == 0
    assert data["students_count"] == 0
    assert data["biometrics_enrolled_count"] == 0
    assert data["open_sessions_count"] == 0
    assert data["attendance_today_count"] == 0
    assert data["pending_reviews_count"] == 0

    # 2. Add department, class, student
    dept = client.post("/api/v1/admin/college/departments", json={"code": "CSE", "name": "Computer Science"}).json()
    group = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": dept["department_id"],
        "year_of_study": 3,
        "section": "A",
        "academic_year": "2026-2027",
    }).json()
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "CSE101",
        "full_name": "Aarav Sharma",
        "email": "aarav@example.edu",
        "class_group_id": group["class_group_id"],
    }).json()

    # Create an open session
    client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": group["class_group_id"],
        "subject_name": "Deep Learning",
        "subject_code": "CS601",
    })

    # Check stats before embedding
    response = client.get("/api/v1/admin/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["departments_count"] == 1
    assert data["classes_count"] == 1
    assert data["students_count"] == 1
    assert data["biometrics_enrolled_count"] == 0
    assert data["open_sessions_count"] == 1

    # Enroll an embedding record
    with sessions() as session:
        emb = EmbeddingRecord(
            embedding_id=str(uuid.uuid4()),
            person_id=student["person_id"],
            enrollment_version=1,
            recognizer_id="arcface",
            model_version="1.0.0",
            preprocessing_id="insightface_112x112",
            embedding_dim=512,
            ciphertext=b"dummy_ciphertext",
            nonce=b"dummy_nonce_12",
            sample_sha256="a" * 64,
            quality_json="{}",
            accepted=True,
        )
        session.add(emb)
        session.commit()

    response = client.get("/api/v1/admin/stats")
    assert response.json()["biometrics_enrolled_count"] == 1


def test_review_queue_and_resolution(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    # Setup hierarchy
    dept = client.post("/api/v1/admin/college/departments", json={"code": "ECE", "name": "Electronics"}).json()
    group = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": dept["department_id"],
        "year_of_study": 2,
        "section": "B",
        "academic_year": "2026-2027",
    }).json()
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "ECE201",
        "full_name": "Neha Verma",
        "email": "neha@example.edu",
        "class_group_id": group["class_group_id"],
    }).json()

    # Open session
    sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": group["class_group_id"],
        "subject_name": "Signals & Systems",
    }).json()

    # Insert a REJECTED capture batch job directly
    now = datetime.now(timezone.utc)
    batch_id = str(uuid.uuid4())
    with sessions() as session:
        job = CaptureBatchJob(
            batch_id=batch_id,
            attendance_session_id=sess["session_id"],
            class_group_id=group["class_group_id"],
            device_actor_id="device:kiosk-01",
            client_device_id="kiosk:gate-02",
            idempotency_key=str(uuid.uuid4()),
            request_sha256="b" * 64,
            punch_type="CHECK_IN",
            frame_count=3,
            status="REJECTED",
            payload_expires_at=now,
            error_json=json.dumps({"code": "UNKNOWN_FACE", "message": "Similarity below threshold"}),
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        session.commit()

    # 1. Check review queue
    rq_resp = client.get("/api/v1/admin/review-queue")
    assert rq_resp.status_code == 200
    items = rq_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["batch_id"] == batch_id
    assert items[0]["status"] == "REJECTED"
    assert items[0]["subject_name"] == "Signals & Systems"

    # 2. Resolve with APPROVE_MANUAL
    resolve_resp = client.post(f"/api/v1/admin/review-queue/{batch_id}/resolve", json={
        "action": "APPROVE_MANUAL",
        "student_id": student["student_id"],
        "reason_code": "FACULTY_CONFIRMED_IDENTITY",
        "notes": "Verified student ID card in person.",
    })
    assert resolve_resp.status_code == 200
    res_data = resolve_resp.json()
    assert res_data["status"] == "success"
    assert res_data["action"] == "APPROVE_MANUAL"

    # Verify job status updated to SUCCEEDED and attendance recorded
    with sessions() as session:
        updated_job = session.get(CaptureBatchJob, batch_id)
        assert updated_job is not None
        assert updated_job.status == "SUCCEEDED"

        # Check attendance event
        att = session.query(AttendanceEvent).filter(
            AttendanceEvent.attendance_session_id == sess["session_id"]
        ).first()
        assert att is not None
        assert att.employee_id == "ECE201"
        assert att.punch_type == "CHECK_IN"
        assert att.pipeline_version == "manual-administrative-review"

        # Check audit event
        audit = session.query(AuditEvent).filter(
            AuditEvent.action == "review_queue.resolve"
        ).first()
        assert audit is not None
        assert audit.decision_state == "MANUALLY_APPROVED"


def test_attendance_correction_and_revocation(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    # Create dummy Person first so foreign key is satisfied
    now = datetime.now(timezone.utc)
    person_id = str(uuid.uuid4())
    att_id = str(uuid.uuid4())
    with sessions() as session:
        person = Person(
            person_id=person_id,
            employee_id="STU999",
            full_name="Dummy Student",
            department="CSE",
            is_active=True,
            enrollment_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(person)
        session.flush()

        att = AttendanceEvent(
            attendance_id=att_id,
            person_id=person_id,
            employee_id="STU999",
            punch_type="CHECK_IN",
            timestamp=now,
            similarity_score=0.88,
            threshold=0.75,
            client_device_id="kiosk:test",
            pipeline_version="v5",
            evidence_id="evidence:999",
            attendance_session_id=None,
        )
        session.add(att)
        session.commit()

    # 1. Correct punch type to CHECK_OUT
    corr_resp = client.post(f"/api/v1/admin/attendance/{att_id}/correct", json={
        "punch_type": "CHECK_OUT",
        "revoke": False,
        "reason_code": "FACULTY_CORRECTION",
        "justification": "Student mistakenly punched check-in twice.",
    })
    assert corr_resp.status_code == 200
    assert corr_resp.json()["action"] == "attendance.correct_punch"

    with sessions() as session:
        updated_att = session.get(AttendanceEvent, att_id)
        assert updated_att is not None
        assert updated_att.punch_type == "CHECK_OUT"

    # 2. Revoke attendance
    revoke_resp = client.post(f"/api/v1/admin/attendance/{att_id}/correct", json={
        "revoke": True,
        "reason_code": "ADMIN_REVOCATION",
        "justification": "Duplicate entry mistakenly registered.",
    })
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["action"] == "attendance.revoke"

    with sessions() as session:
        deleted_att = session.get(AttendanceEvent, att_id)
        assert deleted_att is None

        # Verify audit entry recorded
        audit = session.query(AuditEvent).filter(AuditEvent.action == "attendance.revoke").first()
        assert audit is not None
        assert audit.decision_state == "REVOKED"


def test_manual_attendance_entry(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    dept = client.post("/api/v1/admin/college/departments", json={"code": "MECH", "name": "Mechanical"}).json()
    group = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": dept["department_id"],
        "year_of_study": 1,
        "section": "A",
        "academic_year": "2026-2027",
    }).json()
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "MECH001",
        "full_name": "Rohan Gupta",
        "email": "rohan@example.edu",
        "class_group_id": group["class_group_id"],
    }).json()

    sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": group["class_group_id"],
        "subject_name": "Thermodynamics",
    }).json()

    # Manual entry request
    entry_resp = client.post("/api/v1/admin/attendance/manual-entry", json={
        "attendance_session_id": sess["session_id"],
        "student_id": student["student_id"],
        "punch_type": "CHECK_IN",
        "reason_code": "MANUAL_FACULTY_OVERRIDE",
        "justification": "Student arrived with signed faculty pass.",
    })
    assert entry_resp.status_code == 200
    att_id = entry_resp.json()["attendance_id"]

    with sessions() as session:
        att = session.get(AttendanceEvent, att_id)
        assert att is not None
        assert att.employee_id == "MECH001"
        assert att.punch_type == "CHECK_IN"
        assert att.pipeline_version == "manual-administrative-entry"


def test_attendance_csv_export(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    dept = client.post("/api/v1/admin/college/departments", json={"code": "CIVIL", "name": "Civil Eng"}).json()
    group = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": dept["department_id"],
        "year_of_study": 4,
        "section": "A",
        "academic_year": "2026-2027",
    }).json()
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "CIV401",
        "full_name": "Pooja Hegde",
        "email": "pooja@example.edu",
        "class_group_id": group["class_group_id"],
    }).json()
    sess = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": group["class_group_id"],
        "subject_name": "Structural Analysis",
    }).json()

    # Create attendance
    client.post("/api/v1/admin/attendance/manual-entry", json={
        "attendance_session_id": sess["session_id"],
        "student_id": student["student_id"],
        "punch_type": "CHECK_IN",
        "reason_code": "FACULTY_CONFIRMED",
        "justification": "On-time arrival in lab.",
    })

    # Export CSV
    export_resp = client.get("/api/v1/admin/attendance/export")
    assert export_resp.status_code == 200
    assert export_resp.headers["content-type"].startswith("text/csv")
    csv_text = export_resp.text
    assert "attendance_id,employee_id,punch_type" in csv_text
    assert "CIV401" in csv_text
    assert "CHECK_IN" in csv_text

    # Filtered export
    filtered_resp = client.get("/api/v1/admin/attendance/export", params={"employee_id": "CIV401"})
    assert filtered_resp.status_code == 200
    assert "CIV401" in filtered_resp.text

    non_matching_resp = client.get("/api/v1/admin/attendance/export", params={"employee_id": "NOBODY"})
    assert non_matching_resp.status_code == 200
    assert "CIV401" not in non_matching_resp.text


def test_storage_endpoints_behavior(client_and_sessions: tuple[TestClient, sessionmaker[Session]]) -> None:
    client, sessions = client_and_sessions

    # 1. When storage is not attached or unconfigured
    status_resp = client.get("/api/v1/admin/storage/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["configured"] is False

    signed_resp = client.post("/api/v1/admin/storage/signed-url", json={
        "public_id": "frs/audit/sample123",
        "expires_in_seconds": 300,
    })
    assert signed_resp.status_code == 503
    assert "Cloud storage is not configured" in signed_resp.json()["detail"]

    del_resp = client.post("/api/v1/admin/storage/delete", json={
        "public_id": "frs/audit/sample123",
        "reason_code": "COMPLIANCE_RETENTION_EXPIRY",
    })
    assert del_resp.status_code == 503

    # 2. When storage is configured
    class MockStorageService:
        is_configured = True
        cloud_name = "test_cloud"

        def generate_signed_url(self, public_id: str, expires_in_seconds: int = 300) -> str:
            return f"https://res.cloudinary.com/test_cloud/image/authenticated/s--signed--/{public_id}?exp={expires_in_seconds}"

        def delete_media(self, public_id: str) -> bool:
            return public_id == "frs/audit/valid123"

    client.app.state.storage = MockStorageService()

    status_resp2 = client.get("/api/v1/admin/storage/status")
    assert status_resp2.status_code == 200
    assert status_resp2.json()["configured"] is True
    assert status_resp2.json()["cloud_name"] == "test_cloud"

    signed_resp2 = client.post("/api/v1/admin/storage/signed-url", json={
        "public_id": "frs/audit/valid123",
        "expires_in_seconds": 600,
    })
    assert signed_resp2.status_code == 200
    assert "https://res.cloudinary.com/test_cloud/image/authenticated" in signed_resp2.json()["signed_url"]

    # Delete media success and audit log
    del_resp2 = client.post("/api/v1/admin/storage/delete", json={
        "public_id": "frs/audit/valid123",
        "reason_code": "COMPLIANCE_RETENTION_EXPIRY",
    })
    assert del_resp2.status_code == 200
    assert del_resp2.json()["status"] == "success"

    with sessions() as session:
        audit = session.query(AuditEvent).filter(AuditEvent.action == "storage.delete_media").first()
        assert audit is not None
        assert audit.decision_state == "DELETED"
        assert "COMPLIANCE_RETENTION_EXPIRY" in audit.reason_codes_json

    # Delete media failure
    del_fail = client.post("/api/v1/admin/storage/delete", json={
        "public_id": "frs/audit/invalid",
        "reason_code": "COMPLIANCE_RETENTION_EXPIRY",
    })
    assert del_fail.status_code == 502

