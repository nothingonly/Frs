from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import admin_actor
from app.api.routes.admin import router as admin_router
from app.api.routes.college import router as college_router
from app.database import Base, get_db
from app.db.entities import AttendanceSession, AuditEvent, ClassEnrollment, Person, Student


@pytest.fixture
def client_and_sessions() -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
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
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    app = FastAPI()
    app.include_router(college_router)
    app.include_router(admin_router)

    def override_db() -> Generator[Session, None, None]:
        session = testing_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[admin_actor] = lambda: "administrator:test"
    with TestClient(app) as client:
        yield client, testing_sessions
    engine.dispose()


def create_department(client: TestClient, code: str = "CSE") -> dict:
    response = client.post("/api/v1/admin/college/departments", json={"code": code, "name": "Computer Science"})
    assert response.status_code == 201, response.text
    return response.json()


def create_class_group(client: TestClient, department_id: str, section: str = "A") -> dict:
    response = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": department_id,
        "year_of_study": 3,
        "section": section,
        "academic_year": "2026-2027",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_student_creation_links_biometric_person_and_class_enrollment(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    department = create_department(client)
    group = create_class_group(client, department["department_id"])

    response = client.post("/api/v1/admin/college/students", json={
        "student_number": "cse-3001",
        "full_name": "Test Student",
        "email": "student@example.edu",
        "class_group_id": group["class_group_id"],
    })
    assert response.status_code == 201, response.text
    student = response.json()
    assert student["student_number"] == "CSE-3001"
    assert student["person_id"]
    assert student["class_groups"] == [{
        "class_group_id": group["class_group_id"],
        "department_code": "CSE",
        "year_of_study": 3,
        "section": "A",
        "academic_year": "2026-2027",
    }]

    with sessions() as db:
        persisted = db.get(Student, student["student_id"])
        assert persisted is not None
        assert db.get(Person, student["person_id"]) is not None
        memberships = db.query(ClassEnrollment).filter_by(student_id=student["student_id"], status="ACTIVE").all()
        assert len(memberships) == 1
        audit_rows = db.query(AuditEvent).filter_by(action="student.create").all()
        assert audit_rows
        assert all(len(row.session_id) <= 36 for row in audit_rows)


def test_department_codes_are_normalized_and_duplicates_conflict(client_and_sessions) -> None:
    client, _ = client_and_sessions
    department = create_department(client, "csd")
    assert department["code"] == "CSD"
    duplicate = client.post("/api/v1/admin/college/departments", json={
        "code": "CSD", "name": "Data Science",
    })
    assert duplicate.status_code == 409


@pytest.mark.parametrize("year,academic_year", [
    (0, "2026-2027"),
    (5, "2026-2027"),
    (3, "2026-2028"),
])
def test_class_group_rejects_invalid_year_values(client_and_sessions, year: int, academic_year: str) -> None:
    client, _ = client_and_sessions
    department = create_department(client)
    response = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": department["department_id"],
        "year_of_study": year,
        "section": "A",
        "academic_year": academic_year,
    })
    assert response.status_code == 422


def test_student_cannot_be_enrolled_in_two_sections_of_same_cohort(client_and_sessions) -> None:
    client, _ = client_and_sessions
    department = create_department(client)
    section_a = create_class_group(client, department["department_id"], "A")
    section_b = create_class_group(client, department["department_id"], "B")
    student_response = client.post("/api/v1/admin/college/students", json={
        "student_number": "CSE-3002", "full_name": "Another Student",
        "class_group_id": section_a["class_group_id"],
    })
    assert student_response.status_code == 201
    student_id = student_response.json()["student_id"]

    conflict = client.post(
        f"/api/v1/admin/college/class-groups/{section_b['class_group_id']}/students/{student_id}"
    )
    assert conflict.status_code == 409

    withdrawn = client.delete(
        f"/api/v1/admin/college/class-groups/{section_a['class_group_id']}/students/{student_id}"
    )
    assert withdrawn.status_code == 200
    reassigned = client.post(
        f"/api/v1/admin/college/class-groups/{section_b['class_group_id']}/students/{student_id}"
    )
    assert reassigned.status_code == 201


