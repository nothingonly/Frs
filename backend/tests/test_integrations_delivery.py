from __future__ import annotations


from datetime import datetime, timezone
import base64
import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.dependencies import admin_actor
from app.database import Base
from app.db.entities import AttendanceSession, ClassGroup, Department
from app.main import app
from app.services.integrations import (
    LtiService,
    NotificationManager,
    NotificationMessage,
    SftpExportService,
    SmsNotificationProvider,
    SmtpEmailProvider,
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


def test_smtp_mock_delivery() -> None:
    provider = SmtpEmailProvider(host="mock", sender_email="admin@campus.edu")
    msg = NotificationMessage(recipient="student@campus.edu", subject="Test", body="Notice")
    res = provider.send(msg)
    assert res["status"] == "SENT_MOCK"
    assert res["recipient"] == "student@campus.edu"
    assert res["channel"] == "email"


def test_sms_mock_delivery() -> None:
    provider = SmsNotificationProvider(api_url="mock")
    msg = NotificationMessage(recipient="+1234567890", subject="Alert", body="Test SMS", channel="sms")
    res = provider.send(msg)
    assert res["status"] == "SENT_MOCK"
    assert res["channel"] == "sms"


def test_notification_manager_dispatch() -> None:
    manager = NotificationManager()
    absentees = [
        {"student_number": "STU101", "full_name": "Student One", "session_id": "sess-1"},
        {"student_number": "STU102", "full_name": "Student Two", "session_id": "sess-1"},
    ]
    batch_res = manager.dispatch_batch(absentees, channel="email")
    assert batch_res["total_alerts"] == 2
    assert len(batch_res["alerts"]) == 2
    assert batch_res["alerts"][0]["recipient"] == "stu101@campus.edu"


def test_sftp_export_packaging(db_session: Session) -> None:
    dept = Department(department_id="d-sftp", code="ECE", name="Electrical Eng")
    cg = ClassGroup(class_group_id="cg-sftp", department_id="d-sftp", year_of_study=2, section="B", academic_year="2026")
    sess = AttendanceSession(session_id="sess-sftp", class_group_id="cg-sftp", subject_name="ECE 101", created_by="tester", status="CLOSED")
    db_session.add_all([dept, cg, sess])
    db_session.commit()

    package = SftpExportService.prepare_export_package(db_session, "sess-sftp")
    assert package["session_id"] == "sess-sftp"
    assert len(package["sha256_checksum"]) == 64
    assert package["filename"].startswith("attendance_session_sess-sftp_")

    dispatch = SftpExportService.dispatch_sftp_export(
        db_session, "sess-sftp", sftp_host="mock", sftp_username="sftpuser"
    )
    assert dispatch["status"] in ("STAGED_MOCK", "DISPATCHED")
    assert dispatch["filename"] == package["filename"]


def test_lti_launch_validation() -> None:
    valid_claims = {
        "https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
        "https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
        "aud": "canvas-client-123",
        "sub": "user-456",
        "https://purl.imsglobal.org/spec/lti/claim/context": {"id": "course-101", "title": "Intro to AI"},
        "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"id": "link-1"},
        "https://purl.imsglobal.org/spec/lti/claim/roles": [
            "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
        ],
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id": "dep-1",
    }
    validated = LtiService.validate_launch_claims(valid_claims, expected_client_id="canvas-client-123")
    assert validated["is_valid"] is True
    assert validated["user_id"] == "user-456"
    assert validated["course_id"] == "course-101"

    with pytest.raises(ValueError, match="audience does not match"):
        LtiService.validate_launch_claims(valid_claims, expected_client_id="other-client")


def test_lti_ags_outcome_formatting() -> None:
    outcome = LtiService.format_ags_outcome(sourcedid="student-99", score=1.0)
    assert outcome["scoreGiven"] == 1.0
    assert outcome["activityProgress"] == "Completed"
    assert outcome["gradingProgress"] == "FullyGraded"
    assert outcome["userId"] == "student-99"

    with pytest.raises(ValueError, match="out of bounds"):
        LtiService.format_ags_outcome(sourcedid="student-99", score=1.5)


def test_integrations_api_endpoints() -> None:
    app.dependency_overrides[admin_actor] = lambda: "administrator:super-admin"
    client = TestClient(app)
    # LTI Launch Validate
    launch_resp = client.post(
        "/api/v1/integrations/lti/launch/validate",
        json={
            "claims": {
                "https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
                "https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
                "aud": "client-abc",
                "sub": "user-123",
            },
            "expected_client_id": "client-abc",
        },
    )
    assert launch_resp.status_code == 200
    assert launch_resp.json()["is_valid"] is True

    # LTI AGS Passback
    ags_resp = client.post(
        "/api/v1/integrations/lti/ags/passback",
        json={"sourcedid": "stu-1", "score": 1.0, "comment": "Present in session"},
    )
    assert ags_resp.status_code == 200
    assert ags_resp.json()["scoreGiven"] == 1.0


def test_webhook_dispatcher_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.integrations import WebhookDispatcher

    class MockResponse:
        def __init__(self, code: int = 200) -> None:
            self.code = code
        def getcode(self) -> int:
            return self.code
        def read(self) -> bytes:
            return b'{"ok": true}'
        def __enter__(self) -> "MockResponse":
            return self
        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10.0: MockResponse(200))

    prep = WebhookDispatcher.prepare_webhook_request(
        event_type="attendance.session_closed",
        data={"session_id": "sess-123"},
        secret="test-secret",
        target_url="https://campus.edu/api/webhook",
    )
    res = WebhookDispatcher.dispatch(prep)
    assert res["status"] == "DELIVERED"
    assert res["status_code"] == 200
    assert res["url"] == "https://campus.edu/api/webhook"


