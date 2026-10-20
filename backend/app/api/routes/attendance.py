from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import device_actor
from app.database import get_db
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.security import encrypt_capture_payload
from app.services.capture_batches import pack_capture_frames, serialize_capture_batch

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])


async def _read_burst(
    images: list[UploadFile] | None,
    image: UploadFile | None,
    max_image_bytes: int,
    max_total_bytes: int,
    minimum_frames: int,
    maximum_frames: int,
) -> list[bytes]:
    if images and image is not None:
        raise HTTPException(status_code=422, detail="Send either repeated 'images' parts or legacy 'image', not both.")
    uploads = images or ([image] if image is not None else [])
    if not uploads:
        raise HTTPException(status_code=422, detail="Camera frame burst is required.")
    if len(uploads) < minimum_frames:
        raise HTTPException(status_code=422, detail=f"At least {minimum_frames} frames are required.")
    if len(uploads) > maximum_frames:
        raise HTTPException(status_code=413, detail=f"At most {maximum_frames} frames are accepted.")
    payloads: list[bytes] = []
    total = 0
    for part in uploads:
        content_type = (part.content_type or "").lower()
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail=f"Unsupported image content type: {content_type}")
        payload = await part.read(max_image_bytes + 1)
        if len(payload) > max_image_bytes:
            raise HTTPException(status_code=413, detail="A camera frame exceeds the configured upload limit.")
        total += len(payload)
        if total > max_total_bytes:
            raise HTTPException(status_code=413, detail="Total camera burst exceeds the configured upload limit.")
        payloads.append(payload)
    return payloads


