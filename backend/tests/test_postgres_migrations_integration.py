from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.db.migrator import verify_all_migrations, verify_required_rls


@pytest.fixture(scope="module")
def database_url() -> str:
    url = os.environ.get("FRS_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        pytest.skip("PostgreSQL integration checks run only in the dedicated CI job.")
    return url


def test_postgresql_migrations_are_current_and_rls_is_enabled(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        ready, pending = verify_all_migrations(engine)
        assert ready, f"PostgreSQL migration drift or pending migrations: {pending}"
        assert verify_required_rls(engine) == []
        with engine.connect() as connection:
            trigger = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM pg_trigger
                    WHERE tgrelid = 'public.audit_events'::regclass
                      AND tgname = 'trg_audit_events_append_only'
                      AND NOT tgisinternal
                    """
                )
            ).scalar_one()
        assert trigger == 1, "append-only audit-events trigger is missing"
    finally:
        engine.dispose()


def test_restricted_application_role_cannot_mutate_or_drop_audit_trigger(
    database_url: str,
) -> None:
    admin_engine = create_engine(database_url)
    app_password = "frs-app-ci-password-only"
    audit_id = str(uuid.uuid4())
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'frs_app_ci') THEN
                            CREATE ROLE frs_app_ci LOGIN PASSWORD 'frs-app-ci-password-only'
                                NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION BYPASSRLS;
                        END IF;
                    END
                    $$;
                    """
                )
            )
            connection.execute(text("GRANT USAGE ON SCHEMA public TO frs_app_ci"))
            connection.execute(
                text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO frs_app_ci")
            )
            connection.execute(
                text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO frs_app_ci")
            )

        app_url = make_url(database_url).set(username="frs_app_ci", password=app_password)
        app_engine = create_engine(app_url)
        try:
            with app_engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO public.audit_events (
                            audit_id, session_id, occurred_at, actor_type, actor_id,
                            action, decision_state, reason_codes_json, evidence_json
                        ) VALUES (
                            :audit_id, :session_id, now(), 'CI', 'integration-test',
                            'APPEND_ONLY_TEST', 'RECORDED', '[]', '{}'
                        )
                        """
                    ),
                    {"audit_id": audit_id, "session_id": audit_id},
                )

            with pytest.raises(DBAPIError, match="audit_events is append-only"):
                with app_engine.begin() as connection:
                    connection.execute(
                        text("UPDATE public.audit_events SET action='TAMPERED' WHERE audit_id=:audit_id"),
                        {"audit_id": audit_id},
                    )

            with pytest.raises(DBAPIError, match="audit_events is append-only"):
                with app_engine.begin() as connection:
                    connection.execute(
                        text("DELETE FROM public.audit_events WHERE audit_id=:audit_id"),
                        {"audit_id": audit_id},
                    )

            with pytest.raises(DBAPIError, match="must be owner of table audit_events"):
                with app_engine.begin() as connection:
                    connection.execute(
                        text("DROP TRIGGER trg_audit_events_append_only ON public.audit_events")
                    )
        finally:
            app_engine.dispose()
    finally:
        admin_engine.dispose()
