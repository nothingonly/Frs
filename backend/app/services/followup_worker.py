from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.metrics import get_metrics
from app.database import SessionLocal, create_schema
from app.db.entities import AttendanceEvent, AttendanceSession, AuditEvent, ClassEnrollment
from app.services.integrations import (
    AbsenteeAlertService,
    NotificationManager,
    SftpExportService,
    SmsNotificationProvider,
    SmtpEmailProvider,
)

setup_logging()
logger = logging.getLogger("frs.followup_worker")


class AttendanceFollowupDaemon:
    """Automated attendance follow-up, absentee alerting, and institutional reconciliation worker."""

    def __init__(self, interval_seconds: float = 300.0, channel: str = "email") -> None:
        self.interval_seconds = interval_seconds
        self.channel = channel
        self._shutdown_requested = False

    def request_shutdown(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.info("Follow-up worker shutdown signal received (%s); exiting...", sig_name)
        self._shutdown_requested = True

    @staticmethod
    def get_unreconciled_closed_sessions(db: Session, limit: int = 20) -> list[AttendanceSession]:
        """Find closed attendance sessions that have not yet undergone follow-up reconciliation."""
        reconciled_subquery = (
            select(AuditEvent.session_id)
            .where(AuditEvent.action == "attendance.followup_reconciled")
        )

        statement = (
            select(AttendanceSession)
            .where(
                AttendanceSession.status == "CLOSED",
                AttendanceSession.session_id.not_in(reconciled_subquery),
            )
            .order_by(AttendanceSession.starts_at.asc())
            .limit(limit)
        )
        return list(db.execute(statement).scalars().all())

    def reconcile_session(self, db: Session, session: AttendanceSession) -> dict[str, Any]:
        """Perform reconciliation, absentee notification, and optional SFTP export for a closed session."""
        session_id = session.session_id
        logger.info("Reconciling attendance follow-up for closed session '%s'...", session_id)

        # 1. Total active enrollments
        total_enrolled = len(
            db.execute(
                select(ClassEnrollment).where(
                    ClassEnrollment.class_group_id == session.class_group_id,
                    ClassEnrollment.status == "ACTIVE",
                )
            ).scalars().all()
        )

        # 2. Present events
        present_count = len(
            db.execute(
                select(AttendanceEvent).where(
                    AttendanceEvent.attendance_session_id == session_id,
                    AttendanceEvent.similarity_score >= AttendanceEvent.threshold,
                )
            ).scalars().all()
        )

        # 3. Absentees
        absentees = AbsenteeAlertService.find_absentees(db, session_id)
        absent_count = len(absentees)

        # 4. Dispatch Notifications
        settings = get_settings()
        email_provider = SmtpEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            sender_email=settings.smtp_sender_email,
            mock_fallback=True,
        )
        sms_provider = SmsNotificationProvider(
            api_url=settings.sms_gateway_url,
            auth_token=settings.sms_auth_token,
            sender_id=settings.sms_sender_id,
            mock_fallback=True,
        )
        notifier = NotificationManager(email_provider=email_provider, sms_provider=sms_provider)
        dispatch_summary = notifier.dispatch_batch(absentees, channel=self.channel)

        # 5. Optional SFTP dispatch if configured
        sftp_status = "SKIPPED_NOT_CONFIGURED"
        if settings.sftp_host and settings.sftp_username:
            try:
                sftp_res = SftpExportService.dispatch_sftp_export(
                    db=db,
                    session_id=session_id,
                    sftp_host=settings.sftp_host,
                    sftp_port=settings.sftp_port,
                    sftp_username=settings.sftp_username,
                    remote_path=settings.sftp_remote_path,
                )
                sftp_status = sftp_res.get("status", "SUCCESS")
            except Exception as exc:
                logger.warning("Automated SFTP export failed for session '%s': %s", session_id, exc)
                sftp_status = f"FAILED: {exc}"

        # 6. Record immutable Audit Event
        now = datetime.now(timezone.utc)
        evidence = {
            "session_id": session_id,
            "subject_name": session.subject_name,
            "class_group_id": session.class_group_id,
            "total_enrolled": total_enrolled,
            "present_count": present_count,
            "absent_count": absent_count,
            "notifications": dispatch_summary,
            "sftp_export": sftp_status,
            "reconciled_at": now.isoformat(),
        }

        audit = AuditEvent(
            session_id=session_id,
            actor_type="scheduler",
            actor_id="automated-attendance-followup",
            action="attendance.followup_reconciled",
            decision_state="RECONCILED",
            reason_codes_json=json.dumps(["AUTOMATED_SESSION_CLOSE_FOLLOWUP"]),
            evidence_json=json.dumps(evidence),
            occurred_at=now,
        )
        db.add(audit)
        db.commit()

        get_metrics().inc_counter("frs_attendance_reconciliations_total")
        get_metrics().inc_counter("frs_absentee_notifications_sent_total", value=float(absent_count))

        logger.info(
            "Session '%s' reconciled: %d present, %d absent, %d alerts sent, sftp=%s",
            session_id, present_count, absent_count, absent_count, sftp_status,
        )
        return evidence

    def run_sweep(self) -> int:
        """Run one pass over all unreconciled closed sessions. Returns count of sessions reconciled."""
        with SessionLocal() as db:
            unreconciled = self.get_unreconciled_closed_sessions(db)
            if not unreconciled:
                logger.debug("No unreconciled closed sessions found.")
                return 0

            reconciled_count = 0
            for session in unreconciled:
                if self._shutdown_requested:
                    break
                try:
                    self.reconcile_session(db, session)
                    reconciled_count += 1
                except Exception:
                    logger.exception("Failed to reconcile closed session '%s'", session.session_id)

            return reconciled_count

    def start(self, once: bool = False) -> None:
        """Run the scheduled follow-up loop."""
        logger.info(
            "FRS attendance follow-up daemon started (interval=%.0fs, channel=%s)",
            self.interval_seconds, self.channel,
        )
        while not self._shutdown_requested:
            self.run_sweep()
            if once:
                logger.info("Follow-up sweep completed with --once; stopping.")
                break

            sleep_slices = int(self.interval_seconds)
            for _ in range(sleep_slices):
                if self._shutdown_requested:
                    break
                time.sleep(1)

        logger.info("FRS attendance follow-up daemon stopped cleanly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="FRS Automated Attendance Follow-up & Absentee Alert Worker")
    parser.add_argument("--once", action="store_true", help="Process pending closed sessions once and exit.")
    parser.add_argument("--interval-seconds", type=float, default=300.0, help="Interval between sweeps (default: 300s / 5min).")
    parser.add_argument("--channel", type=str, default="email", choices=["email", "sms"], help="Notification channel.")
    args = parser.parse_args()

    create_schema()
    daemon = AttendanceFollowupDaemon(interval_seconds=args.interval_seconds, channel=args.channel)

    signal.signal(signal.SIGINT, daemon.request_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, daemon.request_shutdown)

    daemon.start(once=args.once)


if __name__ == "__main__":
    main()
