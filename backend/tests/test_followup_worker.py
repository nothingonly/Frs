from __future__ import annotations

from datetime import datetime, timezone
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    AuditEvent,
    ClassEnrollment,
    ClassGroup,
    Department,
    Person,
    SessionClassGroup,
    Student,
)
from app.services.followup_worker import AttendanceFollowupDaemon


@pytest.fixture
def followup_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_sessions = sessionmaker(bind=engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)

    with testing_sessions() as db:
        dept = Department(department_id="dept-1", code="CS", name="Computer Science", is_active=True)
        db.add(dept)
        db.commit()

        cg = ClassGroup(class_group_id="cg-1", department_id="dept-1", year_of_study=3, section="A", academic_year="2026-2027", is_active=True)
        db.add(cg)
        db.commit()

        p1 = Person(person_id="p-1", employee_id="STU01", full_name="Student One", department="CS", is_active=True)
        p2 = Person(person_id="p-2", employee_id="STU02", full_name="Student Two", department="CS", is_active=True)
        db.add_all([p1, p2])
        db.commit()

        s1 = Student(student_id="s-1", student_number="STU01", full_name="Student One", person_id="p-1", is_active=True)
        s2 = Student(
            student_id="s-2", student_number="STU02", full_name="Student Two",
            person_id="p-2", email="student.two@campus.edu", is_active=True,
        )
        db.add_all([s1, s2])
        db.commit()

        e1 = ClassEnrollment(enrollment_id="e-1", student_id="s-1", class_group_id="cg-1", status="ACTIVE")
        e2 = ClassEnrollment(enrollment_id="e-2", student_id="s-2", class_group_id="cg-1", status="ACTIVE")
        db.add_all([e1, e2])
        db.commit()

        # Session 1: OPEN (should not be reconciled)
        sess_open = AttendanceSession(
            session_id="sess-open",
            class_group_id="cg-1",
            subject_name="Algorithms",
            created_by="prof",
            status="OPEN",
            starts_at=now,
        )
        # Session 2: CLOSED (should be reconciled)
        sess_closed = AttendanceSession(
            session_id="sess-closed",
            class_group_id="cg-1",
            subject_name="Databases",
            created_by="prof",
            status="CLOSED",
            starts_at=now,
        )
        db.add_all([sess_open, sess_closed])
        db.commit()

        # Only Student 1 checked in
        att = AttendanceEvent(
            attendance_id="att-1",
            person_id="p-1",
            employee_id="STU01",
            punch_type="CHECK_IN",
            timestamp=now,
            similarity_score=0.95,
            threshold=0.65,
            client_device_id="kiosk-1",
            pipeline_version="v5",
            evidence_id="ev-1",
            attendance_session_id="sess-closed",
        )
        db.add(att)
        db.commit()

    with testing_sessions() as session:
        yield session
    engine.dispose()



def test_followup_counts_all_groups_and_distinct_students(followup_db):
    # Add a second department/group to a mixed session.
    department = Department(
        department_id="dept-two", code="ECE", name="Electrical Engineering", is_active=True
    )
    followup_db.add(department)
    followup_db.commit()
    group = ClassGroup(
        class_group_id="cg-two",
        department_id="dept-two",
        year_of_study=3,
        section="B",
        academic_year="2026-2027",
        is_active=True,
    )
    person = Person(
        person_id="p-3",
        employee_id="STU03",
        full_name="Student Three",
        department="ECE",
        is_active=True,
    )
    student = Student(
        student_id="s-3",
        student_number="STU03",
        full_name="Student Three",
        person_id="p-3",
        is_active=True,
    )
    followup_db.add_all([group, person, student])
    followup_db.commit()
    enrollment = ClassEnrollment(
        enrollment_id="e-3",
        student_id="s-3",
        class_group_id="cg-two",
        status="ACTIVE",
    )
    link = SessionClassGroup(session_id="sess-closed", class_group_id="cg-two")
    duplicate_punch = AttendanceEvent(
        attendance_id="att-1-checkout",
        person_id="p-1",
        employee_id="STU01",
        punch_type="CHECK_OUT",
        timestamp=datetime.now(timezone.utc),
        similarity_score=0.95,
        threshold=0.65,
        client_device_id="kiosk-1",
        pipeline_version="v5",
        evidence_id="ev-1-checkout",
        attendance_session_id="sess-closed",
    )
    followup_db.add_all([enrollment, link, duplicate_punch])
    followup_db.commit()

    evidence = AttendanceFollowupDaemon().reconcile_session(
        followup_db, followup_db.get(AttendanceSession, "sess-closed")
    )
    assert evidence["total_enrolled"] == 3
    assert evidence["present_count"] == 1
    assert evidence["absent_count"] == 2
    assert evidence["notifications"]["total_alerts"] == 2
    assert evidence["notifications"]["skipped_count"] == 1


def test_followup_worker_detects_only_unreconciled_closed_sessions(followup_db):
    unreconciled = AttendanceFollowupDaemon.get_unreconciled_closed_sessions(followup_db)
    # Only sess-closed is picked up, sess-open is ignored
    assert len(unreconciled) == 1
    assert unreconciled[0].session_id == "sess-closed"


def test_followup_worker_reconciles_session_and_records_audit(followup_db):
    daemon = AttendanceFollowupDaemon()
    session = followup_db.get(AttendanceSession, "sess-closed")

    evidence = daemon.reconcile_session(followup_db, session)

    assert evidence["session_id"] == "sess-closed"
    assert evidence["total_enrolled"] == 2
    assert evidence["present_count"] == 1
    assert evidence["absent_count"] == 1

    # Absentee notification summary
    notifications = evidence["notifications"]
    assert notifications["total_alerts"] == 1
    alerts = notifications["alerts"]
    assert len(alerts) == 1
    assert alerts[0]["status"] in ("SENT", "SENT_MOCK")
    assert alerts[0]["recipient"] == "student.two@campus.edu"

    # Audit event written
    audit = followup_db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.session_id == "sess-closed",
            AuditEvent.action == "attendance.followup_reconciled",
        )
    ).scalar_one_or_none()

    assert audit is not None
    assert audit.decision_state == "RECONCILED"

    # Subsequent check shows zero unreconciled sessions
    remaining = AttendanceFollowupDaemon.get_unreconciled_closed_sessions(followup_db)
    assert len(remaining) == 0
