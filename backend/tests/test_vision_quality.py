import cv2
import numpy as np

from app.core.config import Settings
from app.schemas.contracts import QualityState
from app.vision.quality import assess_quality


def _face_points() -> np.ndarray:
    return np.array([[45, 45], [75, 45], [60, 60], [48, 78], [72, 78]], dtype=np.float32)


def test_sharp_moderately_lit_face_crop_is_not_rejected_for_exposure() -> None:
    settings = Settings(_env_file=None, env="test", min_face_size_px=40, min_laplacian_variance=1.0)
    image = np.full((160, 160, 3), 110, dtype=np.uint8)
    cv2.circle(image, (60, 60), 24, (40, 40, 40), -1)
    cv2.line(image, (40, 75), (80, 75), (240, 240, 240), 2)
    bbox = np.array([20, 20, 100, 115, 0.99], dtype=np.float32)
    measured = assess_quality(image, bbox, _face_points(), settings)
    assert measured.result.face_size_px >= 40
    assert measured.result.blur_score >= 0
    assert measured.result.status in {QualityState.GOOD, QualityState.DEGRADED}


def test_tiny_face_is_routed_to_recapture() -> None:
    settings = Settings(_env_file=None, env="test", min_face_size_px=80)
    image = np.full((160, 160, 3), 110, dtype=np.uint8)
    bbox = np.array([30, 30, 65, 65, 0.99], dtype=np.float32)
    measured = assess_quality(image, bbox, _face_points(), settings)
    assert measured.result.status is QualityState.RECAPTURE
    assert "FACE_TOO_SMALL" in measured.result.failure_codes


def test_moderate_low_exposure_routes_to_degraded_specialist() -> None:
    settings = Settings(
        _env_file=None, env="test", min_face_size_px=30,
        min_laplacian_variance=0.0, min_mean_luminance=35.0,
    )
    image = np.full((160, 160, 3), 25, dtype=np.uint8)
    cv2.rectangle(image, (30, 30), (110, 115), (60, 60, 60), -1)
    bbox = np.array([20, 20, 125, 130, 0.99], dtype=np.float32)
    measured = assess_quality(image, bbox, _face_points(), settings)
    assert measured.result.status is QualityState.DEGRADED
    assert "UNDEREXPOSED" in measured.result.failure_codes


def test_zero_face_crop_requests_recapture_without_crashing() -> None:
    settings = Settings(_env_file=None, env="test")
    image = np.zeros((32, 32, 3), dtype=np.uint8)
    bbox = np.array([0, 0, 0, 0, 0.0], dtype=np.float32)
    measured = assess_quality(image, bbox, np.empty((0, 2), dtype=np.float32), settings)
    assert measured.result.status is QualityState.RECAPTURE
    assert "INVALID_FACE_CROP" in measured.result.failure_codes
