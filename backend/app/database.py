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


def create_schema() -> None:
    # Import models before create_all so every mapped entity is registered.
    from app.db import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _upgrade_model_registry_provenance(engine)
