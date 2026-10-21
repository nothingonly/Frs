from __future__ import annotations

import hashlib
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
    """De-enroll biometric records and issue an Ed25519-signed evidence record.

    The signature protects canonical payload integrity and can be checked with the public
    key. Verifiers must pin the public key against an institutional trust record; the public
    key embedded in a certificate is not, by itself, a trust anchor. A valid signature does
    not prove remote media erasure: deletion is complete only when the storage provider
    confirms deletion of every requested object.
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
            qualification = "MEDIA_PROVIDER_DELETION_CONFIRMED"
        else:
            media_purged = False
            status_state = "DELETION_INCOMPLETE"
            qualification = "DELETION_INCOMPLETE"
    else:
        for mid in target_ids:
            media_outcomes[mid] = "NO_STORAGE_SERVICE_PROVIDED"
        status_state = "DELETION_INCOMPLETE"
        qualification = "STORAGE_SERVICE_REQUIRED_FOR_VERIFIED_DELETION"

    now_iso = datetime.now(timezone.utc).isoformat()
    certificate_payload = {
        "student_id": student_id,
        "person_id": student.person_id,
        "deleted_embeddings_count": deleted_embeddings_count,
        "operator_id": operator_id,
        "qualification": qualification,
        "issued_at": now_iso,
        "media_purged": media_purged,
        "media_deletion_details": media_outcomes,
    }
    canonical_payload = json.dumps(
        certificate_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    cert_hash = hashlib.sha256(canonical_payload).hexdigest()

    settings = get_settings()
    # Production signatures must always come from the private key provisioned at startup.
    # Internal callers cannot override the institutional signing identity.
    secret = settings.deletion_certificate_key if settings.is_production else (
        signing_key or settings.deletion_certificate_key
    )
    if not secret and not settings.is_production:
        # Stable development-only seed; never accepted as a production private key.
        secret = "frs-development-only-deletion-certificate-key-not-for-production"
    if not secret:
        raise RuntimeError("A dedicated biometric deletion-certificate signing key must be configured.")

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_pem_private_key,
    )

    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    if settings.is_production:
        try:
            private_key = load_pem_private_key(secret_bytes, password=None)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Production deletion-certificate key is not a valid PEM private key.") from exc
        if not isinstance(private_key, Ed25519PrivateKey):
            raise RuntimeError("Production deletion-certificate key must be Ed25519.")
    else:
        # Deterministic development keys preserve repeatable local tests while using the
        # same public-key signature format as production. This seed is never production-safe.
        private_key = Ed25519PrivateKey.from_private_bytes(hashlib.sha256(secret_bytes).digest())

    public_key_pem = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    public_key_sha256 = hashlib.sha256(public_key_pem.encode("ascii")).hexdigest()
    cert_signature = private_key.sign(canonical_payload).hex()
    certificate_assurance = (
        "ED25519_SIGNATURE_OVER_CANONICAL_PAYLOAD; VERIFY_WITH_AN_INSTITUTION-TRUSTED_PUBLIC_KEY; "
        "SIGNATURE_DOES_NOT_INDEPENDENTLY_PROVE_REMOTE_MEDIA_ERASURE"
    )

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
            "signature_algorithm": "Ed25519",
            "signature_public_key_sha256": public_key_sha256,
            "certificate_assurance": certificate_assurance,
            "signature_public_key_pem": public_key_pem,
            "certificate_payload": certificate_payload,
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
        # Compatibility alias retained; callers should use deletion_authentication_tag.
        "deletion_signature": cert_signature,
        "deletion_authentication_tag": cert_signature,
        "signed_certificate": {
            "certificate_id": f"cert-{cert_hash[:16]}",
            "digest": cert_hash,
            "payload": certificate_payload,
            "signature": cert_signature,
            "algorithm": "Ed25519",
            "assurance": certificate_assurance,
            "public_key_pem": public_key_pem,
            "public_key_sha256": public_key_sha256,
            "issuer": "FRS-Biometric-Privacy-Lifecycle",
            "qualification": qualification,
            "signed_at": now_iso,
        },
        "media_purged": media_purged,
        "media_deletion_details": media_outcomes,
        "timestamp": now_iso,
    }
