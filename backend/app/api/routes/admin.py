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

from app.api.dependencies import admin_actor
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


@router.get("/people")
def list_people(
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    active_only: bool = True,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(Person)
    if active_only:
        statement = statement.where(Person.is_active.is_(True))
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
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    if person.is_active:
        person.is_active = False
        person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor,
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
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    person = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
    if person is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    person.is_active = True
    person.updated_at = datetime.now(timezone.utc)
    event = AuditEvent(
        session_id=f"admin:{employee_id}",
        actor_type="administrator",
        actor_id=actor,
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
    _actor: Annotated[str, Depends(admin_actor)],
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
        statement = statement.where(AttendanceEvent.attendance_session_id == attendance_session_id)
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: str | None = None,
    attendance_session_id: str | None = None,
):
    statement = select(AttendanceEvent)
    if employee_id:
        statement = statement.where(AttendanceEvent.employee_id == employee_id)
    if attendance_session_id:
        statement = statement.where(AttendanceEvent.attendance_session_id == attendance_session_id)
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    session_id: str | None = None,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    statement = select(AuditEvent)
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.get(AuditEvent, audit_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found.")
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
    _actor: Annotated[str, Depends(admin_actor)],
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    attendance_session_id: str | None = None,
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    statement = select(CaptureBatchJob)
    if attendance_session_id:
        statement = statement.where(CaptureBatchJob.attendance_session_id == attendance_session_id)
    if status:
        normalized_status = status.strip().upper()
        if normalized_status not in {"QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED"}:
            raise HTTPException(status_code=422, detail="Unknown capture-batch status.")
        statement = statement.where(CaptureBatchJob.status == normalized_status)
    rows = db.execute(statement.order_by(CaptureBatchJob.created_at.desc()).limit(limit)).scalars().all()
    return {"items": [serialize_capture_batch(row) for row in rows]}


@router.post("/attendance-batches/{batch_id}/retry")
def retry_capture_batch(
    batch_id: str,
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    job = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.batch_id == batch_id
    ).with_for_update()).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Capture batch not found.")
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    now = datetime.now(timezone.utc)
    today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)

    dept_count = db.scalar(select(func.count(Department.department_id)).where(Department.is_active.is_(True))) or 0
    group_count = db.scalar(select(func.count(ClassGroup.class_group_id)).where(ClassGroup.is_active.is_(True))) or 0
    student_count = db.scalar(select(func.count(Student.student_id)).where(Student.is_active.is_(True))) or 0
    biometric_count = db.scalar(select(func.count(func.distinct(EmbeddingRecord.person_id)))) or 0
    open_sess_count = db.scalar(select(func.count(AttendanceSession.session_id)).where(AttendanceSession.status == "OPEN")) or 0
    today_att_count = db.scalar(select(func.count(AttendanceEvent.attendance_id)).where(AttendanceEvent.timestamp >= today_start)) or 0
    pending_rev_count = db.scalar(select(func.count(CaptureBatchJob.batch_id)).where(CaptureBatchJob.status.in_(["FAILED", "REJECTED"]))) or 0

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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
):
    statement = (
        select(CaptureBatchJob)
        .where(CaptureBatchJob.status.in_(["REJECTED", "FAILED"]))
        .order_by(CaptureBatchJob.created_at.desc())
        .limit(limit)
    )
    jobs = db.execute(statement).scalars().all()
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
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    job = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.batch_id == batch_id
    ).with_for_update()).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Review item not found.")
    if job.status not in ("REJECTED", "FAILED"):
        raise HTTPException(status_code=409, detail="Only rejected or failed capture jobs can be reviewed.")

    now = datetime.now(timezone.utc)
    sess = db.get(AttendanceSession, job.attendance_session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Associated attendance session not found.")

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
            "actor": actor,
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
        actor_id=actor,
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
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.execute(
        select(AttendanceEvent).where(AttendanceEvent.attendance_id == attendance_id).with_for_update()
    ).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Attendance record not found.")

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
        actor_id=actor,
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
    actor: Annotated[str, Depends(admin_actor)],
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

    enrollment = db.execute(
        select(ClassEnrollment)
        .where(ClassEnrollment.student_id == student.student_id)
        .where(ClassEnrollment.class_group_id == sess.class_group_id)
        .where(ClassEnrollment.status == "ACTIVE")
    ).scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=409, detail="Student is not actively enrolled in this session's class.")

    now = datetime.now(timezone.utc)
    attendance_event = AttendanceEvent(
        attendance_id=str(uuid.uuid4()),
        person_id=student.person_id,
        employee_id=student.student_number,
        punch_type=payload.punch_type,
        timestamp=now,
        similarity_score=1.0,
        threshold=1.0,
        client_device_id=f"manual:{actor}",
        pipeline_version="manual-administrative-entry",
        evidence_id=f"manual:{uuid.uuid4()}",
        attendance_session_id=sess.session_id,
    )
    db.add(attendance_event)

    audit = AuditEvent(
        session_id=sess.session_id,
        actor_type="administrator",
        actor_id=actor,
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
    _actor: Annotated[str, Depends(admin_actor)],
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
    _actor: Annotated[str, Depends(admin_actor)],
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
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    storage = getattr(request.app.state, "storage", None)
    if not storage or not storage.is_configured:
        raise HTTPException(status_code=503, detail="Cloud storage is not configured.")
    success = storage.delete_media(payload.public_id)
    if not success:
        raise HTTPException(status_code=502, detail="Failed to delete media asset.")
    audit = AuditEvent(
        session_id=f"storage:{payload.public_id}",
        actor_type="administrator",
        actor_id=actor,
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
    _actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
):
    """List poisoned or retry-exhausted capture batches for operator triage."""
    items = list_dead_letter_batches(db, limit=limit)
    return {"items": items, "total": len(items)}


@router.post("/batches/{batch_id}/requeue")
@router.post("/batches/{batch_id}/retry")
def requeue_batch(
    batch_id: str,
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    """Requeue an exhausted dead-letter batch back to the queue for reprocessing."""
    return requeue_dead_letter_batch(db, batch_id, operator_id=actor)


@router.post("/retention/purge")
def trigger_retention_purge(
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    retention_days: int | None = Query(default=None, ge=1, le=365),
):
    """Trigger data retention purge for expired raw capture frames."""
    days = retention_days or get_settings().retention_purge_days
    return run_retention_purge(db, retention_days=days, operator_id=actor)


@router.post("/students/{student_id}/de-enroll")
def de_enroll_student(
    student_id: str,
    request: Request,
    actor: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    """Permanently de-enroll student biometrics, purge embeddings, and issue a cryptographic deletion certificate."""
    storage = getattr(request.app.state, "storage", None)
    try:
        return de_enroll_student_biometrics(
            db=db,
            student_id=student_id,
            operator_id=actor,
            storage_service=storage,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
