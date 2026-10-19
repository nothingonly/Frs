from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.config import Settings
from app.schemas.contracts import DetectionState, QualityState
from app.vision.onnx_models import OnnxEmbeddingRecognizer, OnnxLivenessModel, sha256_file
from app.vision.quality import QualityMeasurements, assess_quality

logger = logging.getLogger(__name__)


class VisionError(RuntimeError):
    pass


@dataclass
class FrameObservation:
    frame_id: str
    image_bgr: np.ndarray
    detection_state: DetectionState
    detector_id: str
    detector_version: str
    bbox: np.ndarray | None
    keypoints: np.ndarray | None
    detection_confidence: float | None
    quality: QualityMeasurements | None
    primary_embedding: np.ndarray | None
    aligned_face_bgr: np.ndarray | None
    recognizer_id: str
    recognizer_version: str
    detection_latency_ms: float
    recognition_latency_ms: float
    frame_sha256: str


class VisionEngine:
    """Runs real model inference. It never substitutes generated or synthetic identity scores."""

    def __init__(self, settings: Settings):
        self.settings = settings
        root = Path(settings.model_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._provider = settings.model_provider
        self._ctx_id = 0 if self._provider == "CUDAExecutionProvider" else -1

        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise VisionError("InsightFace is required for the SCRFD + ArcFace baseline") from exc

        logger.info(
            "Loading real face models: model_pack=%s, root=%s, provider=%s",
            settings.model_pack, root, self._provider,
        )
        # InsightFace may download its selected model pack on first load. Verify the
        # exact model-weight license before real deployment; the default public packs
        # are restricted to non-commercial research absent a separate license.
        self.face_app = FaceAnalysis(
            name=settings.model_pack,
            root=str(root),
            allowed_modules=["detection", "recognition"],
            providers=[self._provider],
        )
        self.face_app.prepare(ctx_id=self._ctx_id, det_size=(settings.detect_size, settings.detect_size))
        self.detector = self.face_app.models.get("detection")
        self.recognizer = self.face_app.models.get("recognition")
        if self.detector is None or self.recognizer is None:
            raise VisionError("Selected model pack must contain real detection and recognition models")

        detector_class = type(self.detector).__name__
        recognizer_class = type(self.recognizer).__name__
        self.detector_id = "SCRFD" if "scrfd" in detector_class.lower() else detector_class
        self.recognizer_id = "ArcFace" if "arcface" in recognizer_class.lower() else recognizer_class
        self.detector_version = self._model_version(self.detector)
        self.recognizer_version = self._model_version(self.recognizer)
        self.pipeline_version = f"frs-v5:{settings.model_pack}:{self.detector_version}:{self.recognizer_version}"

        self.recovery_detector = None
        self.recovery_detector_version = ""
        if settings.retinaface_onnx_path.strip():
            from insightface.model_zoo import get_model

            path = Path(settings.retinaface_onnx_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Configured recovery detector not found: {path}")
            self.recovery_detector = get_model(str(path), providers=[self._provider])
            self.recovery_detector.prepare(ctx_id=self._ctx_id, det_size=(settings.detect_size, settings.detect_size))
            if "retina" not in type(self.recovery_detector).__name__.lower():
                raise VisionError(
                    "FRS_RETINAFACE_ONNX_PATH did not load a RetinaFace implementation; "
                    "refusing to silently mislabel a different detector."
                )
            self.recovery_detector_version = sha256_file(path)[:16]

        self.adaface = (
            OnnxEmbeddingRecognizer(settings.adaface_onnx_path, self._provider, recognizer_id="AdaFace")
            if settings.adaface_onnx_path.strip() else None
        )
        self.mobilefacenet = (
            OnnxEmbeddingRecognizer(settings.mobilefacenet_onnx_path, self._provider, recognizer_id="MobileFaceNet")
            if settings.mobilefacenet_onnx_path.strip() else None
        )
        self.liveness = (
            OnnxLivenessModel(settings.minifasnet_onnx_path, self._provider)
            if settings.minifasnet_onnx_path.strip() else None
        )

    @staticmethod
    def _model_version(model: object) -> str:
        model_file = getattr(model, "model_file", None)
        if model_file and Path(str(model_file)).is_file():
            return sha256_file(Path(str(model_file)))[:16]
        return type(model).__name__

    @property
    def component_status(self) -> dict[str, str]:
        return {
            "detection_primary": f"READY:{self.detector_id}:{self.detector_version}",
            "recognition_primary": f"READY:{self.recognizer_id}:{self.recognizer_version}",
            "detection_recovery": (
                f"READY:RetinaFace:{self.recovery_detector_version}"
                if self.recovery_detector else "UNCONFIGURED"
            ),
            "recognition_adaface": f"READY:{self.adaface.model_version}" if self.adaface else "UNCONFIGURED",
            "recognition_mobilefacenet": (
                f"READY:{self.mobilefacenet.model_version}" if self.mobilefacenet else "UNCONFIGURED"
            ),
            "liveness_minifasnet": (
                f"READY:{self.liveness.model_version}" if self.liveness else "UNCONFIGURED"
            ),
        }

    @staticmethod
    def _decode_image(image_bytes: bytes) -> np.ndarray:
        if not image_bytes:
            raise VisionError("Empty image payload")
        decoded = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.size == 0:
            raise VisionError("Image cannot be decoded; submit a valid JPEG or PNG")
        return decoded

    @staticmethod
    def _detect(detector: object, image: np.ndarray, max_num: int = 0):
        return detector.detect(image, max_num=max_num, metric="default")

    def _extract_embedding(self, aligned_bgr: np.ndarray) -> np.ndarray:
        vector = np.asarray(self.recognizer.get_feat(aligned_bgr), dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if vector.size == 0 or not np.all(np.isfinite(vector)) or norm <= 1e-12:
            raise VisionError(f"{self.recognizer_id} produced an invalid embedding")
        return vector / norm

    def primary_embedding(self, aligned_bgr: np.ndarray) -> np.ndarray:
        """Run the configured primary recognizer on a previously quality-gated aligned crop."""
        return self._extract_embedding(aligned_bgr)

    def analyze(self, image_bytes: bytes, frame_id: str) -> FrameObservation:
        image = self._decode_image(image_bytes)
        frame_hash = hashlib.sha256(image_bytes).hexdigest()
        start = time.perf_counter()
        try:
            bboxes, keypoints = self._detect(self.detector, image)
        except Exception as exc:
            raise VisionError(f"Primary detector inference failed: {type(exc).__name__}") from exc
        detector_latency = (time.perf_counter() - start) * 1000.0
        detector_id, detector_version = self.detector_id, self.detector_version

        if len(bboxes) == 0 and self.recovery_detector is not None:
            recovery_start = time.perf_counter()
            try:
                bboxes, keypoints = self._detect(self.recovery_detector, image)
            except Exception as exc:
                raise VisionError(f"RetinaFace recovery detector failed: {type(exc).__name__}") from exc
            detector_latency += (time.perf_counter() - recovery_start) * 1000.0
            if len(bboxes) > 0:
                detector_id = "RetinaFace"
                detector_version = self.recovery_detector_version

        if len(bboxes) == 0:
            return FrameObservation(
                frame_id=frame_id, image_bgr=image, detection_state=DetectionState.NO_FACE,
                detector_id=detector_id, detector_version=detector_version, bbox=None, keypoints=None,
                detection_confidence=None, quality=None, primary_embedding=None, aligned_face_bgr=None,
                recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
                detection_latency_ms=detector_latency, recognition_latency_ms=0.0, frame_sha256=frame_hash,
            )

        if len(bboxes) != 1:
            return FrameObservation(
                frame_id=frame_id, image_bgr=image, detection_state=DetectionState.MULTIPLE_FACES,
                detector_id=detector_id, detector_version=detector_version, bbox=None, keypoints=None,
                detection_confidence=None, quality=None, primary_embedding=None, aligned_face_bgr=None,
                recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
                detection_latency_ms=detector_latency, recognition_latency_ms=0.0, frame_sha256=frame_hash,
            )

        box = np.asarray(bboxes[0], dtype=np.float32)
        kps = np.asarray(keypoints[0], dtype=np.float32) if keypoints is not None else None
        measurements = assess_quality(image, box, kps, self.settings) if kps is not None else assess_quality(
            image, box, np.empty((0, 2), dtype=np.float32), self.settings
        )
        if measurements.result.status == QualityState.RECAPTURE:
            return FrameObservation(
                frame_id=frame_id, image_bgr=image, detection_state=DetectionState.OK,
                detector_id=detector_id, detector_version=detector_version, bbox=box, keypoints=kps,
                detection_confidence=float(box[4]) if box.size > 4 else None,
                quality=measurements, primary_embedding=None, aligned_face_bgr=None,
                recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
                detection_latency_ms=detector_latency, recognition_latency_ms=0.0, frame_sha256=frame_hash,
            )
        if kps is None or kps.shape != (5, 2):
            measurements.result.status = QualityState.RECAPTURE
            measurements.result.failure_codes.append("LANDMARKS_REQUIRED_FOR_ALIGNMENT")
            measurements.result.route_hint = "RECAPTURE"
            return FrameObservation(
                frame_id=frame_id, image_bgr=image, detection_state=DetectionState.OK,
                detector_id=detector_id, detector_version=detector_version, bbox=box, keypoints=kps,
                detection_confidence=float(box[4]) if box.size > 4 else None,
                quality=measurements, primary_embedding=None, aligned_face_bgr=None,
                recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
                detection_latency_ms=detector_latency, recognition_latency_ms=0.0, frame_sha256=frame_hash,
            )

        from insightface.utils.face_align import norm_crop

        align_start = time.perf_counter()
        aligned = norm_crop(image, kps, image_size=getattr(self.recognizer, "input_size", (112, 112))[0])
        align_time = (time.perf_counter() - align_start) * 1000.0
        # Do not run ArcFace on degraded frames. The orchestrator must choose AdaFace
        # (or abstain/recapture when that specialist is unavailable) for this route.
        if measurements.result.status == QualityState.DEGRADED:
            return FrameObservation(
                frame_id=frame_id, image_bgr=image, detection_state=DetectionState.OK,
                detector_id=detector_id, detector_version=detector_version, bbox=box, keypoints=kps,
                detection_confidence=float(box[4]) if box.size > 4 else None,
                quality=measurements, primary_embedding=None, aligned_face_bgr=aligned,
                recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
                detection_latency_ms=detector_latency, recognition_latency_ms=0.0, frame_sha256=frame_hash,
            )
        recognition_start = time.perf_counter()
        embedding = self._extract_embedding(aligned)
        recognition_latency = align_time + (time.perf_counter() - recognition_start) * 1000.0
        return FrameObservation(
            frame_id=frame_id, image_bgr=image, detection_state=DetectionState.OK,
            detector_id=detector_id, detector_version=detector_version, bbox=box, keypoints=kps,
            detection_confidence=float(box[4]) if box.size > 4 else None,
            quality=measurements, primary_embedding=embedding, aligned_face_bgr=aligned,
            recognizer_id=self.recognizer_id, recognizer_version=self.recognizer_version,
            detection_latency_ms=detector_latency, recognition_latency_ms=recognition_latency,
            frame_sha256=frame_hash,
        )

    def secondary_embedding(self, recognizer_id: str, aligned_face_bgr: np.ndarray) -> tuple[np.ndarray, str, str]:
        if recognizer_id == "AdaFace" and self.adaface:
            return self.adaface.embed(aligned_face_bgr), "AdaFace", self.adaface.model_version
        if recognizer_id == "MobileFaceNet" and self.mobilefacenet:
            return self.mobilefacenet.embed(aligned_face_bgr), "MobileFaceNet", self.mobilefacenet.model_version
        raise VisionError(f"Requested recognizer {recognizer_id} is not configured with a real model artifact")

    def liveness_probability(self, observation: FrameObservation) -> float:
        if self.liveness is None:
            raise VisionError("Liveness is required by policy but no MiniFASNet ONNX artifact is configured")
        if observation.bbox is None:
            raise VisionError("Cannot run liveness without a single detected face")
        box = observation.bbox
        h, w = observation.image_bgr.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in box[:4]]
        bw, bh = x2 - x1, y2 - y1
        scale = 1.35
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        sx, sy = bw * scale / 2, bh * scale / 2
        left, top = max(0, int(cx - sx)), max(0, int(cy - sy))
        right, bottom = min(w, int(cx + sx)), min(h, int(cy + sy))
        crop = observation.image_bgr[top:bottom, left:right]
        if crop.size == 0:
            raise VisionError("Liveness face crop is empty")
        return self.liveness.predict_live_probability(crop)
