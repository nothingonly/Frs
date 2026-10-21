from __future__ import annotations

import logging
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)


class CloudinaryStorageService:
    """Manages secure, private biometric media and audit evidence storage."""

    def __init__(self, settings: Settings) -> None:
        self.cloud_name = settings.cloudinary_cloud_name
        self.api_key = settings.cloudinary_api_key
        self.api_secret = settings.cloudinary_api_secret
        self._configured = bool(self.cloud_name and self.api_key and self.api_secret)
        if self._configured:
            try:
                import cloudinary
                cloudinary.config(
                    cloud_name=self.cloud_name,
                    api_key=self.api_key,
                    api_secret=self.api_secret,
                    secure=True,
                )
            except Exception as exc:
                logger.warning("Failed to initialize Cloudinary SDK: %s", exc)
                self._configured = False

    @property
    def is_configured(self) -> bool:
        return self._configured

    def upload_private_image(
        self,
        image_bytes: bytes,
        folder: str = "frs/audit",
        public_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload image with authenticated delivery type so it is never publicly accessible."""
        if not self._configured:
            raise RuntimeError("Cloudinary storage is not configured.")

        import cloudinary.uploader

        options: dict[str, Any] = {
            "folder": folder,
            "type": "authenticated",
            "overwrite": True,
            "invalidate": True,
            "resource_type": "image",
        }
        if public_id:
            options["public_id"] = public_id

        result = cloudinary.uploader.upload(image_bytes, **options)
        return {
            "public_id": result.get("public_id"),
            "format": result.get("format"),
            "bytes": result.get("bytes"),
            "created_at": result.get("created_at"),
            "delivery_type": "authenticated",
        }

    def generate_signed_url(self, public_id: str, expires_in_seconds: int = 300) -> str:
        """Generate a time-bounded signed access URL for authorized administrative preview."""
        if not self._configured:
            raise RuntimeError("Cloudinary storage is not configured.")

        import time
        import cloudinary.utils

        expires_at = int(time.time()) + max(10, expires_in_seconds)
        url, _ = cloudinary.utils.cloudinary_url(
            public_id,
            type="authenticated",
            sign_url=True,
            expires_at=expires_at,
            secure=True,
        )
        return url

    def delete_media(self, public_id: str) -> bool:
        """Delete stored media to comply with biometric retention and deletion deadlines."""
        if not self._configured:
            return False

        import cloudinary.uploader

        try:
            res = cloudinary.uploader.destroy(public_id, type="authenticated", invalidate=True)
            return res.get("result") == "ok"
        except Exception as exc:
            logger.error("Failed to delete Cloudinary asset %s: %s", public_id, exc)
            return False
