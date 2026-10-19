from __future__ import annotations

import json
from functools import lru_cache
from pydantic import Field, field_validator
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

    model_pack: str = "buffalo_l"
    model_root: str = "~/.insightface"
    detect_size: int = Field(default=640, ge=320, le=1280)
    model_provider: str = "CPUExecutionProvider"
    retinaface_onnx_path: str = ""
    adaface_onnx_path: str = ""
    mobilefacenet_onnx_path: str = ""
    minifasnet_onnx_path: str = ""

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
            if not self.device_keys or any(len(token) < 32 for token in self.device_keys):
                raise ValueError("Production requires device API keys of at least 32 characters")
            if len(self.admin_api_key) < 32:
                raise ValueError("Production requires a separate admin API key of at least 32 characters")
            self.encryption_key_bytes()
            if not self.threshold_calibrated or "ArcFace" not in self.calibrated_models:
                raise ValueError("Production startup refused: ArcFace threshold must be calibrated on project data")
            if self.require_liveness and not self.minifasnet_onnx_path:
                raise ValueError("Production requires FRS_MINIFASNET_ONNX_PATH when liveness is mandatory")

    @property
    def device_keys(self) -> tuple[str, ...]:
        return tuple(token.strip() for token in self.device_api_keys.split(",") if token.strip())

    @property
    def calibrated_models(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.calibrated_models_csv.split(",") if item.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

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
