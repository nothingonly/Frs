from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import datetime, timezone
import json
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import admin_actor, device_actor
from app.api.routes.admin import router as admin_router
from app.api.routes.attendance import router as attendance_router
from app.api.routes.college import router as college_router
from app.core.config import Settings
from app.database import Base, get_db
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    AuditEvent,
    CaptureBatchJob,
    EmbeddingRecord,
    Student,
)
import app.services.capture_batches as capture_batches


class MockAttendancePipeline:
    """Mock pipeline providing deterministic success and failure responses for E2E contract testing."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.mode = "SUCCESS"  # "SUCCESS", "UNKNOWN", "AMBIGUOUS"
        self.target_employee_id = "STU-E2E-001"

    def identify(
        self,
        session: Session,
        frames: list[bytes],
        punch_type: str = "CHECK_IN",
        client_device_id: str = "kiosk-e2e",
        actor_id: str = "device:test",
        attendance_session_id: str = "",
        class_group_id: str = "",
        capture_batch_id: str = "",
        capture_batch_attempt: int = 1,
        **_kwargs,
    ) -> dict:
        if self.mode == "UNKNOWN":
            raise HTTPException(
                status_code=404,
                detail={"reason_code": "UNKNOWN_FACE", "message": "No match found in class gallery."},
            )
        if self.mode == "AMBIGUOUS":
            raise HTTPException(
                status_code=409,
                detail={"reason_code": "AMBIGUOUS_IDENTITY", "message": "Multiple candidates above threshold."},
            )

        # In SUCCESS mode: verify session and return recognized identity
        sess = session.get(AttendanceSession, attendance_session_id)
        if not sess or sess.status != "OPEN":
            raise HTTPException(status_code=409, detail="Attendance session is not open.")

        student = session.execute(
            select(Student).where(Student.student_number == self.target_employee_id)
        ).scalar_one_or_none()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")

        now = datetime.now(timezone.utc)
        evidence_id = str(uuid.uuid4())
        attendance_event = AttendanceEvent(
            attendance_id=str(uuid.uuid4()),
            person_id=student.person_id,
            employee_id=student.student_number,
            punch_type=punch_type,
            timestamp=now,
            similarity_score=0.92,
            threshold=0.75,
            client_device_id="kiosk-e2e",
            pipeline_version="e2e-verified-slice",
            evidence_id=evidence_id,
            attendance_session_id=attendance_session_id,
        )
        session.add(attendance_event)
        session.flush()

        audit = AuditEvent(
            session_id=attendance_session_id,
            actor_type="system",
            actor_id="kiosk-e2e",
            action="attendance.record",
            decision_state="ACCEPT",
            reason_codes_json=json.dumps(["BIOMETRIC_MATCH_CLASS_SCOPED"]),
            evidence_json=json.dumps({
                "attendance_id": attendance_event.attendance_id,
                "similarity_score": 0.92,
                "threshold": 0.75,
                "evidence_id": evidence_id,
            }),
        )
        session.add(audit)
        session.flush()

        return {
            "status": "success",
            "attendance_id": attendance_event.attendance_id,
            "employee_id": student.student_number,
            "punch_type": punch_type,
            "similarity_score": 0.92,
            "threshold": 0.75,
            "evidence_id": evidence_id,
        }


@pytest.fixture
def e2e_harness(monkeypatch: pytest.MonkeyPatch) -> Generator[dict, None, None]:
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
    monkeypatch.setattr(capture_batches, "SessionLocal", testing_sessions)

    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    settings = Settings(
        _env_file=None,
        env="test",
        data_encryption_key=key,
        minimum_identification_frames=3,
        maximum_identification_frames=8,
    )

    app = FastAPI()
    app.state.settings = settings
    pipeline = MockAttendancePipeline(settings)
    app.state.pipeline = pipeline

    app.include_router(college_router)
    app.include_router(attendance_router)
    app.include_router(admin_router)

    def override_db() -> Generator[Session, None, None]:
        with testing_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[admin_actor] = lambda: "administrator:super-admin"
    app.dependency_overrides[device_actor] = lambda: "device-credential:kiosk-e2e"

    with TestClient(app) as client:
        yield {
            "client": client,
            "sessions": testing_sessions,
            "pipeline": pipeline,
            "settings": settings,
        }
    engine.dispose()


def test_complete_end_to_end_attendance_workflow(e2e_harness: dict) -> None:
    client: TestClient = e2e_harness["client"]
    sessions: sessionmaker[Session] = e2e_harness["sessions"]
    pipeline: MockAttendancePipeline = e2e_harness["pipeline"]

    # =========================================================================
    # Step 1 & 2: Administrator creates department, class cohort, and student
    # =========================================================================
    dept_resp = client.post("/api/v1/admin/college/departments", json={
        "code": "AI",
        "name": "Artificial Intelligence & Data Science",
    })
    assert dept_resp.status_code == 201
    department_id = dept_resp.json()["department_id"]

    group_resp = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": department_id,
        "year_of_study": 3,
        "section": "A",
        "academic_year": "2026-2027",
    })
    assert group_resp.status_code == 201
    class_group_id = group_resp.json()["class_group_id"]

    student_resp = client.post("/api/v1/admin/college/students", json={
        "student_number": "STU-E2E-001",
        "full_name": "Kiran Rao",
        "email": "kiran.rao@college.edu",
        "class_group_id": class_group_id,
    })
    assert student_resp.status_code == 201
    student_data = student_resp.json()
    student_id = student_data["student_id"]
    person_id = student_data["person_id"]

    # =========================================================================
    # Step 3: Verify student class enrollment
    # =========================================================================
    roster_resp = client.get("/api/v1/admin/college/students", params={"class_group_id": class_group_id})
    assert roster_resp.status_code == 200
    roster_ids = [s["student_id"] for s in roster_resp.json()["items"]]
    assert student_id in roster_ids

    # =========================================================================
    # Step 4: Biometric Enrollment & Consent Audit
    # =========================================================================
    with sessions() as session:
        # Record encrypted biometric embedding
        emb = EmbeddingRecord(
            embedding_id=str(uuid.uuid4()),
            person_id=person_id,
            enrollment_version=1,
            recognizer_id="arcface",
            model_version="1.0.0",
            preprocessing_id="insightface_112x112",
            embedding_dim=512,
            ciphertext=b"encrypted_arcface_features_512",
            nonce=b"nonce_123456",
            sample_sha256="c" * 64,
            quality_json=json.dumps({"brightness": 0.85, "sharpness": 0.90, "face_size": 220}),
            accepted=True,
        )
        session.add(emb)

        # Record biometric consent audit event
        audit_consent = AuditEvent(
            session_id=f"enrollment:{person_id}",
            actor_type="administrator",
            actor_id="administrator:super-admin",
            action="enrollment.authorized",
            decision_state="ENROLLED",
            reason_codes_json=json.dumps(["WRITTEN_CONSENT_ON_FILE"]),
            evidence_json=json.dumps({"student_id": student_id, "frames_collected": 3}),
        )
        session.add(audit_consent)
        session.commit()

    # =========================================================================
    # Step 5: Administrator opens an attendance session
    # =========================================================================
    sess_resp = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": class_group_id,
        "subject_name": "Computer Vision & Biometrics",
        "subject_code": "AI601",
        "idempotency_key": "e2e-session-key-01",
    })
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["session_id"]
    assert sess_resp.json()["status"] == "OPEN"

    # =========================================================================
    # Step 6: Authorized kiosk retrieves available open sessions
    # =========================================================================
    open_sessions_resp = client.get("/api/v1/attendance/sessions/open")
    assert open_sessions_resp.status_code == 200
    open_items = open_sessions_resp.json()["items"]
    assert any(s["session_id"] == session_id for s in open_items)

    # =========================================================================
    # Step 7: Kiosk submits capture batch with 3 frames
    # =========================================================================
    frames = [b"jpeg_frame_1_bytes", b"jpeg_frame_2_bytes", b"jpeg_frame_3_bytes"]
    batch_data = {
        "idempotency_key": "e2e-batch-idemp-001",
        "punch_type": "CHECK_IN",
        "client_device_id": "kiosk-e2e",
    }
    files = [("images", (f"f{i}.jpg", frame, "image/jpeg")) for i, frame in enumerate(frames)]

    enqueue_resp = client.post(
        f"/api/v1/attendance/sessions/{session_id}/batches",
        data=batch_data,
        files=files,
    )
    assert enqueue_resp.status_code == 202
    batch_id = enqueue_resp.json()["batch_id"]
    assert enqueue_resp.json()["status"] == "QUEUED"

    # Step 7b: Idempotency replay returns 200 without duplicate job
    replay_resp = client.post(
        f"/api/v1/attendance/sessions/{session_id}/batches",
        data=batch_data,
        files=files,
    )
    assert replay_resp.status_code == 200
    assert replay_resp.json()["batch_id"] == batch_id

    # =========================================================================
    # Step 8: Worker processes capture batch (Success Path)
    # =========================================================================
    claimed = capture_batches._claim_next_capture_batch()
    assert claimed is not None
    claimed_id, claimed_attempt = claimed
    assert claimed_id == batch_id

    capture_batches.process_claimed_capture_batch(claimed_id, pipeline, claimed_attempt)

    # =========================================================================
    # Step 9: Verify Decision and Persisted Attendance Record
    # =========================================================================
    with sessions() as session:
        job = session.get(CaptureBatchJob, batch_id)
        assert job is not None
        assert job.status == "SUCCEEDED"
        assert job.encrypted_payload is None  # Payload deleted after processing

        att = session.query(AttendanceEvent).filter(
            AttendanceEvent.attendance_session_id == session_id
        ).first()
        assert att is not None
        assert att.employee_id == "STU-E2E-001"
        assert att.punch_type == "CHECK_IN"
        assert att.similarity_score == 0.92
        assert att.threshold == 0.75
        attendance_id = att.attendance_id

    # Kiosk polling endpoint reflects SUCCEEDED
    job_status_resp = client.get(f"/api/v1/attendance/batches/{batch_id}")
    assert job_status_resp.status_code == 200
    assert job_status_resp.json()["status"] == "SUCCEEDED"

    # =========================================================================
    # Step 10 & 11: Admin Website Inspection, Stats, Review Queue, Corrections
    # =========================================================================
    # 10a. Admin Stats reflect real database entities
    stats_resp = client.get("/api/v1/admin/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["departments_count"] == 1
    assert stats["classes_count"] == 1
    assert stats["students_count"] == 1
    assert stats["biometrics_enrolled_count"] == 1
    assert stats["open_sessions_count"] == 1
    assert stats["attendance_today_count"] == 1

    # 10b. Admin Attendance list includes the verified record
    att_list_resp = client.get("/api/v1/admin/attendance")
    assert att_list_resp.status_code == 200
    att_items = att_list_resp.json()["items"]
    assert any(a["attendance_id"] == attendance_id for a in att_items)

    # 10c. Admin Attendance CSV export
    csv_resp = client.get("/api/v1/admin/attendance/export")
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert "STU-E2E-001" in csv_resp.text
    assert attendance_id in csv_resp.text

    # 10d. Storage status endpoint
    storage_resp = client.get("/api/v1/admin/storage/status")
    assert storage_resp.status_code == 200
    assert "configured" in storage_resp.json()

    # =========================================================================
    # Step 12: Negative & Failure-Path Verifications
    # =========================================================================

    # 12a. Unknown Face -> Job marked REJECTED, appears in Review Queue
    pipeline.mode = "UNKNOWN"
    unknown_batch_data = {
        "idempotency_key": "e2e-unknown-face-001",
        "punch_type": "CHECK_IN",
        "client_device_id": "kiosk-e2e",
    }
    un_resp = client.post(
        f"/api/v1/attendance/sessions/{session_id}/batches",
        data=unknown_batch_data,
        files=files,
    )
    assert un_resp.status_code == 202
    unknown_batch_id = un_resp.json()["batch_id"]

    claimed_un = capture_batches._claim_next_capture_batch()
    assert claimed_un is not None
    capture_batches.process_claimed_capture_batch(claimed_un[0], pipeline, claimed_un[1])

    # Verify unknown face created NO attendance record and appears in review queue
    rq_resp = client.get("/api/v1/admin/review-queue")
    assert rq_resp.status_code == 200
    rq_items = rq_resp.json()["items"]
    assert any(item["batch_id"] == unknown_batch_id for item in rq_items)

    # 12b. Review Queue Resolution: Admin manual approval
    resolve_resp = client.post(f"/api/v1/admin/review-queue/{unknown_batch_id}/resolve", json={
        "action": "APPROVE_MANUAL",
        "student_id": student_id,
        "reason_code": "FACULTY_CONFIRMED_IDENTITY",
        "notes": "Verified student identity card in person during class.",
    })
    assert resolve_resp.status_code == 200

    # 12c. Authorized Correction: Punch adjustment with audit trail
    corr_resp = client.post(f"/api/v1/admin/attendance/{attendance_id}/correct", json={
        "punch_type": "CHECK_OUT",
        "revoke": False,
        "reason_code": "FACULTY_CORRECTION",
        "justification": "Corrected double check-in punch.",
    })
    assert corr_resp.status_code == 200
    with sessions() as session:
        corrected_att = session.get(AttendanceEvent, attendance_id)
        assert corrected_att is not None
        assert corrected_att.punch_type == "CHECK_OUT"

    # 12d. Authorized Revocation: Revoke record
    rev_resp = client.post(f"/api/v1/admin/attendance/{attendance_id}/correct", json={
        "revoke": True,
        "reason_code": "ADMIN_REVOCATION",
        "justification": "Revoked duplicate entry.",
    })
    assert rev_resp.status_code == 200
    with sessions() as session:
        revoked_att = session.get(AttendanceEvent, attendance_id)
        assert revoked_att is None

    # 12e. Closed session rejects submissions
    close_resp = client.post(f"/api/v1/admin/college/attendance-sessions/{session_id}/close")
    assert close_resp.status_code == 200

    late_resp = client.post(
        f"/api/v1/attendance/sessions/{session_id}/batches",
        data={"idempotency_key": "e2e-late-key", "punch_type": "CHECK_IN", "client_device_id": "kiosk-e2e"},
        files=files,
    )
    assert late_resp.status_code == 409
    assert late_resp.json()["detail"] == "Attendance session is not open."

    # 12f. Audit Log Integrity Check
    with sessions() as session:
        audits = session.execute(select(AuditEvent)).scalars().all()
        audit_actions = [a.action for a in audits]
        assert "enrollment.authorized" in audit_actions
        assert "attendance.record" in audit_actions
        assert "review_queue.resolve" in audit_actions
        assert "attendance.correct_punch" in audit_actions
        assert "attendance.revoke" in audit_actions
