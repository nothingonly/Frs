from __future__ import annotations

import asyncio
import json
import logging
import struct
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.db.entities import AttendanceSession, CaptureBatchJob, ClassGroup, Department
from app.security import decrypt_capture_payload

logger = logging.getLogger("frs.capture_batches")
_MAGIC = b"FRSB1"
_PAYLOAD_TTL = timedelta(hours=24)
_STALE_AFTER = timedelta(minutes=45)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """Normalize SQLite's naive DateTime readback and Postgres-aware timestamps."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def pack_capture_frames(frames: list[bytes]) -> bytes:
    if not frames or len(frames) > 16:
        raise ValueError("Capture payload must contain between 1 and 16 frames.")
    parts = [_MAGIC, struct.pack(">H", len(frames))]
    for frame in frames:
        if not frame or len(frame) > 0xFFFFFFFF:
            raise ValueError("Capture frame is empty or too large.")
        parts.extend((struct.pack(">I", len(frame)), frame))
    return b"".join(parts)


def unpack_capture_frames(payload: bytes) -> list[bytes]:
    if not payload.startswith(_MAGIC) or len(payload) < len(_MAGIC) + 2:
        raise ValueError("Capture payload header is invalid.")
    cursor = len(_MAGIC)
    count = struct.unpack_from(">H", payload, cursor)[0]
    cursor += 2
    if count < 1 or count > 16:
        raise ValueError("Capture payload frame count is invalid.")
    frames: list[bytes] = []
    for _ in range(count):
        if cursor + 4 > len(payload):
            raise ValueError("Capture payload is truncated before a frame length.")
        size = struct.unpack_from(">I", payload, cursor)[0]
        cursor += 4
        if size < 1 or cursor + size > len(payload):
            raise ValueError("Capture payload has an invalid frame length.")
        frames.append(payload[cursor:cursor + size])
        cursor += size
    if cursor != len(payload):
        raise ValueError("Capture payload has trailing bytes.")
    return frames


def serialize_capture_batch(job: CaptureBatchJob) -> dict:
    return {
        "batch_id": job.batch_id,
        "attendance_session_id": job.attendance_session_id,
        "class_group_id": job.class_group_id,
        "status": job.status,
        "frame_count": job.frame_count,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "request_sha256": job.request_sha256,
        "payload_expires_at": as_utc(job.payload_expires_at).isoformat(),
        "payload_available": bool(
            job.encrypted_payload and job.payload_nonce and as_utc(job.payload_expires_at) > utcnow()
        ),
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "result": json.loads(job.result_json) if job.result_json else None,
        "error": json.loads(job.error_json) if job.error_json else None,
    }


def _recover_stale_jobs(db: Session, now: datetime) -> None:
    cutoff = now - _STALE_AFTER
    rows = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.status == "PROCESSING",
        CaptureBatchJob.updated_at < cutoff,
    )).scalars().all()
    for job in rows:
        if job.attempts < job.max_attempts and as_utc(job.payload_expires_at) > now and job.encrypted_payload:
            job.status = "QUEUED"
            job.next_attempt_at = now
            job.started_at = None
            job.error_json = json.dumps({"status_code": 503, "detail": "The processing lease expired; encrypted capture returned to the queue.", "reason_code": "PROCESSING_LEASE_EXPIRED"})
        else:
            job.status = "DEAD_LETTER" if job.attempts >= job.max_attempts else "FAILED"
            job.completed_at = now
            if job.status == "FAILED":
                job.encrypted_payload = None
                job.payload_nonce = None
            job.error_json = json.dumps({"status_code": 503, "detail": "Batch exhausted retry/retention window after processing interruption.", "reason_code": "PROCESSING_LEASE_EXPIRED"})
    expired = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.status == "QUEUED",
        CaptureBatchJob.payload_expires_at <= now,
    )).scalars().all()
    for job in expired:
        job.status = "FAILED"
        job.completed_at = now
        job.encrypted_payload = None
        job.payload_nonce = None
        job.error_json = json.dumps({"status_code": 410, "detail": "Encrypted capture expired before processing.", "reason_code": "CAPTURE_PAYLOAD_EXPIRED"})
    expired_terminal = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.status.in_(["FAILED", "DEAD_LETTER"]),
        CaptureBatchJob.payload_expires_at <= now,
        CaptureBatchJob.encrypted_payload.is_not(None),
    )).scalars().all()
    for job in expired_terminal:
        job.encrypted_payload = None
        job.payload_nonce = None
        job.updated_at = now
        error = json.loads(job.error_json) if job.error_json else {}
        error["payload_expired"] = True
        error["reason_code"] = "CAPTURE_PAYLOAD_EXPIRED"
        db.add(job)
        job.error_json = json.dumps(error, default=str)
    if rows or expired or expired_terminal:
        db.commit()


def _claim_next_capture_batch() -> tuple[str, int] | None:
    now = utcnow()
    with SessionLocal() as db:
        _recover_stale_jobs(db, now)
        candidate = db.execute(select(CaptureBatchJob.batch_id, CaptureBatchJob.attempts).where(
            CaptureBatchJob.status == "QUEUED",
            (CaptureBatchJob.next_attempt_at.is_(None) | (CaptureBatchJob.next_attempt_at <= now)),
            CaptureBatchJob.payload_expires_at > now,
            CaptureBatchJob.attempts < CaptureBatchJob.max_attempts,
            CaptureBatchJob.encrypted_payload.is_not(None),
        ).order_by(CaptureBatchJob.created_at).limit(1)).first()
        if candidate is None:
            return None
        batch_id, previous_attempts = candidate
        claimed = db.execute(update(CaptureBatchJob).where(
            CaptureBatchJob.batch_id == batch_id,
            CaptureBatchJob.status == "QUEUED",
        ).values(
            status="PROCESSING",
            attempts=CaptureBatchJob.attempts + 1,
            started_at=now,
            updated_at=now,
            error_json=None,
        ))
        db.commit()
        return (batch_id, previous_attempts + 1) if claimed.rowcount == 1 else None


def _finish_failure(
    db: Session, job: CaptureBatchJob, status_code: int, detail, now: datetime,
    expected_attempt: int | None = None,
) -> None:
    # Re-read and lock the row: the object in this Session may be stale after a worker lease expires.
    statement = select(CaptureBatchJob).where(
        CaptureBatchJob.batch_id == job.batch_id,
        CaptureBatchJob.status == "PROCESSING",
    )
    if expected_attempt is not None:
        statement = statement.where(CaptureBatchJob.attempts == expected_attempt)
    current_job = db.execute(
        statement.with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if current_job is None:
        db.rollback()
        return
    job = current_job
    retryable = status_code >= 500 and job.attempts < job.max_attempts and as_utc(job.payload_expires_at) > now
    job.error_json = json.dumps({"status_code": status_code, "detail": detail}, default=str)
    job.updated_at = now
    if retryable:
        job.status = "QUEUED"
        job.next_attempt_at = now + timedelta(seconds=min(60, 2 ** job.attempts))
        job.started_at = None
    else:
        if status_code >= 500 and job.attempts >= job.max_attempts:
            job.status = "DEAD_LETTER"
        else:
            job.status = "REJECTED" if status_code < 500 else "FAILED"
        job.completed_at = now
        if job.status == "REJECTED":
            job.encrypted_payload = None
            job.payload_nonce = None
    db.commit()


def list_dead_letter_batches(db: Session, limit: int = 50) -> list[dict]:
    """Retrieve dead-letter capture batches for operator inspection and triage."""
    statement = (
        select(CaptureBatchJob)
        .where(CaptureBatchJob.status == "DEAD_LETTER")
        .order_by(CaptureBatchJob.updated_at.desc())
        .limit(min(max(1, limit), 100))
    )
    rows = db.execute(statement).scalars().all()
    return [serialize_capture_batch(job) for job in rows]


def requeue_dead_letter_batch(db: Session, batch_id: str, operator_id: str | None = None) -> dict:
    """Reset an exhausted dead-letter batch back to QUEUED for replay."""
    job = db.get(CaptureBatchJob, batch_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Capture batch not found.")
    if job.status != "DEAD_LETTER":
        raise HTTPException(
            status_code=400,
            detail=f"Batch {batch_id} is in status '{job.status}', only DEAD_LETTER batches can be requeued.",
        )
    now = utcnow()
    if not job.encrypted_payload or not job.payload_nonce:
        raise HTTPException(
            status_code=410,
            detail="Batch payload has been purged or expired; cannot be requeued.",
        )
    job.status = "QUEUED"
    job.attempts = 0
    job.started_at = None
    job.completed_at = None
    job.next_attempt_at = now
    job.updated_at = now
    if as_utc(job.payload_expires_at) <= now + timedelta(minutes=15):
        job.payload_expires_at = now + timedelta(hours=1)

    error_data = json.loads(job.error_json) if job.error_json else {}
    error_data["requeued_at"] = now.isoformat()
    if operator_id:
        error_data["requeued_by"] = operator_id
    job.error_json = json.dumps(error_data, default=str)

    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_capture_batch(job)


def process_claimed_capture_batch(batch_id: str, pipeline, claimed_attempt: int) -> None:
    """Run one claimed job through the configured real recognition pipeline."""
    try:
        with SessionLocal() as db:
            job = db.get(CaptureBatchJob, batch_id)
            if job is None or job.status != "PROCESSING" or job.attempts != claimed_attempt:
                db.rollback()
                return
            now = utcnow()
            if as_utc(job.payload_expires_at) <= now or not job.encrypted_payload or not job.payload_nonce:
                _finish_failure(db, job, 410, "Encrypted capture is unavailable or expired.", now, claimed_attempt)
                return
            attendance_session = db.get(AttendanceSession, job.attendance_session_id)
            group = db.get(ClassGroup, job.class_group_id)
            department = db.get(Department, group.department_id) if group else None
            if (
                attendance_session is None or attendance_session.status != "OPEN"
                or attendance_session.class_group_id != job.class_group_id
                or group is None or not group.is_active
                or department is None or not department.is_active
            ):
                _finish_failure(db, job, 409, "Attendance session or its class group is not active.", now, claimed_attempt)
                return
            payload = decrypt_capture_payload(job.encrypted_payload, job.payload_nonce, pipeline.settings)
            frames = unpack_capture_frames(payload)
            if len(frames) != job.frame_count:
                _finish_failure(db, job, 422, "Stored frame count differs from the batch manifest.", now, claimed_attempt)
                return
            result = pipeline.identify(
                db, frames, punch_type=job.punch_type,
                client_device_id=job.client_device_id, actor_id=job.device_actor_id,
                attendance_session_id=job.attendance_session_id,
                class_group_id=job.class_group_id, capture_batch_id=job.batch_id,
                capture_batch_attempt=claimed_attempt,
            )
            job = db.get(CaptureBatchJob, batch_id)
            if job is None:
                return
            job.status = "SUCCEEDED"
            job.result_json = json.dumps(result, separators=(",", ":"), default=str)
            job.error_json = None
            job.encrypted_payload = None
            job.payload_nonce = None
            job.completed_at = utcnow()
            job.updated_at = job.completed_at
            db.commit()
    except HTTPException as exc:
        with SessionLocal() as db:
            job = db.get(CaptureBatchJob, batch_id)
            if job is not None:
                _finish_failure(db, job, exc.status_code, exc.detail, utcnow(), claimed_attempt)
    except Exception:
        logger.exception("Capture batch failed unexpectedly; batch_id=%s", batch_id)
        with SessionLocal() as db:
            job = db.get(CaptureBatchJob, batch_id)
            if job is not None:
                _finish_failure(db, job, 503, "Worker failed unexpectedly; encrypted capture retained for retry.", utcnow(), claimed_attempt)


async def run_capture_batch_worker(pipeline) -> None:
    """Poll the durable database queue; stale claims are recovered after process restart."""
    while True:
        try:
            claim = await asyncio.to_thread(_claim_next_capture_batch)
            if claim:
                batch_id, claimed_attempt = claim
                await asyncio.to_thread(process_claimed_capture_batch, batch_id, pipeline, claimed_attempt)
            else:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Capture queue polling failed")
            await asyncio.sleep(2)
