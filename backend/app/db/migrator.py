from __future__ import annotations

import argparse
import hashlib
import logging
from contextlib import contextmanager
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from collections.abc import Iterator

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.database import engine as default_engine

logger = logging.getLogger("frs.migrator")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"


class MigrationIntegrityError(RuntimeError):
    """Raised when a historical migration file's checksum does not match its recorded applied state."""
    pass


def get_migration_files(directory: Path | None = None) -> list[tuple[str, Path]]:
    """Return sorted list of (version_name, path) for all valid SQL migration files."""
    mig_dir = directory or MIGRATIONS_DIR
    if not mig_dir.is_dir():
        return []

    pattern = re.compile(r"^(\d{4}_[\w\-]+)\.sql$")
    files: list[tuple[str, Path]] = []
    for p in mig_dir.iterdir():
        if p.is_file():
            match = pattern.match(p.name)
            if match:
                files.append((match.group(1), p))

    files.sort(key=lambda item: item[0])
    return files


def init_migration_table(engine: Engine) -> None:
    """Ensure the schema_migrations table exists."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(80) PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL,
                checksum VARCHAR(64) NOT NULL,
                description TEXT
            );
        """))


def get_applied_migrations(
    engine: Engine,
    *,
    create_if_missing: bool = True,
) -> dict[str, dict[str, Any]]:
    """Return applied migration records.

    Verification callers may set create_if_missing=False to ensure a readiness check never
    creates schema_migrations as a side effect.
    """
    if create_if_missing:
        init_migration_table(engine)
    elif not inspect(engine).has_table("schema_migrations"):
        return {}
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version, applied_at, checksum, description FROM schema_migrations ORDER BY version"))
        return {
            row[0]: {
                "version": row[0],
                "applied_at": row[1],
                "checksum": row[2],
                "description": row[3],
            }
            for row in result.fetchall()
        }


def compute_file_checksum(file_path: Path) -> str:
    """Compute normalized SHA-256 checksum for a migration file."""
    content = file_path.read_bytes()
    # Normalize CRLF to LF to avoid cross-platform Git checkout discrepancies
    normalized = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(normalized).hexdigest()


def apply_migration(engine: Engine, version: str, file_path: Path) -> None:
    """Apply a single SQL migration file inside a transaction and record it."""
    sql_text = file_path.read_text(encoding="utf-8")
    if engine.dialect.name == "sqlite" and "-- POSTGRESQL_ONLY" in sql_text:
        # PostgreSQL-specific trigger/function migrations are checksum-tracked but not executed
        # by SQLite unit-test fixtures. Production remains fail-closed on PostgreSQL.
        sql_text = ""
    checksum = compute_file_checksum(file_path)
    now = datetime.now(timezone.utc)

    logger.info("Applying migration %s from %s...", version, file_path.name)
    with engine.begin() as conn:
        # Split statements on semicolon for engines that don't execute multiple statements at once (like SQLite)
        # For PostgreSQL/Supabase, multi-statement SQL strings execute natively.
        if engine.dialect.name == "sqlite":
            statements = [s.strip() for s in sql_text.split(";") if s.strip()]
            for stmt in statements:
                # Skip PostgreSQL-specific features like gen_random_uuid, TIMESTAMPTZ, BYTEA, and RLS when on SQLite
                sqlite_compat = _sqlite_compat_transform(stmt)
                if sqlite_compat:
                    conn.execute(text(sqlite_compat))
        else:
            conn.execute(text(sql_text))

        conn.execute(
            text("INSERT INTO schema_migrations (version, applied_at, checksum, description) VALUES (:v, :at, :cs, :desc)"),
            {"v": version, "at": now, "cs": checksum, "desc": file_path.name},
        )
    logger.info("Migration %s applied successfully.", version)


def _sqlite_compat_transform(stmt: str) -> str | None:
    """Transform or filter PostgreSQL-specific syntax when testing on SQLite."""
    lower = stmt.lower()
    if "enable row level security" in lower:
        return None
    if "create extension" in lower:
        return None

    # Replace Postgres types and defaults for SQLite test runs
    stmt = re.sub(r"gen_random_uuid\(\)::text", "lower(hex(randomblob(16)))", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"\bTIMESTAMPTZ\b", "DATETIME", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"\bBYTEA\b", "BLOB", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"\bDOUBLE PRECISION\b", "REAL", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"\bBOOLEAN\b", "INTEGER", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"\bnow\(\)", "CURRENT_TIMESTAMP", stmt, flags=re.IGNORECASE)
    stmt = re.sub(r"check\s*\(academic_year\s*~\s*'\^\[0-9\]\{4\}-\[0-9\]\{4\}\$'\)", "CHECK (length(academic_year) = 9)", stmt, flags=re.IGNORECASE)
    return stmt


