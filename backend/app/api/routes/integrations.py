from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import (
    ROLE_DEAN,
    ROLE_FACULTY,
    TokenClaims,
    check_class_access,
    check_department_access,
    scoped_actor,
    scoped_admin,
)
from app.core.config import get_settings
from app.database import get_db
from app.db.entities import AttendanceSession, ClassGroup, LtiLaunchNonce, LtiNonceUse
from app.services.integrations import (
    AbsenteeAlertService,
    LtiService,
    NotificationManager,
    SftpExportService,
    SmsNotificationProvider,
    SmtpEmailProvider,
)

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


class AbsenteeAlertRequest(BaseModel):
    session_id: str
    channel: str = Field(default="email", pattern="^(email|sms)$")
    dry_run: bool = False


class SftpExportRequest(BaseModel):
    session_id: str
    remote_path: str | None = None
    sftp_host_key_fingerprint: str | None = None


class LtiLaunchValidationRequest(BaseModel):
    id_token: str | None = None
    claims: dict[str, Any] | None = None
    expected_client_id: str | None = None
    expected_deployment_id: str | None = None
    expected_issuer: str | None = None
    signing_key_or_secret: str | None = None
    nonce: str | None = None


class LtiAgsPassbackRequest(BaseModel):
    sourcedid: str
    score: float = Field(ge=0.0, le=1.0)
    comment: str = "FRS attendance passback"


