from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
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
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    AuditEvent,
    CaptureBatchJob,
    ClassEnrollment,
    ClassGroup,
    Department,
    EmbeddingRecord,
    ModelRegistryEntry,
    Person,
    Student,
    SessionClassGroup,
)
from app.schemas.college import (
    AttendanceCorrectionRequest,
    DeleteMediaRequest,
    ManualAttendanceRequest,
    ResolveReviewRequest,
    SignedUrlRequest,
)
from app.core.config import get_settings
from app.services.capture_batches import (
    list_dead_letter_batches,
    requeue_dead_letter_batch,
    serialize_capture_batch,
)
from app.services.retention import de_enroll_student_biometrics, run_retention_purge

router = APIRouter(prefix="/api/v1/admin", tags=["administration"])


def _session_scope_groups(db: Session, session: AttendanceSession) -> list[ClassGroup]:
    linked_ids = db.execute(
        select(SessionClassGroup.class_group_id).where(
            SessionClassGroup.session_id == session.session_id
        )
    ).scalars().all()
    group_ids = list(dict.fromkeys([session.class_group_id, *linked_ids]))
    groups = db.execute(
        select(ClassGroup).where(ClassGroup.class_group_id.in_(group_ids))
    ).scalars().all()
    if {group.class_group_id for group in groups} != set(group_ids):
        raise HTTPException(status_code=409, detail="Attendance session references a missing class group.")
    return groups


def _check_session_scope(db: Session, actor: TokenClaims, session: AttendanceSession) -> None:
    """Enforce authorization over every class group attached to a single/mixed session."""
    groups = _session_scope_groups(db, session)
    for group in groups:
        check_class_access(actor, group.class_group_id, group.department_id)


def _scoped_session_ids(actor: TokenClaims):
    """SQL subquery for sessions whose entire class-group scope belongs to the actor."""
    if actor.role == ROLE_SUPER_ADMIN:
        return select(AttendanceSession.session_id)
    if actor.role == ROLE_DEAN:
        foreign_group_link = (
            select(SessionClassGroup.session_id)
            .join(ClassGroup, ClassGroup.class_group_id == SessionClassGroup.class_group_id)
            .where(
                SessionClassGroup.session_id == AttendanceSession.session_id,
                ClassGroup.department_id != actor.department_id,
            )
            .exists()
        )
        return (
            select(AttendanceSession.session_id)
            .join(ClassGroup, ClassGroup.class_group_id == AttendanceSession.class_group_id)
            .where(
                ClassGroup.department_id == actor.department_id,
                ~foreign_group_link,
            )
        )
    if actor.role == ROLE_FACULTY:
        allowed = tuple(actor.class_group_ids)
        if not allowed:
            return select(AttendanceSession.session_id).where(False)
        foreign_group_link = (
            select(SessionClassGroup.session_id)
            .where(
                SessionClassGroup.session_id == AttendanceSession.session_id,
                ~SessionClassGroup.class_group_id.in_(allowed),
            )
            .exists()
        )
        return select(AttendanceSession.session_id).where(
            AttendanceSession.class_group_id.in_(allowed),
            ~foreign_group_link,
        )
    return select(AttendanceSession.session_id).where(False)


