from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.storage import CloudinaryStorageService

pytest.importorskip("cloudinary")


def test_storage_service_unconfigured_by_default() -> None:
    settings = Settings(_env_file=None, env="test")
    service = CloudinaryStorageService(settings)
    assert not service.is_configured
    with pytest.raises(RuntimeError, match="not configured"):
        service.upload_private_image(b"fake-image")
    with pytest.raises(RuntimeError, match="not configured"):
        service.generate_signed_url("some-id")
    assert service.delete_media("some-id") is False


def test_storage_service_configured_with_credentials() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        cloudinary_cloud_name="test-cloud",
        cloudinary_api_key="test-key",
        cloudinary_api_secret="test-secret",
    )
    service = CloudinaryStorageService(settings)
    assert service.is_configured


def test_upload_private_image_uses_authenticated_type() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        cloudinary_cloud_name="test-cloud",
        cloudinary_api_key="test-key",
        cloudinary_api_secret="test-secret",
    )
    service = CloudinaryStorageService(settings)

    mock_upload = MagicMock(return_value={
        "public_id": "frs/audit/test-id",
        "format": "jpg",
        "bytes": 1024,
        "created_at": "2026-10-20T12:00:00Z",
    })

    with patch("cloudinary.uploader.upload", mock_upload):
        res = service.upload_private_image(b"fake-image-bytes", folder="frs/custom", public_id="custom-id")
        assert res["public_id"] == "frs/audit/test-id"
        assert res["delivery_type"] == "authenticated"

        mock_upload.assert_called_once_with(
            b"fake-image-bytes",
            folder="frs/custom",
            type="authenticated",
            overwrite=True,
            invalidate=True,
            resource_type="image",
            public_id="custom-id",
        )


def test_generate_signed_url_requests_authenticated_signature() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        cloudinary_cloud_name="test-cloud",
        cloudinary_api_key="test-key",
        cloudinary_api_secret="test-secret",
    )
    service = CloudinaryStorageService(settings)

    mock_url = MagicMock(return_value=("https://res.cloudinary.com/test-cloud/image/authenticated/s--xyz--/sample.jpg", {}))

    with patch("cloudinary.utils.cloudinary_url", mock_url):
        url = service.generate_signed_url("sample", expires_in_seconds=600)
        assert "authenticated" in url
        mock_url.assert_called_once()
        _, kwargs = mock_url.call_args
        assert kwargs["type"] == "authenticated"
        assert kwargs["sign_url"] is True


def test_delete_media_invokes_destroy_with_invalidation() -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        cloudinary_cloud_name="test-cloud",
        cloudinary_api_key="test-key",
        cloudinary_api_secret="test-secret",
    )
    service = CloudinaryStorageService(settings)

    mock_destroy = MagicMock(return_value={"result": "ok"})

    with patch("cloudinary.uploader.destroy", mock_destroy):
        success = service.delete_media("sample-asset")
        assert success is True
        mock_destroy.assert_called_once_with("sample-asset", type="authenticated", invalidate=True)
