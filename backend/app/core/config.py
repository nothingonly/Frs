from __future__ import annotations

import json
import os
from functools import lru_cache
from urllib.parse import urlsplit
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = "development"
    database_url: str = Field(default="sqlite:///./frs.db", validation_alias=AliasChoices("FRS_DATABASE_URL", "DATABASE_URL", "database_url"))
    device_api_keys: str = ""
    admin_api_key: str = ""
    data_encryption_key: str = ""
    jwt_secret: str = ""
    jwt_issuer: str = "frs-auth"
    jwt_expiry_minutes: int = 60
    # Scope kiosk credentials to an explicit allowlist of class-group IDs. Keys are full
    # SHA-256 hex digests of device tokens, never raw device secrets.
    device_class_group_scopes_json: str = "{}"
    deletion_certificate_key: str = ""
    worker_in_process: bool = Field(default=True, validation_alias=AliasChoices("FRS_WORKER_IN_PROCESS", "WORKER_IN_PROCESS"))
    max_capture_batch_retries: int = Field(default=3, ge=1, le=10)
    retention_purge_days: int = Field(default=30, ge=1, le=365)

    # Optional cloud integrations
    cloudinary_cloud_name: str = Field(default="", validation_alias=AliasChoices("FRS_CLOUDINARY_CLOUD_NAME", "CLOUDINARY_CLOUD_NAME"))
    cloudinary_api_key: str = Field(default="", validation_alias=AliasChoices("FRS_CLOUDINARY_API_KEY", "CLOUDINARY_API_KEY"))
    cloudinary_api_secret: str = Field(default="", validation_alias=AliasChoices("FRS_CLOUDINARY_API_SECRET", "CLOUDINARY_API_SECRET"))
    supabase_url: str = Field(default="", validation_alias=AliasChoices("FRS_SUPABASE_URL", "SUPABASE_URL"))
    supabase_key: str = Field(default="", validation_alias=AliasChoices("FRS_SUPABASE_KEY", "SUPABASE_KEY", "SUPABASE_SECRET_KEY"))

    # SMTP / Notifications
    smtp_host: str = Field(default="", validation_alias=AliasChoices("FRS_SMTP_HOST", "SMTP_HOST"))
    smtp_port: int = Field(default=587, validation_alias=AliasChoices("FRS_SMTP_PORT", "SMTP_PORT"))
    smtp_username: str = Field(default="", validation_alias=AliasChoices("FRS_SMTP_USERNAME", "SMTP_USERNAME"))
    smtp_password: str = Field(default="", validation_alias=AliasChoices("FRS_SMTP_PASSWORD", "SMTP_PASSWORD"))
    smtp_use_tls: bool = Field(default=True, validation_alias=AliasChoices("FRS_SMTP_USE_TLS", "SMTP_USE_TLS"))
    smtp_sender_email: str = Field(default="noreply@campus.edu", validation_alias=AliasChoices("FRS_SMTP_SENDER_EMAIL", "SMTP_SENDER_EMAIL"))
    sms_gateway_url: str = Field(default="", validation_alias=AliasChoices("FRS_SMS_GATEWAY_URL", "SMS_GATEWAY_URL"))
    sms_auth_token: str = Field(default="", validation_alias=AliasChoices("FRS_SMS_AUTH_TOKEN", "SMS_AUTH_TOKEN"))
    sms_sender_id: str = Field(default="FRS", validation_alias=AliasChoices("FRS_SMS_SENDER_ID", "SMS_SENDER_ID"))

    # SFTP / SIS export
    sftp_host: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_HOST", "SFTP_HOST"))
    sftp_port: int = Field(default=22, validation_alias=AliasChoices("FRS_SFTP_PORT", "SFTP_PORT"))
    sftp_username: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_USERNAME", "SFTP_USERNAME"))
    sftp_password: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_PASSWORD", "SFTP_PASSWORD"))
    sftp_key_path: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_KEY_PATH", "SFTP_KEY_PATH"))
    sftp_host_key_fingerprint: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_HOST_KEY_FINGERPRINT", "SFTP_HOST_KEY_FINGERPRINT"))
    sftp_known_hosts_file: str = Field(default="", validation_alias=AliasChoices("FRS_SFTP_KNOWN_HOSTS_FILE", "SFTP_KNOWN_HOSTS_FILE"))
    sftp_remote_path: str = Field(default="/uploads/attendance", validation_alias=AliasChoices("FRS_SFTP_REMOTE_PATH", "SFTP_REMOTE_PATH"))

    # Canvas / Moodle LTI 1.3
    lti_client_id: str = Field(default="", validation_alias=AliasChoices("FRS_LTI_CLIENT_ID", "LTI_CLIENT_ID"))
    lti_deployment_id: str = Field(default="", validation_alias=AliasChoices("FRS_LTI_DEPLOYMENT_ID", "LTI_DEPLOYMENT_ID"))
    lti_issuer: str = Field(default="https://canvas.instructure.com", validation_alias=AliasChoices("FRS_LTI_ISSUER", "LTI_ISSUER"))
    lti_keyset_url: str = Field(default="", validation_alias=AliasChoices("FRS_LTI_KEYSET_URL", "LTI_KEYSET_URL"))
    # PEM-encoded LMS platform public key used for RS256 ID-token verification.
    lti_platform_public_key_pem: str = Field(default="", validation_alias=AliasChoices("FRS_LTI_PLATFORM_PUBLIC_KEY_PEM", "LTI_PLATFORM_PUBLIC_KEY_PEM"))

    model_pack: str = "buffalo_l"
    model_root: str = "~/.insightface"
    detect_size: int = Field(default=640, ge=320, le=1280)
    model_provider: str = "CPUExecutionProvider"
    # Deprecated for compatibility. This boolean never overrides actual manifest terms.
    model_license_attested: bool = False
    require_all_specialists: bool = False
    retinaface_onnx_path: str = ""
    adaface_onnx_path: str = ""
    mobilefacenet_onnx_path: str = ""
    minifasnet_onnx_path: str = ""
    fiqa_onnx_path: str = ""
    fiqa_min_quality_score: float = Field(default=0.45, ge=0.0, le=1.0)

    require_liveness: bool = True
    minimum_identification_frames: int = Field(default=3, ge=2, le=12)
    maximum_identification_frames: int = Field(default=8, ge=3, le=16)
    temporal_min_vote_fraction: float = Field(default=0.67, gt=0.5, le=1.0)
    attendance_cooldown_seconds: int = Field(default=60, ge=0, le=86400)
    similarity_threshold: float = Field(default=0.5, ge=-1.0, le=1.0)
    model_thresholds_json: str = '{"ArcFace": 0.5}'
    threshold_calibrated: bool = False
    calibrated_models_csv: str = ""
    required_liveness_score: float = Field(default=0.9, ge=0.0, le=1.0)
    enrollment_min_profile_consistency: float = Field(default=0.45, ge=-1.0, le=1.0)

    min_face_size_px: int = Field(default=80, ge=32, le=1000)
    min_laplacian_variance: float = Field(default=25.0, ge=0.0)
    min_mean_luminance: float = Field(default=35.0, ge=0.0, le=255.0)
    max_mean_luminance: float = Field(default=220.0, ge=0.0, le=255.0)
    max_clipped_pixel_ratio: float = Field(default=0.4, ge=0.0, le=1.0)
    ambiguity_margin: float = Field(default=0.05, ge=0.0, le=1.0)
    recognition_top_k: int = Field(default=5, ge=1, le=100)
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)
    max_request_bytes: int = Field(default=40 * 1024 * 1024, ge=1024)
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("database_url")
    @classmethod
    def normalize_database_driver(cls, value: str) -> str:
        """Use the installed psycopg v3 driver for standard PostgreSQL URL schemes.

        Render commonly supplies postgres:// or postgresql:// URLs; SQLAlchemy's
        plain postgresql:// default selects psycopg2, which is not installed here.
        Normalize those aliases (and legacy +psycopg2 URLs) to the project's driver.
        """
        url = value.strip()
        for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://"):
            if url.lower().startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @field_validator("model_provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        allowed = {"CPUExecutionProvider", "CUDAExecutionProvider"}
        if value not in allowed:
            raise ValueError(f"Unsupported ONNX Runtime provider: {value}")
        return value

    @field_validator("model_thresholds_json")
    @classmethod
    def validate_threshold_map(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("FRS_MODEL_THRESHOLDS_JSON must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("FRS_MODEL_THRESHOLDS_JSON must be a JSON object")
        for model_name, threshold in parsed.items():
            if not isinstance(model_name, str) or not isinstance(threshold, (float, int)):
                raise ValueError("Each model threshold must map a model name to a number")
            if not -1.0 <= float(threshold) <= 1.0:
                raise ValueError(f"Invalid similarity threshold for {model_name}")
        return value

    @field_validator("device_class_group_scopes_json")
    @classmethod
    def validate_device_class_group_scopes(cls, value: str) -> str:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("FRS_DEVICE_CLASS_GROUP_SCOPES_JSON must be a JSON object") from exc
        if not isinstance(parsed, dict):
            raise ValueError("FRS_DEVICE_CLASS_GROUP_SCOPES_JSON must be a JSON object")
        for digest, groups in parsed.items():
            if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in digest):
                raise ValueError("Device scope keys must be full 64-character SHA-256 hex digests")
            if not isinstance(groups, list) or any(not isinstance(group, str) or not group.strip() for group in groups):
                raise ValueError("Each device scope must be a list of non-empty class-group IDs")
        return value

    def validate_startup_security(self) -> None:
        if self.minimum_identification_frames > self.maximum_identification_frames:
            raise ValueError("Minimum identification frames cannot exceed maximum frames")
        # Render sets RENDER=true for deployed services. Fail closed instead of
        # accidentally starting with development defaults and an ephemeral SQLite DB.
        if os.getenv("RENDER", "").strip().lower() == "true" and self.env.lower() != "production":
            raise ValueError(
                "Render deployment refused: set FRS_ENV=production so production database, "
                "credential, encryption, calibration, and model-provenance checks are enforced."
            )
        if self.env.lower() == "production":
            db_url = self.database_url.lower().strip()
            if db_url.startswith("sqlite") or not (
                db_url.startswith("postgresql") or db_url.startswith("postgres")
            ):
                raise ValueError(
                    "Production startup refused: SQLite is not permitted in production. "
                    "Configure FRS_DATABASE_URL with a production PostgreSQL URL (postgresql+psycopg:// or postgresql://)."
                )
            # Render runs outside the repository's Docker Compose network, so the
            # Compose service name "db" cannot resolve there. Detect this misconfiguration
            # before SQLAlchemy attempts a connection and emits an opaque DNS error.
            if os.getenv("RENDER", "").strip().lower() == "true":
                database_host = urlsplit(db_url).hostname
                if database_host and database_host.lower() == "db":
                    raise ValueError(
                        "Render production startup refused: FRS_DATABASE_URL points to the "
                        "Docker Compose-only hostname 'db'. Set it to the Render PostgreSQL "
                        "Internal Database URL (when services share a region) or another "
                        "database URL reachable from this Render service."
                    )
            if not self.device_keys or any(len(token) < 32 for token in self.device_keys):
                raise ValueError("Production requires device API keys of at least 32 characters")
            if len(self.admin_api_key) < 32:
                raise ValueError("Production requires a separate admin API key of at least 32 characters")
            jwt_secret = self.jwt_secret.strip()
            if len(jwt_secret) < 32:
                raise ValueError("Production requires an explicit FRS_JWT_SECRET of at least 32 characters")
            if jwt_secret == self.admin_api_key.strip() or jwt_secret in self.device_keys:
                raise ValueError("Production requires FRS_JWT_SECRET to be distinct from admin and device API keys")
            self.encryption_key_bytes()
            if not self.threshold_calibrated or "ArcFace" not in self.calibrated_models:
                raise ValueError("Production startup refused: ArcFace threshold must be calibrated on project data")
            # Fail during startup rather than letting /health raise a 500 for a missing threshold.
            self.threshold_for("ArcFace")
            # FRS_MODEL_LICENSE_ATTESTED is informational only. Actual artifact
            # license terms are always enforced by VisionEngine from the signed/hashed
            # provenance manifest and cannot be overridden by a boolean setting.
            if self.require_liveness and not self.minifasnet_onnx_path:
                raise ValueError("Production requires FRS_MINIFASNET_ONNX_PATH when liveness is mandatory")
            if self.require_all_specialists:
                required = {
                    "FRS_RETINAFACE_ONNX_PATH": self.retinaface_onnx_path,
                    "FRS_ADAFACE_ONNX_PATH": self.adaface_onnx_path,
                    "FRS_MOBILEFACENET_ONNX_PATH": self.mobilefacenet_onnx_path,
                    "FRS_MINIFASNET_ONNX_PATH": self.minifasnet_onnx_path,
                    "FRS_FIQA_ONNX_PATH": self.fiqa_onnx_path,
                }
                missing = [name for name, path in required.items() if not path.strip()]
                if missing:
                    raise ValueError("Production missing required specialist model paths: " + ", ".join(missing))
                for model_id in ("ArcFace", "AdaFace", "MobileFaceNet"):
                    if not self.is_model_calibrated(model_id):
                        raise ValueError(f"Production requires a calibrated threshold for {model_id}")
                    self.threshold_for(model_id)
            if self.sftp_host and self.sftp_host != "mock" and not (self.sftp_host_key_fingerprint or self.sftp_known_hosts_file):
                raise ValueError("Production startup refused: SFTP export requires sftp_host_key_fingerprint or sftp_known_hosts_file to pin server identity")
            try:
                import base64
                import binascii
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

                deletion_seed = base64.b64decode(
                    self.deletion_certificate_key.strip().encode("ascii"),
                    altchars=b"-_",
                    validate=True,
                )
            except (UnicodeError, ValueError, binascii.Error) as exc:
                raise ValueError(
                    "Production requires FRS_DELETION_CERTIFICATE_KEY to be URL-safe base64 for a 32-byte Ed25519 private-key seed"
                ) from exc
            if len(deletion_seed) != 32:
                raise ValueError(
                    "FRS_DELETION_CERTIFICATE_KEY must decode to exactly 32 bytes for Ed25519"
                )
            # Construction validates that the seed is accepted by the configured crypto library.
            Ed25519PrivateKey.from_private_bytes(deletion_seed)
            if self.lti_client_id and not self.lti_platform_public_key_pem.strip():
                raise ValueError("Production LTI is enabled but FRS_LTI_PLATFORM_PUBLIC_KEY_PEM is missing")
            if self.lti_client_id and (not self.lti_issuer.strip() or not self.lti_deployment_id.strip()):
                raise ValueError("Production LTI requires configured issuer and deployment ID")

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def device_keys(self) -> tuple[str, ...]:
        return tuple(token.strip() for token in self.device_api_keys.split(",") if token.strip())

    @property
    def device_class_group_scopes(self) -> dict[str, tuple[str, ...]]:
        parsed = json.loads(self.device_class_group_scopes_json)
        return {
            digest.lower(): tuple(dict.fromkeys(group.strip() for group in groups))
            for digest, groups in parsed.items()
        }

    @property
    def calibrated_models(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.calibrated_models_csv.split(",") if item.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def effective_jwt_secret(self) -> str:
        return self.jwt_secret or self.admin_api_key or "frs-dev-jwt-secret-do-not-use-in-production"

    def is_model_calibrated(self, model_id: str) -> bool:
        # ArcFace has a legacy explicit calibration gate in addition to the model list.
        # Parenthesize the conditions so listing ArcFace alone cannot override its gate.
        if model_id == "ArcFace":
            return self.threshold_calibrated and model_id in self.calibrated_models
        return model_id in self.calibrated_models

    def threshold_for(self, model_id: str) -> float:
        parsed = json.loads(self.model_thresholds_json)
        if model_id not in parsed:
            raise ValueError(f"No calibrated threshold configured for {model_id}")
        return float(parsed[model_id])

    def encryption_key_bytes(self) -> bytes:
        import base64
        import binascii

        try:
            key = base64.urlsafe_b64decode(self.data_encryption_key.encode("ascii"))
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise ValueError("FRS_DATA_ENCRYPTION_KEY must be URL-safe base64 for exactly 32 bytes") from exc
        if len(key) != 32:
            raise ValueError("FRS_DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
