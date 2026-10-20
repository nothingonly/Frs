from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.capture_batches as capture_batches
from app.core.config import Settings
from app.database import Base
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    CaptureBatchJob,
    ClassGroup,
    Department,
)
from app.security import encrypt_capture_payload
from app.services.capture_batches import pack_capture_frames


class RejectingPipeline:
    """Pipeline test double for fail-closed biometric decisions."""

    def __init__(self, settings: Settings, status_code: int) -> None:
        self.settings = settings
        self.status_code = status_code

    def identify(self, *_args, **_kwargs) -> dict[str, str]:
        raise HTTPException(
            status_code=self.status_code,
            detail={"reason_code": "NO_ACCEPTABLE_IDENTITY", "message": "No attendance."},
        )


@pytest.mark.parametrize("decision_status", [404, 409])
def test_non_accept_decision_rejects_batch_and_never_records_attendance(
    monkeypatch: pytest.MonkeyPatch,
    decision_status: int,
) -> None:
    """Unknown and ambiguous outcomes must not become attendance successes."""
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
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(capture_batches, "SessionLocal", test_sessions)

    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    settings = Settings(
        _env_file=None,
        env="test",
        data_encryption_key=key,
        minimum_identification_frames=3,
        maximum_identification_frames=8,
    )
    now = datetime.now(timezone.utc)
    frames = [b"frame-one", b"frame-two", b"frame-three"]
    encrypted_payload, nonce = encrypt_capture_payload(pack_capture_frames(frames), settings)

    try:
        with test_sessions() as db:
            department = Department(code="TST", name="Test Department")
            db.add(department)
            db.flush()
            group = ClassGroup(
                department_id=department.department_id,
                year_of_study=2,
                section="A",
                academic_year="2026-2027",
                is_active=True,
            )
            db.add(group)
            db.flush()
            attendance_session = AttendanceSession(
                class_group_id=group.class_group_id,
                subject_name="Regression Testing",
                starts_at=now,
                status="OPEN",
                created_by="admin:test",
            )
            db.add(attendance_session)
            db.flush()
            job = CaptureBatchJob(
                attendance_session_id=attendance_session.session_id,
                class_group_id=group.class_group_id,
                device_actor_id="device:test",
                client_device_id="kiosk:test",
                idempotency_key="worker-fail-closed-test",
                request_sha256="a" * 64,
                frame_count=len(frames),
                punch_type="CHECK_IN",
                status="PROCESSING",
                encrypted_payload=encrypted_payload,
                payload_nonce=nonce,
                payload_expires_at=now + timedelta(hours=1),
                attempts=1,
                max_attempts=3,
                started_at=now,
                updated_at=now,
            )
            db.add(job)
            db.commit()
            batch_id = job.batch_id

        pipeline = RejectingPipeline(settings, decision_status)
        capture_batches.process_claimed_capture_batch(batch_id, pipeline, claimed_attempt=1)

        with test_sessions() as db:
            persisted = db.get(CaptureBatchJob, batch_id)
            assert persisted is not None
            assert persisted.status == "REJECTED"
            assert persisted.completed_at is not None
            assert persisted.encrypted_payload is None
            assert persisted.payload_nonce is None
            assert persisted.error_json is not None
            assert f'"status_code": {decision_status}' in persisted.error_json
            assert db.execute(select(AttendanceEvent)).scalars().all() == []
    finally:
        engine.dispose()
