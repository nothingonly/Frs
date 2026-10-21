from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.entities import AuditEvent, CaptureBatchJob, EmbeddingRecord, Person, Student

logger = logging.getLogger("frs.retention")


def purge_expired_capture_payloads(db: Session, retention_days: int = 30) -> int:
    """Purge raw encrypted image payloads and nonces from capture jobs that have expired.

    Checks both:
    1. payload_expires_at <= now (the 24-hour sensitive payload expiry horizon), and
    2. created_at < cutoff (the overall retention days policy window).

    Preserves all attendance event records, audit entries, and job metadata while securely
    erasing sensitive biometric frame data after the policy window expires.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)
    expired_jobs = db.execute(
        select(CaptureBatchJob).where(
            or_(
                CaptureBatchJob.payload_expires_at <= now,
                CaptureBatchJob.created_at < cutoff,
            ),
            CaptureBatchJob.encrypted_payload.is_not(None),
        )
    ).scalars().all()

    purged_count = 0
    for job in expired_jobs:
        job.encrypted_payload = None
        job.payload_nonce = None
        job.updated_at = now
        error_dict = json.loads(job.error_json) if job.error_json else {}
        error_dict["retention_purged"] = True
        error_dict["retention_purged_at"] = now.isoformat()
        job.error_json = json.dumps(error_dict)
        purged_count += 1

    if purged_count > 0:
        db.commit()
        logger.info(
            "Purged %d raw capture payloads (expired before now or older than %d days).",
            purged_count,
            retention_days,
        )

    return purged_count


def run_retention_purge(
    db: Session,
    retention_days: int = 30,
    operator_id: str = "system",
) -> dict[str, Any]:
    """Execute scheduled retention purge with durable audit logging."""
    purged = purge_expired_capture_payloads(db, retention_days)
    now_iso = datetime.now(timezone.utc).isoformat()
    audit_entry = AuditEvent(
        session_id="system-retention-purge",
        occurred_at=datetime.now(timezone.utc),
        actor_type="SYSTEM",
        actor_id=operator_id,
        action="RETENTION_PURGE_EXECUTED",
        decision_state="EXECUTED",
        reason_codes_json=json.dumps(["POLICY_SCHEDULED_PURGE"]),
        evidence_json=json.dumps({
            "purged_payloads": purged,
            "retention_days": retention_days,
            "executed_at": now_iso,
        }),
    )
    db.add(audit_entry)
    db.commit()
    return {
        "status": "SUCCESS",
        "purged_payloads": purged,
        "retention_days": retention_days,
        "executed_at": now_iso,
    }


def de_enroll_student_biometrics(
    db: Session,
    student_id: str,
    operator_id: str,
    storage_service: Any | None = None,
    signing_key: str | None = None,
) -> dict[str, Any]:
    """Execute complete student biometric de-enrollment with cryptographic deletion verification.
    
    1. Removes all biometric embedding records.
    2. Deactivates the Person identity record.
    3. Purges associated cloud-stored face crops (if storage_service is provided).
    4. Writes an immutable audit log entry.
    5. Returns an HMAC-SHA256 authenticated digital deletion certificate.
    """
    student = db.get(Student, student_id)
    if student is None:
        raise ValueError(f"Student '{student_id}' does not exist.")

    person = db.get(Person, student.person_id) if student.person_id else None
    deleted_embeddings_count = 0

    if person is not None:
        embeddings = db.execute(
            select(EmbeddingRecord).where(EmbeddingRecord.person_id == person.person_id)
        ).scalars().all()

        for rec in embeddings:
            db.delete(rec)
            deleted_embeddings_count += 1

        person.is_active = False

    target_ids = [f"students/{student_id}"]
    if student.person_id:
        target_ids.append(f"faces/{student.person_id}")

    media_outcomes: dict[str, str] = {}
    media_purged = False
    storage_configured = bool(storage_service is not None and getattr(storage_service, "is_configured", False))

    if storage_service is not None and not storage_configured:
        for mid in target_ids:
            media_outcomes[mid] = "STORAGE_NOT_CONFIGURED"
        status_state = "DELETION_INCOMPLETE"
        qualification = "STORAGE_UNCONFIGURED_DELETION_INCOMPLETE"
    elif storage_configured:
        for mid in target_ids:
            try:
                res = storage_service.delete_media(mid)
                if res is True:
                    media_outcomes[mid] = "CONFIRMED_DELETED"
                else:
                    media_outcomes[mid] = "FAILED_OR_NOT_FOUND"
            except Exception as exc:
                logger.warning("Error deleting media %s for student %s: %s", mid, student_id, exc)
                media_outcomes[mid] = f"ERROR: {exc}"

        all_confirmed = bool(target_ids and all(s == "CONFIRMED_DELETED" for s in media_outcomes.values()))
        if all_confirmed:
            media_purged = True
            status_state = "DE_ENROLLED"
            qualification = "FULL_DELETION_VERIFIED"
        else:
            media_purged = False
            status_state = "DELETION_INCOMPLETE"
            qualification = "DELETION_INCOMPLETE"
    else:
        for mid in target_ids:
            media_outcomes[mid] = "NO_STORAGE_SERVICE_PROVIDED"
        status_state = "DE_ENROLLED"
        qualification = "DATABASE_ONLY_UNVERIFIED_MEDIA"

    now_iso = datetime.now(timezone.utc).isoformat()
    raw_cert_string = f"{student_id}:{student.person_id}:{now_iso}:{deleted_embeddings_count}:{operator_id}:{qualification}"
    cert_hash = hashlib.sha256(raw_cert_string.encode("utf-8")).hexdigest()

    secret = signing_key or get_settings().effective_jwt_secret
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    cert_signature = hmac.new(secret_bytes, raw_cert_string.encode("utf-8"), hashlib.sha256).hexdigest()

    audit_entry = AuditEvent(
        audit_id=f"audit-{cert_hash[:16]}",
        session_id="system-retention",
        occurred_at=datetime.now(timezone.utc),
        actor_type="ADMINISTRATOR",
        actor_id=operator_id,
        action="BIOMETRIC_DE_ENROLLMENT",
        decision_state="EXECUTED" if status_state == "DE_ENROLLED" else "PARTIALLY_EXECUTED",
        reason_codes_json=json.dumps(["DE_ENROLLMENT_REQUESTED", qualification]),
        evidence_json=json.dumps({
            "student_id": student_id,
            "person_id": student.person_id,
            "deleted_embeddings": deleted_embeddings_count,
            "deletion_certificate": cert_hash,
            "signature": cert_signature,
            "media_purged": media_purged,
            "qualification": qualification,
            "media_deletion_details": media_outcomes,
            "timestamp": now_iso,
        }),
    )
    db.add(audit_entry)
    db.commit()

    logger.info(
        "Student %s biometrics de-enrolled by %s (deleted %d embeddings, status=%s, cert=%s, media_purged=%s, qual=%s)",
        student_id, operator_id, deleted_embeddings_count, status_state, cert_hash, media_purged, qualification,
    )

    return {
        "status": status_state,
        "student_id": student_id,
        "person_id": student.person_id,
        "deleted_embeddings_count": deleted_embeddings_count,
        "deletion_certificate": cert_hash,
        "deletion_signature": cert_signature,
        "signed_certificate": {
            "certificate_id": f"cert-{cert_hash[:16]}",
            "digest": cert_hash,
            "signature": cert_signature,
            "algorithm": "HMAC-SHA256",
            "issuer": "FRS-Biometric-Privacy-Lifecycle",
            "qualification": qualification,
            "signed_at": now_iso,
        },
        "media_purged": media_purged,
        "media_deletion_details": media_outcomes,
        "timestamp": now_iso,
    }
