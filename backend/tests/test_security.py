import base64
import os

import pytest

from app.core.config import Settings
from app.security import (
    authenticate_admin,
    authenticate_device,
    decrypt_embedding,
    encrypt_embedding,
)


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        env="test",
        device_api_keys="device-token-with-at-least-32-chars-0001,second-device-token-with-32-chars-02",
        admin_api_key="admin-token-that-is-not-the-device-token-0001",
        data_encryption_key=base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
    )


def test_device_and_admin_credentials_are_separate() -> None:
    settings = make_settings()
    device_key = settings.device_keys[0]
    assert authenticate_device(device_key, settings)
    assert not authenticate_admin(device_key, settings)
    assert authenticate_admin(settings.admin_api_key, settings)
    assert not authenticate_device(settings.admin_api_key, settings)


def test_missing_credentials_fail_closed() -> None:
    settings = make_settings()
    assert not authenticate_device(None, settings)
    assert not authenticate_admin("", settings)
    unconfigured = Settings(_env_file=None, env="test", device_api_keys="", admin_api_key="")
    assert not authenticate_device("some-key", unconfigured)
    assert not authenticate_admin("some-key", unconfigured)


def test_embedding_round_trip_and_ciphertext_is_not_plaintext() -> None:
    settings = make_settings()
    original = b"actual-biometric-embedding-byte-sequence"
    ciphertext, nonce = encrypt_embedding(original, settings)
    assert ciphertext != original
    assert decrypt_embedding(ciphertext, nonce, settings) == original


def test_embedding_authentication_rejects_tampering() -> None:
    settings = make_settings()
    ciphertext, nonce = encrypt_embedding(b"embedding", settings)
    changed = bytearray(ciphertext)
    changed[-1] ^= 0x01
    with pytest.raises(Exception):
        decrypt_embedding(bytes(changed), nonce, settings)


def test_production_refuses_unready_calibration_and_secrets() -> None:
    settings = Settings(_env_file=None, env="production")
    with pytest.raises(ValueError):
        settings.validate_startup_security()