def test_sms_live_http_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockSmsResponse:
        def read(self) -> bytes:
            return b'{"status": "delivered", "message_id": "sms-999"}'
        def __enter__(self) -> "MockSmsResponse":
            return self
        def __exit__(self, exc_type, exc_val, exc_tb) -> None:
            pass

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10.0: MockSmsResponse())

    provider = SmsNotificationProvider(api_url="https://sms-gateway.campus.local/v1/send", auth_token="sms-token-xyz")
    msg = NotificationMessage(recipient="+19876543210", subject="Alert", body="Test message", channel="sms")
    res = provider.send(msg)
    assert res["status"] == "SENT"
    assert res["channel"] == "sms"
    assert res["provider"] == "sms_gateway"
    assert "sms-999" in res["gateway_response"]


def test_lti_signed_token_cryptographic_verification() -> None:
    secret = "lti-hmac-shared-secret-key-32chars!"
    token = LtiService.create_launch_token(
        sub="student-uuid-888",
        secret=secret,
        client_id="canvas-client-123",
        issuer="https://canvas.instructure.com",
        deployment_id="dep-deployment-42",
        nonce="secure-nonce-12345",
    )

    validated = LtiService.validate_launch_id_token(
        id_token=token,
        signing_key_or_secret=secret,
        expected_issuer="https://canvas.instructure.com",
        expected_client_id="canvas-client-123",
        expected_deployment_id="dep-deployment-42",
        expected_nonce="secure-nonce-12345",
    )

    assert validated["is_valid"] is True
    assert validated["cryptographically_verified"] is True
    assert validated["user_id"] == "student-uuid-888"
    assert validated["deployment_id"] == "dep-deployment-42"
    assert validated["course_id"] == "course-101"


def test_lti_rs256_verification_uses_trusted_platform_public_key() -> None:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": "test-platform-key"}
    claims = {
        "iss": "https://canvas.example.edu",
        "aud": "frs-client-id",
        "sub": "learner-123",
        "exp": now + 300,
        "iat": now,
        "nonce": "server-issued-nonce-abc",
        "https://purl.imsglobal.org/spec/lti/claim/message_type": "LtiResourceLinkRequest",
        "https://purl.imsglobal.org/spec/lti/claim/version": "1.3.0",
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id": "deployment-1",
        "https://purl.imsglobal.org/spec/lti/claim/context": {"id": "course-1", "title": "Test Course"},
        "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"id": "resource-1"},
        "https://purl.imsglobal.org/spec/lti/claim/roles": ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
    }
    encoded_header = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_claims = b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    id_token = f"{encoded_header}.{encoded_claims}.{b64url(signature)}"
    trusted_public_key = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    verified = LtiService.validate_launch_id_token(
        id_token=id_token,
        signing_key_or_secret=trusted_public_key,
        expected_issuer="https://canvas.example.edu",
        expected_client_id="frs-client-id",
        expected_deployment_id="deployment-1",
        expected_nonce="server-issued-nonce-abc",
    )
    assert verified["cryptographically_verified"] is True
    assert verified["nonce"] == "server-issued-nonce-abc"
    assert verified["user_id"] == "learner-123"


