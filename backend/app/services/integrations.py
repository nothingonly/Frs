from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
import hashlib
import hmac
import io
import json
import logging
import smtplib
import socket
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    ClassEnrollment,
    ClassGroup,
    Department,
    Student,
)

logger = logging.getLogger("frs.integrations")


class CsvExportService:
    """Export standardized attendance records for registrar and campus SIS batch ingestion."""

    @staticmethod
    def export_attendance_csv(db: Session, session_id: str) -> str:
        session = db.get(AttendanceSession, session_id)
        if session is None:
            raise ValueError(f"Attendance session '{session_id}' not found.")

        group = db.get(ClassGroup, session.class_group_id)
        department = db.get(Department, group.department_id) if group else None

        # Fetch enrolled students
        enrollments = db.execute(
            select(Student, ClassEnrollment)
            .join(ClassEnrollment, Student.student_id == ClassEnrollment.student_id)
            .where(
                ClassEnrollment.class_group_id == session.class_group_id,
                ClassEnrollment.status == "ACTIVE",
            )
        ).all()

        # Fetch attendance events for this session
        events = db.execute(
            select(AttendanceEvent).where(AttendanceEvent.attendance_session_id == session_id)
        ).scalars().all()
        events_by_person = {e.person_id: e for e in events}

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Session ID",
            "Academic Year",
            "Department",
            "Section",
            "Student Number",
            "Full Name",
            "Attendance Status",
            "Punch Type",
            "Similarity Score",
            "Recorded At (UTC)",
        ])

        dept_code = department.code if department else "UNKNOWN"
        section_name = group.section if group else "UNKNOWN"
        acad_year = group.academic_year if group else "UNKNOWN"

        for student, _ in enrollments:
            event = events_by_person.get(student.person_id)
            status = "PRESENT" if event and event.similarity_score >= event.threshold else ("RECORDED" if event else "ABSENT")
            punch_type = event.punch_type if event else "N/A"
            score = f"{event.similarity_score:.3f}" if event and event.similarity_score is not None else "0.000"
            timestamp = event.timestamp.isoformat() if event else "N/A"

            writer.writerow([
                session_id,
                acad_year,
                dept_code,
                section_name,
                student.student_number,
                student.full_name,
                status,
                punch_type,
                score,
                timestamp,
            ])

        return output.getvalue()


