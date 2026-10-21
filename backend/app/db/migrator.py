from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def get_applied_migrations(engine: Engine) -> dict[str, dict[str, Any]]:
    """Return a dict of applied migrations: version -> {applied_at, checksum, description}."""
    init_migration_table(engine)
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


def apply_all_migrations(engine: Engine, directory: Path | None = None) -> list[str]:
    """Apply all pending migrations in sequential order. Returns list of applied versions."""
    init_migration_table(engine)
    applied = get_applied_migrations(engine)
    available = get_migration_files(directory)

    newly_applied: list[str] = []
    for version, file_path in available:
        if version not in applied:
            apply_migration(engine, version, file_path)
            newly_applied.append(version)
        else:
            current_cs = compute_file_checksum(file_path)
            recorded_cs = applied[version]["checksum"]
            if current_cs != recorded_cs:
                msg = (
                    f"Migration checksum mismatch for {version}! Recorded: {recorded_cs}, Current: {current_cs}. "
                    "Historical migration files must never be modified after application. "
                    "Apply changes via new forward migrations."
                )
                logger.error(msg)
                settings = get_settings()
                if settings.is_production:
                    raise MigrationIntegrityError(msg)

    # Post-migration check: verify and enforce RLS and constraints if on PostgreSQL
    if engine.dialect.name == "postgresql":
        verify_and_enforce_rls(engine)
        verify_and_enforce_constraints(engine)

    return newly_applied


def verify_all_migrations(engine: Engine, directory: Path | None = None) -> tuple[bool, list[str]]:
    """Check if all available migrations have been applied. Returns (is_up_to_date, pending_versions)."""
    applied = get_applied_migrations(engine)
    available = get_migration_files(directory)

    pending = [version for version, _ in available if version not in applied]
    return (len(pending) == 0, pending)


def verify_and_enforce_rls(engine: Engine) -> list[str]:
    """Ensure all public application tables have Row Level Security enabled on PostgreSQL."""
    if engine.dialect.name != "postgresql":
        return []

    tables_to_protect = [
        "persons", "embedding_records", "attendance_events", "audit_events",
        "model_registry", "departments", "class_groups", "students",
        "class_enrollments", "attendance_sessions", "capture_batch_jobs",
    ]

    enforced: list[str] = []
    with engine.connect() as conn:
        inspector = inspect(engine)
        for tbl in tables_to_protect:
            if inspector.has_table(tbl):
                query = text("""
                    SELECT rowsecurity FROM pg_tables
                    WHERE schemaname = 'public' AND tablename = :tbl
                """)
                row = conn.execute(query, {"tbl": tbl}).first()
                if row and not row[0]:
                    with engine.begin() as tx:
                        tx.execute(text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
                    enforced.append(tbl)
                    logger.info("Enforced RLS on table: %s", tbl)

    return enforced


def verify_and_enforce_constraints(engine: Engine) -> None:
    """Verify required check constraints exist on PostgreSQL."""
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    if not inspector.has_table("capture_batch_jobs"):
        return

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS ck_capture_batch_jobs_status"))
        conn.execute(text("ALTER TABLE capture_batch_jobs DROP CONSTRAINT IF EXISTS capture_batch_jobs_status_check"))
        conn.execute(text("""
            ALTER TABLE capture_batch_jobs ADD CONSTRAINT ck_capture_batch_jobs_status
            CHECK (status IN ('QUEUED', 'PROCESSING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'DEAD_LETTER'))
        """))


def assert_production_schema_ready(engine: Engine) -> None:
    """Enforce on startup in production that all migrations are applied and RLS is active.
    
    Raises RuntimeError if any migration is unapplied or if SQLite is in use.
    """
    settings = get_settings()
    if settings.env.lower() != "production":
        return

    if engine.dialect.name != "postgresql":
        raise RuntimeError("Production database must be PostgreSQL (Supabase / AWS RDS).")

    is_ready, pending = verify_all_migrations(engine)
    if not is_ready:
        raise RuntimeError(
            f"Production startup halted: Database schema is out of date. "
            f"Pending migrations: {pending}. Run 'python -m app.db.migrator --apply' before starting."
        )

    verify_and_enforce_rls(engine)
    verify_and_enforce_constraints(engine)
    logger.info("Production database schema verified: all migrations applied, RLS active.")


def main() -> None:
    parser = argparse.ArgumentParser(description="FRS PostgreSQL Schema Migration Engine")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true", help="Apply all pending migrations")
    group.add_argument("--verify", action="store_true", help="Verify if all migrations are applied")
    group.add_argument("--status", action="store_true", help="Display migration status table")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.status:
        applied = get_applied_migrations(default_engine)
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