def _audit_object_scope(db: Session, actor: TokenClaims, object_id: str) -> None:
    """Map non-session audit references to their owning department, fail closed when unknown."""
    if actor.role == ROLE_SUPER_ADMIN:
        return
    if actor.role != ROLE_DEAN:
        raise HTTPException(status_code=403, detail="Only Super Administrators and scoped Deans can inspect audit evidence.")

    session = db.get(AttendanceSession, object_id)
    if session is not None:
        _check_session_scope(db, actor, session)
        return

    department = db.get(Department, actor.department_id) if actor.department_id else None
    if department is None:
        raise HTTPException(status_code=403, detail="Dean token must reference an existing department.")

    if object_id.startswith("admin:"):
        employee_id = object_id.split(":", 1)[1]
        person = db.execute(select(Person).where(Person.employee_id == employee_id)).scalar_one_or_none()
        if person is not None and person.department == department.code:
            return
        raise HTTPException(status_code=403, detail="Audit object is outside the Dean's department or unresolvable.")

    group = db.get(ClassGroup, object_id)
    if group is not None:
        check_department_access(actor, group.department_id)
        return
    if object_id in {row.department_id for row in db.execute(select(Department)).scalars()}:
        check_department_access(actor, object_id)
        return

    student = db.get(Student, object_id)
    if student is not None:
        departments = set(db.execute(
            select(ClassGroup.department_id)
            .join(ClassEnrollment, ClassEnrollment.class_group_id == ClassGroup.class_group_id)
            .where(ClassEnrollment.student_id == student.student_id, ClassEnrollment.status == "ACTIVE")
        ).scalars().all())
        if departments == {actor.department_id}:
            return
        raise HTTPException(status_code=403, detail="Audit object is outside the Dean's department or unresolvable.")

    enrollment = db.get(ClassEnrollment, object_id)
    if enrollment is not None:
        group = db.get(ClassGroup, enrollment.class_group_id)
        if group is not None:
            check_department_access(actor, group.department_id)
            return

    person = db.get(Person, object_id)
    if person is not None and person.department == department.code:
        return
    raise HTTPException(status_code=403, detail="Audit object has no verifiable department scope.")


@router.get("/people")
def list_people(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(Person)
    if active_only:
        statement = statement.where(Person.is_active.is_(True))
    if actor.role == ROLE_DEAN and actor.department_id:
        dept = db.get(Department, actor.department_id)
        if dept:
            statement = statement.where(Person.department == dept.code)
    elif actor.role == ROLE_FACULTY:
        if not actor.class_group_ids:
            return {"items": [], "limit": limit, "offset": offset, "total": 0}
        subq = (
            select(Student.person_id)
            .join(ClassEnrollment, ClassEnrollment.student_id == Student.student_id)
            .where(
                ClassEnrollment.class_group_id.in_(actor.class_group_ids),
                ClassEnrollment.status == "ACTIVE",
                Student.person_id.is_not(None),
            )
        )
        statement = statement.where(Person.person_id.in_(subq))

    people = db.execute(statement.order_by(Person.employee_id).limit(limit).offset(offset)).scalars().all()
    return {
        "items": [{
            "person_id": p.person_id,
            "employee_id": p.employee_id,
            "full_name": p.full_name,
            "department": p.department,
            "is_active": p.is_active,
            "enrollment_version": p.enrollment_version,
            "created_at": p.created_at.isoformat(),
            "updated_at": p.updated_at.isoformat(),
        } for p in people],
        "limit": limit,
        "offset": offset,
    }


@router.post("/people/{employee_id}/deactivate")
def deactivate_person(
    employee_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if actor.role == ROLE_DEAN and actor.department_id:
        dept = db.get(Department, actor.department_id)
        if dept and person.department != dept.code:
            raise HTTPException(status_code=403, detail="Deans can only modify identities in their department.")
    if person.is_active:
        person.is_active = False
        person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor.email or actor.sub,
        action="person.deactivate",
        decision_state="REVOKED",
        reason_codes_json=json.dumps(["ADMINISTRATIVE_REVOCATION"]),
        evidence_json=json.dumps({"employee_id": employee_id, "enrollment_version": person.enrollment_version}),
    )
    db.add(event)
    db.commit()
    return {"status": "success", "employee_id": employee_id, "is_active": False, "audit_id": event.audit_id}


@router.post("/people/{employee_id}/reactivate")
def reactivate_person(
    employee_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if actor.role == ROLE_DEAN and actor.department_id:
        dept = db.get(Department, actor.department_id)
        if dept and person.department != dept.code:
            raise HTTPException(status_code=403, detail="Deans can only modify identities in their department.")
    person.is_active = True
    person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor.email or actor.sub,
        action="person.reactivate",
        decision_state="REACTIVATED",
        reason_codes_json=json.dumps(["ADMINISTRATIVE_REACTIVATION"]),
        evidence_json=json.dumps({"employee_id": employee_id, "enrollment_version": person.enrollment_version}),
    )
    db.add(event)
    db.commit()
    return {"status": "success", "employee_id": employee_id, "is_active": True, "audit_id": event.audit_id}


@router.get("/attendance")
def list_attendance(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: str | None = None,
    attendance_session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(AttendanceEvent)
    if employee_id:
        statement = statement.where(AttendanceEvent.employee_id == employee_id)
    if attendance_session_id:
        sess = db.get(AttendanceSession, attendance_session_id)
        if sess:
            _check_session_scope(db, actor, sess)
        statement = statement.where(AttendanceEvent.attendance_session_id == attendance_session_id)
    elif actor.role != ROLE_SUPER_ADMIN:
        statement = statement.where(
            AttendanceEvent.attendance_session_id.in_(_scoped_session_ids(actor))
        )

    rows = db.execute(statement.order_by(AttendanceEvent.timestamp.desc()).limit(limit).offset(offset)).scalars().all()
    return {
        "items": [{
            "attendance_id": row.attendance_id,
            "employee_id": row.employee_id,
            "punch_type": row.punch_type,
            "timestamp": row.timestamp.isoformat(),
            "similarity_score": row.similarity_score,
            "threshold": row.threshold,
            "client_device_id": row.client_device_id,
            "pipeline_version": row.pipeline_version,
            "evidence_id": row.evidence_id,
            "attendance_session_id": row.attendance_session_id,
        } for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/attendance/export")
def export_attendance_csv(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: str | None = None,
    attendance_session_id: str | None = None,
):
    statement = select(AttendanceEvent)
    if employee_id:
        statement = statement.where(AttendanceEvent.employee_id == employee_id)
    if attendance_session_id:
        sess = db.get(AttendanceSession, attendance_session_id)
        if sess:
            _check_session_scope(db, actor, sess)
        statement = statement.where(AttendanceEvent.attendance_session_id == attendance_session_id)
    elif actor.role != ROLE_SUPER_ADMIN:
        statement = statement.where(
            AttendanceEvent.attendance_session_id.in_(_scoped_session_ids(actor))
        )

    rows = db.execute(statement.order_by(AttendanceEvent.timestamp.desc())).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "attendance_id",
        "employee_id",
        "punch_type",
        "timestamp",
        "similarity_score",
        "threshold",
        "client_device_id",
        "pipeline_version",
        "evidence_id",
        "attendance_session_id",
    ])
    for row in rows:
        writer.writerow([
            row.attendance_id,
            row.employee_id,
            row.punch_type,
            row.timestamp.isoformat(),
            f"{row.similarity_score:.4f}",
            f"{row.threshold:.4f}",
            row.client_device_id,
            row.pipeline_version,
            row.evidence_id,
            row.attendance_session_id or "",
        ])
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=attendance_export.csv",
            "Cache-Control": "no-store",
        },
    )


