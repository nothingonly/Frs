from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Person(Base):
    __tablename__ = "persons"

    person_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    employee_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enrollment_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    embeddings: Mapped[list["EmbeddingRecord"]] = relationship(back_populates="person", cascade="all, delete-orphan")


class EmbeddingRecord(Base):
    __tablename__ = "embedding_records"
    __table_args__ = (Index("ix_embedding_person_model", "person_id", "recognizer_id", "model_version"),)

    embedding_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.person_id", ondelete="CASCADE"), index=True)
    enrollment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recognizer_id: Mapped[str] = mapped_column(String(80), index=True)
    model_version: Mapped[str] = mapped_column(String(120))
    preprocessing_id: Mapped[str] = mapped_column(String(120))
    embedding_dim: Mapped[int] = mapped_column(Integer)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    sample_sha256: Mapped[str] = mapped_column(String(64), index=True)
    quality_json: Mapped[str] = mapped_column(Text)
    accepted: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    person: Mapped[Person] = relationship(back_populates="embeddings")


class AttendanceEvent(Base):
    __tablename__ = "attendance_events"
    __table_args__ = (
        Index("ix_attendance_person_time", "person_id", "timestamp"),
        Index("ix_attendance_employee_time", "employee_id", "timestamp"),
    )

    attendance_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id: Mapped[str] = mapped_column(ForeignKey("persons.person_id", ondelete="RESTRICT"), index=True)
    employee_id: Mapped[str] = mapped_column(String(80), index=True)
    punch_type: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True, nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float)
    threshold: Mapped[float] = mapped_column(Float)
    client_device_id: Mapped[str] = mapped_column(String(120))
    pipeline_version: Mapped[str] = mapped_column(String(120))
    evidence_id: Mapped[str] = mapped_column(String(36))
    attendance_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="SET NULL"), nullable=True, index=True
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(40))
    actor_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120))
    decision_state: Mapped[str] = mapped_column(String(40))
    reason_codes_json: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[str] = mapped_column(Text)
    # Store controlled references and non-biometric evidence, never raw images or embeddings.


class LtiLaunchNonce(Base):
    """Short-lived server-issued nonce challenge for a production LTI launch."""

    __tablename__ = "lti_launch_nonces"

    nonce: Mapped[str] = mapped_column(String(255), primary_key=True)
    issued_by: Mapped[str] = mapped_column(String(120), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LtiNonceUse(Base):
    """Persistent one-time nonce consumption prevents reuse of a validated LTI launch token."""

    __tablename__ = "lti_nonce_uses"

    nonce: Mapped[str] = mapped_column(String(255), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("model_id", "model_version", name="uq_model_registry_version"),)

    registry_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id: Mapped[str] = mapped_column(String(80), index=True)
    model_version: Mapped[str] = mapped_column(String(120))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_path: Mapped[str] = mapped_column(Text)
    license_name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)
    permitted_use: Mapped[str] = mapped_column(String(240))
    preprocessing_id: Mapped[str] = mapped_column(String(120))
    input_contract_json: Mapped[str] = mapped_column(Text)
    output_contract_json: Mapped[str] = mapped_column(Text)
    benchmark_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)



class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("code", name="uq_departments_code"),
    )

    department_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ClassGroup(Base):
    __tablename__ = "class_groups"
    __table_args__ = (
        CheckConstraint("year_of_study BETWEEN 1 AND 4", name="ck_class_groups_year_of_study"),
        UniqueConstraint(
            "department_id", "year_of_study", "section", "academic_year",
            name="uq_class_groups_cohort",
        ),
    )

    class_group_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department_id: Mapped[str] = mapped_column(
        ForeignKey("departments.department_id", ondelete="RESTRICT"), index=True, nullable=False
    )
    year_of_study: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_lab: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lab_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Student(Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("student_number", name="uq_students_student_number"),
        UniqueConstraint("person_id", name="uq_students_person_id"),
    )

    student_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    # Optional link to the existing biometric identity record. New student API records create both.
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "class_group_id", name="uq_class_enrollments_student_group"),
        CheckConstraint("status IN ('ACTIVE', 'WITHDRAWN')", name="ck_class_enrollments_status"),
        Index("ix_class_enrollments_group_status", "class_group_id", "status"),
    )

    enrollment_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.student_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    class_group_id: Mapped[str] = mapped_column(
        ForeignKey("class_groups.class_group_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('OPEN', 'CLOSED', 'CANCELLED')", name="ck_attendance_sessions_status"),
        UniqueConstraint("idempotency_key", name="uq_attendance_sessions_idempotency_key"),
        Index("ix_attendance_sessions_group_started", "class_group_id", "starts_at"),
    )

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_group_id: Mapped[str] = mapped_column(
        ForeignKey("class_groups.class_group_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_type: Mapped[str] = mapped_column(String(20), default="SPECIFIC", nullable=False)
    lab_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subject_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(160), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionClassGroup(Base):
    """Associates multiple class groups with a single session for mixed-class or lab attendance."""
    __tablename__ = "session_class_groups"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="CASCADE"), primary_key=True
    )
    class_group_id: Mapped[str] = mapped_column(
        ForeignKey("class_groups.class_group_id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SessionGroupCapture(Base):
    """Tracks each multi-face group photograph taken during an active attendance session."""
    __tablename__ = "session_group_captures"
    __table_args__ = (
        Index("ix_session_captures_session_idx", "session_id", "photo_index"),
    )

    capture_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="CASCADE"), index=True, nullable=False
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    photo_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    faces_detected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    faces_matched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    faces_uncertain_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    faces_unknown_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates_ignored_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class SessionProvisionalAttendance(Base):
    """Provisional recognized attendance for a session, deduplicated per student, awaiting faculty finalization."""
    __tablename__ = "session_provisional_attendance"
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_session_provisional_student"),
        Index("ix_session_provisional_session_status", "session_id", "status"),
    )

    provisional_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="CASCADE"), index=True, nullable=False
    )
    student_id: Mapped[str] = mapped_column(
        ForeignKey("students.student_id", ondelete="CASCADE"), index=True, nullable=False
    )
    person_id: Mapped[str | None] = mapped_column(
        ForeignKey("persons.person_id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(30), default="PRESENT", nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    first_capture_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CaptureBatchJob(Base):
    """Durable queue row; input image bytes are encrypted and short-lived."""

    __tablename__ = "capture_batch_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'DEAD_LETTER')", name="ck_capture_batch_jobs_status"),
        CheckConstraint("punch_type IN ('CHECK_IN', 'CHECK_OUT')", name="ck_capture_batch_jobs_punch_type"),
        CheckConstraint("attempts >= 0 AND max_attempts >= 1", name="ck_capture_batch_jobs_attempts"),
        UniqueConstraint("device_actor_id", "idempotency_key", name="uq_capture_batch_device_idempotency"),
        Index("ix_capture_batch_status_created", "status", "created_at"),
        Index("ix_capture_batch_session_created", "attendance_session_id", "created_at"),
    )

    batch_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    attendance_session_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_sessions.session_id", ondelete="RESTRICT"), nullable=False
    )
    class_group_id: Mapped[str] = mapped_column(
        ForeignKey("class_groups.class_group_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    device_actor_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    client_device_id: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    punch_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="QUEUED", nullable=False, index=True)
    encrypted_payload: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    payload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
