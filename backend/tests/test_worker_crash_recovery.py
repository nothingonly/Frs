from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.services.capture_batches import (
    _claim_next_capture_batch,
    _recover_stale_jobs,
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


def test_worker_mid_batch_crash_and_lease_expiry_recovery(db_session: Session) -> None:
    """Simulate an abrupt worker crash mid-batch.

    The job remains in PROCESSING status. Once the lease timeout passes,
    stale recovery automatically reclaims it back to QUEUED status with zero data loss.
    """
    now = utcnow()
    dept = Department(department_id="dept-crash", code="EE", name="Electrical Engineering")
    cg = ClassGroup(class_group_id="cg-crash", department_id="dept-crash", year_of_study=2, section="B", academic_year="2026")
    session = AttendanceSession(
        session_id="session-crash",
        class_group_id="cg-crash",
        subject_name="Circuits",
        created_by="prof-smith",
        status="OPEN",
        starts_at=now,
    )
    # Batch was claimed by worker 1 (attempt 1) and marked PROCESSING, but worker 1 crashed
    stale_time = now - timedelta(minutes=50)
    job = CaptureBatchJob(
        batch_id="batch-crash-001",
        attendance_session_id="session-crash",
        class_group_id="cg-crash",
        device_actor_id="kiosk-actor-1",
        client_device_id="kiosk-tablet-01",
        idempotency_key="idem-crash-001",
        request_sha256="d" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="PROCESSING",
        encrypted_payload=b"encrypted_frames_data_never_lost",
        payload_nonce=b"nonce_secure_123",
        payload_expires_at=now + timedelta(hours=20),
        attempts=1,
        max_attempts=3,
        started_at=stale_time,
        updated_at=stale_time,
    )
    db_session.add_all([dept, cg, session, job])
    db_session.commit()

    # Stale recovery sweep runs (e.g. before next claim)
    _recover_stale_jobs(db_session, now)

    persisted = db_session.get(CaptureBatchJob, "batch-crash-001")
    assert persisted is not None
    # Must be restored to QUEUED so another worker can process it
    assert persisted.status == "QUEUED"
    assert persisted.started_at is None
    # Payload must be intact
    assert persisted.encrypted_payload == b"encrypted_frames_data_never_lost"
    assert persisted.payload_nonce == b"nonce_secure_123"
    # Diagnostic reason must reflect the expired lease
    assert persisted.error_json is not None
    assert "PROCESSING_LEASE_EXPIRED" in persisted.error_json


def test_concurrent_worker_claim_is_atomic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that worker claims are atomic and prevent double-processing of the same batch."""
    from sqlalchemy.pool import StaticPool
    import app.services.capture_batches as capture_batches

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(capture_batches, "SessionLocal", test_sessions)

    now = utcnow()
    with test_sessions() as db:
        dept = Department(department_id="dept-conc", code="ME", name="Mechanical")
        cg = ClassGroup(class_group_id="cg-conc", department_id="dept-conc", year_of_study=3, section="A", academic_year="2026")
        session = AttendanceSession(
            session_id="session-conc",
            class_group_id="cg-conc",
            subject_name="Thermodynamics",
            created_by="prof-jones",
            status="OPEN",
            starts_at=now,
        )
        job1 = CaptureBatchJob(
            batch_id="batch-conc-1",
            attendance_session_id="session-conc",
            class_group_id="cg-conc",
            device_actor_id="kiosk-actor-2",
            client_device_id="kiosk-tablet-02",
            idempotency_key="idem-conc-1",
            request_sha256="e" * 64,
            frame_count=3,
            punch_type="CHECK_IN",
            status="QUEUED",
            encrypted_payload=b"test_payload_bytes",
            payload_nonce=b"test_nonce_bytes",
            payload_expires_at=now + timedelta(hours=2),
            attempts=0,
            max_attempts=3,
        )
        db.add_all([dept, cg, session, job1])
        db.commit()

    # Worker 1 claims the batch
    claim1 = _claim_next_capture_batch()
    assert claim1 is not None
    assert claim1[0] == "batch-conc-1"
    assert claim1[1] == 1  # First attempt

    # Worker 2 simultaneously queries for available batches while Worker 1 is processing
    claim2 = _claim_next_capture_batch()
    # Must be None: cannot double-claim or race on the same batch
    assert claim2 is None

    # Verify database state shows PROCESSING
    with test_sessions() as db:
        job = db.get(CaptureBatchJob, "batch-conc-1")
        assert job is not None
        assert job.status == "PROCESSING"
        assert job.attempts == 1


def test_repeated_worker_crashes_transition_to_dead_letter(db_session: Session) -> None:
    """When a job repeatedly crashes until max_attempts is reached, it transitions to DEAD_LETTER."""
    now = utcnow()
    dept = Department(department_id="dept-repeat", code="CIVIL", name="Civil Engineering")
    cg = ClassGroup(class_group_id="cg-repeat", department_id="dept-repeat", year_of_study=4, section="A", academic_year="2026")
    session = AttendanceSession(
        session_id="session-repeat",
        class_group_id="cg-repeat",
        subject_name="Structures",
        created_by="prof-civil",
        status="OPEN",
        starts_at=now,
    )
    stale_time = now - timedelta(minutes=50)
    job = CaptureBatchJob(
        batch_id="batch-crash-exhausted",
        attendance_session_id="session-repeat",
        class_group_id="cg-repeat",
        device_actor_id="kiosk-actor-3",
        client_device_id="kiosk-tablet-03",
        idempotency_key="idem-crash-exhausted",
        request_sha256="f" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="PROCESSING",
        encrypted_payload=b"persistent_poison_payload",
        payload_nonce=b"nonce_poison_123",
        payload_expires_at=now + timedelta(hours=10),
        attempts=3,  # Already at max_attempts
        max_attempts=3,
        started_at=stale_time,
        updated_at=stale_time,
    )
    db_session.add_all([dept, cg, session, job])
    db_session.commit()

    _recover_stale_jobs(db_session, now)

    persisted = db_session.get(CaptureBatchJob, "batch-crash-exhausted")
    assert persisted is not None
    assert persisted.status == "DEAD_LETTER"
    assert persisted.completed_at is not None
    assert persisted.encrypted_payload is not None
