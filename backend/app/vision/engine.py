from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.core.config import Settings
from app.schemas.contracts import DetectionState, QualityState
from app.vision.onnx_models import OnnxEmbeddingRecognizer, OnnxLivenessModel, OnnxQualityScorer, sha256_file
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


@dataclass
class GroupFaceObservation:
    face_index: int
    bbox: list[float]
    detection_confidence: float
    keypoints: list[list[float]] | None
    primary_embedding: np.ndarray | None
    quality_score: float
    is_usable: bool
    rejection_reason: str | None


class VisionEngine:
    """Runs real model inference. It never substitutes generated or synthetic identity scores."""

    def __init__(self, settings: Settings):
        self.settings = settings
        root = Path(settings.model_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._provider = settings.model_provider
        self._ctx_id = 0 if self._provider == "CUDAExecutionProvider" else -1

        # Do not allow a library convenience downloader to fetch unreviewed model weights.
        # Model artifacts must be separately provisioned with a verified license and checksum.
        pack_dir = root / "models" / settings.model_pack
        expected_pack_files = {"SCRFD": "det_10g.onnx", "ArcFace": "w600k_r50.onnx"}
        missing_pack = [name for name in expected_pack_files.values() if not (pack_dir / name).is_file()]
        if missing_pack:
            raise FileNotFoundError(
                f"Real SCRFD/ArcFace weights are missing from {pack_dir}: {', '.join(missing_pack)}. "
                "Provision properly licensed model artifacts and verify their published checksums; "
                "the application will not download unreviewed weights automatically."
            )
        pack_manifest_path = pack_dir / "manifest.json"
        if not pack_manifest_path.is_file():
            raise FileNotFoundError(
                f"Missing primary model provenance manifest: {pack_manifest_path}. "
                "Every weight must have a verified SHA-256, immutable source, license and permitted-use record."
            )
        pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
        self.primary_model_provenance: dict[str, dict[str, str]] = {}
        manifest_models = pack_manifest.get("models")
        if not isinstance(manifest_models, dict):
            raise ValueError("Primary model manifest must contain a models object keyed by SCRFD and ArcFace")
        for role, filename in expected_pack_files.items():
            record = manifest_models.get(role)
            if not isinstance(record, dict):
                raise ValueError(f"Primary model manifest has no provenance record for {role}")
            for field in ("file", "sha256", "source_url", "license_name", "permitted_use"):
                value = record.get(field)
                if not isinstance(value, str) or not value.strip() or value.lower().startswith("replace"):
                    raise ValueError(f"Primary model manifest requires a real {field} for {role}")
            if record["file"] != filename:
                raise ValueError(f"Primary manifest file for {role} must match {filename}")
            actual_sha = sha256_file(pack_dir / filename)
            if record["sha256"].lower() != actual_sha.lower():
                raise ValueError(f"Primary model SHA-256 mismatch for {role}; refusing to load modified/unverified weights")
            publisher = record.get("publisher", "unresolved")
            if isinstance(publisher, str) and publisher.lower().startswith("replace"):
                raise ValueError(f"Primary model manifest requires a real publisher for {role}")
            training_dataset = record.get("training_dataset", "unresolved")
            if isinstance(training_dataset, str) and training_dataset.lower().startswith("replace"):
                raise ValueError(f"Primary model manifest requires a real training_dataset for {role}")
            self.primary_model_provenance[role] = {
                **dict(record),
                "publisher": str(publisher).strip() or "unresolved",
                "training_dataset": str(training_dataset).strip() or "unresolved",
            }

        if settings.env.lower() == "production" and not settings.model_license_attested:
            for role, prov in self.primary_model_provenance.items():
                perm = prov.get("permitted_use", "").lower()
                lic = prov.get("license_name", "").lower()
                if "research" in perm or "academic" in perm or "non-commercial" in lic:
                    raise VisionError(
                        f"Production startup blocked: {role} weights have non-commercial terms ({prov.get('license_name')}). "
                        "Commercial license clearance or permissible weights must be attested via FRS_MODEL_LICENSE_ATTESTED."
                    )

        try:
            from insightface.app import FaceAnalysis

            logger.info(
                "Loading real face models via FaceAnalysis: model_pack=%s, root=%s, provider=%s",
                settings.model_pack, root, self._provider,
            )
            self.face_app = FaceAnalysis(
                name=settings.model_pack,
                root=str(root),
                allowed_modules=["detection", "recognition"],
                providers=[self._provider],
            )
            self.face_app.prepare(ctx_id=self._ctx_id, det_size=(settings.detect_size, settings.detect_size))
            self.detector = self.face_app.models.get("detection")
            self.recognizer = self.face_app.models.get("recognition")
        except ImportError:
            logger.info(
                "FaceAnalysis package unavailable; loading verified Buffalo_L ONNX artifacts directly via ONNX Runtime: %s",
                pack_dir,
            )
            from app.vision.onnx_models import ArcFaceRecognizer, SCRFDDetector

            self.face_app = None
            self.detector = SCRFDDetector(pack_dir / expected_pack_files["SCRFD"], provider=self._provider, det_size=settings.detect_size)
            self.recognizer = ArcFaceRecognizer(pack_dir / expected_pack_files["ArcFace"], provider=self._provider)

        if self.detector is None or self.recognizer is None:
            raise VisionError("Selected model pack must contain real detection and recognition models")

        detector_class = type(self.detector).__name__
        recognizer_class = type(self.recognizer).__name__
        if "scrfd" not in detector_class.lower() or "arcface" not in recognizer_class.lower():
            raise VisionError(
                f"Selected model pack is not the required SCRFD + ArcFace baseline "
                f"(loaded {detector_class} and {recognizer_class})."
            )
        self.detector_id = "SCRFD"
        self.recognizer_id = "ArcFace"
        self.detector_version = self._model_version(self.detector)
        self.recognizer_version = self._model_version(self.recognizer)
        if Path(str(getattr(self.detector, "model_file", ""))).resolve() != (pack_dir / expected_pack_files["SCRFD"]).resolve():
            raise VisionError("Loaded detector path differs from the provenance-verified SCRFD artifact")
        if Path(str(getattr(self.recognizer, "model_file", ""))).resolve() != (pack_dir / expected_pack_files["ArcFace"]).resolve():
            raise VisionError("Loaded recognizer path differs from the provenance-verified ArcFace artifact")
        self.pipeline_version = f"frs-v5:{settings.model_pack}:{self.detector_version}:{self.recognizer_version}"

        self.recovery_detector = None
        self.recovery_detector_version = ""
        if settings.retinaface_onnx_path.strip():
            try:
                from insightface.model_zoo import get_model
            except ImportError as exc:
                raise VisionError(
                    "insightface library is required to load RetinaFace recovery detector"
                ) from exc

            path = Path(settings.retinaface_onnx_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Configured recovery detector not found: {path}")
            sidecar = path.with_suffix(path.suffix + ".json")
            if not sidecar.is_file():
                raise FileNotFoundError(f"RetinaFace artifact requires license/provenance sidecar: {sidecar}")
            retina_contract = json.loads(sidecar.read_text(encoding="utf-8"))
            for required in ("license_name", "source_url", "permitted_use", "preprocessing_id", "sha256"):
                if not isinstance(retina_contract.get(required), str) or not retina_contract[required].strip() or retina_contract[required].lower().startswith("replace"):
                    raise ValueError(f"RetinaFace sidecar must declare a real {required}")
            if retina_contract["sha256"].lower() != sha256_file(path).lower():
                raise ValueError("RetinaFace ONNX checksum differs from its sidecar; refusing to run modified weights")
            self.recovery_contract = retina_contract
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
        self.fiqa = (
            OnnxQualityScorer(settings.fiqa_onnx_path, self._provider)
            if settings.fiqa_onnx_path.strip() else None
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
            "quality_fiqa": f"READY:{self.fiqa.model_version}" if self.fiqa else "UNCONFIGURED",
        }

    @property
    def provenance(self) -> dict[str, Any]:
        return {
            "pack": self.settings.model_pack,
            "pipeline_version": self.pipeline_version,
            "primary": self.primary_model_provenance,
            "specialists": {
                "AdaFace": self.adaface.provenance_record if self.adaface else None,
                "MobileFaceNet": self.mobilefacenet.provenance_record if self.mobilefacenet else None,
                "MiniFASNet": self.liveness.provenance_record if self.liveness else None,
                "FIQA": self.fiqa.provenance_record if self.fiqa else None,
            },
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
        frame_hash = hashlib.sha256(np.ascontiguousarray(image).tobytes()).hexdigest()
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

        try:
            from insightface.utils.face_align import norm_crop
        except ImportError:
            from app.vision.onnx_models import norm_crop

        align_start = time.perf_counter()
        aligned = norm_crop(image, kps, image_size=getattr(self.recognizer, "input_size", (112, 112))[0])
        align_time = (time.perf_counter() - align_start) * 1000.0
        if self.fiqa is not None:
            try:
                fiqa_score = self.fiqa.score(aligned)
            except Exception as exc:
                raise VisionError(f"Learned FIQA inference failed: {type(exc).__name__}") from exc
            measurements.result.fiqa_score = fiqa_score
            if fiqa_score < self.settings.fiqa_min_quality_score:
                measurements.result.status = QualityState.DEGRADED
                measurements.result.route_hint = "DIFFICULT_QUALITY"
                measurements.result.failure_codes.append("LEARNED_FIQA_LOW_SCORE")
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

    def detect_all_faces(self, image_bytes: bytes) -> list[GroupFaceObservation]:
        """Detect and extract ArcFace embeddings for all usable faces in a multi-person group photo."""
        image = self._decode_image(image_bytes)
        try:
            from insightface.utils.face_align import norm_crop
        except ImportError:
            from app.vision.onnx_models import norm_crop

        try:
            bboxes, keypoints = self._detect(self.detector, image, max_num=0)
        except Exception as exc:
            raise VisionError(f"Primary detector inference failed: {type(exc).__name__}") from exc

        if len(bboxes) == 0 and self.recovery_detector is not None:
            try:
                bboxes, keypoints = self._detect(self.recovery_detector, image, max_num=0)
            except Exception as exc:
                raise VisionError(f"RetinaFace recovery detector failed: {type(exc).__name__}") from exc

        observations: list[GroupFaceObservation] = []
        for idx in range(len(bboxes)):
            box = np.asarray(bboxes[idx], dtype=np.float32)
            kps = np.asarray(keypoints[idx], dtype=np.float32) if keypoints is not None and len(keypoints) > idx else None
            conf = float(box[4]) if box.size > 4 else 1.0
            x1, y1, x2, y2 = [float(v) for v in box[:4]]
            bw, bh = x2 - x1, y2 - y1

            if conf < 0.40:
                observations.append(GroupFaceObservation(
                    face_index=idx,
                    bbox=[x1, y1, x2, y2],
                    detection_confidence=conf,
                    keypoints=kps.tolist() if kps is not None else None,
                    primary_embedding=None,
                    quality_score=conf,
                    is_usable=False,
                    rejection_reason="LOW_DETECTION_CONFIDENCE",
                ))
                continue

            if bw < 14 or bh < 14:
                observations.append(GroupFaceObservation(
                    face_index=idx,
                    bbox=[x1, y1, x2, y2],
                    detection_confidence=conf,
                    keypoints=kps.tolist() if kps is not None else None,
                    primary_embedding=None,
                    quality_score=conf,
                    is_usable=False,
                    rejection_reason="FACE_TOO_SMALL",
                ))
                continue

            if kps is None or kps.shape != (5, 2):
                observations.append(GroupFaceObservation(
                    face_index=idx,
                    bbox=[x1, y1, x2, y2],
                    detection_confidence=conf,
                    keypoints=None,
                    primary_embedding=None,
                    quality_score=conf,
                    is_usable=False,
                    rejection_reason="LANDMARKS_MISSING",
                ))
                continue

            try:
                aligned = norm_crop(image, kps, image_size=getattr(self.recognizer, "input_size", (112, 112))[0])
                embedding = self._extract_embedding(aligned)
                gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                observations.append(GroupFaceObservation(
                    face_index=idx,
                    bbox=[x1, y1, x2, y2],
                    detection_confidence=conf,
                    keypoints=kps.tolist(),
                    primary_embedding=embedding,
                    quality_score=sharpness,
                    is_usable=True,
                    rejection_reason=None,
                ))
            except Exception as exc:
                observations.append(GroupFaceObservation(
                    face_index=idx,
                    bbox=[x1, y1, x2, y2],
                    detection_confidence=conf,
                    keypoints=kps.tolist() if kps is not None else None,
                    primary_embedding=None,
                    quality_score=conf,
                    is_usable=False,
                    rejection_reason=f"ALIGNMENT_OR_EMBEDDING_FAILED:{type(exc).__name__}",
                ))

        return observations