@contextmanager
def _migration_advisory_lock(engine: Engine) -> Iterator[None]:
    """Serialize concurrent PostgreSQL migration invocations with a session-level lock."""
    if engine.dialect.name != "postgresql":
        yield
        return

    with engine.connect() as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(143152, 20261021)"))
        lock_connection.commit()
        try:
            yield
        finally:
            lock_connection.execute(text("SELECT pg_advisory_unlock(143152, 20261021)"))
            lock_connection.commit()


def apply_all_migrations(engine: Engine, directory: Path | None = None) -> list[str]:
    """Apply pending migrations serially, refuse drift, then enforce deployed DB safeguards."""
    newly_applied: list[str] = []
    with _migration_advisory_lock(engine):
        init_migration_table(engine)
        applied = get_applied_migrations(engine, create_if_missing=False)
        available = get_migration_files(directory)
        if not available:
            raise MigrationIntegrityError(
                "No SQL migration files were found. Refusing to report the database as migrated."
            )
        available_versions = {version for version, _ in available}

        unknown = sorted(set(applied) - available_versions)
        if unknown:
            raise MigrationIntegrityError(
                "Applied database migrations have no matching source files: "
                + ", ".join(unknown)
                + ". Restore the historical migration files before continuing."
            )

        for version, file_path in available:
            current_cs = compute_file_checksum(file_path)
            if version not in applied:
                apply_migration(engine, version, file_path)
                newly_applied.append(version)
                applied[version] = {"checksum": current_cs}
                continue

            recorded_cs = applied[version]["checksum"]
            if current_cs != recorded_cs:
                msg = (
                    f"Migration checksum mismatch for {version}! Recorded: {recorded_cs}, Current: {current_cs}. "
                    "Historical migration files must never be modified after application. "
                    "Apply changes via new forward migrations."
                )
                logger.error(msg)
                raise MigrationIntegrityError(msg)

        # Only the explicit migration command may change database-level security DDL.
        if engine.dialect.name == "postgresql":
            verify_and_enforce_rls(engine)
            verify_and_enforce_constraints(engine)

    return newly_applied


def verify_all_migrations(engine: Engine, directory: Path | None = None) -> tuple[bool, list[str]]:
    """Verify pending migrations, historical checksums, and migration-registry integrity."""
    available = get_migration_files(directory)
    if not available:
        return False, ["no migration files found"]
    available_by_version = {version: path for version, path in available}

    if not inspect(engine).has_table("schema_migrations"):
        pending = [version for version, _ in available]
        if not pending:
            pending = ["schema_migrations_missing"]
        return False, pending

    applied = get_applied_migrations(engine, create_if_missing=False)
    problems = [
        version for version, _ in available
        if version not in applied
    ]

    for version, file_path in available:
        if version in applied:
            recorded_cs = applied[version]["checksum"]
            current_cs = compute_file_checksum(file_path)
            if current_cs != recorded_cs:
                problems.append(f"{version} (checksum mismatch)")

    for version in sorted(set(applied) - set(available_by_version)):
        problems.append(f"{version} (migration file missing from repository)")

    return (len(problems) == 0, problems)


def _protected_tables() -> tuple[str, ...]:
    return (
        "persons", "embedding_records", "attendance_events", "audit_events",
        "model_registry", "departments", "class_groups", "students",
        "class_enrollments", "attendance_sessions", "session_class_groups",
        "session_group_captures", "session_provisional_attendance",
        "capture_batch_jobs", "lti_nonce_uses", "lti_launch_nonces",
    )


