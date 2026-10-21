from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
from app.db.entities import AttendanceSession, ClassGroup
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


@router.post("/lti/launch/validate")
def validate_lti_launch(
    payload: LtiLaunchValidationRequest,
    _actor: Annotated[TokenClaims, Depends(scoped_admin)],
):
    """Validate incoming 1EdTech LTI 1.3 launch token or claims for Canvas/Moodle LMS integration."""
    settings = get_settings()
    expected_client_id = payload.expected_client_id or (settings.lti_client_id if settings.lti_client_id else None)
    expected_issuer = payload.expected_issuer or (settings.lti_issuer if settings.lti_issuer else None)
    expected_deployment = payload.expected_deployment_id or (settings.lti_deployment_id if settings.lti_deployment_id else None)

    if payload.id_token:
        secret_or_key = payload.signing_key_or_secret or settings.effective_jwt_secret
        try:
            return LtiService.validate_launch_id_token(
                id_token=payload.id_token,
                signing_key_or_secret=secret_or_key,
                expected_issuer=expected_issuer,
                expected_client_id=expected_client_id,
                expected_deployment_id=expected_deployment,
                expected_nonce=payload.nonce,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

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
