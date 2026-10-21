from __future__ import annotations

import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import admin_actor
from app.database import Base
from app.db.entities import AuditEvent, CaptureBatchJob, EmbeddingRecord, Person, Student
from app.main import app
from app.services.retention import (
    de_enroll_student_biometrics,
    run_retention_purge,
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


def test_run_retention_purge_with_audit(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=40)
    job = CaptureBatchJob(
        batch_id="batch-ret-1",
        attendance_session_id="as1",
        class_group_id="cg1",
        device_actor_id="dev-1",
        client_device_id="kiosk-1",
        idempotency_key="idem-ret",
        request_sha256="d" * 64,
        frame_count=1,
        punch_type="CHECK_IN",
        status="SUCCEEDED",
        encrypted_payload=b"old_sensitive_data",
        payload_nonce=b"nonce",
        payload_expires_at=now,
        created_at=old_time,
        updated_at=old_time,
    )
    db_session.add(job)
    db_session.commit()

    result = run_retention_purge(db_session, retention_days=30, operator_id="cron-worker")
    assert result["status"] == "SUCCESS"
    assert result["purged_payloads"] == 1

    reloaded = db_session.get(CaptureBatchJob, "batch-ret-1")
    assert reloaded.encrypted_payload is None
    assert reloaded.payload_nonce is None

    audit = db_session.query(AuditEvent).filter(AuditEvent.action == "RETENTION_PURGE_EXECUTED").first()
    assert audit is not None
    assert audit.actor_id == "cron-worker"


def test_de_enroll_student_with_signed_certificate_and_media_purge(db_session: Session) -> None:
    person = Person(person_id="p-de1", employee_id="EMP-DE1", full_name="Carol Student", is_active=True)
    student = Student(student_id="s-de1", student_number="STU-DE1", full_name="Carol Student", person_id="p-de1", is_active=True)
    emb = EmbeddingRecord(
        embedding_id="emb-de1",
        person_id="p-de1",
        enrollment_version=1,
        recognizer_id="ArcFace",
        model_version="v1.0",
        preprocessing_id="insightface_112",
        embedding_dim=512,
        ciphertext=b"enc",
        nonce=b"nonce",
        sample_sha256="e" * 64,
        quality_json="{}",
        accepted=True,
    )
    db_session.add_all([person, student, emb])
    db_session.commit()

    mock_storage = MagicMock()
    mock_storage.is_configured = True
    mock_storage.delete_media.return_value = True

    result = de_enroll_student_biometrics(
        db=db_session,
        student_id="s-de1",
        operator_id="dean-smith",
        storage_service=mock_storage,
        signing_key="super-secret-institution-signing-key",
    )

    assert result["status"] == "DE_ENROLLED"
    assert result["deleted_embeddings_count"] == 1
    assert result["media_purged"] is True
    assert mock_storage.delete_media.called

    # Verify cryptographic signature on certificate
    signed_cert = result["signed_certificate"]
    assert signed_cert["algorithm"] == "HMAC-SHA256"
    assert signed_cert["issuer"] == "FRS-Biometric-Privacy-Lifecycle"
    assert len(signed_cert["signature"]) == 64

    # Verify signature calculation matches expected HMAC
    raw_str = f"s-de1:p-de1:{result['timestamp']}:1:dean-smith:FULL_DELETION_VERIFIED"
    expected_sig = hmac.new(b"super-secret-institution-signing-key", raw_str.encode("utf-8"), hashlib.sha256).hexdigest()
    assert signed_cert["signature"] == expected_sig
    assert signed_cert["qualification"] == "FULL_DELETION_VERIFIED"


def test_de_enroll_storage_delete_false_fails_closed(db_session: Session) -> None:
    person = Person(person_id="p-de2", employee_id="EMP-DE2", full_name="Dan Fail", is_active=True)
    student = Student(student_id="s-de2", student_number="STU-DE2", full_name="Dan Fail", person_id="p-de2", is_active=True)
    emb = EmbeddingRecord(
        embedding_id="emb-de2",
        person_id="p-de2",
        enrollment_version=1,
        recognizer_id="ArcFace",
        model_version="v1.0",
        preprocessing_id="insightface_112",
        embedding_dim=512,
        ciphertext=b"enc",
        nonce=b"nonce",
        sample_sha256="f" * 64,
        quality_json="{}",
        accepted=True,
    )
    db_session.add_all([person, student, emb])
    db_session.commit()

    mock_storage = MagicMock()
    mock_storage.is_configured = True
    mock_storage.delete_media.return_value = False  # Cloud provider could not delete or 404

    result = de_enroll_student_biometrics(
        db=db_session,
        student_id="s-de2",
        operator_id="dean-smith",
        storage_service=mock_storage,
    )

    # Must fail closed: media_purged must NEVER be true, status must be DELETION_INCOMPLETE
    assert result["media_purged"] is False
    assert result["status"] == "DELETION_INCOMPLETE"
    assert result["signed_certificate"]["qualification"] == "DELETION_INCOMPLETE"
    assert result["media_deletion_details"]["students/s-de2"] == "FAILED_OR_NOT_FOUND"


def test_de_enroll_storage_unconfigured_fails_closed(db_session: Session) -> None:
    person = Person(person_id="p-de3", employee_id="EMP-DE3", full_name="Eve Unconf", is_active=True)
    student = Student(student_id="s-de3", student_number="STU-DE3", full_name="Eve Unconf", person_id="p-de3", is_active=True)
    db_session.add_all([person, student])
    db_session.commit()

    mock_storage = MagicMock()
    mock_storage.is_configured = False

    result = de_enroll_student_biometrics(
        db=db_session,
        student_id="s-de3",
        operator_id="dean-smith",
        storage_service=mock_storage,
    )

    assert result["media_purged"] is False
    assert result["status"] == "DELETION_INCOMPLETE"
    assert "STORAGE_NOT_CONFIGURED" in result["media_deletion_details"]["students/s-de3"]


def test_de_enroll_storage_partial_success_fails_closed(db_session: Session) -> None:
    person = Person(person_id="p-de4", employee_id="EMP-DE4", full_name="Frank Partial", is_active=True)
    student = Student(student_id="s-de4", student_number="STU-DE4", full_name="Frank Partial", person_id="p-de4", is_active=True)
    db_session.add_all([person, student])
    db_session.commit()

    mock_storage = MagicMock()
    mock_storage.is_configured = True
    # First call succeeds, second call fails
    mock_storage.delete_media.side_effect = [True, False]

    result = de_enroll_student_biometrics(
        db=db_session,
        student_id="s-de4",
        operator_id="dean-smith",
        storage_service=mock_storage,
    )

    assert result["media_purged"] is False
    assert result["status"] == "DELETION_INCOMPLETE"
    assert result["signed_certificate"]["qualification"] == "DELETION_INCOMPLETE"


def test_admin_retention_purge_api() -> None:
    app.dependency_overrides[admin_actor] = lambda: "administrator:super-admin"
    client = TestClient(app)
    response = client.post(
        "/api/v1/admin/retention/purge?retention_days=30",
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "purged_payloads" in data
