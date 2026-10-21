from __future__ import annotations

import time
from dataclasses import dataclass
import cv2
import numpy as np

from app.core.config import Settings
from app.schemas.contracts import PoseResult, QualityResult, QualityState


@dataclass(frozen=True)
class QualityMeasurements:
    result: QualityResult
    pose: tuple[float, float, float] | None


def _estimate_pose(kps: np.ndarray, width: int, height: int) -> tuple[float, float, float] | None:
    """Estimate pose from five landmarks; values are routing evidence, not biometric identity."""
    if kps.shape != (5, 2) or width < 2 or height < 2:
        return None
    # Five-point generic face template. Validate/calibrate its operating ranges per camera.
    model_points = np.array([
        [-32.0, -28.0, -25.0],
        [32.0, -28.0, -25.0],
        [0.0, 0.0, 0.0],
        [-24.0, 28.0, -20.0],
        [24.0, 28.0, -20.0],
    ], dtype=np.float64)
    image_points = kps.astype(np.float64)
    focal = float(max(width, height))
    camera = np.array([
        [focal, 0.0, width / 2.0],
        [0.0, focal, height / 2.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    distortion = np.zeros((4, 1), dtype=np.float64)
    ok, rotation_vector, _ = cv2.solvePnP(
        model_points, image_points, camera, distortion, flags=cv2.SOLVEPNP_EPNP
    )
    if not ok:
        return None
    rotation, _ = cv2.Rodrigues(rotation_vector)
    sy = float(np.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2))
    singular = sy < 1e-6
    if not singular:
        pitch = np.arctan2(rotation[2, 1], rotation[2, 2])
        yaw = np.arctan2(-rotation[2, 0], sy)
        roll = np.arctan2(rotation[1, 0], rotation[0, 0])
    else:
        pitch = np.arctan2(-rotation[1, 2], rotation[1, 1])
        yaw = np.arctan2(-rotation[2, 0], sy)
        roll = 0.0
    return tuple(float(np.degrees(v)) for v in (yaw, pitch, roll))


def assess_quality(
    image_bgr: np.ndarray,
    bbox: np.ndarray,
    keypoints: np.ndarray,
    settings: Settings,
) -> QualityMeasurements:
    started = time.perf_counter()
    image_h, image_w = image_bgr.shape[:2]
    x1, y1, x2, y2 = [int(round(float(v))) for v in bbox[:4]]
    x1, x2 = max(0, x1), min(image_w, x2)
    y1, y2 = max(0, y1), min(image_h, y2)
    face_w, face_h = max(0, x2 - x1), max(0, y2 - y1)
    face_size = min(face_w, face_h)

    failures: list[str] = []
    if face_w < 2 or face_h < 2:
        crop = np.empty((0, 0), dtype=np.uint8)
        blur_score = 0.0
        luminance = 0.0
        clipping_ratio = 1.0
        failures.append("INVALID_FACE_CROP")
    else:
        crop = image_bgr[y1:y2, x1:x2]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        luminance = float(gray.mean())
        clipping_ratio = float(np.mean((gray <= 5) | (gray >= 250)))

    pose_tuple = _estimate_pose(keypoints, image_w, image_h) if keypoints is not None else None
    pose = PoseResult()
    if pose_tuple is not None:
        pose = PoseResult(yaw=pose_tuple[0], pitch=pose_tuple[1], roll=pose_tuple[2])

    if face_size < settings.min_face_size_px:
        failures.append("FACE_TOO_SMALL")
    if blur_score < settings.min_laplacian_variance:
        failures.append("MOTION_OR_FOCUS_BLUR")
    if luminance < settings.min_mean_luminance:
        failures.append("UNDEREXPOSED")
    if luminance > settings.max_mean_luminance:
        failures.append("OVEREXPOSED")
    if clipping_ratio > settings.max_clipped_pixel_ratio:
        failures.append("EXCESSIVE_CLIPPING")
    if pose_tuple is None:
        failures.append("POSE_UNAVAILABLE")
    elif abs(pose_tuple[0]) > 35 or abs(pose_tuple[1]) > 30:
        failures.append("EXTREME_POSE")

    # Moderate exposure problems route through the conditional enhancement branch;
    # extreme clipping remains unrecoverable and requests a new capture.
    exposure_unrecoverable = luminance < 8.0 or luminance > 248.0
    hard_failure = any(code in failures for code in (
        "INVALID_FACE_CROP", "FACE_TOO_SMALL", "MOTION_OR_FOCUS_BLUR", "EXCESSIVE_CLIPPING"
    )) or exposure_unrecoverable
    degraded_only = any(code in failures for code in ("EXTREME_POSE", "POSE_UNAVAILABLE"))
    if hard_failure:
        state = QualityState.RECAPTURE
        route_hint = "RECAPTURE"
    elif degraded_only or failures:
        state = QualityState.DEGRADED
        route_hint = "DIFFICULT_QUALITY"
    else:
        state = QualityState.GOOD
        route_hint = "FAST"

    result = QualityResult(
        status=state,
        face_size_px=face_size,
        blur_score=blur_score,
        mean_luminance=luminance,
        clipped_pixel_ratio=clipping_ratio,
        pose=pose,
        alignment_score=None,
        route_hint=route_hint,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        failure_codes=failures,
    )
    return QualityMeasurements(result=result, pose=pose_tuple)
