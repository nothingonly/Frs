from __future__ import annotations


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import device_actor
from app.database import Base, get_db
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    AuditEvent,
    ClassEnrollment,
    ClassGroup,
    Department,
    Person,
    Student,
)
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


def test_record_alternative_attendance_success() -> None:
    db = TestingSessionLocal()
    dept = Department(code="CS", name="Computer Science", is_active=True)
    db.add(dept)
    db.flush()

    cg = ClassGroup(department_id=dept.department_id, year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
    db.add(cg)
    db.flush()

    person = Person(employee_id="STU-001", full_name="John Doe", department="CS", is_active=True)
    db.add(person)
    db.flush()

    student = Student(student_number="STU-001", full_name="John Doe", person_id=person.person_id, is_active=True)
    db.add(student)
    db.flush()

    enrollment = ClassEnrollment(student_id=student.student_id, class_group_id=cg.class_group_id, status="ACTIVE")
    db.add(enrollment)

    session = AttendanceSession(
        session_id="session-alt-1",
        class_group_id=cg.class_group_id,
        subject_name="Operating Systems",
        created_by="dean@campus.edu",
        status="OPEN",
    )
    db.add(session)
    db.commit()
    db.close()

    resp = client.post(
        "/api/v1/attendance/sessions/session-alt-1/alternative",
        json={
            "student_number": "STU-001",
            "punch_type": "CHECK_IN",
            "alternative_method": "STUDENT_ID_PIN",
            "client_device_id": "KIOSK-01",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "ACCEPTED"
    assert data["employee_id"] == "STU-001"
    assert data["full_name"] == "John Doe"
    assert data["method"] == "STUDENT_ID_PIN"

    # Verify AttendanceEvent and AuditEvent written
    db_verify = TestingSessionLocal()
    event = db_verify.query(AttendanceEvent).filter_by(employee_id="STU-001").first()
    assert event is not None
    assert event.punch_type == "CHECK_IN"
    assert "kiosk-alternative:student_id_pin" in event.pipeline_version

    audit = db_verify.query(AuditEvent).filter_by(action="attendance.kiosk_alternative").first()
    assert audit is not None
    assert audit.decision_state == "ACCEPTED"
    db_verify.close()


def test_record_alternative_attendance_rejects_unenrolled_or_closed() -> None:
    db = TestingSessionLocal()
    dept = Department(code="CS", name="Computer Science", is_active=True)
    db.add(dept)
    db.flush()

    cg = ClassGroup(department_id=dept.department_id, year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
    db.add(cg)
    db.flush()

    person = Person(employee_id="STU-002", full_name="Jane Doe", department="CS", is_active=True)
    db.add(person)
    db.flush()

    student = Student(student_number="STU-002", full_name="Jane Doe", person_id=person.person_id, is_active=True)
    db.add(student)

    closed_session = AttendanceSession(
        session_id="session-closed",
        class_group_id=cg.class_group_id,
        subject_name="Databases",
        created_by="dean@campus.edu",
        status="CLOSED",
    )
    db.add(closed_session)
    db.commit()
    db.close()

    # Reject on closed session
    resp = client.post(
        "/api/v1/attendance/sessions/session-closed/alternative",
        json={"student_number": "STU-002", "punch_type": "CHECK_IN"},
    )
    assert resp.status_code == 409
    assert "not open" in resp.json()["detail"].lower()
