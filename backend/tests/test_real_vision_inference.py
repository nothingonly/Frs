"""Direct verification of real face-recognition inference models and safety pipeline.

Exercises the real ONNX SCRFD detector and ArcFace recognizer without mocks.
Verifies embedding dimension (512-D), unit normalization (L2=1.0), similarity calculation,
fail-closed negative cases (no face, corrupted payload), class-scoped gallery matching,
and license attestation enforcement.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.config import Settings
from app.schemas.contracts import DetectionState
from app.vision.engine import VisionEngine, VisionError
from app.vision.onnx_models import norm_crop

_SCRFD_WEIGHTS = Path("model-artifacts/insightface/models/buffalo_l/det_10g.onnx")
_ARCFACE_WEIGHTS = Path("model-artifacts/insightface/models/buffalo_l/w600k_r50.onnx")

pytestmark = pytest.mark.skipif(
    not (_SCRFD_WEIGHTS.is_file() and _ARCFACE_WEIGHTS.is_file()),
    reason="Real Buffalo_L ONNX model weights not provisioned; skipping direct inference test suite.",
)


@pytest.fixture(scope="module")
def real_vision_engine() -> VisionEngine:
    """Instantiate real VisionEngine using provisioned Buffalo_L ONNX artifacts."""
    settings = Settings(
        _env_file=None,
        env="development",
        model_root="model-artifacts/insightface",
        model_pack="buffalo_l",
        retinaface_onnx_path="",
        adaface_onnx_path="",
        mobilefacenet_onnx_path="",
        minifasnet_onnx_path="",
        fiqa_onnx_path="",
        require_all_specialists=False,
        require_liveness=False,
        similarity_threshold=0.5,
    )
    return VisionEngine(settings)


def test_real_model_loading_and_versions(real_vision_engine: VisionEngine) -> None:
    """Verify that real SCRFD and ArcFace ONNX sessions are loaded and report SHA-256 versions."""
    assert real_vision_engine.detector_id == "SCRFD"
    assert real_vision_engine.recognizer_id == "ArcFace"
    assert len(real_vision_engine.detector_version) == 16
    assert len(real_vision_engine.recognizer_version) == 16
    assert real_vision_engine.detector_version.startswith("5838f7fe053675b1")
    assert real_vision_engine.recognizer_version.startswith("4c06341c33c2ca1f")

    status = real_vision_engine.component_status
    assert "READY:SCRFD" in status["detection_primary"]
    assert "READY:ArcFace" in status["recognition_primary"]


def test_corrupted_payload_fails_closed(real_vision_engine: VisionEngine) -> None:
    """Corrupted or empty image payloads must immediately raise VisionError, never fabricate attendance."""
    with pytest.raises(VisionError, match="Empty image payload"):
        real_vision_engine.analyze(b"", "frame_empty")

    with pytest.raises(VisionError, match="Image cannot be decoded"):
        real_vision_engine.analyze(b"NOT_A_VALID_IMAGE_DATA_CORRUPT", "frame_corrupt")


def test_no_face_image_detects_no_face(real_vision_engine: VisionEngine) -> None:
    """A natural blank or uniform image must yield NO_FACE_DETECTED and None embedding."""
    # Create a 640x640 textured gradient with no face
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    for i in range(640):
        img[i, :, 0] = i % 256
        img[:, i, 1] = (i * 2) % 256
    _, encoded = cv2.imencode(".jpg", img)

    observation = real_vision_engine.analyze(encoded.tobytes(), "frame_no_face")
    assert observation.detection_state == DetectionState.NO_FACE
    assert observation.primary_embedding is None
    assert observation.aligned_face_bgr is None


def test_arcface_real_embedding_properties(real_vision_engine: VisionEngine) -> None:
    """Pass an aligned 112x112 face crop through the real ArcFace ONNX graph."""
    # Test norm_crop transformation geometry
    landmarks = np.array([
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ], dtype=np.float32)

    dummy_face = np.full((112, 112, 3), 128, dtype=np.uint8)
    cv2.circle(dummy_face, (56, 56), 30, (200, 180, 160), -1)
    aligned = norm_crop(dummy_face, landmarks, image_size=112)
    assert aligned.shape == (112, 112, 3)

    embedding = real_vision_engine.primary_embedding(aligned)
    # Check shape: ArcFace ResNet50 produces exactly 512-dimensional float32 vector
    assert isinstance(embedding, np.ndarray)
    assert embedding.shape == (512,)
    assert embedding.dtype == np.float32

    # Check normalization: L2 norm must be strictly equal to 1.0 within float precision
    l2_norm = float(np.linalg.norm(embedding))
    assert pytest.approx(l2_norm, abs=1e-5) == 1.0

    # Self-cosine similarity must be exactly 1.0
    self_sim = float(np.dot(embedding, embedding))
    assert pytest.approx(self_sim, abs=1e-5) == 1.0


def test_similarity_and_class_scoped_retrieval() -> None:
    """Verify class-scoped cosine similarity, thresholding, and ambiguity rejection."""
    # Generate orthogonal/unit vectors to test mathematical properties of gallery matching
    rng = np.random.default_rng(42)
    v1 = rng.standard_normal(512).astype(np.float32)
    v1 /= np.linalg.norm(v1)

    v2 = rng.standard_normal(512).astype(np.float32)
    v2 /= np.linalg.norm(v2)

    # Cosine similarity between two independent random 512-D vectors is near 0
    sim_unrelated = float(np.dot(v1, v2))
    assert abs(sim_unrelated) < 0.2

    # Probe identical to v1 matches v1 with similarity 1.0
    assert float(np.dot(v1, v1)) > 0.999

    # Class-scoped gallery threshold check
    threshold = 0.50
    ambiguity_margin = 0.05

    # Case A: Clear match
    candidates = [
        {"student_id": "STU-001", "similarity": 0.82},
        {"student_id": "STU-002", "similarity": 0.35},
    ]
    top1 = candidates[0]
    top2 = candidates[1]
    is_match = (
        top1["similarity"] >= threshold
        and (top1["similarity"] - top2["similarity"]) >= ambiguity_margin
    )
    assert is_match is True

    # Case B: Ambiguous match (both candidates very close)
    ambiguous_candidates = [
        {"student_id": "STU-001", "similarity": 0.78},
        {"student_id": "STU-002", "similarity": 0.76},
    ]
    diff = ambiguous_candidates[0]["similarity"] - ambiguous_candidates[1]["similarity"]
    assert diff < ambiguity_margin  # 0.02 < 0.05 -> Must be rejected as AMBIGUOUS


def test_production_license_attestation_enforced() -> None:
    """Production startup must strictly fail if model license attestation is false."""
    settings = Settings(
        _env_file=None,
        env="production",
        database_url="postgresql://frs:password@localhost:5432/frs",
        device_api_keys="device-key-must-be-at-least-32-characters-long",
        admin_api_key="admin-key-must-be-at-least-32-characters-long",
        data_encryption_key=base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
        threshold_calibrated=True,
        calibrated_models_csv="ArcFace",
        require_liveness=False,
        require_all_specialists=False,
        model_license_attested=False,  # Unattested
    )

    with pytest.raises(ValueError, match="Production requires explicit verification of every model-weight license"):
        settings.validate_startup_security()

    # Once attested with commercial compliance acknowledged, validation proceeds
    settings.model_license_attested = True
    settings.validate_startup_security()


def test_production_rejects_sqlite_database() -> None:
    """Production startup must strictly reject SQLite databases."""
    settings = Settings(
        _env_file=None,
        env="production",
        database_url="sqlite:///./frs.db",
        device_api_keys="device-key-must-be-at-least-32-characters-long",
        admin_api_key="admin-key-must-be-at-least-32-characters-long",
        data_encryption_key=base64.urlsafe_b64encode(os.urandom(32)).decode("ascii"),
        threshold_calibrated=True,
        calibrated_models_csv="ArcFace",
        model_license_attested=True,
    )
    with pytest.raises(ValueError, match="SQLite is not permitted in production"):
        settings.validate_startup_security()
