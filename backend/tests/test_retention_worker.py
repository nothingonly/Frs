from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.retention_worker as retention_worker_module
from app.core.metrics import get_metrics
from app.database import Base
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.retention_worker import RetentionPurgeDaemon


@pytest.fixture
def isolated_db(monkeypatch: pytest.MonkeyPatch) -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(retention_worker_module, "SessionLocal", test_sessions)
    session = test_sessions()
    try:
        yield session
    finally:
        session.close()


def test_retention_purge_daemon_run_sweep(isolated_db: Session) -> None:
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=45)

    dept = Department(department_id="dept-ret", code="IT", name="Information Tech")
    cg = ClassGroup(class_group_id="cg-ret", department_id="dept-ret", year_of_study=1, section="A", academic_year="2026")
    sess = AttendanceSession(
        session_id="sess-ret",
        class_group_id="cg-ret",
        subject_name="Databases",
        created_by="prof-db",
        status="OPEN",
        starts_at=old_date,
    )
    old_job = CaptureBatchJob(
        batch_id="batch-ret-expired",
        attendance_session_id="sess-ret",
        class_group_id="cg-ret",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-ret-1",
        request_sha256="1" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="SUCCEEDED",
        encrypted_payload=b"old_biometric_data",
        payload_nonce=b"old_nonce",
        payload_expires_at=old_date + timedelta(hours=24),
        attempts=1,
        max_attempts=3,
        created_at=old_date,
    )
    fresh_job = CaptureBatchJob(
        batch_id="batch-ret-fresh",
        attendance_session_id="sess-ret",
        class_group_id="cg-ret",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-ret-2",
        request_sha256="2" * 64,
        frame_count=3,
        punch_type="CHECK_IN",
        status="SUCCEEDED",
        encrypted_payload=b"fresh_biometric_data",
        payload_nonce=b"fresh_nonce",
        payload_expires_at=now + timedelta(hours=24),
        attempts=1,
        max_attempts=3,
        created_at=now,
    )
    isolated_db.add_all([dept, cg, sess, old_job, fresh_job])
    isolated_db.commit()

    daemon = RetentionPurgeDaemon(retention_days=30)
    result = daemon.run_sweep()

    assert result["purged_payloads"] == 1
    assert result["retention_days"] == 30

    # Check metrics
    metrics_text = get_metrics().render()
    assert "frs_retention_purges_total" in metrics_text
    assert "frs_retention_payloads_purged_total" in metrics_text

    # Fresh job payload remains intact
    isolated_db.expire_all()
    reloaded_fresh = isolated_db.get(CaptureBatchJob, "batch-ret-fresh")
    assert reloaded_fresh is not None
    assert reloaded_fresh.encrypted_payload == b"fresh_biometric_data"

    # Expired job payload was securely wiped
    reloaded_old = isolated_db.get(CaptureBatchJob, "batch-ret-expired")
    assert reloaded_old is not None
    assert reloaded_old.encrypted_payload is None
    assert reloaded_old.payload_nonce is None


def test_retention_purge_daemon_start_once(isolated_db: Session) -> None:
    daemon = RetentionPurgeDaemon(retention_days=30, interval_seconds=1.0)
    # --once should complete the sweep and exit without hanging
    daemon.start(once=True)