@router.post("/notifications/absentees")
def dispatch_session_absentee_alerts(
    payload: AbsenteeAlertRequest,
    actor: Annotated[TokenClaims, Depends(scoped_actor)],
    db: Annotated[Session, Depends(get_db)],
):
    """Identify absentees for a session and dispatch email or SMS notifications with retries."""
    sess = db.get(AttendanceSession, payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Attendance session '{payload.session_id}' not found.")

    if actor.role == ROLE_FACULTY:
        check_class_access(actor, sess.class_group_id)
    elif actor.role == ROLE_DEAN:
        cg = db.get(ClassGroup, sess.class_group_id)
        if cg:
            check_department_access(actor, cg.department_id)

    try:
        absentees = AbsenteeAlertService.find_absentees(db, payload.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    if payload.dry_run:
        return {
            "session_id": payload.session_id,
            "dry_run": True,
            "channel": payload.channel,
            "absentees_count": len(absentees),
            "absentees": absentees,
        }

    settings = get_settings()
    email_provider = SmtpEmailProvider(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        sender_email=settings.smtp_sender_email,
        mock_fallback=not settings.is_production,
    )
    sms_provider = SmsNotificationProvider(
        api_url=settings.sms_gateway_url,
        auth_token=settings.sms_auth_token,
        sender_id=settings.sms_sender_id,
        mock_fallback=not settings.is_production,
    )
    manager = NotificationManager(email_provider=email_provider, sms_provider=sms_provider)
    dispatch_summary = manager.dispatch_batch(absentees, channel=payload.channel)
    return {
        "session_id": payload.session_id,
        "dry_run": False,
        "summary": dispatch_summary,
    }


@router.post("/sftp/export")
def trigger_sftp_attendance_export(
    payload: SftpExportRequest,
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Generate standardized SIS attendance CSV and stage/dispatch it via SFTP with host key verification."""
    sess = db.get(AttendanceSession, payload.session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail=f"Attendance session '{payload.session_id}' not found.")

    if actor.role == ROLE_DEAN:
        cg = db.get(ClassGroup, sess.class_group_id)
        if cg:
            check_department_access(actor, cg.department_id)

    settings = get_settings()
    remote_path = payload.remote_path or settings.sftp_remote_path
    try:
        result = SftpExportService.dispatch_sftp_export(
            db=db,
            session_id=payload.session_id,
            sftp_host=settings.sftp_host,
            sftp_port=settings.sftp_port,
            sftp_username=settings.sftp_username,
            sftp_password=settings.sftp_password,
            sftp_key_path=settings.sftp_key_path,
            sftp_host_key_fingerprint=payload.sftp_host_key_fingerprint or settings.sftp_host_key_fingerprint,
            sftp_known_hosts_file=settings.sftp_known_hosts_file,
            remote_path=remote_path,
        )
        if result.get("status") == "REJECTED_HOST_KEY_MISMATCH":
            raise HTTPException(status_code=422, detail=result.get("error", "SFTP host key verification rejected."))
        return result
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/lti/launch/nonce", status_code=201)
def issue_lti_launch_nonce(
    actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Issue a short-lived server nonce to include in an LMS OIDC authorization request."""
    settings = get_settings()
    if settings.is_production and not (
        settings.lti_client_id.strip()
        and settings.lti_issuer.strip()
        and settings.lti_deployment_id.strip()
        and settings.lti_platform_public_key_pem.strip()
    ):
        raise HTTPException(
            status_code=503,
            detail="Production LTI issuer, client ID, deployment ID and trusted public key must be configured.",
        )

    now = datetime.now(timezone.utc)
    nonce = secrets.token_urlsafe(32)
    challenge = LtiLaunchNonce(
        nonce=nonce,
        issued_by=actor.email or actor.sub,
        issued_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    db.add(challenge)
    db.commit()
    return {
        "nonce": nonce,
        "issued_at": now.isoformat(),
        "expires_at": challenge.expires_at.isoformat(),
        "expires_in_seconds": 300,
    }


@router.post("/lti/launch/validate")
def validate_lti_launch(
    payload: LtiLaunchValidationRequest,
    _actor: Annotated[TokenClaims, Depends(scoped_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    """Validate incoming 1EdTech LTI 1.3 launch token or claims for Canvas/Moodle LMS integration."""
    settings = get_settings()
    if settings.is_production:
        if payload.signing_key_or_secret:
            raise HTTPException(
                status_code=422,
                detail="Request-supplied signing keys or secrets are forbidden in production. Verification must use server-configured LMS platform keys.",
            )
        expected_client_id = settings.lti_client_id or None
        expected_issuer = settings.lti_issuer or None
        expected_deployment = settings.lti_deployment_id or None
    else:
        expected_client_id = payload.expected_client_id or (settings.lti_client_id if settings.lti_client_id else None)
        expected_issuer = payload.expected_issuer or (settings.lti_issuer if settings.lti_issuer else None)
        expected_deployment = payload.expected_deployment_id or (settings.lti_deployment_id if settings.lti_deployment_id else None)

    if payload.id_token:
        if settings.is_production:
            if not settings.lti_platform_public_key_pem.strip():
                raise HTTPException(status_code=503, detail="Trusted LMS platform verification key is not configured.")
            if not payload.nonce:
                raise HTTPException(status_code=422, detail="Production LTI launch requires a server-initiated nonce.")
            nonce_challenge = db.execute(
                select(LtiLaunchNonce)
                .where(
                    LtiLaunchNonce.nonce == payload.nonce,
                    LtiLaunchNonce.consumed_at.is_(None),
                    LtiLaunchNonce.expires_at > datetime.now(timezone.utc),
                )
                .with_for_update()
            ).scalar_one_or_none()
            if nonce_challenge is None:
                raise HTTPException(
                    status_code=409,
                    detail="LTI nonce was not issued by this server, has expired, or was already consumed.",
                )
            if not expected_client_id or not expected_issuer or not expected_deployment:
                raise HTTPException(status_code=503, detail="Production LTI issuer, client ID, and deployment ID must be configured.")
            secret_or_key = settings.lti_platform_public_key_pem
        else:
            secret_or_key = payload.signing_key_or_secret or settings.lti_platform_public_key_pem or settings.effective_jwt_secret
        try:
            verified = LtiService.validate_launch_id_token(
                id_token=payload.id_token,
                signing_key_or_secret=secret_or_key,
                expected_issuer=expected_issuer,
                expected_client_id=expected_client_id,
                expected_deployment_id=expected_deployment,
                expected_nonce=payload.nonce,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if settings.is_production:
            nonce = verified.get("nonce")
            if not isinstance(nonce, str) or not nonce:
                raise HTTPException(status_code=422, detail="Verified LTI ID token does not contain a nonce.")
            # Consume the server-issued challenge and record token replay evidence atomically.
            nonce_challenge.consumed_at = datetime.now(timezone.utc)
            db.add(LtiNonceUse(
                nonce=nonce,
                token_sha256=hashlib.sha256(payload.id_token.encode("utf-8")).hexdigest(),
            ))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail="LTI nonce has already been consumed; launch replay rejected.") from exc
        return verified

    if payload.claims:
        if settings.is_production:
            raise HTTPException(
                status_code=422,
                detail="Production environment requires cryptographically signed id_token for LTI launch validation. Plain claim dictionaries are forbidden.",
            )
        try:
            return LtiService.validate_launch_claims(payload.claims, expected_client_id=expected_client_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    raise HTTPException(status_code=422, detail="Either 'id_token' or 'claims' must be provided.")


@router.post("/lti/ags/passback")
def format_lti_ags_passback(
    payload: LtiAgsPassbackRequest,
    _actor: Annotated[TokenClaims, Depends(scoped_admin)],
):
    """Format and prepare an LTI 1.3 Assignment and Grade Services (AGS) lineitem outcome."""
    try:
        return LtiService.format_ags_outcome(
            sourcedid=payload.sourcedid,
            score=payload.score,
            comment=payload.comment,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
