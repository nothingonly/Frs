from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import device_actor
from app.api.routes.attendance import router as attendance_router
from app.core.config import Settings
from app.database import Base, get_db
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.security import decrypt_capture_payload
from app.services.capture_batches import _finish_failure, pack_capture_frames, unpack_capture_frames


def test_capture_payload_round_trip_and_truncation_guard() -> None:
    frames = [b"first-image", b"second-image", b"third-image"]
    packed = pack_capture_frames(frames)
    assert unpack_capture_frames(packed) == frames
    try:
        unpack_capture_frames(packed[:-1])
    except ValueError:
        pass
    else:
        raise AssertionError("Truncated payload must be rejected.")


def test_capture_batch_is_encrypted_idempotent_and_requires_open_session() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    
    @event.listens_for(engine, 'connect')
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    key = base64.urlsafe_b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
    settings = Settings(_env_file=None, env="test", data_encryption_key=key, minimum_identification_frames=3, maximum_identification_frames=8)
    app = FastAPI()
    app.state.settings = settings
    app.include_router(attendance_router)

    def override_db() -> Generator[Session, None, None]:
        with testing_sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[device_actor] = lambda: "device-credential:test"

    with testing_sessions() as db:
        department = Department(code="CSE", name="Computer Science")
        db.add(department)
        db.flush()
        group = ClassGroup(department_id=department.department_id, year_of_study=3, section='A', academic_year='2026-2027', is_active=True)
        db.add(group)
        db.flush()
        session = AttendanceSession(class_group_id=group.class_group_id, subject_name="Networks", starts_at=datetime.now(timezone.utc), status="OPEN", created_by="admin:test")
        db.add(session)
        db.commit()
        session_id, group_id = session.session_id, group.class_group_id

    with TestClient(app) as client:
        data = {"idempotency_key": "stable-request-key-001", "punch_type": "CHECK_IN", "client_device_id": "kiosk-A"}
        files = [("images", ("frame1.jpg", b"frame-one", "image/jpeg")), ("images", ("frame2.jpg", b"frame-two", "image/jpeg")), ("images", ("frame3.jpg", b"frame-three", "image/jpeg"))]
        url = f"/api/v1/attendance/sessions/{session_id}/batches"
        created = client.post(url, data=data, files=files)
        assert created.status_code == 202, created.text
        payload = created.json()
        assert payload["status"] == "QUEUED"
        assert payload["frame_count"] == 3
        assert payload["class_group_id"] == group_id
        batch_id = payload["batch_id"]

        with testing_sessions() as db:
            job = db.get(CaptureBatchJob, batch_id)
            assert job is not None
            assert job.encrypted_payload is not None
            assert b"frame-one" not in job.encrypted_payload
            decoded = unpack_capture_frames(decrypt_capture_payload(job.encrypted_payload, job.payload_nonce, settings))
            assert decoded == [b"frame-one", b"frame-two", b"frame-three"]

        replay_files = [("images", ("frame1.jpg", b"frame-one", "image/jpeg")), ("images", ("frame2.jpg", b"frame-two", "image/jpeg")), ("images", ("frame3.jpg", b"frame-three", "image/jpeg"))]
        replay = client.post(url, data=data, files=replay_files)
        assert replay.status_code == 200, replay.text
        assert replay.json()["batch_id"] == batch_id

        changed_files = [("images", ("frame1.jpg", b"changed-one", "image/jpeg")), ("images", ("frame2.jpg", b"frame-two", "image/jpeg")), ("images", ("frame3.jpg", b"frame-three", "image/jpeg"))]
        conflict = client.post(url, data=data, files=changed_files)
        assert conflict.status_code == 409

        status = client.get(f"/api/v1/attendance/batches/{batch_id}")
        assert status.status_code == 200
        assert status.json()["attendance_session_id"] == session_id
        assert status.json()["class_group_id"] == group_id
        assert status.json()["status"] == "QUEUED"

        with testing_sessions() as db:
            row = db.get(AttendanceSession, session_id)
            row.status = "CLOSED"
            db.commit()

        denied = client.post(url, data={**data, "idempotency_key": "another-request-key-002"}, files=files)
        assert denied.status_code == 409
        assert denied.json()["detail"] == "Attendance session is not open."

    engine.dispose()



def test_stale_worker_failure_cannot_overwrite_newer_claim() -> None:
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
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with sessions() as db:
        department = Department(code="CSD", name="Data Science")
        db.add(department)
        db.flush()
        group = ClassGroup(
            department_id=department.department_id, year_of_study=2,
            section="A", academic_year="2026-2027", is_active=True,
        )
        db.add(group)
        db.flush()
        attendance_session = AttendanceSession(
            class_group_id=group.class_group_id, subject_name="Algorithms",
            starts_at=now, status="OPEN", created_by="admin:test",
        )
        db.add(attendance_session)
        db.flush()
        job = CaptureBatchJob(
            attendance_session_id=attendance_session.session_id,
            class_group_id=group.class_group_id,
            device_actor_id="device:test",
            client_device_id="kiosk-test",
            idempotency_key="stale-worker-test-key",
            request_sha256="a" * 64,
            frame_count=3,
            punch_type="CHECK_IN",
            status="PROCESSING",
            encrypted_payload=b"ciphertext",
            payload_nonce=b"0123456789ab",
            payload_expires_at=now + timedelta(hours=1),
            attempts=2,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        batch_id = job.batch_id

    with sessions() as db:
        stale_job = db.get(CaptureBatchJob, batch_id)
        assert stale_job is not None
        _finish_failure(
            db, stale_job, 503, "late worker error", now, expected_attempt=1,
        )

    with sessions() as db:
        persisted = db.get(CaptureBatchJob, batch_id)
        assert persisted is not None
        assert persisted.status == "PROCESSING"
        assert persisted.attempts == 2
        assert persisted.encrypted_payload == b"ciphertext"

    engine.dispose()
