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
            job.status = "FAILED"
            job.completed_at = now
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
    expired_failed = db.execute(select(CaptureBatchJob).where(
        CaptureBatchJob.status == "FAILED",
        CaptureBatchJob.payload_expires_at <= now,
        CaptureBatchJob.encrypted_payload.is_not(None),
    )).scalars().all()
    for job in expired_failed:
        job.encrypted_payload = None
        job.payload_nonce = None
        job.updated_at = now
        error = json.loads(job.error_json) if job.error_json else {}
        error["payload_expired"] = True
        error["reason_code"] = "CAPTURE_PAYLOAD_EXPIRED"
        db.add(job)
        job.error_json = json.dumps(error, default=str)
    if rows or expired or expired_failed:
        db.commit()


def _claim_next_capture_batch() -> str | None:
    now = utcnow()
    with SessionLocal() as db:
        _recover_stale_jobs(db, now)
        batch_id = db.execute(select(CaptureBatchJob.batch_id).where(
            CaptureBatchJob.status == "QUEUED",
            (CaptureBatchJob.next_attempt_at.is_(None) | (CaptureBatchJob.next_attempt_at <= now)),
            CaptureBatchJob.payload_expires_at > now,
            CaptureBatchJob.attempts < CaptureBatchJob.max_attempts,
            CaptureBatchJob.encrypted_payload.is_not(None),
        ).order_by(CaptureBatchJob.created_at).limit(1)).scalar_one_or_none()
        if batch_id is None:
            return None
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
        return batch_id if claimed.rowcount == 1 else None


def _finish_failure(db: Session, job: CaptureBatchJob, status_code: int, detail, now: datetime) -> None:
    # A racing worker must not overwrite a terminal result committed with its attendance event.
    if job.status != "PROCESSING":
        db.rollback()
        return
    retryable = status_code >= 500 and job.attempts < job.max_attempts and as_utc(job.payload_expires_at) > now
    job.error_json = json.dumps({"status_code": status_code, "detail": detail}, default=str)
    job.updated_at = now
    if retryable:
        job.status = "QUEUED"
        job.next_attempt_at = now + timedelta(seconds=min(60, 2 ** job.attempts))
        job.started_at = None
    else:
        job.status = "REJECTED" if status_code < 500 else "FAILED"
        job.completed_at = now
        if job.status == "REJECTED":
            job.encrypted_payload = None
            job.payload_nonce = None
    db.commit()


def process_claimed_capture_batch(batch_id: str, pipeline) -> None:
    """Run one claimed job through the configured real recognition pipeline."""
    try:
        with SessionLocal() as db:
            job = db.get(CaptureBatchJob, batch_id)
            if job is None or job.status != "PROCESSING":
                return
            now = utcnow()
            if as_utc(job.payload_expires_at) <= now or not job.encrypted_payload or not job.payload_nonce:
                _finish_failure(db, job, 410, "Encrypted capture is unavailable or expired.", now)
                return
            claimed_attempt = job.attempts
            attendance_session = db.get(AttendanceSession, job.attendance_session_id)
            group = db.get(ClassGroup, job.class_group_id)
            department = db.get(Department, group.department_id) if group else None
            if (
                attendance_session is None or attendance_session.status != "OPEN"
                or attendance_session.class_group_id != job.class_group_id
                or group is None or not group.is_active
                or department is None or not department.is_active
            ):
                _finish_failure(db, job, 409, "Attendance session or its class group is not active.", now)
                return
            payload = decrypt_capture_payload(job.encrypted_payload, job.payload_nonce, pipeline.settings)
            frames = unpack_capture_frames(payload)
            if len(frames) != job.frame_count:
                _finish_failure(db, job, 422, "Stored frame count differs from the batch manifest.", now)
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
                _finish_failure(db, job, exc.status_code, exc.detail, utcnow())
    except Exception:
        logger.exception("Capture batch failed unexpectedly; batch_id=%s", batch_id)
        with SessionLocal() as db:
            job = db.get(CaptureBatchJob, batch_id)
            if job is not None:
                _finish_failure(db, job, 503, "Worker failed unexpectedly; encrypted capture retained for retry.", utcnow())


async def run_capture_batch_worker(pipeline) -> None:
    """Poll the durable database queue; stale claims are recovered after process restart."""
    while True:
        try:
            batch_id = await asyncio.to_thread(_claim_next_capture_batch)
            if batch_id:
                await asyncio.to_thread(process_claimed_capture_batch, batch_id, pipeline)
            else:
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Capture queue polling failed")
            await asyncio.sleep(2)
