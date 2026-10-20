from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.database import _upgrade_attendance_session_link, _upgrade_model_registry_provenance


def test_model_registry_provenance_columns_are_added_to_existing_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("""
                CREATE TABLE model_registry (
                    registry_id VARCHAR(36) PRIMARY KEY,
                    model_id VARCHAR(80) NOT NULL,
                    model_version VARCHAR(120) NOT NULL,
                    artifact_sha256 VARCHAR(64) NOT NULL,
                    artifact_path TEXT NOT NULL,
                    license_name VARCHAR(200) NOT NULL,
                    preprocessing_id VARCHAR(120) NOT NULL,
                    input_contract_json TEXT NOT NULL,
                    output_contract_json TEXT NOT NULL,
                    benchmark_json TEXT DEFAULT '{}',
                    active BOOLEAN NOT NULL DEFAULT 1,
                    registered_at DATETIME NOT NULL
                )
            """))
            connection.execute(text("""
                INSERT INTO model_registry (
                    registry_id, model_id, model_version, artifact_sha256, artifact_path,
                    license_name, preprocessing_id, input_contract_json, output_contract_json,
                    benchmark_json, active, registered_at
                ) VALUES (
                    'legacy', 'ArcFace', 'old-version', 'sha256', '/models/old.onnx',
                    'UNVERIFIED', 'legacy-preprocessing', '{}', '{}', '{}', 1, CURRENT_TIMESTAMP
                )
            """))

        _upgrade_model_registry_provenance(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("model_registry")}
        assert "source_url" in columns
        assert "permitted_use" in columns
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT source_url, permitted_use FROM model_registry WHERE registry_id='legacy'"
            )).one()
        assert row.source_url == ""
        assert row.permitted_use == "UNVERIFIED LEGACY RECORD"

        # The migration is idempotent and does not fail on the already upgraded table.
        _upgrade_model_registry_provenance(engine)
    finally:
        engine.dispose()



def test_attendance_session_link_is_added_to_an_existing_database() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE attendance_sessions (session_id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(text(
                "CREATE TABLE attendance_events (attendance_id VARCHAR(36) PRIMARY KEY, employee_id VARCHAR(80) NOT NULL)"
            ))

        _upgrade_attendance_session_link(engine)
        columns = {column["name"] for column in inspect(engine).get_columns("attendance_events")}
        assert "attendance_session_id" in columns
        indexes = {index["name"] for index in inspect(engine).get_indexes("attendance_events")}
        assert "ix_attendance_events_attendance_session_id" in indexes

        # Re-running the compatibility migration is safe.
        _upgrade_attendance_session_link(engine)
    finally:
        engine.dispose()
