from __future__ import annotations

import json
from functools import lru_cache
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
    database_url: str = "sqlite:///./frs.db"
    device_api_keys: str = ""
    admin_api_key: str = ""
    data_encryption_key: str = ""
    jwt_secret: str = ""
    jwt_issuer: str = "frs-auth"
    jwt_expiry_minutes: int = 60
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

    model_pack: str = "buffalo_l"
    model_root: str = "~/.insightface"
    detect_size: int = Field(default=640, ge=320, le=1280)
    model_provider: str = "CPUExecutionProvider"
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

    def validate_startup_security(self) -> None:
        if self.minimum_identification_frames > self.maximum_identification_frames:
            raise ValueError("Minimum identification frames cannot exceed maximum frames")
        if self.env.lower() == "production":
            db_url = self.database_url.lower().strip()
            if db_url.startswith("sqlite") or not (
                db_url.startswith("postgresql") or db_url.startswith("postgres")
            ):
                raise ValueError(
                    "Production startup refused: SQLite is not permitted in production. "
                    "Configure a production PostgreSQL database URL (postgresql+psycopg2:// or postgresql://)."
                )
            if not self.device_keys or any(len(token) < 32 for token in self.device_keys):
                raise ValueError("Production requires device API keys of at least 32 characters")
            if len(self.admin_api_key) < 32:
                raise ValueError("Production requires a separate admin API key of at least 32 characters")
            if self.jwt_secret and len(self.jwt_secret) < 32:
                raise ValueError("Production requires FRS_JWT_SECRET of at least 32 characters when configured")
            self.encryption_key_bytes()
            if not self.threshold_calibrated or "ArcFace" not in self.calibrated_models:
                raise ValueError("Production startup refused: ArcFace threshold must be calibrated on project data")
            if not self.model_license_attested:
                raise ValueError("Production requires explicit verification of every model-weight license")
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

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def device_keys(self) -> tuple[str, ...]:
        return tuple(token.strip() for token in self.device_api_keys.split(",") if token.strip())

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
        return self.threshold_calibrated and model_id == "ArcFace" or model_id in self.calibrated_models

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
