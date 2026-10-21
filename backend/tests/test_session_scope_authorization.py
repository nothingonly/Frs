from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import ROLE_DEAN, ROLE_FACULTY, ROLE_KIOSK, ROLE_SUPER_ADMIN, SessionActor
from app.api.routes.attendance import _can_access_session, router as attendance_router
from app.api.dependencies import session_actor
from app.database import Base, get_db
from app.db.entities import AttendanceSession, ClassGroup, Department, SessionClassGroup


@pytest.fixture
def scope_db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        dept_cse = Department(department_id="dept-cse", code="CSE", name="Computer Science", is_active=True)
        dept_ece = Department(department_id="dept-ece", code="ECE", name="Electrical", is_active=True)
        db.add_all([dept_cse, dept_ece])
        db.flush()
        cse = ClassGroup(
            class_group_id="cg-cse", department_id=dept_cse.department_id,
            year_of_study=3, section="A", academic_year="2026-2027", is_active=True,
        )
        ece = ClassGroup(
            class_group_id="cg-ece", department_id=dept_ece.department_id,
            year_of_study=3, section="A", academic_year="2026-2027", is_active=True,
        )
        db.add_all([cse, ece])
        db.flush()
        db.add_all([
            AttendanceSession(
                session_id="session-cse", class_group_id=cse.class_group_id,
                subject_name="Databases", created_by="admin", status="OPEN",
            ),
            AttendanceSession(
                session_id="session-mixed", class_group_id=cse.class_group_id,
                subject_name="Joint lab", created_by="admin", status="OPEN",
            ),
            SessionClassGroup(session_id="session-mixed", class_group_id=ece.class_group_id),
        ])
        db.commit()
        yield db
    finally:
        db.close()
        engine.dispose()


def test_dean_must_own_every_department_in_mixed_session(scope_db: Session) -> None:
    dean_cse = SessionActor("dean:cse", role=ROLE_DEAN, department_id="dept-cse")
    dean_ece = SessionActor("dean:ece", role=ROLE_DEAN, department_id="dept-ece")
    unscoped_dean = SessionActor("dean:unscoped", role=ROLE_DEAN)

    assert _can_access_session(scope_db, "session-cse", dean_cse)
    assert not _can_access_session(scope_db, "session-mixed", dean_cse)
    assert not _can_access_session(scope_db, "session-mixed", dean_ece)
    assert not _can_access_session(scope_db, "session-cse", unscoped_dean)


def test_faculty_and_kiosk_need_explicit_scope_for_every_session_group(scope_db: Session) -> None:
    faculty_one_group = SessionActor("faculty:one", role=ROLE_FACULTY, class_group_ids=["cg-cse"])
    faculty_both_groups = SessionActor(
        "faculty:both", role=ROLE_FACULTY, class_group_ids=["cg-cse", "cg-ece"]
    )
    unscoped_kiosk = SessionActor("device:empty", role=ROLE_KIOSK)
    kiosk_both_groups = SessionActor(
        "device:scoped", role=ROLE_KIOSK, class_group_ids=["cg-cse", "cg-ece"]
    )

    assert _can_access_session(scope_db, "session-cse", faculty_one_group)
    assert not _can_access_session(scope_db, "session-mixed", faculty_one_group)
    assert _can_access_session(scope_db, "session-mixed", faculty_both_groups)
    assert not _can_access_session(scope_db, "session-cse", unscoped_kiosk)
    assert _can_access_session(scope_db, "session-mixed", kiosk_both_groups)
    assert not _can_access_session(scope_db, "session-mixed", kiosk_both_groups, allow_kiosk=False)


def test_super_admin_remains_unrestricted_and_missing_session_is_denied(scope_db: Session) -> None:
    admin = SessionActor("administrator:root", role=ROLE_SUPER_ADMIN)
    assert _can_access_session(scope_db, "session-mixed", admin)
    assert not _can_access_session(scope_db, "missing", admin)


def test_roster_route_denies_mixed_session_for_single_department_actor(scope_db: Session) -> None:
    dean_cse = SessionActor("dean:cse", role=ROLE_DEAN, department_id="dept-cse")
    app = FastAPI()
    app.include_router(attendance_router)

    def override_get_db():
        yield scope_db

    class StubPipeline:
        def get_session_roster(self, _db, _session_id):
            return [{"student_id": "test"}]

    app.state.pipeline = StubPipeline()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[session_actor] = lambda: dean_cse

    with TestClient(app) as client:
        denied = client.get("/api/v1/attendance/sessions/session-mixed/roster")
        assert denied.status_code == 403
        allowed = client.get("/api/v1/attendance/sessions/session-cse/roster")
        assert allowed.status_code == 200
