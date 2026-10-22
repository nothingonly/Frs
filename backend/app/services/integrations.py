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

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.auth import _b64url_decode, _b64url_encode
from app.core.config import get_settings
from app.db.entities import (
    AttendanceEvent,
    AttendanceSession,
    ClassEnrollment,
    ClassGroup,
    Department,
    SessionClassGroup,
    Student,
)

logger = logging.getLogger("frs.integrations")

MANUAL_ATTENDANCE_PIPELINES = (
    "manual-administrative-entry",
    "manual-administrative-review",
)


def _session_class_group_ids(db: Session, session: AttendanceSession) -> tuple[str, ...]:
    """Return every distinct class group attached to a specific or mixed session."""
    linked = db.execute(
        select(SessionClassGroup.class_group_id).where(
            SessionClassGroup.session_id == session.session_id
        )
    ).scalars().all()
    return tuple(dict.fromkeys([session.class_group_id, *linked]))


class CsvExportService:
    """Export standardized attendance records for registrar and campus SIS batch ingestion."""

    @staticmethod
    def export_attendance_csv(db: Session, session_id: str) -> str:
        session = db.get(AttendanceSession, session_id)
        if session is None:
            raise ValueError(f"Attendance session '{session_id}' not found.")

        # Mixed sessions may span several departments/sections. Keep each student's actual
        # membership metadata instead of incorrectly labeling every row as the primary group.
        group_ids = _session_class_group_ids(db, session)
        enrollment_rows = db.execute(
            select(Student, ClassGroup, Department)
            .join(ClassEnrollment, Student.student_id == ClassEnrollment.student_id)
            .join(ClassGroup, ClassGroup.class_group_id == ClassEnrollment.class_group_id)
            .join(Department, Department.department_id == ClassGroup.department_id)
            .where(
                ClassEnrollment.class_group_id.in_(group_ids),
                ClassEnrollment.status == "ACTIVE",
            )
            .order_by(Student.student_number, Department.code, ClassGroup.section)
        ).all()

        enrollments: dict[str, dict[str, Any]] = {}
        for student, class_group, department in enrollment_rows:
            record = enrollments.setdefault(
                student.student_id,
                {"student": student, "groups": [], "departments": []},
            )
            record["groups"].append(class_group)
            record["departments"].append(department.code)

        events = db.execute(
            select(AttendanceEvent).where(AttendanceEvent.attendance_session_id == session_id)
        ).scalars().all()
        events_by_person: dict[str, AttendanceEvent] = {}
        for event in events:
            previous = events_by_person.get(event.person_id)
            if previous is None:
                events_by_person[event.person_id] = event
                continue
            event_is_match = (
                event.pipeline_version in MANUAL_ATTENDANCE_PIPELINES
                or (event.similarity_score is not None and event.similarity_score >= event.threshold)
            )
            previous_is_match = (
                previous.pipeline_version in MANUAL_ATTENDANCE_PIPELINES
                or (previous.similarity_score is not None and previous.similarity_score >= previous.threshold)
            )
            if (event_is_match and not previous_is_match) or (
                event_is_match == previous_is_match and event.similarity_score > previous.similarity_score
            ):
                events_by_person[event.person_id] = event

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

        for record in enrollments.values():
            student = record["student"]
            groups = record["groups"]
            event = events_by_person.get(student.person_id)
            is_present = bool(
                event and (
                    event.pipeline_version in MANUAL_ATTENDANCE_PIPELINES
                    or (event.similarity_score is not None and event.similarity_score >= event.threshold)
                )
            )
            status = "PRESENT" if is_present else ("RECORDED" if event else "ABSENT")
            punch_type = event.punch_type if event else "N/A"
            score = (
                "N/A"
                if event and event.pipeline_version in MANUAL_ATTENDANCE_PIPELINES
                else f"{event.similarity_score:.3f}"
                if event and event.similarity_score is not None
                else "0.000"
            )
            timestamp = event.timestamp.isoformat() if event else "N/A"
            acad_years = sorted({item.academic_year for item in groups})
            departments = sorted(set(record["departments"]))
            sections = sorted({item.section for item in groups})

            writer.writerow([
                session_id,
                ", ".join(acad_years),
                ", ".join(departments),
                ", ".join(sections),
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
        if session.status != "CLOSED":
            raise ValueError(f"Attendance session '{session_id}' must be closed before calculating absentees.")

        group_ids = _session_class_group_ids(db, session)
        enrollments = db.execute(
            select(Student)
            .join(ClassEnrollment, Student.student_id == ClassEnrollment.student_id)
            .where(
                ClassEnrollment.class_group_id.in_(group_ids),
                ClassEnrollment.status == "ACTIVE",
            )
        ).scalars().unique().all()

        attended_person_ids = set(
            db.execute(
                select(AttendanceEvent.person_id).where(
                    AttendanceEvent.attendance_session_id == session_id,
                    or_(
                        AttendanceEvent.similarity_score >= AttendanceEvent.threshold,
                        AttendanceEvent.pipeline_version.in_(MANUAL_ATTENDANCE_PIPELINES),
                    ),
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
                    # Never synthesize a recipient address. Missing contact information must
                    # result in a visible skipped delivery, not a guessed destination.
                    "email": (s.email or "").strip(),
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
        mock_fallback: bool | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.sender_email = sender_email
        self.timeout = timeout
        settings = get_settings()
        if mock_fallback is None:
            self.mock_fallback = not settings.is_production
        else:
            self.mock_fallback = False if settings.is_production else mock_fallback

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        now_ts = int(time.time())
        settings = get_settings()
        if not self.host or self.host == "mock" or (not self.username and self.mock_fallback):
            if settings.is_production:
                logger.error("SMTP provider is unconfigured in production environment; mock delivery is forbidden.")
                return {
                    "status": "FAILED",
                    "error": "SMTP provider is unconfigured; mock delivery is forbidden in production.",
                    "recipient": message.recipient,
                    "channel": "email",
                    "timestamp": now_ts,
                    "provider": "smtp",
                }
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

        if self.mock_fallback and not settings.is_production:
            return {
                "status": "FAILED_FALLBACK_MOCK",
                "recipient": message.recipient,
                "channel": "email",
                "error": last_error,
                "timestamp": now_ts,
                "provider": "smtp",
            }
        return {
            "status": "FAILED",
            "recipient": message.recipient,
            "channel": "email",
            "error": last_error,
            "timestamp": now_ts,
            "provider": "smtp",
        }


class SmsNotificationProvider(BaseNotificationProvider):
    def __init__(
        self,
        api_url: str = "",
        auth_token: str = "",
        sender_id: str = "FRS",
        timeout: float = 10.0,
        mock_fallback: bool | None = None,
    ) -> None:
        self.api_url = api_url
        self.auth_token = auth_token
        self.sender_id = sender_id
        self.timeout = timeout
        settings = get_settings()
        if mock_fallback is None:
            self.mock_fallback = not settings.is_production
        else:
            self.mock_fallback = False if settings.is_production else mock_fallback

    def send(self, message: NotificationMessage) -> dict[str, Any]:
        now_ts = int(time.time())
        settings = get_settings()
        if not self.api_url or self.api_url == "mock" or (not self.auth_token and self.mock_fallback):
            if settings.is_production:
                logger.error("SMS gateway is unconfigured in production environment; mock delivery is forbidden.")
                return {
                    "status": "FAILED",
                    "error": "SMS gateway is unconfigured; mock delivery is forbidden in production.",
                    "recipient": message.recipient,
                    "channel": "sms",
                    "timestamp": now_ts,
                    "provider": "sms_gateway",
                }
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

        if self.mock_fallback and not settings.is_production:
            return {
                "status": "FAILED_FALLBACK_MOCK",
                "recipient": message.recipient,
                "channel": "sms",
                "error": last_error,
                "timestamp": now_ts,
                "provider": "sms_gateway",
            }
        return {
            "status": "FAILED",
            "recipient": message.recipient,
            "channel": "sms",
            "error": last_error,
            "timestamp": now_ts,
            "provider": "sms_gateway",
        }


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
        recipient = (contact_address or "").strip()
        if not recipient:
            return {
                "status": "SKIPPED_NO_VERIFIED_CONTACT",
                "recipient": "",
                "channel": channel,
                "reason": "No contact address was supplied for this student.",
                "timestamp": int(time.time()),
            }
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
        sent_count = 0
        mocked_count = 0
        failed_count = 0
        skipped_count = 0
        for a in absentees:
            res = self.send_absentee_alert(
                student_name=a.get("full_name", "Student"),
                student_number=a.get("student_number", ""),
                session_id=a.get("session_id", ""),
                channel=channel,
                contact_address=a.get("email") if channel == "email" else a.get("phone"),
            )
            results.append(res)
            st = res.get("status")
            if st == "SENT":
                sent_count += 1
            elif st in ("SENT_MOCK", "FAILED_FALLBACK_MOCK"):
                mocked_count += 1
            elif st == "SKIPPED_NO_VERIFIED_CONTACT":
                skipped_count += 1
            else:
                failed_count += 1

        return {
            "total_alerts": len(results),
            "sent_count": sent_count,
            "mocked_count": mocked_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
            "is_mock": bool(mocked_count > 0 and sent_count == 0 and skipped_count == 0),
            "channel": channel,
            "alerts": results,
        }


class SftpSecurityError(RuntimeError):
    """Raised when remote SFTP server identity cannot be verified or host key fails check."""
    pass


class SftpExportService:
    """Generates standardized SIS attendance CSV files and dispatches to campus SFTP servers."""

    @staticmethod
    def prepare_export_package(db: Session, session_id: str) -> dict[str, Any]:
        session = db.get(AttendanceSession, session_id)
        if session is None:
            raise ValueError(f"Attendance session '{session_id}' not found.")
        if session.status != "CLOSED":
            raise ValueError(f"Attendance session '{session_id}' must be closed before SIS export.")
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
        sftp_host_key_fingerprint: str = "",
        sftp_known_hosts_file: str = "",
        remote_path: str = "/uploads/attendance",
    ) -> dict[str, Any]:
        package = cls.prepare_export_package(db, session_id)
        settings = get_settings()
        host = sftp_host or settings.sftp_host
        user = sftp_username or settings.sftp_username
        is_live = bool(host and host != "mock" and user)
        if not is_live:
            return {
                "status": "STAGED_MOCK",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": f"{remote_path.rstrip('/')}/{package['filename']}",
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": host or "mock-sftp-host",
                "dispatched_at": int(time.time()),
            }

        dest_file = f"{remote_path.rstrip('/')}/{package['filename']}"
        now_ts = int(time.time())
        transport = None
        sftp = None

        # Attempt live SFTP connection via paramiko with strict host key verification
        try:
            import paramiko  # type: ignore

            transport = paramiko.Transport((host, sftp_port))
            transport.start_client(timeout=10.0)

            remote_key = transport.get_remote_server_key()
            if remote_key is None:
                raise SftpSecurityError(f"SFTP remote server {host} presented no host key.")

            server_fingerprint = hashlib.sha256(remote_key.asbytes()).hexdigest()
            expected_fp = sftp_host_key_fingerprint or settings.sftp_host_key_fingerprint
            known_hosts_path = sftp_known_hosts_file or settings.sftp_known_hosts_file

            if expected_fp:
                clean_exp = expected_fp.lower().replace(":", "").replace("sha256=", "").strip()
                clean_act = server_fingerprint.lower().replace(":", "").replace("sha256=", "").strip()
                if clean_exp != clean_act:
                    raise SftpSecurityError(
                        f"SFTP host key fingerprint mismatch for {host}! "
                        f"Expected {expected_fp}, remote presented {server_fingerprint}. Transfer aborted."
                    )
            elif known_hosts_path:
                host_keys = paramiko.util.load_host_keys(known_hosts_path)
                if host not in host_keys:
                    raise SftpSecurityError(f"SFTP host {host} not in known_hosts file {known_hosts_path}. Transfer aborted.")
                if remote_key != host_keys[host].get(remote_key.get_name()):
                    raise SftpSecurityError(f"SFTP host key for {host} does not match known_hosts entry! Transfer aborted.")
            elif settings.is_production:
                raise SftpSecurityError("Production requires SFTP host key pinning via sftp_host_key_fingerprint or sftp_known_hosts_file.")

            # Authenticate client credentials
            key_path = sftp_key_path or settings.sftp_key_path
            password = sftp_password or settings.sftp_password
            if key_path:
                key = paramiko.RSAKey.from_private_key_file(key_path)
                transport.auth_publickey(username=user, key=key)
            else:
                transport.auth_password(username=user, password=password)

            if not transport.is_authenticated():
                raise PermissionError(f"SFTP authentication failed for user {user} on {host}")

            sftp = paramiko.SFTPClient.from_transport(transport)
            with io.BytesIO(package["csv_content"].encode("utf-8")) as fl:
                sftp.putfo(fl, dest_file)

            return {
                "status": "DISPATCHED",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": dest_file,
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": host,
                "server_host_key_fingerprint": server_fingerprint,
                "dispatched_at": now_ts,
            }
        except ImportError as imp_err:
            if settings.is_production:
                logger.error("paramiko is not installed; live SFTP export cannot execute in production.")
                raise RuntimeError("Production requires paramiko for live SFTP exports.") from imp_err
            logger.warning("paramiko not installed; staged SFTP package without live transfer.")
            return {
                "status": "STAGED_MOCK",
                "session_id": session_id,
                "filename": package["filename"],
                "remote_path": dest_file,
                "byte_count": package["byte_count"],
                "sha256_checksum": package["sha256_checksum"],
                "sftp_host": host,
                "dispatched_at": now_ts,
                "note": "paramiko_not_installed",
            }
        except SftpSecurityError as sec_err:
            logger.error("SFTP host key verification rejected for %s: %s", host, sec_err)
            return {
                "status": "REJECTED_HOST_KEY_MISMATCH",
                "session_id": session_id,
                "filename": package["filename"],
                "error": str(sec_err),
                "sftp_host": host,
                "dispatched_at": now_ts,
            }
        except Exception as exc:
            logger.error("SFTP export failed for session %s: %s", session_id, exc)
            return {
                "status": "FAILED",
                "session_id": session_id,
                "filename": package["filename"],
                "error": "SFTP transfer failed. Check endpoint, credentials, or network.",
                "sftp_host": host,
                "dispatched_at": now_ts,
            }
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass


class LtiService:
    """LTI 1.3 Advantage integration for Canvas, Moodle, and Blackboard LMS platforms."""

    LTI_MESSAGE_TYPE_LAUNCH = "LtiResourceLinkRequest"
    LTI_VERSION = "1.3.0"

    @classmethod
    def validate_launch_id_token(
        cls,
        id_token: str,
        signing_key_or_secret: str | bytes | None = None,
        expected_issuer: str | None = None,
        expected_client_id: str | None = None,
        expected_deployment_id: str | None = None,
        expected_nonce: str | None = None,
        leeway_seconds: int = 60,
    ) -> dict[str, Any]:
        """Cryptographically verify and parse a 1EdTech LTI 1.3 / OIDC signed ID token (JWT)."""
        if not id_token or not isinstance(id_token, str):
            raise ValueError("Missing or invalid LTI ID token.")

        parts = id_token.strip().split(".")
        if len(parts) != 3:
            raise ValueError("Malformed LTI ID token: expected 3 dot-separated JWT segments.")

        try:
            header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
            payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
            signature = _b64url_decode(parts[2])
        except Exception as exc:
            raise ValueError(f"Failed to decode LTI token segments: {exc}") from exc

        alg = header.get("alg", "HS256")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")

        # Signature verification
        settings = get_settings()
        key = signing_key_or_secret
        if key is None and alg == "RS256" and settings:
            key = settings.lti_platform_public_key_pem or None
        if key is None and alg == "HS256" and settings and not settings.is_production:
            key = settings.effective_jwt_secret or None
        if not key:
            raise ValueError("LTI token verification refused: no trusted platform key configured.")
        if settings and settings.is_production and alg != "RS256":
            raise ValueError("Production LTI 1.3 launches must use RS256 platform signatures.")

        if alg == "HS256":
            key_bytes = key.encode("utf-8") if isinstance(key, str) else key
            expected_sig = hmac.new(key_bytes, signing_input, hashlib.sha256).digest()
            if not hmac.compare_digest(expected_sig, signature):
                raise ValueError("Invalid LTI token HMAC signature.")
        elif alg == "RS256":
            try:
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.asymmetric import padding
                from cryptography.hazmat.primitives.serialization import load_pem_public_key

                pem_key = key.encode("utf-8") if isinstance(key, str) else key
                pub_key = load_pem_public_key(pem_key)
                pub_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            except Exception as exc:
                raise ValueError(f"Invalid LTI token RSA signature: {exc}") from exc
        else:
            raise ValueError(f"Unsupported LTI signing algorithm: {alg}")

        # Temporal bounds verification
        now = int(time.time())
        exp = payload.get("exp")
        if exp is None:
            raise ValueError("LTI token missing mandatory expiration ('exp') claim.")
        if exp + leeway_seconds < now:
            raise ValueError(f"LTI token has expired (exp={exp}, now={now}).")

        iat = payload.get("iat")
        if iat is not None and (iat - leeway_seconds) > now:
            raise ValueError("LTI token was issued in the future.")

        # Protocol claims verification
        if expected_issuer:
            iss = payload.get("iss")
            if iss != expected_issuer:
                raise ValueError(f"LTI token issuer mismatch: expected '{expected_issuer}', got '{iss}'.")

        aud = payload.get("aud")
        if expected_client_id:
            audiences = [aud] if isinstance(aud, str) else (aud or [])
            if expected_client_id not in audiences:
                raise ValueError(f"LTI token audience does not match expected client_id: '{expected_client_id}'.")

        sub = payload.get("sub")
        if not sub:
            raise ValueError("LTI token missing mandatory subject ('sub') claim.")

        if expected_nonce:
            token_nonce = payload.get("nonce")
            if token_nonce != expected_nonce:
                raise ValueError("LTI token nonce mismatch; possible replay attempt.")

        deployment_id = payload.get("https://purl.imsglobal.org/spec/lti/claim/deployment_id")
        if expected_deployment_id and deployment_id != expected_deployment_id:
            raise ValueError(f"LTI token deployment_id mismatch: expected '{expected_deployment_id}', got '{deployment_id}'.")

        if payload.get("https://purl.imsglobal.org/spec/lti/claim/message_type") != cls.LTI_MESSAGE_TYPE_LAUNCH:
            raise ValueError("Invalid LTI message_type; expected LtiResourceLinkRequest.")

        if payload.get("https://purl.imsglobal.org/spec/lti/claim/version") != cls.LTI_VERSION:
            raise ValueError(f"Unsupported LTI version; expected {cls.LTI_VERSION}.")

        context = payload.get("https://purl.imsglobal.org/spec/lti/claim/context", {})
        resource_link = payload.get("https://purl.imsglobal.org/spec/lti/claim/resource_link", {})
        roles = payload.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])

        return {
            "is_valid": True,
            "cryptographically_verified": True,
            "user_id": sub,
            "issuer": payload.get("iss"),
            "audience": aud,
            "deployment_id": deployment_id,
            "roles": roles,
            "course_id": context.get("id"),
            "course_title": context.get("title"),
            "resource_link_id": resource_link.get("id"),
            "nonce": payload.get("nonce"),
            "jti": payload.get("jti"),
            "verified_at": now,
        }

    @classmethod
    def create_launch_token(
        cls,
        sub: str,
        secret: str,
        client_id: str = "canvas-client-123",
        issuer: str = "https://canvas.instructure.com",
        deployment_id: str = "dep-1",
        nonce: str = "nonce-xyz",
        expires_delta_seconds: int = 3600,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        """Create a signed HS256 LTI 1.3 launch token for testing and simulation."""
        now = int(time.time())
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": issuer,
            "aud": client_id,
            "sub": sub,
            "exp": now + expires_delta_seconds,
            "iat": now,
            "nonce": nonce,
            "https://purl.imsglobal.org/spec/lti/claim/message_type": cls.LTI_MESSAGE_TYPE_LAUNCH,
            "https://purl.imsglobal.org/spec/lti/claim/version": cls.LTI_VERSION,
            "https://purl.imsglobal.org/spec/lti/claim/deployment_id": deployment_id,
            "https://purl.imsglobal.org/spec/lti/claim/context": {"id": "course-101", "title": "Intro to AI"},
            "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"id": "link-1"},
            "https://purl.imsglobal.org/spec/lti/claim/roles": [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"
            ],
        }
        if extra_claims:
            payload.update(extra_claims)
        hdr_b64 = _b64url_encode(json.dumps(header).encode("utf-8"))
        payload_b64 = _b64url_encode(json.dumps(payload).encode("utf-8"))
        signing_input = f"{hdr_b64}.{payload_b64}".encode("ascii")
        sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{hdr_b64}.{payload_b64}.{_b64url_encode(sig)}"

    @classmethod
    def validate_launch_claims(cls, claims: dict[str, Any], expected_client_id: str | None = None) -> dict[str, Any]:
        """Validate 1EdTech LTI 1.3 claim dictionary structure (non-cryptographic shape check)."""
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
            "cryptographically_verified": False,
            "warning": "UNVERIFIED_CLAIM_DICTIONARY_ONLY",
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