def verify_and_enforce_rls(engine: Engine) -> list[str]:
    """Enable RLS on required application tables during the explicit migration step."""
    if engine.dialect.name != "postgresql":
        return []

    inspector = inspect(engine)
    enforced: list[str] = []
    with engine.connect() as conn:
        for table_name in _protected_tables():
            if not inspector.has_table(table_name):
                continue
            row = conn.execute(
                text(
                    "SELECT rowsecurity FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename = :table_name"
                ),
                {"table_name": table_name},
            ).first()
            if row and not row[0]:
                with engine.begin() as tx:
                    tx.execute(text(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY"))
                enforced.append(table_name)
                logger.info("Enforced RLS on table: %s", table_name)
    return enforced


def verify_required_rls(engine: Engine) -> list[str]:
    """Read-only production check for every required application table's existence and RLS."""
    if engine.dialect.name != "postgresql":
        return ["database dialect is not PostgreSQL"]

    inspector = inspect(engine)
    issues: list[str] = []
    with engine.connect() as conn:
        for table_name in _protected_tables():
            if not inspector.has_table(table_name):
                issues.append(f"required table missing: {table_name}")
                continue
            row = conn.execute(
                text(
                    "SELECT rowsecurity FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename = :table_name"
                ),
                {"table_name": table_name},
            ).first()
            if row is None or not row[0]:
                issues.append(f"row-level security not enabled: {table_name}")
    return issues


def verify_and_enforce_constraints(engine: Engine) -> None:
    """Install the required capture status constraint during explicit migration execution."""
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("capture_batch_jobs"):
        raise RuntimeError("Cannot enforce capture status constraint: capture_batch_jobs is missing.")

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS ck_capture_batch_jobs_status"))
        conn.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS capture_batch_jobs_status_check"))
        conn.execute(text("""
            ALTER TABLE capture_batch_jobs ADD CONSTRAINT ck_capture_batch_jobs_status
            CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'DEAD_LETTER'))
        """))


def verify_required_constraints(engine: Engine) -> list[str]:
    """Read-only startup check for required data integrity constraints."""
    if engine.dialect.name != "postgresql":
        return ["database dialect is not PostgreSQL"]

    inspector = inspect(engine)
    if not inspector.has_table("capture_batch_jobs"):
        return ["required table missing: capture_batch_jobs"]

    checks = inspector.get_check_constraints("capture_batch_jobs")
    required_statuses = ("QUEUED", "PROCESSING", "SUCCEEDED", "REJECTED", "FAILED", "DEAD_LETTER")
    for constraint in checks:
        sqltext = (constraint.get("sqltext") or "").upper()
        if all(status in sqltext for status in required_statuses):
            return []
    return ["capture_batch_jobs status constraint missing or does not allow DEAD_LETTER"]


def assert_production_schema_ready(engine: Engine) -> None:
    """Read-only readiness gate for a schema migrated by the explicit release step.

    Startup never creates tables, repairs constraints, enables RLS, or applies SQL files.
    """
    settings = get_settings()
    if settings.env.lower() != "production":
        return

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Production database must be PostgreSQL (Supabase / AWS RDS).")

    is_ready, problems = verify_all_migrations(engine)
    if not is_ready:
        raise RuntimeError(
            "Production startup halted: database migration state is not ready. "
            f"Pending or invalid migrations: {problems}. "
            "Run 'python -m app.db.migrator --apply' as a controlled release step."
        )

    rls_issues = verify_required_rls(engine)
    if rls_issues:
        raise RuntimeError(
            "Production startup halted: database security controls failed verification: "
            + "; ".join(rls_issues)
        )

    constraint_issues = verify_required_constraints(engine)
    if constraint_issues:
        raise RuntimeError(
            "Production startup halted: database constraints failed verification: "
            + "; ".join(constraint_issues)
        )

    with engine.connect() as conn:
        trigger = conn.execute(text("""
            SELECT t.tgenabled, pg_get_triggerdef(t.oid)
            FROM pg_trigger AS t
            JOIN pg_class AS c ON c.oid = t.tgrelid
            JOIN pg_namespace AS n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public'
              AND c.relname = 'audit_events'
              AND t.tgname = 'trg_audit_events_append_only'
              AND NOT t.tgisinternal
        """)).first()
    if trigger is None or trigger[0] != "O":
        raise RuntimeError(
            "Production startup halted: append-only audit_events trigger is missing or disabled."
        )
    trigger_sql = (trigger[1] or "").upper()
    if "UPDATE" not in trigger_sql or "DELETE" not in trigger_sql:
        raise RuntimeError(
            "Production startup halted: audit_events trigger does not block both UPDATE and DELETE."
        )

    logger.info(
        "Production database verified read-only: migrations/checksums, RLS, constraints, and audit trigger are valid."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="FRS PostgreSQL Schema Migration Engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Apply all pending migrations")
    group.add_argument("--verify", action="store_true", help="Verify if all migrations are applied")
    group.add_argument("--status", action="store_true", help="Display migration status table")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.status:
        applied = get_applied_migrations(default_engine, create_if_missing=False)
        available = get_migration_files()
        print("\n=== FRS Database Migrations Status ===")
        print(f"Database dialect: {default_engine.dialect.name}")
        print(f"{'Version':<35} {'Status':<15} {'Applied At':<30}")
        print("-" * 80)
        for version, _ in available:
            if version in applied:
                info = applied[version]
                print(f"{version:<35} {'APPLIED':<15} {str(info['applied_at']):<30}")
            else:
                print(f"{version:<35} {'PENDING':<15} {'-':<30}")
        print()
    elif args.verify:
        is_ready, pending = verify_all_migrations(default_engine)
        if is_ready:
            print("Database schema is fully up to date.")
            sys.exit(0)
        else:
            print(f"Database schema has {len(pending)} pending migrations: {', '.join(pending)}")
            sys.exit(1)
    elif args.apply:
        newly_applied = apply_all_migrations(default_engine)
        print(f"Applied {len(newly_applied)} migrations: {', '.join(newly_applied) if newly_applied else 'None (Already up to date)'}")


if __name__ == "__main__":
    main()
