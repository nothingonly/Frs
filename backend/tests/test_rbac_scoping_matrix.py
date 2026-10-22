from __future__ import annotations

import json
from datetime import datetime, timezone
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import router as admin_router
from app.api.routes.college import router as college_router
from app.api.routes.integrations import router as integrations_router
from app.services.integrations import AbsenteeAlertService, CsvExportService
from app.api.routes.enrollment import router as enrollment_router
from app.core.config import Settings
from app.core.auth import ROLE_DEAN, ROLE_FACULTY, create_access_token
from app.core.config import get_settings
from app.database import Base, get_db
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    AuditEvent,
    CaptureBatchJob,
    ClassEnrollment,
    ClassGroup,
    Department,
    Person,
    SessionClassGroup,
    Student,
)


@pytest.fixture
def matrix_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(college_router)
    app.include_router(admin_router)
    app.include_router(integrations_router)
    app.include_router(enrollment_router)
    app.state.settings = get_settings()

    class EnrollmentPipelineStub:
        def enroll(self, db, payloads, *, employee_id, full_name, department, admin_actor_id):
            return {
                "status": "TEST_ENROLLED",
                "employee_id": employee_id,
                "department": department,
                "admin_actor_id": admin_actor_id,
                "frame_count": len(payloads),
            }

    app.state.pipeline = EnrollmentPipelineStub()

    def override_db():
        session = testing_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    now = datetime.now(timezone.utc)

    with testing_sessions() as db:
        cse = Department(department_id="dept-cse", code="CSE", name="Computer Science", is_active=True)
        ece = Department(department_id="dept-ece", code="ECE", name="Electrical Engineering", is_active=True)
        db.add_all([cse, ece])
        db.commit()

        cg_cse_a = ClassGroup(class_group_id="cg-cse-a", department_id="dept-cse", year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
        cg_cse_b = ClassGroup(class_group_id="cg-cse-b", department_id="dept-cse", year_of_study=3, section="B", academic_year="2026-2027", is_active=True)
        cg_ece_a = ClassGroup(class_group_id="cg-ece-a", department_id="dept-ece", year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
        db.add_all([cg_cse_a, cg_cse_b, cg_ece_a])
        db.commit()

        p1 = Person(person_id="per-1", employee_id="STU001", full_name="Alice Smith", department="CSE", is_active=True)
        p2 = Person(person_id="per-2", employee_id="STU002", full_name="Bob Jones", department="ECE", is_active=True)
        db.add_all([p1, p2])
        db.commit()

        s1 = Student(student_id="stu-1", student_number="STU001", full_name="Alice Smith", person_id="per-1", is_active=True)
        s2 = Student(student_id="stu-2", student_number="STU002", full_name="Bob Jones", person_id="per-2", is_active=True)
        db.add_all([s1, s2])
        db.commit()

        e1 = ClassEnrollment(enrollment_id="enr-1", student_id="stu-1", class_group_id="cg-cse-a", status="ACTIVE")
        e2 = ClassEnrollment(enrollment_id="enr-2", student_id="stu-2", class_group_id="cg-ece-a", status="ACTIVE")
        db.add_all([e1, e2])
        db.commit()

        sess_cse = AttendanceSession(session_id="sess-cse-1", class_group_id="cg-cse-a", subject_name="Databases", created_by="admin", status="OPEN")
        sess_cse_closed = AttendanceSession(session_id="sess-cse-closed", class_group_id="cg-cse-a", subject_name="Databases closed", created_by="admin", status="CLOSED")
        sess_ece = AttendanceSession(session_id="sess-ece-1", class_group_id="cg-ece-a", subject_name="Circuits", created_by="admin", status="OPEN")
        sess_mixed = AttendanceSession(session_id="sess-mixed-1", class_group_id="cg-cse-a", subject_name="Joint Lab", created_by="admin", status="CLOSED")
        db.add_all([sess_cse, sess_cse_closed, sess_ece, sess_mixed])
        db.commit()
        db.add(SessionClassGroup(session_id="sess-mixed-1", class_group_id="cg-ece-a"))
        db.commit()

        att_cse = AttendanceEvent(
            attendance_id="att-cse-1",
            person_id="per-1",
            employee_id="STU001",
            punch_type="CHECK_IN",
            timestamp=now,
            similarity_score=0.92,
            threshold=0.65,
            client_device_id="kiosk-cse",
            pipeline_version="v4.1",
            evidence_id="ev-1",
            attendance_session_id="sess-cse-1",
        )
        att_ece = AttendanceEvent(
            attendance_id="att-ece-1",
            person_id="per-2",
            employee_id="STU002",
            punch_type="CHECK_IN",
            timestamp=now,
            similarity_score=0.88,
            threshold=0.65,
            client_device_id="kiosk-ece",
            pipeline_version="v4.1",
            evidence_id="ev-2",
            attendance_session_id="sess-ece-1",
        )
        db.add_all([att_cse, att_ece])
        db.commit()

        job_cse_fail = CaptureBatchJob(
            batch_id="batch-cse-fail",
            attendance_session_id="sess-cse-1",
            class_group_id="cg-cse-a",
            device_actor_id="kiosk-cse",
            client_device_id="kiosk-cse",
            punch_type="CHECK_IN",
            idempotency_key="idemp-cse-1",
            request_sha256="hash1",
            frame_count=3,
            status="FAILED",
            encrypted_payload=b"fake",
            payload_nonce=b"nonce",
            payload_expires_at=now,
            error_json=json.dumps({"detail": "Ambiguous match"}),
        )
        job_ece_fail = CaptureBatchJob(
            batch_id="batch-ece-fail",
            attendance_session_id="sess-ece-1",
            class_group_id="cg-ece-a",
            device_actor_id="kiosk-ece",
            client_device_id="kiosk-ece",
            punch_type="CHECK_IN",
            idempotency_key="idemp-ece-1",
            request_sha256="hash2",
            frame_count=3,
            status="FAILED",
            encrypted_payload=b"fake",
            payload_nonce=b"nonce",
            payload_expires_at=now,
            error_json=json.dumps({"detail": "No face detected"}),
        )
        job_ece_dl = CaptureBatchJob(
            batch_id="batch-ece-dl",
            attendance_session_id="sess-ece-1",
            class_group_id="cg-ece-a",
            device_actor_id="kiosk-ece",
            client_device_id="kiosk-ece",
            punch_type="CHECK_IN",
            idempotency_key="idemp-ece-2",
            request_sha256="hash3",
            frame_count=3,
            status="DEAD_LETTER",
            encrypted_payload=b"fake",
            payload_nonce=b"nonce",
            payload_expires_at=now,
            error_json=json.dumps({"detail": "Retry exhausted"}),
        )
        db.add_all([job_cse_fail, job_ece_fail, job_ece_dl])
        db.commit()

        audit_cse = AuditEvent(
            audit_id="audit-cse-1",
            session_id="sess-cse-1",
            occurred_at=now,
            actor_type="administrator",
            actor_id="admin:dean.cse@campus.edu",
            action="session.open",
            decision_state="OPEN",
            reason_codes_json=json.dumps(["SESSION_STARTED"]),
            evidence_json=json.dumps({"session_id": "sess-cse-1"}),
        )
        audit_ece = AuditEvent(
            audit_id="audit-ece-1",
            session_id="sess-ece-1",
            occurred_at=now,
            actor_type="administrator",
            actor_id="admin:dean.ece@campus.edu",
            action="session.open",
            decision_state="OPEN",
            reason_codes_json=json.dumps(["SESSION_STARTED"]),
            evidence_json=json.dumps({"session_id": "sess-ece-1"}),
        )
        db.add_all([audit_cse, audit_ece])
        db.commit()

    with TestClient(app) as client:
        yield client, testing_sessions
    engine.dispose()



def test_dean_legacy_biometric_enrollment_is_department_scoped(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {dean_cse}"}
    frames = [
        ("images", (f"frame-{index}.jpg", b"demo-frame", "image/jpeg"))
        for index in range(3)
    ]

    denied = client.post(
        "/api/v1/biometrics/enroll/admin",
        data={"employee_id": "STU-ECE-01", "full_name": "ECE Student", "department": "ECE"},
        files=frames,
        headers=headers,
    )
    assert denied.status_code == 403

    allowed = client.post(
        "/api/v1/biometrics/enroll/admin",
        data={"employee_id": "STU-CSE-01", "full_name": "CSE Student", "department": "CSE"},
        files=frames,
        headers=headers,
    )
    assert allowed.status_code == 201
    assert allowed.json()["department"] == "CSE"
    assert allowed.json()["frame_count"] == 3


def test_production_sftp_rejects_request_supplied_trust_and_path(matrix_client, monkeypatch):
    client, _ = matrix_client
    settings = get_settings()
    super_admin = create_access_token(
        sub="super-admin", role="super_admin", secret=settings.effective_jwt_secret,
        email="admin@campus.edu",
    )
    monkeypatch.setattr(
        "app.api.routes.integrations.get_settings",
        lambda: Settings(
            _env_file=None,
            env="production",
            sftp_remote_path="/approved/attendance",
            sftp_host_key_fingerprint="SHA256:trusted-host-key",
        ),
    )
    headers = {"Authorization": f"Bearer {super_admin}"}

    path_override = client.post(
        "/api/v1/integrations/sftp/export",
        json={"session_id": "sess-cse-1", "remote_path": "/other/path"},
        headers=headers,
    )
    assert path_override.status_code == 422
    assert "server configuration" in path_override.json()["detail"]

    key_override = client.post(
        "/api/v1/integrations/sftp/export",
        json={"session_id": "sess-cse-1", "sftp_host_key_fingerprint": "SHA256:attacker-key"},
        headers=headers,
    )
    assert key_override.status_code == 422
    assert "server configuration" in key_override.json()["detail"]


def test_mixed_session_exports_and_absentee_lists_include_all_groups(matrix_client):
    _, testing_sessions = matrix_client
    with testing_sessions() as db:
        ece_student = db.query(Student).filter_by(student_number="STU002").one()
        db.add(AttendanceEvent(
            attendance_id="evt-mixed-manual",
            attendance_session_id="sess-mixed-1",
            person_id=ece_student.person_id,
            employee_id=ece_student.student_number,
            punch_type="CHECK_IN",
            timestamp=datetime.now(timezone.utc),
            similarity_score=0.0,
            threshold=1.0,
            client_device_id="manual-demo",
            pipeline_version="manual-administrative-review",
            evidence_id="manual-review-evidence",
        ))
        db.commit()

        csv_text = CsvExportService.export_attendance_csv(db, "sess-mixed-1")
        assert "STU001" in csv_text
        assert "STU002" in csv_text
        # The ECE enrollment must not be mislabeled as the primary CSE group.
        assert ",ECE,A,STU002," in csv_text
        ece_row = next(line for line in csv_text.splitlines() if "STU002" in line)
        assert ",PRESENT,CHECK_IN,N/A," in ece_row

        absentees = AbsenteeAlertService.find_absentees(db, "sess-mixed-1")
        assert {student["student_number"] for student in absentees} == {"STU001"}



def test_mixed_session_listing_and_closing_require_every_group_scope(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    faculty_cse = create_access_token(
        sub="fac-cse", role=ROLE_FACULTY, secret=settings.effective_jwt_secret,
        email="prof.cse@campus.edu", class_group_ids=["cg-cse-a"],
    )

    for token in (dean_cse, faculty_cse):
        headers = {"Authorization": f"Bearer {token}"}
        sessions = client.get("/api/v1/admin/college/attendance-sessions", headers=headers)
        assert sessions.status_code == 200
        visible_ids = {item["session_id"] for item in sessions.json()["items"]}
        assert "sess-mixed-1" not in visible_ids
        assert "sess-cse-1" in visible_ids

        denied = client.post(
            "/api/v1/admin/college/attendance-sessions/sess-mixed-1/close",
            headers=headers,
        )
        assert denied.status_code == 403


def test_people_identity_routes_fail_closed_for_unscoped_deans(matrix_client):
    client, sessions = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {dean_cse}"}
    people = client.get("/api/v1/admin/people", headers=headers)
    assert people.status_code == 200
    assert {item["employee_id"] for item in people.json()["items"]} == {"STU001"}

    missing_department = create_access_token(
        sub="dean-no-dept", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.unknown@campus.edu",
    )
    missing_headers = {"Authorization": f"Bearer {missing_department}"}
    assert client.get("/api/v1/admin/people", headers=missing_headers).status_code == 403
    assert client.post(
        "/api/v1/admin/people/STU002/deactivate", headers=missing_headers,
    ).status_code == 403

    unknown_department = create_access_token(
        sub="dean-unknown-dept", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.unknown@campus.edu", department_id="dept-does-not-exist",
    )
    unknown_headers = {"Authorization": f"Bearer {unknown_department}"}
    assert client.get("/api/v1/admin/people", headers=unknown_headers).status_code == 403
    assert client.post(
        "/api/v1/admin/people/STU002/reactivate", headers=unknown_headers,
    ).status_code == 403

    with sessions() as db:
        assert db.get(Person, "per-2").is_active is True


def test_dean_cannot_generate_arbitrary_cloudinary_signed_urls(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    response = client.post(
        "/api/v1/admin/storage/signed-url",
        json={"public_id": "frs/faces/STU002", "expires_in_seconds": 300},
        headers={"Authorization": f"Bearer {dean_cse}"},
    )
    assert response.status_code == 403


def test_dean_cross_department_audit_forbidden(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {dean_cse}"}

    # Dean CSE inspecting CSE audit log succeeds
    resp = client.get("/api/v1/admin/audit?session_id=sess-cse-1", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    # Dean CSE inspecting ECE audit log returns 403 Forbidden
    resp = client.get("/api/v1/admin/audit?session_id=sess-ece-1", headers=headers)
    assert resp.status_code == 403
    # Session-level authorization rejects the foreign class group before querying its audit rows.
    assert "Forbidden" in resp.json()["detail"]

    # Direct get_audit for ECE event returns 403 Forbidden
    resp = client.get("/api/v1/admin/audit/audit-ece-1", headers=headers)
    assert resp.status_code == 403


def test_faculty_forbidden_from_admin_audit_and_retention(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    faculty_cse = create_access_token(
        sub="fac-1", role=ROLE_FACULTY, secret=settings.effective_jwt_secret,
        email="prof.cse@campus.edu", class_group_ids=["cg-cse-a"],
    )
    headers = {"Authorization": f"Bearer {faculty_cse}"}

    # Audit list requires scoped_admin -> Faculty gets 403
    resp = client.get("/api/v1/admin/audit", headers=headers)
    assert resp.status_code == 403

    # Retention purge requires Super Admin -> Faculty gets 403
    resp = client.post("/api/v1/admin/retention/purge", headers=headers)
    assert resp.status_code == 403

    # Dead letter triage requires scoped_admin -> Faculty gets 403
    resp = client.get("/api/v1/admin/batches/dead-letter", headers=headers)
    assert resp.status_code == 403

    # SFTP export requires scoped_admin -> Faculty gets 403
    resp = client.post("/api/v1/integrations/sftp/export", json={"session_id": "sess-cse-1"}, headers=headers)
    assert resp.status_code == 403

    # De-enrollment requires scoped_admin -> Faculty gets 403
    resp = client.post("/api/v1/admin/students/stu-1/de-enroll", headers=headers)
    assert resp.status_code == 403


def test_review_queue_and_resolution_scoping(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers_dean_cse = {"Authorization": f"Bearer {dean_cse}"}

    faculty_cse = create_access_token(
        sub="fac-1", role=ROLE_FACULTY, secret=settings.effective_jwt_secret,
        email="prof.cse@campus.edu", class_group_ids=["cg-cse-a"],
    )
    headers_fac_cse = {"Authorization": f"Bearer {faculty_cse}"}

    # Dean CSE only sees CSE reviews
    resp = client.get("/api/v1/admin/review-queue", headers=headers_dean_cse)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["batch_id"] == "batch-cse-fail"

    # Faculty CSE only sees assigned class group reviews
    resp = client.get("/api/v1/admin/review-queue", headers=headers_fac_cse)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1

    # Faculty CSE cannot resolve review for ECE batch -> 403
    resp = client.post("/api/v1/admin/review-queue/batch-ece-fail/resolve", json={
        "action": "DISMISS",
        "reason_code": "MANUAL_DISMISS",
    }, headers=headers_fac_cse)
    assert resp.status_code == 403

    # Dean CSE cannot resolve review for ECE batch -> 403
    resp = client.post("/api/v1/admin/review-queue/batch-ece-fail/resolve", json={
        "action": "DISMISS",
        "reason_code": "MANUAL_DISMISS",
    }, headers=headers_dean_cse)
    assert resp.status_code == 403


def test_attendance_correction_scoping(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    faculty_cse = create_access_token(
        sub="fac-1", role=ROLE_FACULTY, secret=settings.effective_jwt_secret,
        email="prof.cse@campus.edu", class_group_ids=["cg-cse-a"],
    )
    headers_fac_cse = {"Authorization": f"Bearer {faculty_cse}"}

    # Faculty can correct attendance in assigned session
    resp = client.post("/api/v1/admin/attendance/att-cse-1/correct", json={
        "punch_type": "CHECK_OUT",
        "reason_code": "ADMINISTRATIVE_OVERRIDE",
        "justification": "Student left early with permission",
    }, headers=headers_fac_cse)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Faculty is FORBIDDEN from correcting attendance in unassigned ECE session
    resp = client.post("/api/v1/admin/attendance/att-ece-1/correct", json={
        "punch_type": "CHECK_OUT",
        "reason_code": "ADMINISTRATIVE_OVERRIDE",
        "justification": "Cross-department attempt",
    }, headers=headers_fac_cse)
    assert resp.status_code == 403


def test_dean_cross_department_de_enroll_forbidden(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {dean_cse}"}

    # Dean CSE cannot de-enroll ECE student stu-2
    resp = client.post("/api/v1/admin/students/stu-2/de-enroll", headers=headers)
    assert resp.status_code == 403
    assert "own department" in resp.json()["detail"]

    # Dean CSE can de-enroll CSE student stu-1
    resp = client.post("/api/v1/admin/students/stu-1/de-enroll", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["student_id"] == "stu-1"
    assert resp.json()["status"] == "DELETION_INCOMPLETE"


def test_absentee_notifications_and_sftp_scoping(matrix_client):
    client, _ = matrix_client
    settings = get_settings()
    dean_cse = create_access_token(
        sub="dean-cse", role=ROLE_DEAN, secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu", department_id="dept-cse",
    )
    headers_dean_cse = {"Authorization": f"Bearer {dean_cse}"}

    faculty_cse = create_access_token(
        sub="fac-1", role=ROLE_FACULTY, secret=settings.effective_jwt_secret,
        email="prof.cse@campus.edu", class_group_ids=["cg-cse-a"],
    )
    headers_fac_cse = {"Authorization": f"Bearer {faculty_cse}"}

    # Faculty can dry-run absentee alerts for assigned class session
    resp = client.post("/api/v1/integrations/notifications/absentees", json={
        "session_id": "sess-cse-closed",
        "dry_run": True,
    }, headers=headers_fac_cse)
    assert resp.status_code == 200

    # Faculty cannot dispatch absentee alerts for unassigned ECE session -> 403
    resp = client.post("/api/v1/integrations/notifications/absentees", json={
        "session_id": "sess-ece-1",
        "dry_run": True,
    }, headers=headers_fac_cse)
    assert resp.status_code == 403

    # Dean CSE cannot trigger SFTP export for ECE session -> 403
    resp = client.post("/api/v1/integrations/sftp/export", json={
        "session_id": "sess-ece-1",
    }, headers=headers_dean_cse)
    assert resp.status_code == 403

    # Mixed sessions require permission for every participating class group.
    # A user authorized for the primary CSE group must not see ECE absentees.
    resp = client.post("/api/v1/integrations/notifications/absentees", json={
        "session_id": "sess-mixed-1",
        "dry_run": True,
    }, headers=headers_fac_cse)
    assert resp.status_code == 403

    # A Dean's department authority must cover every linked class group too.
    resp = client.post("/api/v1/integrations/notifications/absentees", json={
        "session_id": "sess-mixed-1",
        "dry_run": True,
    }, headers=headers_dean_cse)
    assert resp.status_code == 403

    resp = client.post("/api/v1/integrations/sftp/export", json={
        "session_id": "sess-mixed-1",
    }, headers=headers_dean_cse)
    assert resp.status_code == 403

