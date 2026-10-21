from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    ROLE_DEAN,
    ROLE_FACULTY,
    ROLE_SUPER_ADMIN,
    TokenClaims,
    check_class_access,
    check_department_access,
    scoped_actor,
    scoped_admin,
)
from app.database import get_db
from app.db.entities import AttendanceSession, AuditEvent, ClassEnrollment, ClassGroup, Department, Person, Student
from app.schemas.college import AttendanceSessionCreate, ClassGroupCreate, DepartmentCreate, StudentCreate

router = APIRouter(prefix="/api/v1/admin/college", tags=["college administration"])


def _actor_id(actor: TokenClaims | str) -> str:
    if isinstance(actor, str):
        return actor
    return f"admin:{actor.email or actor.sub}"


def _audit(db: Session, actor: TokenClaims | str, action: str, state: str, item_id: str, evidence: dict[str, Any]) -> None:
    db.add(AuditEvent(
        session_id=item_id, actor_type="administrator", actor_id=_actor_id(actor),
        action=action, decision_state=state,
        reason_codes_json=json.dumps([action.upper().replace(".", "_")]),
        evidence_json=json.dumps(evidence, sort_keys=True),
    ))



def _commit(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


def _department(row: Department) -> dict[str, Any]:
    return {
        "department_id": row.department_id, "code": row.code, "name": row.name,
        "is_active": row.is_active, "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _group(row: ClassGroup, department: Department, active_count: int = 0) -> dict[str, Any]:
    return {
        "class_group_id": row.class_group_id, "department_id": row.department_id,
        "department_code": department.code, "department_name": department.name,
        "year_of_study": row.year_of_study, "section": row.section,
        "academic_year": row.academic_year, "is_active": row.is_active,
        "active_enrollments": active_count, "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _session(row: AttendanceSession) -> dict[str, Any]:
    return {
        "session_id": row.session_id, "class_group_id": row.class_group_id,
        "subject_code": row.subject_code, "subject_name": row.subject_name,
        "starts_at": row.starts_at.isoformat(),
        "ends_at": row.ends_at.isoformat() if row.ends_at else None,
        "status": row.status, "idempotency_key": row.idempotency_key,
        "created_by": row.created_by, "created_at": row.created_at.isoformat(),
    }


@router.get("/departments")
def list_departments(
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = True,
):
    statement = select(Department)
    if active_only:
        statement = statement.where(Department.is_active.is_(True))
    if actor.role == ROLE_DEAN and actor.department_id:
        statement = statement.where(Department.department_id == actor.department_id)
    return {"items": [_department(row) for row in db.execute(statement.order_by(Department.code)).scalars()]}


@router.post("/departments", status_code=201)
def create_department(
    payload: DepartmentCreate, actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    if actor.role != ROLE_SUPER_ADMIN:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: only Super Administrators can create academic departments.",
        )
    if db.execute(select(Department.department_id).where(Department.code == payload.code)).first():
        raise HTTPException(status_code=409, detail="A department with this code already exists.")
    row = Department(code=payload.code, name=payload.name)
    db.add(row)
    db.flush()
    _audit(db, actor, "department.create", "CREATED", row.department_id, {"code": row.code})
    _commit(db, "A department with this code already exists.")
    db.refresh(row)
    return _department(row)


@router.get("/class-groups")
def list_class_groups(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    department_code: str | None = None,
    academic_year: str | None = Query(default=None, min_length=9, max_length=9),
    year_of_study: int | None = Query(default=None, ge=1, le=4),
    active_only: bool = True,
):
    stmt = select(ClassGroup, Department).join(Department, Department.department_id == ClassGroup.department_id)
    if actor.role == ROLE_DEAN and actor.department_id:
        stmt = stmt.where(ClassGroup.department_id == actor.department_id)
    elif actor.role == ROLE_FACULTY and actor.class_group_ids:
        stmt = stmt.where(ClassGroup.class_group_id.in_(actor.class_group_ids))
    elif actor.role == ROLE_FACULTY and not actor.class_group_ids:
        return {"items": []}
    if department_code:
        stmt = stmt.where(Department.code == department_code.strip().upper())
    if academic_year:
        stmt = stmt.where(ClassGroup.academic_year == academic_year)
    if year_of_study is not None:
        stmt = stmt.where(ClassGroup.year_of_study == year_of_study)
    if active_only:
        stmt = stmt.where(ClassGroup.is_active.is_(True), Department.is_active.is_(True))
    rows = db.execute(stmt.order_by(Department.code, ClassGroup.year_of_study, ClassGroup.section)).all()
    items = []
    for group, dept in rows:
        count = db.scalar(select(func.count()).select_from(ClassEnrollment).where(
            ClassEnrollment.class_group_id == group.class_group_id, ClassEnrollment.status == "ACTIVE"
        )) or 0
        items.append(_group(group, dept, count))
    return {"items": items}


@router.post("/class-groups", status_code=201)
def create_class_group(
    payload: ClassGroupCreate, actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    check_department_access(actor, payload.department_id)
    dept = db.get(Department, payload.department_id)
    if dept is None or not dept.is_active:
        raise HTTPException(status_code=404, detail="Active department not found.")
    exists = db.execute(select(ClassGroup.class_group_id).where(
        ClassGroup.department_id == payload.department_id,
        ClassGroup.year_of_study == payload.year_of_study,
        ClassGroup.section == payload.section,
        ClassGroup.academic_year == payload.academic_year,
    )).first()
    if exists:
        raise HTTPException(status_code=409, detail="This class group already exists for the academic year.")
    row = ClassGroup(
        department_id=payload.department_id, year_of_study=payload.year_of_study,
        section=payload.section, academic_year=payload.academic_year,
    )
    db.add(row)
    db.flush()
    _audit(db, actor, "class_group.create", "CREATED", row.class_group_id, {
        "department_code": dept.code, "year_of_study": row.year_of_study,
        "section": row.section, "academic_year": row.academic_year,
    })
    _commit(db, "This class group already exists for the academic year.")
    db.refresh(row)
    return _group(row, dept)


@router.get("/students")
def list_students(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    class_group_id: str | None = None,
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Student)
    if active_only:
        stmt = stmt.where(Student.is_active.is_(True))
    if actor.role == ROLE_DEAN and actor.department_id:
        dept_class_ids = select(ClassGroup.class_group_id).where(ClassGroup.department_id == actor.department_id)
        dept_student_ids = select(ClassEnrollment.student_id).where(
            ClassEnrollment.class_group_id.in_(dept_class_ids), ClassEnrollment.status == "ACTIVE"
        )
        stmt = stmt.where(Student.student_id.in_(dept_student_ids))
    elif actor.role == ROLE_FACULTY and actor.class_group_ids:
        fac_student_ids = select(ClassEnrollment.student_id).where(
            ClassEnrollment.class_group_id.in_(actor.class_group_ids), ClassEnrollment.status == "ACTIVE"
        )
        stmt = stmt.where(Student.student_id.in_(fac_student_ids))
    elif actor.role == ROLE_FACULTY and not actor.class_group_ids:
        return {"items": [], "limit": limit, "offset": offset}

    if class_group_id:
        if actor.role == ROLE_FACULTY and class_group_id not in actor.class_group_ids:
            raise HTTPException(status_code=403, detail=f"Forbidden: actor lacks authority over class group '{class_group_id}'.")
        ids_for_group = select(ClassEnrollment.student_id).where(
            ClassEnrollment.class_group_id == class_group_id, ClassEnrollment.status == "ACTIVE"
        )
        stmt = stmt.where(Student.student_id.in_(ids_for_group))
    rows = db.execute(stmt.order_by(Student.student_number).limit(limit).offset(offset)).scalars().all()
    ids = [row.student_id for row in rows]
    memberships: dict[str, list[dict[str, Any]]] = {student_id: [] for student_id in ids}
    if ids:
        linked = db.execute(
            select(Student.student_id, ClassGroup.class_group_id, Department.code,
                   ClassGroup.year_of_study, ClassGroup.section, ClassGroup.academic_year)
            .join(ClassEnrollment, ClassEnrollment.student_id == Student.student_id)
            .join(ClassGroup, ClassGroup.class_group_id == ClassEnrollment.class_group_id)
            .join(Department, Department.department_id == ClassGroup.department_id)
            .where(Student.student_id.in_(ids), ClassEnrollment.status == "ACTIVE")
        ).all()
        for student_id, group_id, code, year, section, academic_year in linked:
            memberships[student_id].append({
                "class_group_id": group_id, "department_code": code, "year_of_study": year,
                "section": section, "academic_year": academic_year,
            })
    return {"items": [{
        "student_id": row.student_id, "student_number": row.student_number,
        "full_name": row.full_name, "email": row.email, "person_id": row.person_id,
        "is_active": row.is_active, "class_groups": memberships[row.student_id],
        "created_at": row.created_at.isoformat(), "updated_at": row.updated_at.isoformat(),
    } for row in rows], "limit": limit, "offset": offset}


@router.post("/students", status_code=201)
def create_student(
    payload: StudentCreate, actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    if db.execute(select(Student.student_id).where(Student.student_number == payload.student_number)).first():
        raise HTTPException(status_code=409, detail="A student with this number already exists.")
    group = db.get(ClassGroup, payload.class_group_id) if payload.class_group_id else None
    if payload.class_group_id and (group is None or not group.is_active):
        raise HTTPException(status_code=404, detail="Active class group not found.")
    dept = db.get(Department, group.department_id) if group else None
    if group and (dept is None or not dept.is_active):
        raise HTTPException(status_code=409, detail="The class group's department is inactive.")
    if group and actor.role == ROLE_DEAN:
        check_department_access(actor, group.department_id)

    person = db.execute(select(Person).where(Person.employee_id == payload.student_number)).scalar_one_or_none()
    if person is not None and not person.is_active:
        raise HTTPException(
            status_code=409,
            detail="The matching biometric identity is inactive; review/reactivate it before creating an active student.",
        )
    if person and person.full_name.strip().casefold() != payload.full_name.strip().casefold():
        raise HTTPException(status_code=409, detail="This student number is linked to a different biometric identity.")
    if person is None:
        person = Person(
            employee_id=payload.student_number, full_name=payload.full_name,
            department=dept.code if dept else None,
        )
        db.add(person)
        db.flush()
    elif dept:
        person.department = dept.code

    student = Student(
        student_number=payload.student_number, full_name=payload.full_name,
        email=payload.email, person_id=person.person_id,
    )
    db.add(student)
    db.flush()
    if group:
        db.add(ClassEnrollment(student_id=student.student_id, class_group_id=group.class_group_id))
    _audit(db, actor, "student.create", "CREATED", student.student_id, {
        "student_number": student.student_number,
        "class_group_id": group.class_group_id if group else None,
        "biometric_person_id": person.person_id,
    })
    _commit(db, "A student or biometric identity with this number already exists.")
    db.refresh(student)
    return {
        "student_id": student.student_id, "student_number": student.student_number,
        "full_name": student.full_name, "email": student.email, "person_id": student.person_id,
        "is_active": student.is_active,
        "class_groups": [{
            "class_group_id": group.class_group_id, "department_code": dept.code,
            "year_of_study": group.year_of_study, "section": group.section,
            "academic_year": group.academic_year,
        }] if group and dept else [],
        "created_at": student.created_at.isoformat(), "updated_at": student.updated_at.isoformat(),
    }


@router.post("/students/{student_id}/deactivate")
def deactivate_student(
    student_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    student = db.execute(select(Student).where(Student.student_id == student_id).with_for_update()).scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    if actor.role == ROLE_DEAN and actor.department_id:
        student_depts = db.execute(
            select(ClassGroup.department_id)
            .join(ClassEnrollment, ClassEnrollment.class_group_id == ClassGroup.class_group_id)
            .where(ClassEnrollment.student_id == student_id, ClassEnrollment.status == "ACTIVE")
        ).scalars().all()
        if student_depts and actor.department_id not in student_depts:
            raise HTTPException(status_code=403, detail="Forbidden: cannot modify student outside your assigned department.")
    student.is_active = False
    student.updated_at = datetime.now(timezone.utc)
    if student.person_id:
        person = db.get(Person, student.person_id)
        if person:
            person.is_active = False
            person.updated_at = datetime.now(timezone.utc)
    _audit(db, actor, "student.deactivate", "DEACTIVATED", student.student_id, {
        "student_number": student.student_number, "person_id": student.person_id,
    })
    db.commit()
    return {"status": "success", "student_id": student.student_id, "is_active": False}


@router.post("/students/{student_id}/reactivate")
def reactivate_student(
    student_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    student = db.execute(select(Student).where(Student.student_id == student_id).with_for_update()).scalar_one_or_none()
    if student is None:
        raise HTTPException(status_code=404, detail="Student not found.")
    if actor.role == ROLE_DEAN and actor.department_id:
        student_depts = db.execute(
            select(ClassGroup.department_id)
            .join(ClassEnrollment, ClassEnrollment.class_group_id == ClassGroup.class_group_id)
            .where(ClassEnrollment.student_id == student_id, ClassEnrollment.status == "ACTIVE")
        ).scalars().all()
        if student_depts and actor.department_id not in student_depts:
            raise HTTPException(status_code=403, detail="Forbidden: cannot modify student outside your assigned department.")
    student.is_active = True
    student.updated_at = datetime.now(timezone.utc)
    if student.person_id:
        person = db.get(Person, student.person_id)
        if person:
            person.is_active = True
            person.updated_at = datetime.now(timezone.utc)
    _audit(db, actor, "student.reactivate", "REACTIVATED", student.student_id, {
        "student_number": student.student_number, "person_id": student.person_id,
    })
    db.commit()
    return {"status": "success", "student_id": student.student_id, "is_active": True}


@router.post("/class-groups/{class_group_id}/students/{student_id}", status_code=201)
def enroll_student(
    class_group_id: str, student_id: str, actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    group, student = db.get(ClassGroup, class_group_id), db.get(Student, student_id)
    if group is None or not group.is_active:
        raise HTTPException(status_code=404, detail="Active class group not found.")
    if student is None or not student.is_active:
        raise HTTPException(status_code=404, detail="Active student not found.")
    check_department_access(actor, group.department_id)
    dept = db.get(Department, group.department_id)
    if dept is None or not dept.is_active:
        raise HTTPException(status_code=409, detail="The class group's department is inactive.")

    existing = db.execute(select(ClassEnrollment).where(
        ClassEnrollment.student_id == student_id,
        ClassEnrollment.class_group_id == class_group_id,
    )).scalar_one_or_none()
    if existing and existing.status == "ACTIVE":
        raise HTTPException(status_code=409, detail="Student is already enrolled in this class group.")
    conflict = db.execute(
        select(ClassEnrollment.enrollment_id)
        .join(ClassGroup, ClassGroup.class_group_id == ClassEnrollment.class_group_id)
        .where(
            ClassEnrollment.student_id == student_id, ClassEnrollment.status == "ACTIVE",
            ClassGroup.department_id == group.department_id, ClassGroup.year_of_study == group.year_of_study,
            ClassGroup.academic_year == group.academic_year, ClassGroup.class_group_id != group.class_group_id,
        )
    ).first()
    if conflict:
        raise HTTPException(status_code=409, detail="Student already has an active enrollment in another section of this cohort.")

    now = datetime.now(timezone.utc)
    if existing:
        existing.status, existing.enrolled_at, existing.withdrawn_at = "ACTIVE", now, None
        enrollment_id = existing.enrollment_id
    else:
        enrollment = ClassEnrollment(student_id=student_id, class_group_id=class_group_id)
        db.add(enrollment)
        db.flush()
        enrollment_id = enrollment.enrollment_id
    if student.person_id:
        person = db.get(Person, student.person_id)
        if person:
            person.department = dept.code
    _audit(db, actor, "class_enrollment.create", "ENROLLED", enrollment_id, {
        "student_id": student_id, "class_group_id": class_group_id,
    })
    _commit(db, "Student enrollment conflicts with existing class membership.")
    return {"status": "enrolled", "student_id": student_id, "class_group_id": class_group_id}


@router.delete("/class-groups/{class_group_id}/students/{student_id}")
def withdraw_student(
    class_group_id: str, student_id: str, actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    group = db.get(ClassGroup, class_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Class group not found.")
    check_department_access(actor, group.department_id)
    enrollment = db.execute(select(ClassEnrollment).where(
        ClassEnrollment.student_id == student_id,
        ClassEnrollment.class_group_id == class_group_id,
    )).scalar_one_or_none()
    if enrollment is None or enrollment.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="Active class enrollment not found.")
    enrollment.status, enrollment.withdrawn_at = "WITHDRAWN", datetime.now(timezone.utc)
    _audit(db, actor, "class_enrollment.withdraw", "WITHDRAWN", enrollment.enrollment_id, {
        "student_id": student_id, "class_group_id": class_group_id,
    })
    db.commit()
    return {"status": "withdrawn", "student_id": student_id, "class_group_id": class_group_id}


@router.get("/attendance-sessions")
def list_attendance_sessions(
    actor: Annotated[TokenClaims, Depends(scoped_actor)], db: Annotated[Session, Depends(get_db)],
    class_group_id: str | None = None, limit: int = Query(default=100, ge=1, le=500),
):
    stmt = select(AttendanceSession)
    if actor.role == ROLE_DEAN and actor.department_id:
        stmt = stmt.join(ClassGroup, ClassGroup.class_group_id == AttendanceSession.class_group_id).where(
            ClassGroup.department_id == actor.department_id
        )
    elif actor.role == ROLE_FACULTY and actor.class_group_ids:
        stmt = stmt.where(AttendanceSession.class_group_id.in_(actor.class_group_ids))
    elif actor.role == ROLE_FACULTY and not actor.class_group_ids:
        return {"items": []}

    if class_group_id:
        if actor.role == ROLE_FACULTY and class_group_id not in actor.class_group_ids:
            raise HTTPException(status_code=403, detail=f"Forbidden: actor lacks authority over class group '{class_group_id}'.")
        stmt = stmt.where(AttendanceSession.class_group_id == class_group_id)
    rows = db.execute(stmt.order_by(AttendanceSession.starts_at.desc()).limit(limit)).scalars()
    return {"items": [_session(row) for row in rows]}


@router.post("/attendance-sessions", status_code=201)
def create_attendance_session(
    payload: AttendanceSessionCreate, response: Response,
    actor: Annotated[TokenClaims, Depends(scoped_actor)], db: Annotated[Session, Depends(get_db)],
):
    group = db.get(ClassGroup, payload.class_group_id)
    if group is None or not group.is_active:
        raise HTTPException(status_code=404, detail="Active class group not found.")
    check_class_access(actor, payload.class_group_id, group.department_id)
    dept = db.get(Department, group.department_id)
    if dept is None or not dept.is_active:
        raise HTTPException(status_code=409, detail="The class group's department is inactive.")
    if payload.idempotency_key:
        existing = db.execute(select(AttendanceSession).where(
            AttendanceSession.idempotency_key == payload.idempotency_key
        )).scalar_one_or_none()
        if existing:
            if (
                existing.class_group_id != payload.class_group_id
                or existing.subject_name != payload.subject_name.strip()
                or existing.subject_code != payload.subject_code
            ):
                raise HTTPException(status_code=409, detail="Idempotency key was reused with a different session payload.")
            response.status_code = 200
            return {**_session(existing), "idempotent_replay": True}

    row = AttendanceSession(
        class_group_id=payload.class_group_id, subject_code=payload.subject_code,
        subject_name=payload.subject_name, starts_at=payload.starts_at or datetime.now(timezone.utc),
        status="OPEN", idempotency_key=payload.idempotency_key, created_by=_actor_id(actor),
    )
    db.add(row)
    db.flush()
    _audit(db, actor, "attendance_session.create", "OPEN", row.session_id, {
        "class_group_id": row.class_group_id, "subject_code": row.subject_code,
        "subject_name": row.subject_name,
    })
    _commit(db, "This attendance session conflicts with an existing idempotency key.")
    db.refresh(row)
    return _session(row)


@router.post("/attendance-sessions/{session_id}/close")
def close_attendance_session(
    session_id: str, actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    row = db.execute(select(AttendanceSession).where(
        AttendanceSession.session_id == session_id
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attendance session not found.")
    group = db.get(ClassGroup, row.class_group_id)
    check_class_access(actor, row.class_group_id, group.department_id if group else None)
    if row.status == "CANCELLED":
        raise HTTPException(status_code=409, detail="A cancelled attendance session cannot be closed.")
    if row.status == "OPEN":
        row.status, row.ends_at = "CLOSED", datetime.now(timezone.utc)
        _audit(db, actor, "attendance_session.close", "CLOSED", row.session_id, {
            "class_group_id": row.class_group_id,
        })
        db.commit()
    return _session(row)
