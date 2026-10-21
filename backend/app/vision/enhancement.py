from __future__ import annotations

from dataclasses import dataclass
import cv2
import numpy as np

from app.schemas.contracts import QualityResult


ORIGINAL_PREPROCESSING = "aligned-original-v1"
ENHANCED_PREPROCESSING = "aligned-conditional-gamma-clahe-v1"


@dataclass(frozen=True)
class EnhancementOutput:
    image_bgr: np.ndarray
    preprocessing_id: str
    applied: bool
    reason: str


def conditional_enhance(
    aligned_face_bgr: np.ndarray,
    quality: QualityResult,
    *,
    force_enhanced_reference: bool = False,
) -> EnhancementOutput:
    """Apply exposure-specific enhancement only when indicated; retain original pixels separately."""
    exposure_triggered = any(
        code in quality.failure_codes for code in ("UNDEREXPOSED", "OVEREXPOSED")
    )
    if not exposure_triggered and not force_enhanced_reference:
        return EnhancementOutput(aligned_face_bgr, ORIGINAL_PREPROCESSING, False, "EXPOSURE_BRANCH_NOT_NEEDED")

    image = aligned_face_bgr.copy()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    mean_luma = float(gray.mean())
    if mean_luma < 115.0:
        # Gamma below one lifts mid-tones. A bounded LUT avoids uncontrolled amplification.
        gamma = float(np.clip(np.log(0.62) / np.log(max(mean_luma / 255.0, 1e-3)), 0.55, 0.92))
        lut = np.clip((np.arange(256, dtype=np.float32) / 255.0) ** gamma * 255.0, 0, 255).astype(np.uint8)
        image = cv2.LUT(image, lut)
        reason = "LOW_LIGHT_GAMMA_CLAHE"
    elif mean_luma > 170.0:
        gamma = float(np.clip(np.log(0.76) / np.log(min(mean_luma / 255.0, 0.999)), 1.02, 1.35))
        lut = np.clip((np.arange(256, dtype=np.float32) / 255.0) ** gamma * 255.0, 0, 255).astype(np.uint8)
        image = cv2.LUT(image, lut)
        reason = "HIGH_LIGHT_GAMMA_CLAHE"
    else:
        reason = "CLAHE_REFERENCE_BRANCH"

    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    enhanced = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
    return EnhancementOutput(enhanced, ENHANCED_PREPROCESSING, True, reason)
