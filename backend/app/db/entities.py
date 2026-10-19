from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
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


class ModelRegistryEntry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("model_id", "model_version", name="uq_model_registry_version"),)

    registry_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id: Mapped[str] = mapped_column(String(80), index=True)
    model_version: Mapped[str] = mapped_column(String(120))
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    artifact_path: Mapped[str] = mapped_column(Text)
    license_name: Mapped[str] = mapped_column(String(200))
    preprocessing_id: Mapped[str] = mapped_column(String(120))
    input_contract_json: Mapped[str] = mapped_column(Text)
    output_contract_json: Mapped[str] = mapped_column(Text)
    benchmark_json: Mapped[str] = mapped_column(Text, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