def test_lti_token_verification_failures() -> None:
    secret = "lti-hmac-shared-secret-key-32chars!"
    token = LtiService.create_launch_token(
        sub="student-uuid-888",
        secret=secret,
        client_id="canvas-client-123",
        issuer="https://canvas.instructure.com",
        deployment_id="dep-42",
        nonce="nonce-orig",
    )

    # 1. Forged signature
    with pytest.raises(ValueError, match="Invalid LTI token HMAC signature"):
        LtiService.validate_launch_id_token(
            id_token=token,
            signing_key_or_secret="wrong-secret-key-123456789012345",
        )

    # 2. Issuer mismatch
    with pytest.raises(ValueError, match="issuer mismatch"):
        LtiService.validate_launch_id_token(
            id_token=token,
            signing_key_or_secret=secret,
            expected_issuer="https://moodle.campus.edu",
        )

    # 3. Audience mismatch
    with pytest.raises(ValueError, match="audience does not match"):
        LtiService.validate_launch_id_token(
            id_token=token,
            signing_key_or_secret=secret,
            expected_client_id="wrong-client-id",
        )

    # 4. Nonce mismatch
    with pytest.raises(ValueError, match="nonce mismatch"):
        LtiService.validate_launch_id_token(
            id_token=token,
            signing_key_or_secret=secret,
            expected_nonce="different-nonce",
        )

    # 5. Deployment ID mismatch
    with pytest.raises(ValueError, match="deployment_id mismatch"):
        LtiService.validate_launch_id_token(
            id_token=token,
            signing_key_or_secret=secret,
            expected_deployment_id="wrong-deployment",
        )

    # 6. Expired token
    expired_token = LtiService.create_launch_token(
        sub="student-uuid-888",
        secret=secret,
        expires_delta_seconds=-300,
    )
    with pytest.raises(ValueError, match="expired"):
        LtiService.validate_launch_id_token(
            id_token=expired_token,
            signing_key_or_secret=secret,
            leeway_seconds=0,
        )


def test_lti_api_token_validation_endpoint() -> None:
    app.dependency_overrides[admin_actor] = lambda: "administrator:super-admin"
    client = TestClient(app)
    secret = "lti-secret-for-api-tests-12345678"

    token = LtiService.create_launch_token(
        sub="user-api-99",
        secret=secret,
        client_id="api-client-1",
        issuer="https://canvas.instructure.com",
    )

    # Valid signed token
    resp = client.post(
        "/api/v1/integrations/lti/launch/validate",
        json={
            "id_token": token,
            "signing_key_or_secret": secret,
            "expected_client_id": "api-client-1",
            "expected_issuer": "https://canvas.instructure.com",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True
    assert resp.json()["cryptographically_verified"] is True
    assert resp.json()["user_id"] == "user-api-99"

    # Forged token rejected
    bad_resp = client.post(
        "/api/v1/integrations/lti/launch/validate",
        json={
            "id_token": token,
            "signing_key_or_secret": "forged-secret-key-1234567890123",
            "expected_client_id": "api-client-1",
        },
    )
    assert bad_resp.status_code == 422
    assert "Invalid LTI token" in bad_resp.json()["detail"]


def test_sftp_host_key_fingerprint_mismatch_blocks_export(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    session = db_session
    sess = AttendanceSession(
        session_id="sess-sftp-test",
        class_group_id="cg-1",
        subject_name="Security 101",
        status="CLOSED",
        starts_at=datetime.now(timezone.utc),
        created_by="admin-user",
    )
    session.add(sess)
    session.commit()

    import sys
    from unittest.mock import MagicMock

    mock_paramiko = MagicMock()
    mock_transport = MagicMock()
    mock_key = MagicMock()
    mock_key.asbytes.return_value = b"remote-ssh-server-key-material"
    actual_fp = hashlib.sha256(b"remote-ssh-server-key-material").hexdigest()
    mock_transport.get_remote_server_key.return_value = mock_key

    mock_sftp_client = MagicMock()
    mock_paramiko.Transport.return_value = mock_transport
    mock_paramiko.SFTPClient.from_transport.return_value = mock_sftp_client

    monkeypatch.setitem(sys.modules, "paramiko", mock_paramiko)

    # Calling with mismatched expected fingerprint
    res = SftpExportService.dispatch_sftp_export(
        db=session,
        session_id="sess-sftp-test",
        sftp_host="sftp.campus.edu",
        sftp_username="campus_admin",
        sftp_password="pass",
        sftp_host_key_fingerprint="0000000000000000000000000000000000000000000000000000000000000000",
    )

    assert res["status"] == "REJECTED_HOST_KEY_MISMATCH"
    assert "fingerprint mismatch" in res["error"]
    assert not mock_sftp_client.putfo.called
    assert mock_transport.close.called

    # Calling with matching fingerprint succeeds
    res_ok = SftpExportService.dispatch_sftp_export(
        db=session,
        session_id="sess-sftp-test",
        sftp_host="sftp.campus.edu",
        sftp_username="campus_admin",
        sftp_password="pass",
        sftp_host_key_fingerprint=actual_fp,
    )
    assert res_ok["status"] == "DISPATCHED"
    assert res_ok["server_host_key_fingerprint"] == actual_fp
    assert mock_sftp_client.putfo.called


def test_notification_provider_mock_disallowed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings
    prod_settings = Settings(
        env="production",
        smtp_host="",
        sms_gateway_url="",
    )
    monkeypatch.setattr("app.services.integrations.get_settings", lambda: prod_settings)

    email_provider = SmtpEmailProvider()
    msg = NotificationMessage(recipient="student@campus.edu", subject="Sub", body="Text")
    res = email_provider.send(msg)
    assert res["status"] == "FAILED"
    assert "mock delivery is forbidden in production" in res["error"]

