import numpy as np

from app.schemas.contracts import QualityResult, QualityState
from app.vision.enhancement import (
    ENHANCED_PREPROCESSING,
    ORIGINAL_PREPROCESSING,
    conditional_enhance,
)


def _quality(codes: list[str]) -> QualityResult:
    return QualityResult(
        status=QualityState.DEGRADED if codes else QualityState.GOOD,
        face_size_px=120,
        blur_score=80.0,
        mean_luminance=28.0 if "UNDEREXPOSED" in codes else 110.0,
        clipped_pixel_ratio=0.0,
        route_hint="DIFFICULT_QUALITY" if codes else "FAST",
        latency_ms=0.1,
        failure_codes=codes,
    )


def test_original_branch_is_used_when_exposure_is_normal() -> None:
    image = np.full((112, 112, 3), 80, dtype=np.uint8)
    result = conditional_enhance(image, _quality([]))
    assert result.applied is False
    assert result.preprocessing_id == ORIGINAL_PREPROCESSING
    assert result.image_bgr is image


def test_low_light_uses_named_enhancement_branch_without_mutating_input() -> None:
    image = np.full((112, 112, 3), 25, dtype=np.uint8)
    before = image.copy()
    result = conditional_enhance(image, _quality(["UNDEREXPOSED"]))
    assert result.applied is True
    assert result.preprocessing_id == ENHANCED_PREPROCESSING
    assert result.image_bgr is not image
    assert np.array_equal(image, before)


def test_enrollment_can_capture_separate_enhancement_reference() -> None:
    image = np.full((112, 112, 3), 120, dtype=np.uint8)
    result = conditional_enhance(image, _quality([]), force_enhanced_reference=True)
    assert result.applied is True
    assert result.preprocessing_id == ENHANCED_PREPROCESSING
