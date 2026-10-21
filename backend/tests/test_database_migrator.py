from __future__ import annotations

from pathlib import Path
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.migrator import (
    apply_all_migrations,
    assert_production_schema_ready,
    compute_file_checksum,
    get_applied_migrations,
    get_migration_files,
    init_migration_table,
    verify_all_migrations,
)


def test_get_migration_files_order() -> None:
    files = get_migration_files()
    assert len(files) >= 4
    versions = [v for v, _ in files]
    assert versions[0] == "0001_base_schema"
    assert versions[1] == "0002_college_domain"
    assert versions[2] == "0003_capture_batches"
    assert versions[3] == "0004_dead_letter_status"


def test_compute_file_checksum(tmp_path: Path) -> None:
    f1 = tmp_path / "test.sql"
    f1.write_bytes(b"SELECT 1;\r\n")
    f2 = tmp_path / "test2.sql"
    f2.write_bytes(b"SELECT 1;\n")
    # Normalized checksums must match across CRLF and LF
    assert compute_file_checksum(f1) == compute_file_checksum(f2)


def test_migration_lifecycle(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_migration_table(engine)
    applied = get_applied_migrations(engine)
    assert len(applied) == 0

    # Create two temporary test migrations
    m1 = tmp_path / "0001_initial.sql"
    m1.write_text("CREATE TABLE test_table_1 (id INTEGER PRIMARY KEY, name TEXT);", encoding="utf-8")
    m2 = tmp_path / "0002_add_field.sql"
    m2.write_text("CREATE TABLE test_table_2 (id INTEGER PRIMARY KEY, status TEXT);", encoding="utf-8")

    # Before apply: verify shows pending
    is_ready, pending = verify_all_migrations(engine, directory=tmp_path)
    assert not is_ready
    assert pending == ["0001_initial", "0002_add_field"]

    # Apply all
    newly_applied = apply_all_migrations(engine, directory=tmp_path)
    assert newly_applied == ["0001_initial", "0002_add_field"]

    # After apply: verify shows up to date
    is_ready, pending = verify_all_migrations(engine, directory=tmp_path)
    assert is_ready
    assert len(pending) == 0

    # Verify tables actually exist and can be queried
    with engine.connect() as conn:
        conn.execute(text("INSERT INTO test_table_1 (id, name) VALUES (1, 'alpha')"))
        res = conn.execute(text("SELECT name FROM test_table_1 WHERE id = 1")).scalar_one()
        assert res == "alpha"

    # Second apply is idempotent
    second_run = apply_all_migrations(engine, directory=tmp_path)
    assert len(second_run) == 0


def test_failed_migration_aborts(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_migration_table(engine)

    bad_migration = tmp_path / "0001_syntax_error.sql"
    bad_migration.write_text("CREATE TABLE valid_table (id INT); INVALID SQL SYNTAX HERE;", encoding="utf-8")

    with pytest.raises(Exception):
        apply_all_migrations(engine, directory=tmp_path)

    # Failed migration should not be marked as applied in schema_migrations
    applied = get_applied_migrations(engine)
    assert "0001_syntax_error" not in applied


def test_incremental_migrations_and_recovery(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_migration_table(engine)

    # Step 1: Base migration
    m1 = tmp_path / "0001_base.sql"
    m1.write_text("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT UNIQUE);", encoding="utf-8")
    apply_all_migrations(engine, directory=tmp_path)

    # Insert existing data
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email) VALUES (1, 'alice@campus.edu')"))

    # Step 2: Incremental upgrade adding a table with foreign key
    m2 = tmp_path / "0002_profiles.sql"
    m2.write_text("CREATE TABLE profiles (id INTEGER PRIMARY KEY, user_id INTEGER, bio TEXT, FOREIGN KEY(user_id) REFERENCES users(id));", encoding="utf-8")
    newly_applied = apply_all_migrations(engine, directory=tmp_path)
    assert newly_applied == ["0002_profiles"]

    # Verify existing data preserved
    with engine.connect() as conn:
        res = conn.execute(text("SELECT email FROM users WHERE id = 1")).scalar_one()
        assert res == "alice@campus.edu"

    # Step 3: Failed migration with intentional error
    m3_bad = tmp_path / "0003_broken.sql"
    m3_bad.write_text("CREATE TABLE bad_table (id INT); INSERT INTO bad_table VALUES ('not_an_int_and_syntax_error' INVALID_SQL);", encoding="utf-8")
    with pytest.raises(Exception):
        apply_all_migrations(engine, directory=tmp_path)

    # Assert rollback: 0003_broken is NOT marked as applied
    applied = get_applied_migrations(engine)
    assert "0003_broken" not in applied

    # Step 4: Fix migration and recover
    m3_fixed = tmp_path / "0003_broken.sql"
    m3_fixed.write_text("CREATE TABLE fixed_table (id INTEGER PRIMARY KEY, note TEXT);", encoding="utf-8")
    recovered = apply_all_migrations(engine, directory=tmp_path)
    assert recovered == ["0003_broken"]
    assert "0003_broken" in get_applied_migrations(engine)


def test_assert_production_schema_ready(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # In non-production, no exception is raised
    assert_production_schema_ready(engine)

    # In production with sqlite, must raise
    monkeypatch.setattr("app.db.migrator.get_settings", lambda: Settings(_env_file=None, env="production"))
    with pytest.raises(RuntimeError, match="Production database must be PostgreSQL"):
        assert_production_schema_ready(engine)


def test_assert_production_schema_halts_on_pending_migrations(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # Mock dialect to postgresql
    monkeypatch.setattr(engine.dialect, "name", "postgresql")
    monkeypatch.setattr("app.db.migrator.get_settings", lambda: Settings(_env_file=None, env="production"))
    # Mock verify_all_migrations to simulate pending migration
    monkeypatch.setattr("app.db.migrator.verify_all_migrations", lambda eng: (False, ["0005_future_migration"]))

    with pytest.raises(RuntimeError, match="Production startup halted: Database schema is out of date"):
        assert_production_schema_ready(engine)