def test_class_group_filter_and_attendance_session_idempotency(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    department = create_department(client)
    group = create_class_group(client, department["department_id"])
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "CSE-3003", "full_name": "Session Student",
        "class_group_id": group["class_group_id"],
    }).json()

    roster = client.get("/api/v1/admin/college/students", params={"class_group_id": group["class_group_id"]})
    assert roster.status_code == 200
    assert [item["student_id"] for item in roster.json()["items"]] == [student["student_id"]]

    payload = {
        "class_group_id": group["class_group_id"], "subject_name": "Computer Networks",
        "subject_code": "CS301", "idempotency_key": "unique-session-001",
    }
    created = client.post("/api/v1/admin/college/attendance-sessions", json=payload)
    assert created.status_code == 201, created.text
    replay = client.post("/api/v1/admin/college/attendance-sessions", json=payload)
    assert replay.status_code == 200, replay.text
    assert replay.json()["session_id"] == created.json()["session_id"]
    assert replay.json()["idempotent_replay"] is True

    closed = client.post(
        f"/api/v1/admin/college/attendance-sessions/{created.json()['session_id']}/close"
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"
    with sessions() as db:
        row = db.get(AttendanceSession, created.json()["session_id"])
        assert row is not None and row.status == "CLOSED"



def test_attendance_session_idempotency_key_rejects_different_payload(client_and_sessions) -> None:
    client, _ = client_and_sessions
    department = create_department(client)
    group = create_class_group(client, department["department_id"])
    base_payload = {
        "class_group_id": group["class_group_id"],
        "subject_name": "Operating Systems",
        "idempotency_key": "same-key-different-body",
    }
    assert client.post("/api/v1/admin/college/attendance-sessions", json=base_payload).status_code == 201
    changed = {**base_payload, "subject_name": "Database Systems"}
    response = client.post("/api/v1/admin/college/attendance-sessions", json=changed)
    assert response.status_code == 409



def test_student_creation_rejects_inactive_biometric_identity(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    with sessions() as db:
        db.add(Person(employee_id="CSE-3099", full_name="Disabled Student", is_active=False))
        db.commit()

    response = client.post("/api/v1/admin/college/students", json={
        "student_number": "CSE-3099", "full_name": "Disabled Student",
    })
    assert response.status_code == 409, response.text
    with sessions() as db:
        assert db.query(Student).filter_by(student_number="CSE-3099").count() == 0


def test_student_deactivate_and_reactivate(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    student = client.post("/api/v1/admin/college/students", json={
        "student_number": "CSE-4001", "full_name": "Lifecycle Student",
    }).json()
    student_id = student["student_id"]

    deact = client.post(f"/api/v1/admin/college/students/{student_id}/deactivate")
    assert deact.status_code == 200
    assert deact.json()["is_active"] is False

    with sessions() as db:
        s_row = db.get(Student, student_id)
        assert s_row is not None and s_row.is_active is False
        p_row = db.get(Person, s_row.person_id)
        assert p_row is not None and p_row.is_active is False

    react = client.post(f"/api/v1/admin/college/students/{student_id}/reactivate")
    assert react.status_code == 200
    assert react.json()["is_active"] is True

    with sessions() as db:
        s_row = db.get(Student, student_id)
        assert s_row is not None and s_row.is_active is True
        p_row = db.get(Person, s_row.person_id)
        assert p_row is not None and p_row.is_active is True


def test_list_audit_events_and_attendance_session_filter(client_and_sessions) -> None:
    client, sessions = client_and_sessions
    # Perform an audited action
    create_department(client)

    audit_res = client.get("/api/v1/admin/audit")
    assert audit_res.status_code == 200
    items = audit_res.json()["items"]
    assert len(items) > 0
    assert any(item["action"] == "department.create" for item in items)

    filtered_res = client.get("/api/v1/admin/audit", params={"action": "department.create"})
    assert filtered_res.status_code == 200
    assert all(item["action"] == "department.create" for item in filtered_res.json()["items"])

    # A caller-supplied nonexistent session cannot bypass object-level scope checks.
    # The endpoint now fails closed instead of silently returning an empty list.
    att_res = client.get("/api/v1/admin/attendance", params={"attendance_session_id": "non-existent-session-id"})
    assert att_res.status_code == 404
    assert att_res.json()["detail"] == "Attendance session not found."

