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
        "deletion_certificate_key": "deletion-" + "c" * 48,
    }
    values.update(overrides)
    return Settings(**values)


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
