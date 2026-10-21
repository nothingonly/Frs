from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import device_actor
from app.database import Base, get_db
from app.db.entities import AttendanceEvent, AuditEvent
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def override_device_actor():
    return "test-kiosk-device-actor"


app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[device_actor] = override_device_actor
client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.mark.parametrize("method", ["STUDENT_ID_PIN", "CARD_NFC", "OTP"])
def test_alternative_attendance_fails_closed_without_real_verifier(method: str) -> None:
    """Identifiers and caller-chosen method strings must never be accepted as proof."""
    response = client.post(
        "/api/v1/attendance/sessions/session-alt-1/alternative",
        json={
            "student_number": "STU-001",
            "punch_type": "CHECK_IN",
            "alternative_method": method,
            "client_device_id": "KIOSK-01",
        },
    )
    assert response.status_code == 503
    assert "verifier is not configured" in response.json()["detail"]

    with TestingSessionLocal() as db:
        assert db.scalar(select(AttendanceEvent.attendance_id)) is None
        assert db.scalar(select(AuditEvent.audit_id).where(AuditEvent.action == "attendance.kiosk_alternative")) is None
