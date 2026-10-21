from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import admin_actor
from app.database import Base
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.main import app
from app.services.capture_batches import (
    _finish_failure,
    _recover_stale_jobs,
    list_dead_letter_batches,
    requeue_dead_letter_batch,
    utcnow,
)


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def test_failure_exhaustion_transitions_to_dead_letter(db_session: Session) -> None:
    now = utcnow()
    dept = Department(department_id="d1", code="CS", name="Computer Science")
    cg = ClassGroup(class_group_id="cg1", department_id="d1", year_of_study=1, section="A", academic_year="2026")
    session = AttendanceSession(session_id="as1", class_group_id="cg1", subject_name="Math", created_by="tester", status="OPEN", starts_at=now)
    job = CaptureBatchJob(
        batch_id="batch-dlq-1",
        attendance_session_id="as1",
        class_group_id="cg1",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-1",
        request_sha256="a" * 64,
        frame_count=1,
        punch_type="CHECK_IN",
        status="PROCESSING",
        encrypted_payload=b"dummy",
        payload_nonce=b"nonce",
        payload_expires_at=now + timedelta(hours=1),
        attempts=3,
        max_attempts=3,
    )
    db_session.add_all([dept, cg, session, job])
    db_session.commit()

    # 5xx failure with attempts >= max_attempts should transition to DEAD_LETTER
    _finish_failure(db_session, job, status_code=503, detail="Simulated fatal vision failure", now=now, expected_attempt=3)

    persisted = db_session.get(CaptureBatchJob, "batch-dlq-1")
    assert persisted is not None
    assert persisted.status == "DEAD_LETTER"
    assert persisted.completed_at is not None
    assert persisted.encrypted_payload is not None


def test_stale_lease_exhaustion_transitions_to_dead_letter(db_session: Session) -> None:
    now = utcnow()
    dept = Department(department_id="d1", code="CS", name="Computer Science")
    cg = ClassGroup(class_group_id="cg1", department_id="d1", year_of_study=1, section="A", academic_year="2026")
    session = AttendanceSession(session_id="as1", class_group_id="cg1", subject_name="Math", created_by="tester", status="OPEN", starts_at=now)
    stale_time = now - timedelta(hours=2)
    job = CaptureBatchJob(
        batch_id="batch-dlq-stale",
        attendance_session_id="as1",
        class_group_id="cg1",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-stale",
        request_sha256="b" * 64,
        frame_count=1,
        punch_type="CHECK_IN",
        status="PROCESSING",
        encrypted_payload=b"dummy",
        payload_nonce=b"nonce",
        payload_expires_at=now + timedelta(hours=1),
        attempts=3,
        max_attempts=3,
        updated_at=stale_time,
    )
    db_session.add_all([dept, cg, session, job])
    db_session.commit()

    _recover_stale_jobs(db_session, now)

    persisted = db_session.get(CaptureBatchJob, "batch-dlq-stale")
    assert persisted is not None
    assert persisted.status == "DEAD_LETTER"


def test_requeue_dead_letter_batch(db_session: Session) -> None:
    now = utcnow()
    dept = Department(department_id="d1", code="CS", name="Computer Science")
    cg = ClassGroup(class_group_id="cg1", department_id="d1", year_of_study=1, section="A", academic_year="2026")
    session = AttendanceSession(session_id="as1", class_group_id="cg1", subject_name="Math", created_by="tester", status="OPEN", starts_at=now)
    job = CaptureBatchJob(
        batch_id="batch-dlq-replay",
        attendance_session_id="as1",
        class_group_id="cg1",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-replay",
        request_sha256="c" * 64,
        frame_count=1,
        punch_type="CHECK_IN",
        status="DEAD_LETTER",
        encrypted_payload=b"dummy",
        payload_nonce=b"nonce",
        payload_expires_at=now + timedelta(hours=1),
        attempts=3,
        max_attempts=3,
    )
    db_session.add_all([dept, cg, session, job])
    db_session.commit()

    dead_letters = list_dead_letter_batches(db_session)
    assert len(dead_letters) == 1
    assert dead_letters[0]["batch_id"] == "batch-dlq-replay"

    requeued = requeue_dead_letter_batch(db_session, "batch-dlq-replay", operator_id="admin-1")
    assert requeued["status"] == "QUEUED"
    assert requeued["attempts"] == 0

    reloaded = db_session.get(CaptureBatchJob, "batch-dlq-replay")
    assert reloaded.status == "QUEUED"
    assert reloaded.attempts == 0
    assert "admin-1" in (reloaded.error_json or "")


def test_admin_dlq_api_endpoints() -> None:
    app.dependency_overrides[admin_actor] = lambda: "administrator:super-admin"
    client = TestClient(app)

    response = client.get("/api/v1/admin/batches/dead-letter")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
