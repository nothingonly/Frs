from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.admin import router as admin_router
from app.api.routes.college import router as college_router
from app.core.auth import ROLE_DEAN, ROLE_FACULTY, ROLE_SUPER_ADMIN, create_access_token
from app.core.config import get_settings
from app.database import Base, get_db
from app.db.entities import AttendanceSession, ClassEnrollment, ClassGroup, Department, Student


@pytest.fixture
def rbac_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(college_router)
    app.include_router(admin_router)

    def override_db():
        session = testing_sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db

    with testing_sessions() as db:
        cse = Department(department_id="dept-cse", code="CSE", name="Computer Science", is_active=True)
        ece = Department(department_id="dept-ece", code="ECE", name="Electrical Engineering", is_active=True)
        db.add_all([cse, ece])
        db.commit()

        cg_cse_a = ClassGroup(class_group_id="cg-cse-a", department_id="dept-cse", year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
        cg_cse_b = ClassGroup(class_group_id="cg-cse-b", department_id="dept-cse", year_of_study=3, section="B", academic_year="2026-2027", is_active=True)
        cg_ece_a = ClassGroup(class_group_id="cg-ece-a", department_id="dept-ece", year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
        db.add_all([cg_cse_a, cg_cse_b, cg_ece_a])
        db.commit()

        s1 = Student(student_id="stu-1", student_number="STU001", full_name="Alice Smith", is_active=True)
        s2 = Student(student_id="stu-2", student_number="STU002", full_name="Bob Jones", is_active=True)
        db.add_all([s1, s2])
        db.commit()

        e1 = ClassEnrollment(enrollment_id="enr-1", student_id="stu-1", class_group_id="cg-cse-a", status="ACTIVE")
        e2 = ClassEnrollment(enrollment_id="enr-2", student_id="stu-2", class_group_id="cg-cse-b", status="ACTIVE")
        db.add_all([e1, e2])
        db.commit()

        sess_cse_a = AttendanceSession(session_id="sess-cse-a-1", class_group_id="cg-cse-a", subject_name="Databases", created_by="admin", status="OPEN")
        sess_cse_b = AttendanceSession(session_id="sess-cse-b-1", class_group_id="cg-cse-b", subject_name="Algorithms", created_by="admin", status="OPEN")
        sess_ece_a = AttendanceSession(session_id="sess-ece-a-1", class_group_id="cg-ece-a", subject_name="Circuits", created_by="admin", status="OPEN")
        db.add_all([sess_cse_a, sess_cse_b, sess_ece_a])
        db.commit()

    with TestClient(app) as client:
        yield client, testing_sessions
    engine.dispose()


def test_super_admin_has_unrestricted_access(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    token = create_access_token(
        sub="admin-1",
        role=ROLE_SUPER_ADMIN,
        secret=settings.effective_jwt_secret,
        email="superadmin@campus.edu",
    )
    headers = {"Authorization": f"Bearer {token}"}

    # Can create department
    resp = client.post("/api/v1/admin/college/departments", json={"code": "MECH", "name": "Mechanical"}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["code"] == "MECH"

    # Can list all departments
    resp = client.get("/api/v1/admin/college/departments", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


def test_dean_restricted_to_own_department(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    cse_dean_token = create_access_token(
        sub="dean-cse-1",
        role=ROLE_DEAN,
        secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu",
        department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {cse_dean_token}"}

    # Dean cannot create a new department (only Super Admin can)
    resp = client.post("/api/v1/admin/college/departments", json={"code": "CIVIL", "name": "Civil"}, headers=headers)
    assert resp.status_code == 403
    assert "only Super Administrators" in resp.json()["detail"]

    # Dean only sees their own department in /departments
    resp = client.get("/api/v1/admin/college/departments", headers=headers)
    assert resp.status_code == 200
    depts = resp.json()["items"]
    assert len(depts) == 1
    assert depts[0]["department_id"] == "dept-cse"

    # Dean can create class group in their own department
    resp = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": "dept-cse",
        "year_of_study": 2,
        "section": "A",
        "academic_year": "2026-2027",
    }, headers=headers)
    assert resp.status_code == 201

    # Dean is FORBIDDEN from creating class group in another department
    resp = client.post("/api/v1/admin/college/class-groups", json={
        "department_id": "dept-ece",
        "year_of_study": 2,
        "section": "A",
        "academic_year": "2026-2027",
    }, headers=headers)
    assert resp.status_code == 403
    assert "does not have authority over department" in resp.json()["detail"]


def test_faculty_restricted_to_assigned_class_groups(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    faculty_token = create_access_token(
        sub="faculty-1",
        role=ROLE_FACULTY,
        secret=settings.effective_jwt_secret,
        email="prof.sharma@campus.edu",
        class_group_ids=["cg-cse-a"],
    )

    headers = {"Authorization": f"Bearer {faculty_token}"}

    # Faculty cannot access /departments (requires admin or dean)
    resp = client.get("/api/v1/admin/college/departments", headers=headers)
    assert resp.status_code == 403

    # Faculty only sees their assigned class group
    resp = client.get("/api/v1/admin/college/class-groups", headers=headers)
    assert resp.status_code == 200
    groups = resp.json()["items"]
    assert len(groups) == 1
    assert groups[0]["class_group_id"] == "cg-cse-a"

    # Faculty can create attendance session for assigned class group
    resp = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": "cg-cse-a",
        "subject_name": "Distributed Systems",
    }, headers=headers)
    assert resp.status_code == 201

    # Faculty is FORBIDDEN from creating attendance session for unassigned class group
    resp = client.post("/api/v1/admin/college/attendance-sessions", json={
        "class_group_id": "cg-cse-b",
        "subject_name": "Machine Learning",
    }, headers=headers)
    assert resp.status_code == 403
    assert "does not have authority over class group" in resp.json()["detail"]


def test_faculty_manual_attendance_scoped_to_assigned_class(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    faculty_token = create_access_token(
        sub="faculty-1",
        role=ROLE_FACULTY,
        secret=settings.effective_jwt_secret,
        email="prof.sharma@campus.edu",
        class_group_ids=["cg-cse-a"],
    )
    headers = {"Authorization": f"Bearer {faculty_token}"}

    # Faculty can submit manual attendance for student in assigned class session
    resp = client.post("/api/v1/admin/attendance/manual-entry", json={
        "student_id": "stu-1",
        "attendance_session_id": "sess-cse-a-1",
        "punch_type": "CHECK_IN",
        "reason_code": "NON_BIOMETRIC_ALTERNATIVE",
        "justification": "Religious exemption alternative verification",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Faculty is FORBIDDEN from submitting manual attendance for session in unassigned class group
    resp = client.post("/api/v1/admin/attendance/manual-entry", json={
        "student_id": "stu-2",
        "attendance_session_id": "sess-cse-b-1",
        "punch_type": "CHECK_IN",
        "reason_code": "MEDICAL_EXCEPTION",
        "justification": "Doctor note provided",
    }, headers=headers)
    assert resp.status_code == 403
    assert "does not have authority over class group" in resp.json()["detail"]


def test_dean_manual_attendance_scoped_to_department(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    dean_token = create_access_token(
        sub="dean-1",
        role=ROLE_DEAN,
        secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu",
        department_id="dept-cse",
    )
    headers = {"Authorization": f"Bearer {dean_token}"}

    # Dean can submit manual attendance for class in own department
    resp = client.post("/api/v1/admin/attendance/manual-entry", json={
        "student_id": "stu-2",
        "attendance_session_id": "sess-cse-b-1",
        "punch_type": "CHECK_IN",
        "reason_code": "ADMINISTRATIVE_OVERRIDE",
        "justification": "Dean administrative override for official campus duty",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"

    # Dean is FORBIDDEN from submitting manual attendance for session in another department
    resp = client.post("/api/v1/admin/attendance/manual-entry", json={
        "student_id": "stu-1",
        "attendance_session_id": "sess-ece-a-1",
        "punch_type": "CHECK_IN",
        "reason_code": "ADMINISTRATIVE_OVERRIDE",
        "justification": "Cross department attempt",
    }, headers=headers)
    assert resp.status_code in (403, 409)


def test_dean_with_unknown_department_is_rejected(rbac_client):
    client, _ = rbac_client
    settings = get_settings()
    token = create_access_token(
        sub="dean-no-scope",
        role=ROLE_DEAN,
        secret=settings.effective_jwt_secret,
        email="dean.unknown@campus.edu",
        department_id="department-does-not-exist",
    )
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/admin/college/departments", headers=headers).status_code == 403
    assert client.get("/api/v1/admin/attendance", headers=headers).status_code == 403


def test_dean_cannot_reactivate_student_with_cross_department_enrollment(rbac_client):
    client, sessions = rbac_client
    with sessions() as db:
        student = db.get(Student, "stu-2")
        assert student is not None
        student.is_active = False
        db.add(ClassEnrollment(
            student_id="stu-2",
            class_group_id="cg-ece-a",
            status="ACTIVE",
        ))
        db.commit()

    settings = get_settings()
    token = create_access_token(
        sub="dean-cse",
        role=ROLE_DEAN,
        secret=settings.effective_jwt_secret,
        email="dean.cse@campus.edu",
        department_id="dept-cse",
    )
    response = client.post(
        "/api/v1/admin/college/students/stu-2/reactivate",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