@router.post("/identify")
async def identify_attendance(
    request: Request,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
    punch_type: Annotated[str, Form()],
    client_device_id: Annotated[str, Form(min_length=1, max_length=120)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    settings = request.app.state.settings
    payloads = await _read_burst(
        images, image, settings.max_upload_bytes, settings.max_request_bytes,
        settings.minimum_identification_frames, settings.maximum_identification_frames,
    )
    return request.app.state.pipeline.identify(
        db,
        payloads,
        punch_type=punch_type.strip().upper(),
        client_device_id=client_device_id.strip(),
        actor_id=actor_id,
    )


@router.post("/verify")
async def verify_attendance(
    request: Request,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: Annotated[str, Form(min_length=1, max_length=80)],
    punch_type: Annotated[str, Form()],
    client_device_id: Annotated[str, Form(min_length=1, max_length=120)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    settings = request.app.state.settings
    payloads = await _read_burst(
        images, image, settings.max_upload_bytes, settings.max_request_bytes,
        settings.minimum_identification_frames, settings.maximum_identification_frames,
    )
    return request.app.state.pipeline.identify(
        db,
        payloads,
        punch_type=punch_type.strip().upper(),
        client_device_id=client_device_id.strip(),
        actor_id=actor_id,
        employee_id_claim=employee_id.strip(),
    )


@router.get("/sessions/open")
def list_open_attendance_sessions(
    _actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    """List open attendance sessions in active class groups for an authenticated kiosk."""
    rows = db.execute(
        select(AttendanceSession, ClassGroup, Department)
        .join(ClassGroup, ClassGroup.class_group_id == AttendanceSession.class_group_id)
        .join(Department, Department.department_id == ClassGroup.department_id)
        .where(
            AttendanceSession.status == "OPEN",
            ClassGroup.is_active.is_(True),
            Department.is_active.is_(True),
        )
        .order_by(AttendanceSession.starts_at.desc())
    ).all()
    return {"items": [{
        "session_id": session.session_id,
        "subject_code": session.subject_code,
        "subject_name": session.subject_name,
        "starts_at": session.starts_at.isoformat(),
        "class_group_id": group.class_group_id,
        "department_code": department.code,
        "year_of_study": group.year_of_study,
        "section": group.section,
        "academic_year": group.academic_year,
    } for session, group, department in rows]}


@router.post("/sessions/{attendance_session_id}/batches", status_code=202)
async def enqueue_attendance_batch(
    attendance_session_id: str,
    request: Request,
    response: Response,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[str, Form(min_length=12, max_length=120)],
    punch_type: Annotated[str, Form()],
    client_device_id: Annotated[str, Form(min_length=1, max_length=120)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    settings = request.app.state.settings
    normalized_punch = punch_type.strip().upper()
    if normalized_punch not in {"CHECK_IN", "CHECK_OUT"}:
        raise HTTPException(status_code=422, detail="punch_type must be CHECK_IN or CHECK_OUT")
    frames = await _read_burst(
        images, image, settings.max_upload_bytes, settings.max_request_bytes,
        settings.minimum_identification_frames, settings.maximum_identification_frames,
    )
    packed = pack_capture_frames(frames)
    request_digest = hashlib.sha256(packed).hexdigest()
    key = idempotency_key.strip()
    device_id = client_device_id.strip()

    existing = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.device_actor_id == actor_id,
        CaptureBatchJob.idempotency_key == key,
    )).scalar_one_or_none()
    if existing is not None:
        if (
            existing.request_sha256 != request_digest
            or existing.attendance_session_id != attendance_session_id
            or existing.punch_type != normalized_punch
            or existing.client_device_id != device_id
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was reused for a different capture batch.")
        response.status_code = 200
        return serialize_capture_batch(existing)

    attendance_session = db.get(AttendanceSession, attendance_session_id)
    if attendance_session is None:
        raise HTTPException(status_code=404, detail="Attendance session not found.")
    group = db.get(ClassGroup, attendance_session.class_group_id)
    department = db.get(Department, group.department_id) if group else None
    if attendance_session.status != "OPEN":
        raise HTTPException(status_code=409, detail="Attendance session is not open.")
    if group is None or not group.is_active or department is None or not department.is_active:
        raise HTTPException(status_code=409, detail="Attendance session's class group or department is inactive.")

    try:
        ciphertext, nonce = encrypt_capture_payload(packed, settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Capture queue encryption is not configured.") from exc

    now = datetime.now(timezone.utc)
    job = CaptureBatchJob(
        attendance_session_id=attendance_session.session_id,
        class_group_id=attendance_session.class_group_id,
        device_actor_id=actor_id,
        client_device_id=device_id,
        idempotency_key=key,
        request_sha256=request_digest,
        frame_count=len(frames),
        punch_type=normalized_punch,
        status="QUEUED",
        encrypted_payload=ciphertext,
        payload_nonce=nonce,
        payload_expires_at=now + timedelta(hours=24),
        attempts=0,
        max_attempts=3,
        next_attempt_at=now,
    )
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError as exc:
        db.rollback()
        existing = db.execute(select(CaptureBatchJob).where(
            CaptureBatchJob.device_actor_id == actor_id,
            CaptureBatchJob.idempotency_key == key,
        )).scalar_one_or_none()
        if existing is None:
            raise HTTPException(status_code=409, detail="Capture batch idempotency conflict.") from exc
        if (
            existing.request_sha256 != request_digest
            or existing.attendance_session_id != attendance_session_id
            or existing.punch_type != normalized_punch
            or existing.client_device_id != device_id
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was reused for a different capture batch.") from exc
        response.status_code = 200
        return serialize_capture_batch(existing)
    return serialize_capture_batch(job)


@router.get("/batches/{batch_id}")
def get_attendance_batch(
    batch_id: str,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    job = db.get(CaptureBatchJob, batch_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Capture batch not found.")
    if job.device_actor_id != actor_id:
        raise HTTPException(status_code=403, detail="Capture batch belongs to a different kiosk credential.")
    payload = serialize_capture_batch(job)
    attendance_session = db.get(AttendanceSession, job.attendance_session_id)
    payload["session_open"] = attendance_session is not None and attendance_session.status == "OPEN"
    return payload