class AbsenteeAlertService:
    """Identify absent students from closed sessions and generate notifications."""

    @staticmethod
    def find_absentees(db: Session, session_id: str) -> list[dict[str, str]]:
        session = db.get(AttendanceSession, session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found.")

        enrollments = db.execute(
            select(Student)
            .join(ClassEnrollment, Student.student_id == ClassEnrollment.student_id)
            .where(
                ClassEnrollment.class_group_id == session.class_group_id,
                ClassEnrollment.status == "ACTIVE",
            )
        ).scalars().all()

        attended_person_ids = set(
            db.execute(
                select(AttendanceEvent.person_id).where(
                    AttendanceEvent.attendance_session_id == session_id,
                    AttendanceEvent.similarity_score >= AttendanceEvent.threshold,
                )
            ).scalars().all()
        )

        absentees = []
        for s in enrollments:
            if s.person_id not in attended_person_ids:
                absentees.append({
                    "student_id": s.student_id,
                    "student_number": s.student_number,
                    "full_name": s.full_name,
                    "email": s.email or f"{s.student_number.lower()}@campus.edu",
                    "session_id": session_id,
                })
        return absentees

    @staticmethod
    def dispatch_mock_alerts(absentees: list[dict[str, str]]) -> dict[str, Any]:
        """Dispatch notifications using mock provider for testing and offline runs."""
        dispatched = []
        for a in absentees:
            dispatched.append({
                "recipient": a["student_number"],
                "message": f"Dear {a['full_name']}, you were marked absent for attendance session {a['session_id']}.",
                "status": "SENT_MOCK",
                "timestamp": int(time.time()),
            })
        return {
            "total_alerts": len(dispatched),
            "alerts": dispatched,
        }


class WebhookDispatcher:
    """HMAC-SHA256 signed outbound event webhooks for campus LMS / notification systems."""

    @staticmethod
    def sign_payload(payload_bytes: bytes, secret: str) -> str:
        return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    @classmethod
    def prepare_webhook_request(
        cls,
        event_type: str,
        data: dict[str, Any],
        secret: str,
        target_url: str,
    ) -> dict[str, Any]:
        payload_body = {
            "event_type": event_type,
            "timestamp": int(time.time()),
            "data": data,
        }
        body_bytes = json.dumps(payload_body, separators=(",", ":")).encode("utf-8")
        signature = cls.sign_payload(body_bytes, secret)

        headers = {
            "Content-Type": "application/json",
            "X-FRS-Signature": f"sha256={signature}",
            "X-FRS-Event": event_type,
            "User-Agent": "FRS-Webhook-Dispatcher/1.0",
        }

        return {
            "url": target_url,
            "headers": headers,
            "body": body_bytes.decode("utf-8"),
            "signature": signature,
        }

    @classmethod
    def dispatch(
        cls,
        prepared_request: dict[str, Any],
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Dispatch a prepared webhook request over HTTP with retry backoff."""
        import urllib.request
        import urllib.error

        url = prepared_request["url"]
        body_bytes = prepared_request["body"].encode("utf-8")
        headers = prepared_request.get("headers", {})

        req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
        last_error = ""
        now_ts = int(time.time())

        for attempt in range(1, max_retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    status_code = resp.getcode()
                    return {
                        "status": "DELIVERED",
                        "url": url,
                        "status_code": status_code,
                        "attempts": attempt,
                        "timestamp": now_ts,
                    }
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_error = str(exc)
                logger.warning("Webhook dispatch attempt %d failed for %s: %s", attempt, url, exc)
                time.sleep(0.1 * attempt)

        return {
            "status": "FAILED",
            "url": url,
            "error": last_error,
            "attempts": max_retries,
            "timestamp": now_ts,
        }


@dataclass
class NotificationMessage:
    recipient: str
    subject: str
    body: str
    channel: str = "email"
    metadata: dict[str, Any] | None = None


class BaseNotificationProvider:
    def send(self, message: NotificationMessage) -> dict[str, Any]:
        raise NotImplementedError


class SmtpEmailProvider(BaseNotificationProvider):
    def __init__(
        self,
        host: str = "",
        port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
        sender_email: str = "noreply@campus.edu",
        timeout: float = 10.0,
        mock_fallback: bool = True,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.sender_email = sender_email
        self.timeout = timeout
        self.mock_fallback = mock_fallback

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        now_ts = int(time.time())
        if not self.host or self.host == "mock" or (not self.username and self.mock_fallback):
            logger.info("SMTP host not configured or mock selected; operating in mock mode for %s", message.recipient)
            return {
                "status": "SENT_MOCK",
                "recipient": message.recipient,
                "channel": "email",
                "timestamp": now_ts,
                "provider": "smtp_mock",
            }

        msg = EmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = self.sender_email
        msg["To"] = message.recipient
        msg.set_content(message.body)

        last_error = ""
        for attempt in range(1, 4):
            try:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as server:
                    if self.use_tls:
                        server.starttls()
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.send_message(msg)
                return {
                    "status": "SENT",
                    "recipient": message.recipient,
                    "channel": "email",
                    "timestamp": now_ts,
                    "provider": "smtp",
                    "attempts": attempt,
                }
            except (smtplib.SMTPException, socket.error, OSError) as exc:
                last_error = str(exc)
                logger.warning("SMTP send attempt %d failed for %s: %s", attempt, message.recipient, exc)
                time.sleep(0.1 * attempt)

        if self.mock_fallback:
            return {
                "status": "FAILED_FALLBACK_MOCK",
                "recipient": message.recipient,
                "channel": "email",
                "error": last_error,
                "timestamp": now_ts,
                "provider": "smtp",
            }
        raise RuntimeError(f"SMTP send failed after 3 attempts: {last_error}")


class SmsNotificationProvider(BaseNotificationProvider):
    def __init__(
        self,
        api_url: str = "",
        auth_token: str = "",
        sender_id: str = "FRS",
        timeout: float = 10.0,
        mock_fallback: bool = True,
    ) -> None:
        self.api_url = api_url
        self.auth_token = auth_token
        self.sender_id = sender_id
        self.timeout = timeout
        self.mock_fallback = mock_fallback

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        now_ts = int(time.time())
        if not self.api_url or self.api_url == "mock" or (not self.auth_token and self.mock_fallback):
            logger.info("SMS gateway not configured or mock selected; operating in mock mode for %s", message.recipient)
            return {
                "status": "SENT_MOCK",
                "recipient": message.recipient,
                "channel": "sms",
                "timestamp": now_ts,
                "provider": "sms_mock",
            }

        # Real HTTP dispatch to configured SMS gateway
        import urllib.error
        import urllib.request

        payload = json.dumps({
            "to": message.recipient,
            "message": message.body,
            "sender_id": self.sender_id,
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "FRS-SMS-Dispatcher/1.0",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        req = urllib.request.Request(self.api_url, data=payload, headers=headers, method="POST")
        last_error = ""

        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    resp_body = resp.read().decode("utf-8")
                    return {
                        "status": "SENT",
                        "recipient": message.recipient,
                        "channel": "sms",
                        "timestamp": now_ts,
                        "provider": "sms_gateway",
                        "gateway_response": resp_body[:200],
                        "attempts": attempt,
                    }
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_error = str(exc)
                logger.warning("SMS gateway attempt %d failed for %s: %s", attempt, message.recipient, exc)
                time.sleep(0.1 * attempt)

        if self.mock_fallback:
            return {
                "status": "FAILED_FALLBACK_MOCK",
                "recipient": message.recipient,
                "channel": "sms",
                "error": last_error,
                "timestamp": now_ts,
                "provider": "sms_gateway",
            }
        raise RuntimeError(f"SMS send failed after 3 attempts: {last_error}")


class NotificationManager:
    """Orchestrates delivery across SMS and Email channels with fallback and batching."""

    def __init__(
        self,
        email_provider: BaseNotificationProvider | None = None,
        sms_provider: BaseNotificationProvider | None = None,
    ) -> None:
        self.email_provider = email_provider or SmtpEmailProvider()
        self.sms_provider = sms_provider or SmsNotificationProvider()

    def send_absentee_alert(
        self,
        student_name: str,
        student_number: str,
        session_id: str,
        channel: str = "email",
        contact_address: str | None = None,
    ) -> dict[str, Any]:
        recipient = contact_address or (f"{student_number.lower()}@campus.edu" if channel == "email" else student_number)
        subject = f"Attendance Notice - Session {session_id}"
        body = (
            f"Dear {student_name},\n\n"
            f"You have been recorded as ABSENT for attendance session '{session_id}'. "
            "If you believe this record is in error, please contact your department office within 48 hours.\n\n"
            "Face Recognition Attendance System (FRS)"
        )
        msg = NotificationMessage(recipient=recipient, subject=subject, body=body, channel=channel)
        provider = self.email_provider if channel == "email" else self.sms_provider
        return provider.send(msg)

    def dispatch_batch(self, absentees: list[dict[str, str]], channel: str = "email") -> dict[str, Any]:
        results = []
        for a in absentees:
            res = self.send_absentee_alert(
                student_name=a.get("full_name", "Student"),
                student_number=a.get("student_number", ""),
                session_id=a.get("session_id", ""),
                channel=channel,
                contact_address=a.get("email") if channel == "email" else a.get("phone"),
            )
            results.append(res)
        return {
            "total_alerts": len(results),
            "channel": channel,
            "alerts": results,
        }


class SftpExportService:
    """Generates standardized SIS attendance CSV files and dispatches to campus SFTP servers."""

    @staticmethod
    def prepare_export_package(db: Session, session_id: str) -> dict[str, Any]:
        csv_content = CsvExportService.export_attendance_csv(db, session_id)
        content_bytes = csv_content.encode("utf-8")
        checksum = hashlib.sha256(content_bytes).hexdigest()
        filename = f"attendance_session_{session_id}_{int(time.time())}.csv"
        return {
            "session_id": session_id,
            "filename": filename,
            "byte_count": len(content_bytes),
            "sha256_checksum": checksum,
            "csv_content": csv_content,
        }

    @classmethod
    def dispatch_sftp_export(
        cls,
        db: Session,
        session_id: str,
        sftp_host: str = "",
        sftp_port: int = 22,
        sftp_username: str = "",
        sftp_password: str = "",
        sftp_key_path: str = "",
        remote_path: str = "/uploads/attendance",
    ) -> dict[str, Any]:
        package = cls.prepare_export_package(db, session_id)
        is_live = bool(sftp_host and sftp_host != "mock" and sftp_username)
        if not is_live:
            return {
                "status": "STAGED_MOCK",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": f"{remote_path.rstrip('/')}/{package['filename']}",
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": sftp_host or "mock-sftp-host",
                "dispatched_at": int(time.time()),
            }

        dest_file = f"{remote_path.rstrip('/')}/{package['filename']}"
        now_ts = int(time.time())

        # Attempt live SFTP connection via paramiko if installed
        try:
            import paramiko  # type: ignore
            transport = paramiko.Transport((sftp_host, sftp_port))
            if sftp_key_path:
                key = paramiko.RSAKey.from_private_key_file(sftp_key_path)
                transport.connect(username=sftp_username, pkey=key)
            else:
                transport.connect(username=sftp_username, password=sftp_password)

            sftp = paramiko.SFTPClient.from_transport(transport)
            with io.BytesIO(package["csv_content"].encode("utf-8")) as fl:
                sftp.putfo(fl, dest_file)
            sftp.close()
            transport.close()

            return {
                "status": "DISPATCHED",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": dest_file,
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": sftp_host,
                "dispatched_at": now_ts,
            }
        except ImportError:
            logger.warning("paramiko not installed; staged SFTP package without live transfer.")
            return {
                "status": "STAGED_MOCK",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": dest_file,
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": sftp_host,
                "dispatched_at": now_ts,
                "note": "paramiko_not_installed",
            }
        except Exception as exc:
            logger.error("SFTP export failed for session %s: %s", session_id, exc)
            return {
                "status": "FAILED",
                "session_id": session_id,
                "filename": package["filename"],
                "error": str(exc),
                "sftp_host": sftp_host,
                "dispatched_at": now_ts,
            }


class LtiService:
    """LTI 1.3 Advantage integration for Canvas, Moodle, and Blackboard LMS platforms."""

    LTI_MESSAGE_TYPE_LAUNCH = "LtiResourceLinkRequest"
    LTI_VERSION = "1.3.0"

    @classmethod
    def validate_launch_claims(cls, claims: dict[str, Any], expected_client_id: str | None = None) -> dict[str, Any]:
        """Validate 1EdTech LTI 1.3 core launch claims."""
        if claims.get("https://purl.imsglobal.org/spec/lti/claim/message_type") != cls.LTI_MESSAGE_TYPE_LAUNCH:
            raise ValueError("Invalid LTI message_type; expected LtiResourceLinkRequest.")
        if claims.get("https://purl.imsglobal.org/spec/lti/claim/version") != cls.LTI_VERSION:
            raise ValueError(f"Unsupported LTI version; expected {cls.LTI_VERSION}.")

        aud = claims.get("aud")
        if expected_client_id:
            audiences = [aud] if isinstance(aud, str) else (aud or [])
            if expected_client_id not in audiences:
                raise ValueError("LTI token audience does not match expected client_id.")

        sub = claims.get("sub")
        if not sub:
            raise ValueError("LTI token missing mandatory subject ('sub') claim.")

        context = claims.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
        resource_link = claims.get("https://purl.imsglobal.org/spec/lti/claim/resource_link", {})
        roles = claims.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])

        return {
            "is_valid": True,
            "user_id": sub,
            "roles": roles,
            "course_id": context.get("id"),
            "course_title": context.get("title"),
            "resource_link_id": resource_link.get("id"),
            "deployment_id": claims.get("https://purl.imsglobal.org/spec/lti/claim/deployment_id"),
        }

    @staticmethod
    def format_ags_outcome(
        sourcedid: str,
        score: float,
        max_score: float = 1.0,
        comment: str = "FRS Automated Attendance",
    ) -> dict[str, Any]:
        """Format 1EdTech LTI Assignment and Grade Services (AGS) lineitem outcome."""
        if not 0.0 <= score <= max_score:
            raise ValueError(f"Score {score} out of bounds [0.0, {max_score}]")
        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "timestamp": now_iso,
            "scoreGiven": score,
            "scoreMaximum": max_score,
            "comment": comment,
            "activityProgress": "Completed",
            "gradingProgress": "FullyGraded",
            "userId": sourcedid,
        }
