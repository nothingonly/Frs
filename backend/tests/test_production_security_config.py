from __future__ import annotations

import base64

import pytest

from app.core.config import Settings


def production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "env": "production",
        "database_url": "postgresql://frs:password@localhost/frs",
        "device_api_keys": "device-" + "d" * 48,
        "admin_api_key": "admin-" + "a" * 48,
        "jwt_secret": "jwt-" + "j" * 48,
        "data_encryption_key": base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
        "threshold_calibrated": True,
        "calibrated_models_csv": "ArcFace",
        "require_liveness": False,
        "deletion_certificate_key": base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"),
    }
    values.update(overrides)
    return Settings(**values)



def test_arcface_model_list_does_not_override_calibration_gate() -> None:
    settings = Settings(
        _env_file=None,
        env="development",
        threshold_calibrated=False,
        calibrated_models_csv="ArcFace",
    )

    assert settings.is_model_calibrated("ArcFace") is False


def test_production_rejects_missing_arcface_threshold_value() -> None:
    settings = production_settings(model_thresholds_json='{"UnrelatedModel": 0.5}')

    with pytest.raises(ValueError, match="No calibrated threshold configured for ArcFace"):
        settings.validate_startup_security()


def test_production_requires_explicit_jwt_secret() -> None:
    settings = production_settings(jwt_secret="")

    with pytest.raises(ValueError, match="explicit FRS_JWT_SECRET"):
        settings.validate_startup_security()


def test_production_rejects_jwt_secret_reused_as_admin_key() -> None:
    shared_secret = "shared-" + "s" * 48
    settings = production_settings(admin_api_key=shared_secret, jwt_secret=shared_secret)

    with pytest.raises(ValueError, match="distinct from admin and device API keys"):
        settings.validate_startup_security()


def test_production_rejects_jwt_secret_reused_as_device_key() -> None:
    shared_secret = "shared-" + "s" * 48
    settings = production_settings(
        device_api_keys=shared_secret,
        jwt_secret=shared_secret,
    )

    with pytest.raises(ValueError, match="distinct from admin and device API keys"):
        settings.validate_startup_security()


def test_production_accepts_separate_strong_jwt_secret() -> None:
    settings = production_settings()

    settings.validate_startup_security()



def test_render_rejects_compose_only_database_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    settings = production_settings(
        database_url="postgresql+psycopg://frs:password@db:5432/frs",
    )

    with pytest.raises(ValueError, match="Docker Compose-only hostname 'db'"):
        settings.validate_startup_security()


def test_compose_database_hostname_remains_valid_outside_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER", raising=False)
    settings = production_settings(
        database_url="postgresql+psycopg://frs:password@db:5432/frs",
    )

    settings.validate_startup_security()



@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("postgres://frs:password@db.example.com:5432/frs", "postgresql+psycopg://frs:password@db.example.com:5432/frs"),
        ("postgresql://frs:password@db.example.com:5432/frs", "postgresql+psycopg://frs:password@db.example.com:5432/frs"),
        ("postgresql+psycopg2://frs:password@db.example.com:5432/frs", "postgresql+psycopg://frs:password@db.example.com:5432/frs"),
        ("postgresql+psycopg://frs:password@db.example.com:5432/frs", "postgresql+psycopg://frs:password@db.example.com:5432/frs"),
    ],
)
def test_postgresql_urls_use_installed_psycopg3_driver(
    database_url: str,
    expected: str,
) -> None:
    settings = Settings(_env_file=None, database_url=database_url)

    assert settings.database_url == expected



def test_render_rejects_nonproduction_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    settings = Settings(_env_file=None, env="development")

    with pytest.raises(ValueError, match="set FRS_ENV=production"):
        settings.validate_startup_security()



def test_standard_database_url_environment_alias_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FRS_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://frs:password@db.example.com:5432/frs")

    settings = Settings(_env_file=None)

    assert settings.database_url == "postgresql+psycopg://frs:password@db.example.com:5432/frs"