@router.get("/audit")
def list_audit_events(
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
    session_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(AuditEvent)
    if actor.role == ROLE_DEAN:
        if session_id:
            _audit_object_scope(db, actor, session_id)
        else:
            actor_id_str = actor.email or actor.sub
            statement = statement.where(
                (AuditEvent.session_id.in_(_scoped_session_ids(actor)))
                | (AuditEvent.actor_id == actor_id_str)
            )

    if session_id:
        statement = statement.where(AuditEvent.session_id == session_id)
    if action:
        statement = statement.where(AuditEvent.action == action)
    rows = db.execute(statement.order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)).scalars().all()
    return {
        "items": [{
            "audit_id": row.audit_id,
            "session_id": row.session_id,
            "occurred_at": row.occurred_at.isoformat(),
            "actor_type": row.actor_type,
            "actor_id": row.actor_id,
            "action": row.action,
            "decision_state": row.decision_state,
            "reason_codes": json.loads(row.reason_codes_json),
            "evidence": json.loads(row.evidence_json),
        } for row in rows],
        "limit": limit,
        "offset": offset,
    }


@router.get("/audit/{audit_id}")
def get_audit(
    audit_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.get(AuditEvent, audit_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found.")
    if actor.role == ROLE_DEAN:
        _audit_object_scope(db, actor, event.session_id or "")
    return {
        "audit_id": event.audit_id,
        "session_id": event.session_id,
        "occurred_at": event.occurred_at.isoformat(),
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "action": event.action,
        "decision_state": event.decision_state,
        "reason_codes": json.loads(event.reason_codes_json),
        "evidence": json.loads(event.evidence_json),
    }


@router.get("/models")
def list_models(
    request: Request,
    _actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    rows = db.execute(select(ModelRegistryEntry).order_by(ModelRegistryEntry.model_id, ModelRegistryEntry.model_version)).scalars().all()
    return {
        "runtime_components": request.app.state.vision.component_status,
        "registry": [{
            "model_id": row.model_id,
            "model_version": row.model_version,
            "artifact_sha256": row.artifact_sha256,
            "artifact_path": row.artifact_path,
            "license_name": row.license_name,
            "source_url": row.source_url,
            "permitted_use": row.permitted_use,
            "preprocessing_id": row.preprocessing_id,
            "input_contract": json.loads(row.input_contract_json),
            "output_contract": json.loads(row.output_contract_json),
            "benchmark": json.loads(row.benchmark_json),
            "active": row.active,
            "registered_at": row.registered_at.isoformat(),
        } for row in rows],
    }


@router.get("/attendance-batches")
def list_capture_batches(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    attendance_session_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    statement = select(CaptureBatchJob)
    if attendance_session_id:
        sess = db.get(AttendanceSession, attendance_session_id)
        if sess:
            _check_session_scope(db, actor, sess)
        statement = statement.where(CaptureBatchJob.attendance_session_id == attendance_session_id)
    elif actor.role != ROLE_SUPER_ADMIN:
        statement = statement.where(
            CaptureBatchJob.attendance_session_id.in_(_scoped_session_ids(actor))
        )

    if status:
        normalized_status = status.strip().upper()
        if normalized_status not in {"QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED", "DEAD_LETTER"}:
            raise HTTPException(status_code=422, detail="Unknown capture-batch status.")
        statement = statement.where(CaptureBatchJob.status == normalized_status)
    rows = db.execute(statement.order_by(CaptureBatchJob.created_at.desc()).limit(limit)).scalars().all()
    return {"items": [serialize_capture_batch(row) for row in rows]}


@router.post("/attendance-batches/{batch_id}/retry")
def retry_capture_batch(
    batch_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    job = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.batch_id == batch_id
    ).with_for_update()).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Capture batch not found.")
    session_for_scope = db.get(AttendanceSession, job.attendance_session_id)
    if session_for_scope is None:
        raise HTTPException(status_code=404, detail="Associated attendance session not found.")
    _check_session_scope(db, actor, session_for_scope)
    if job.status != "FAILED":
        raise HTTPException(status_code=409, detail="Only failed capture batches can be retried.")
    now = datetime.now(timezone.utc)
    payload_expires_at = job.payload_expires_at
    if payload_expires_at.tzinfo is None:
        payload_expires_at = payload_expires_at.replace(tzinfo=timezone.utc)
    if not job.encrypted_payload or not job.payload_nonce or payload_expires_at <= now:
        raise HTTPException(status_code=410, detail="Encrypted payload is missing or expired; capture a fresh batch.")
    attendance_session = db.get(AttendanceSession, job.attendance_session_id)
    if attendance_session is None or attendance_session.status != "OPEN":
        raise HTTPException(status_code=409, detail="The original attendance session is no longer open.")
    job.status = "QUEUED"
    job.attempts = 0
    job.next_attempt_at = now
    job.started_at = None
    job.completed_at = None
    job.error_json = None
    job.updated_at = now
    db.commit()
    db.refresh(job)
    return serialize_capture_batch(job)


@router.get("/stats")
def get_system_stats(
    _actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    if _actor.role == ROLE_SUPER_ADMIN:
        allowed_group_ids = None
    elif _actor.role == ROLE_DEAN:
        allowed_group_ids = select(ClassGroup.class_group_id).where(
            ClassGroup.department_id == _actor.department_id
        )
    else:
        allowed_group_ids = tuple(_actor.class_group_ids) or ("__none__",)

    if allowed_group_ids is None:
        dept_scope = select(Department.department_id).where(Department.is_active.is_(True))
        group_scope = select(ClassGroup.class_group_id).where(ClassGroup.is_active.is_(True))
    elif isinstance(allowed_group_ids, tuple):
        group_scope = select(ClassGroup.class_group_id).where(
            ClassGroup.class_group_id.in_(allowed_group_ids),
            ClassGroup.is_active.is_(True),
        )
        dept_scope = select(ClassGroup.department_id).where(
            ClassGroup.class_group_id.in_(group_scope)
        ).distinct()
    else:
        group_scope = select(ClassGroup.class_group_id).where(
            ClassGroup.class_group_id.in_(allowed_group_ids),
            ClassGroup.is_active.is_(True),
        )
        dept_scope = select(ClassGroup.department_id).where(
            ClassGroup.class_group_id.in_(group_scope)
        ).distinct()

    scoped_students = (
        select(ClassEnrollment.student_id)
        .where(
            ClassEnrollment.class_group_id.in_(group_scope),
            ClassEnrollment.status == "ACTIVE",
        )
        .distinct()
    )
    scoped_sessions = _scoped_session_ids(_actor)

    dept_count = db.scalar(select(func.count()).select_from(dept_scope.subquery())) or 0
    group_count = db.scalar(select(func.count()).select_from(group_scope.subquery())) or 0
    student_count = db.scalar(
        select(func.count(func.distinct(Student.student_id)))
        .where(Student.is_active.is_(True), Student.student_id.in_(scoped_students))
    ) or 0
    biometric_count = db.scalar(
        select(func.count(func.distinct(EmbeddingRecord.person_id)))
        .join(Student, Student.person_id == EmbeddingRecord.person_id)
        .where(
            Student.is_active.is_(True),
            Student.student_id.in_(scoped_students),
            EmbeddingRecord.accepted.is_(True),
        )
    ) or 0
    open_sess_count = db.scalar(
        select(func.count(AttendanceSession.session_id)).where(
            AttendanceSession.status == "OPEN",
            AttendanceSession.session_id.in_(scoped_sessions),
        )
    ) or 0
    today_att_count = db.scalar(
        select(func.count(AttendanceEvent.attendance_id)).where(
            AttendanceEvent.timestamp >= today_start,
            AttendanceEvent.attendance_session_id.in_(scoped_sessions),
        )
    ) or 0
    pending_rev_count = db.scalar(
        select(func.count(CaptureBatchJob.batch_id)).where(
            CaptureBatchJob.status.in_(["FAILED", "REJECTED"]),
            CaptureBatchJob.attendance_session_id.in_(scoped_sessions),
        )
    ) or 0

    return {
        "departments_count": dept_count,
        "classes_count": group_count,
        "class_groups_count": group_count,
        "students_count": student_count,
        "biometrics_enrolled_count": biometric_count,
        "open_sessions_count": open_sess_count,
        "attendance_today_count": today_att_count,
        "pending_reviews_count": pending_rev_count,
    }


@router.get("/review-queue")
def list_review_queue(
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
):
    statement = (
        select(CaptureBatchJob)
        .where(CaptureBatchJob.status.in_(["REJECTED", "FAILED"]))
    )
    if actor.role != ROLE_SUPER_ADMIN:
        statement = statement.where(
            CaptureBatchJob.attendance_session_id.in_(_scoped_session_ids(actor))
        )

    jobs = db.execute(statement.order_by(CaptureBatchJob.created_at.desc()).limit(limit)).scalars().all()
    items = []
    for job in jobs:
        sess = db.get(AttendanceSession, job.attendance_session_id)
        group = db.get(ClassGroup, job.class_group_id) if sess else None
        error_data = json.loads(job.error_json) if job.error_json else {}
        items.append({
            "batch_id": job.batch_id,
            "session_id": job.attendance_session_id,
            "subject_name": sess.subject_name if sess else "Unknown Session",
            "class_group_id": job.class_group_id,
            "section": group.section if group else "?",
            "academic_year": group.academic_year if group else "?",
            "status": job.status,
            "punch_type": job.punch_type,
            "frame_count": job.frame_count,
            "created_at": job.created_at.isoformat(),
            "client_device_id": job.client_device_id,
            "error_detail": error_data,
        })
    return {"items": items}


@router.post("/review-queue/{batch_id}/resolve")
def resolve_review_item(
    batch_id: str,
    payload: ResolveReviewRequest,
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    job = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.batch_id == batch_id
    ).with_for_update()).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    session_for_scope = db.get(AttendanceSession, job.attendance_session_id)
    if session_for_scope is None:
        raise HTTPException(status_code=404, detail="Associated attendance session not found.")
    _check_session_scope(db, actor, session_for_scope)

    if job.status not in ("REJECTED", "FAILED"):
        raise HTTPException(status_code=409, detail="Only rejected or failed capture jobs can be reviewed.")

    now = datetime.now(timezone.utc)
    sess = db.get(AttendanceSession, job.attendance_session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Associated attendance session not found.")

    actor_id_str = actor.email or actor.sub

    if payload.action == "APPROVE_MANUAL":
        if not payload.student_id:
            raise HTTPException(status_code=422, detail="student_id is required to approve manual attendance.")
        student = db.get(Student, payload.student_id)
        if student is None or not student.is_active:
            raise HTTPException(status_code=404, detail="Student not found or inactive.")

        enrollment = db.execute(
            select(ClassEnrollment)
            .where(ClassEnrollment.student_id == student.student_id)
            .where(ClassEnrollment.class_group_id == job.class_group_id)
            .where(ClassEnrollment.status == "ACTIVE")
        ).scalar_one_or_none()
        if enrollment is None:
            raise HTTPException(status_code=409, detail="Student is not actively enrolled in this session's class.")

        if not student.person_id:
            raise HTTPException(status_code=409, detail="Student has no biometric identity record.")

        attendance_event = AttendanceEvent(
            attendance_id=str(uuid.uuid4()),
            person_id=student.person_id,
            employee_id=student.student_number,
            punch_type=job.punch_type,
            timestamp=now,
            similarity_score=1.0,
            threshold=1.0,
            client_device_id=job.client_device_id,
            pipeline_version="manual-administrative-review",
            evidence_id=f"review:{job.batch_id}",
            attendance_session_id=job.attendance_session_id,
        )
        db.add(attendance_event)
        job.status = "SUCCEEDED"
        job.result_json = json.dumps({
            "manual_approval": True,
            "attendance_id": attendance_event.attendance_id,
            "student_id": student.student_id,
            "student_number": student.student_number,
            "actor": actor_id_str,
            "notes": payload.notes,
        })
        decision_state = "MANUALLY_APPROVED"
    else:
        decision_state = "DISMISSED"

    job.completed_at = now
    job.updated_at = now

    audit = AuditEvent(
        session_id=job.attendance_session_id,
        actor_type="administrator",
        actor_id=actor_id_str,
        action="review_queue.resolve",
        decision_state=decision_state,
        reason_codes_json=json.dumps([payload.reason_code]),
        evidence_json=json.dumps({
            "batch_id": batch_id,
            "action": payload.action,
            "student_id": payload.student_id,
            "notes": payload.notes,
        }),
    )
    db.add(audit)
    db.commit()
    return {"status": "success", "action": payload.action, "batch_id": batch_id}


@router.post("/attendance/{attendance_id}/correct")
def correct_attendance_record(
    attendance_id: str,
    payload: AttendanceCorrectionRequest,
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.execute(
        select(AttendanceEvent).where(AttendanceEvent.attendance_id == attendance_id).with_for_update()
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

    if event.attendance_session_id:
        sess = db.get(AttendanceSession, event.attendance_session_id)
        if sess is None:
            raise HTTPException(status_code=409, detail="Attendance record references a missing session.")
        _check_session_scope(db, actor, sess)
    else:
        if actor.role == ROLE_FACULTY:
            raise HTTPException(status_code=403, detail="Faculty can only correct session-scoped attendance records.")
        elif actor.role == ROLE_DEAN:
            dept = db.get(Department, actor.department_id) if actor.department_id else None
            person = db.get(Person, event.person_id) if event.person_id else None
            if dept is None or person is None or person.department != dept.code:
                raise HTTPException(status_code=403, detail="Deans can only modify verifiably scoped attendance records in their department.")

    previous_punch = event.punch_type

    if payload.revoke:
        action = "attendance.revoke"
        decision_state = "REVOKED"
        db.delete(event)
    else:
        if not payload.punch_type:
            raise HTTPException(status_code=422, detail="Specify punch_type or set revoke=true.")
        action = "attendance.correct_punch"
        decision_state = "CORRECTED"
        event.punch_type = payload.punch_type

    audit = AuditEvent(
        session_id=event.attendance_session_id or f"attendance:{attendance_id}",
        actor_type="administrator",
        actor_id=actor.email or actor.sub,
        action=action,
        decision_state=decision_state,
        reason_codes_json=json.dumps([payload.reason_code]),
        evidence_json=json.dumps({
            "attendance_id": attendance_id,
            "previous_punch": previous_punch,
            "new_punch": payload.punch_type,
            "revoked": payload.revoke,
            "justification": payload.justification,
        }),
    )
    db.add(audit)
    db.commit()
    return {"status": "success", "attendance_id": attendance_id, "action": action}


@router.post("/attendance/manual-entry")
def manual_attendance_entry(
    payload: ManualAttendanceRequest,
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    student = db.get(Student, payload.student_id)
    if student is None or not student.is_active:
        raise HTTPException(status_code=404, detail="Student not found or inactive.")
    if not student.person_id:
        person = Person(
            person_id=str(uuid.uuid4()),
            employee_id=student.student_number,
            full_name=student.full_name,
            department="NON_BIOMETRIC_ALTERNATIVE",
            is_active=True,
        )
        db.add(person)
        db.flush()
        student.person_id = person.person_id
        db.add(student)

    sess = db.get(AttendanceSession, payload.attendance_session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Attendance session not found.")

    _check_session_scope(db, actor, sess)

    enrollment = db.execute(
        select(ClassEnrollment)
        .where(ClassEnrollment.student_id == student.student_id)
        .where(ClassEnrollment.class_group_id == sess.class_group_id)
        .where(ClassEnrollment.status == "ACTIVE")
    ).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=409, detail="Student is not actively enrolled in this session's class.")

    now = datetime.now(timezone.utc)
    actor_id_str = actor.email or actor.sub
    attendance_event = AttendanceEvent(
        attendance_id=str(uuid.uuid4()),
        person_id=student.person_id,
        employee_id=student.student_number,
        punch_type=payload.punch_type,
        timestamp=now,
        similarity_score=1.0,
        threshold=1.0,
        client_device_id=f"manual:{actor_id_str}",
        pipeline_version="manual-administrative-entry",
        evidence_id=f"manual:{uuid.uuid4()}",
        attendance_session_id=sess.session_id,
    )
    db.add(attendance_event)

    audit = AuditEvent(
        session_id=sess.session_id,
        actor_type="administrator",
        actor_id=actor_id_str,
        action="attendance.manual_entry",
        decision_state="MANUAL_ENTRY",
        reason_codes_json=json.dumps([payload.reason_code]),
        evidence_json=json.dumps({
            "attendance_id": attendance_event.attendance_id,
            "student_id": student.student_id,
            "student_number": student.student_number,
            "punch_type": payload.punch_type,
            "justification": payload.justification,
        }),
    )
    db.add(audit)
    db.commit()
    return {"status": "success", "attendance_id": attendance_event.attendance_id}


@router.get("/storage/status")
def get_storage_status(
    request: Request,
    _actor: Annotated[TokenClaims, Depends(scoped_admin)],
):
    storage = getattr(request.app.state, "storage", None)
    configured = storage.is_configured if storage else False
    cloud_name = storage.cloud_name if storage and configured else None
    return {
        "configured": configured,
        "cloud_name": cloud_name,
        "provider": "Cloudinary" if configured else "none",
    }


@router.post("/storage/signed-url")
def get_signed_storage_url(
    payload: SignedUrlRequest,
    request: Request,
    _actor: Annotated[TokenClaims, Depends(scoped_admin)],
):
    storage = getattr(request.app.state, "storage", None)
    if not storage or not storage.is_configured:
        raise HTTPException(status_code=503, detail="Cloud storage is not configured.")
    try:
        url = storage.generate_signed_url(payload.public_id, payload.expires_in_seconds)
        return {"signed_url": url, "expires_in_seconds": payload.expires_in_seconds}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to generate signed URL: {exc}")


@router.post("/storage/delete")
def delete_storage_media(
    payload: DeleteMediaRequest,
    request: Request,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    if actor.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only Super Administrators can delete storage media.")
    storage = getattr(request.app.state, "storage", None)
    if not storage or not storage.is_configured:
        raise HTTPException(status_code=503, detail="Cloud storage is not configured.")
    success = storage.delete_media(payload.public_id)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to delete media asset.")
    audit = AuditEvent(
        session_id=f"storage:{payload.public_id}",
        actor_type="administrator",
        actor_id=actor.email or actor.sub,
        action="storage.delete_media",
        decision_state="DELETED",
        reason_codes_json=json.dumps([payload.reason_code]),
        evidence_json=json.dumps({"public_id": payload.public_id}),
    )
    db.add(audit)
    db.commit()
    return {"status": "success", "public_id": payload.public_id}


@router.get("/batches/dead-letter")
def get_dead_letter_batches(
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
):
    """List poisoned or retry-exhausted capture batches for operator triage."""
    dept_id = actor.department_id if actor.role == ROLE_DEAN else None
    items = list_dead_letter_batches(db, limit=limit, department_id=dept_id)
    return {"items": items, "total": len(items)}


@router.post("/batches/{batch_id}/requeue")
@router.post("/batches/{batch_id}/retry")
def requeue_batch(
    batch_id: str,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Requeue an exhausted dead-letter batch back to the queue for reprocessing."""
    allowed_dept = actor.department_id if actor.role == ROLE_DEAN else None
    return requeue_dead_letter_batch(
        db, batch_id, operator_id=actor.email or actor.sub, allowed_department_id=allowed_dept
    )


@router.post("/retention/purge")
def trigger_retention_purge(
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
    retention_days: int | None = Query(default=None, ge=1, le=365),
):
    if actor.role != ROLE_SUPER_ADMIN:
        raise HTTPException(status_code=403, detail="Only Super Administrators can trigger data retention purges.")
    settings = get_settings()
    if settings.is_production and retention_days is not None and retention_days != settings.retention_purge_days:
        raise HTTPException(
            status_code=400,
            detail="In production environments, retention purge policy is strictly enforced by server configuration and cannot be overridden by callers.",
        )
    days = settings.retention_purge_days if settings.is_production else (retention_days or settings.retention_purge_days)
    return run_retention_purge(db, retention_days=days, operator_id=actor.email or actor.sub)


@router.post("/students/{student_id}/de-enroll")
def de_enroll_student(
    student_id: str,
    request: Request,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Permanently de-enroll student biometrics, purge embeddings, and issue a cryptographic deletion certificate."""
    student = db.get(Student, student_id)
    if student is None:
        raise HTTPException(status_code=404, detail=f"Student '{student_id}' does not exist.")
    if actor.role == ROLE_DEAN:
        dept = db.get(Department, actor.department_id) if actor.department_id else None
        in_dept = False
        if dept:
            enrolled = db.execute(
                select(ClassGroup)
                .join(ClassEnrollment, ClassEnrollment.class_group_id == ClassGroup.class_group_id)
                .where(ClassEnrollment.student_id == student_id, ClassGroup.department_id == actor.department_id)
            ).scalars().first()
            if enrolled:
                in_dept = True
            elif student.person_id:
                person = db.get(Person, student.person_id)
                if person and person.department == dept.code:
                    in_dept = True
        if not in_dept:
            raise HTTPException(status_code=403, detail="Deans can only de-enroll students within their own department.")

    storage = getattr(request.app.state, "storage", None)
    try:
        return de_enroll_student_biometrics(
            db=db,
            student_id=student_id,
            operator_id=actor.email or actor.sub,
            storage_service=storage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
