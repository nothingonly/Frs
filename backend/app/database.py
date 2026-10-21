from __future__ import annotations

from collections.abc import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _upgrade_model_registry_provenance(target_engine) -> None:
    """Add provenance fields to databases created by pre-provenance FRS builds."""
    inspector = inspect(target_engine)
    if not inspector.has_table("model_registry"):
        return

    existing = {column["name"] for column in inspector.get_columns("model_registry")}
    # These literal identifiers are application-owned constants, not user input.
    with target_engine.begin() as connection:
        if "source_url" not in existing:
            connection.execute(
                text("ALTER TABLE model_registry ADD COLUMN source_url TEXT NOT NULL DEFAULT ''")
            )
        if "permitted_use" not in existing:
            connection.execute(
                text(
                    "ALTER TABLE model_registry ADD COLUMN permitted_use "
                    "VARCHAR(240) NOT NULL DEFAULT 'UNVERIFIED LEGACY RECORD'"
                )
            )


def _upgrade_attendance_session_link(target_engine) -> None:
    """Add the optional session foreign key to databases created by earlier FRS builds."""
    inspector = inspect(target_engine)
    if not inspector.has_table("attendance_events") or not inspector.has_table("attendance_sessions"):
        return
    existing = {column["name"] for column in inspector.get_columns("attendance_events")}
    if "attendance_session_id" in existing:
        return
    with target_engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE attendance_events ADD COLUMN attendance_session_id VARCHAR(36) "
            "REFERENCES attendance_sessions(session_id) ON DELETE SET NULL"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_attendance_events_attendance_session_id "
            "ON attendance_events (attendance_session_id)"
        ))


def _upgrade_capture_batch_dead_letter_constraint(target_engine) -> None:
    """Ensure capture_batch_jobs status check constraint allows DEAD_LETTER on PostgreSQL."""
    if target_engine.dialect.name != "postgresql":
        return
    inspector = inspect(target_engine)
    if not inspector.has_table("capture_batch_jobs"):
        return
    with target_engine.begin() as connection:
        connection.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS ck_capture_batch_jobs_status"))
        connection.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS capture_batch_jobs_status_check"))
        connection.execute(text(
            "ALTER TABLE capture_batch_jobs ADD CONSTRAINT ck_capture_batch_jobs_status "
            "CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'DEAD_LETTER'))"
        ))


def create_schema() -> None:
    # Import models before create_all so every mapped entity is registered.
    from app.db import entities  # noqa: F401
    from app.db.migrator import apply_all_migrations

    Base.metadata.create_all(bind=engine)
    _upgrade_model_registry_provenance(engine)
    _upgrade_attendance_session_link(engine)
    _upgrade_capture_batch_dead_letter_constraint(engine)
    try:
        apply_all_migrations(engine)
    except Exception:
        # SQLite memory instances in unit tests use metadata create_all
        pass
