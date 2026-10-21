from __future__ import annotations


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

