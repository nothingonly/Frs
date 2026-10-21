from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class OnnxTensorModel:
    """An explicit ONNX input/output contract; unsupported or malformed models fail closed."""

    def __init__(self, model_path: str, provider: str, *, kind: str):
        self.path = Path(model_path).expanduser().resolve()
        if not self.path.is_file():
            raise FileNotFoundError(f"Configured {kind} ONNX artifact does not exist: {self.path}")
        self.config_path = self.path.with_suffix(self.path.suffix + ".json")
        if not self.config_path.is_file():
            raise FileNotFoundError(
                f"Missing model contract sidecar {self.config_path}; input normalization and output "
                "semantics must be declared instead of guessed."
            )
        self.contract: dict[str, Any] = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.kind = kind
        for required in ("license_name", "source_url", "permitted_use", "preprocessing_id", "output_type", "sha256"):
            value = self.contract.get(required)
            if not isinstance(value, str) or not value.strip() or value.lower().startswith("replace"):
                raise ValueError(f"{kind} sidecar must declare a real {required}")
        self.license_name = self.contract["license_name"]
        self.source_url = self.contract["source_url"]
        self.permitted_use = self.contract["permitted_use"]
        self.preprocessing_id = self.contract["preprocessing_id"]

        # Provenance: publisher and training dataset (record as unresolved if unknown, reject placeholder values)
        publisher_val = self.contract.get("publisher", "unresolved")
        if isinstance(publisher_val, str) and publisher_val.lower().startswith("replace"):
            raise ValueError(f"{kind} sidecar must declare a real publisher or record 'unresolved'")
        self.publisher = str(publisher_val).strip() or "unresolved"

        dataset_val = self.contract.get("training_dataset", "unresolved")
        if isinstance(dataset_val, str) and dataset_val.lower().startswith("replace"):
            raise ValueError(f"{kind} sidecar must declare a real training_dataset or record 'unresolved'")
        self.training_dataset = str(dataset_val).strip() or "unresolved"

        self.sha256 = sha256_file(self.path)
        if self.contract["sha256"].lower() != self.sha256.lower():
            raise ValueError(f"{kind} model SHA-256 differs from its sidecar; refusing to run modified weights")
        self.session = ort.InferenceSession(str(self.path), providers=[provider])
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) < 1:
            raise ValueError(f"{kind} model must expose exactly one input and at least one output")
        self.input_name = inputs[0].name
        self.output_name = self.contract.get("output_name", outputs[0].name)
        if self.output_name not in {item.name for item in outputs}:
            raise ValueError(f"{kind} sidecar output_name is not present in the ONNX graph")
        shape = inputs[0].shape
        self.layout = str(self.contract.get("layout", "NCHW")).upper()
        if self.layout not in {"NCHW", "NHWC"}:
            raise ValueError(f"{kind} layout must be NCHW or NHWC")
        if self.layout == "NCHW":
            self.height = int(self.contract.get("height", shape[2] if isinstance(shape[2], int) else 112))
            self.width = int(self.contract.get("width", shape[3] if isinstance(shape[3], int) else 112))
        else:
            self.height = int(self.contract.get("height", shape[1] if isinstance(shape[1], int) else 112))
            self.width = int(self.contract.get("width", shape[2] if isinstance(shape[2], int) else 112))
        self.color_order = str(self.contract.get("color_order", "RGB")).upper()
        self.mean = float(self.contract.get("mean", 127.5))
        self.std = float(self.contract.get("std", 128.0))
        if self.width <= 0 or self.height <= 0 or self.std <= 0:
            raise ValueError(f"Invalid input contract for {kind}")

    @property
    def provenance_record(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "file": self.path.name,
            "sha256": self.sha256,
            "version": self.sha256[:16],
            "source_url": self.source_url,
            "publisher": self.publisher,
            "training_dataset": self.training_dataset,
            "license_name": self.license_name,
            "permitted_use": self.permitted_use,
            "preprocessing_id": self.preprocessing_id,
            "output_type": self.contract.get("output_type"),
            "input_shape": [1, 3, self.height, self.width] if self.layout == "NCHW" else [1, self.height, self.width, 3],
        }

    def input_tensor(self, image_bgr: np.ndarray) -> np.ndarray:
        resized = cv2.resize(image_bgr, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
        if self.color_order == "RGB":
            resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        elif self.color_order != "BGR":
            raise ValueError(f"Unsupported color_order {self.color_order} in {self.path.name}")
        tensor = (resized.astype(np.float32) - self.mean) / self.std
        if self.layout == "NCHW":
            tensor = np.transpose(tensor, (2, 0, 1))
        return np.expand_dims(tensor.astype(np.float32), axis=0)

    def run(self, image_bgr: np.ndarray) -> np.ndarray:
        values = self.session.run([self.output_name], {self.input_name: self.input_tensor(image_bgr)})
        output = np.asarray(values[0], dtype=np.float32).reshape(-1)
        if output.size == 0 or not np.all(np.isfinite(output)):
            raise ValueError(f"{self.kind} ONNX model produced an invalid output")
        return output


class OnnxEmbeddingRecognizer(OnnxTensorModel):
    def __init__(self, model_path: str, provider: str, *, recognizer_id: str):
        super().__init__(model_path, provider, kind=recognizer_id)
        if self.contract.get("output_type", "embedding") != "embedding":
            raise ValueError(f"{recognizer_id} sidecar must declare output_type=embedding")
        self.recognizer_id = recognizer_id
        self.model_version = self.sha256[:16]

    def embed(self, aligned_face_bgr: np.ndarray) -> np.ndarray:
        vector = self.run(aligned_face_bgr)
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-12:
            raise ValueError(f"{self.recognizer_id} produced a zero embedding")
        return vector / norm


class OnnxLivenessModel(OnnxTensorModel):
    def __init__(self, model_path: str, provider: str):
        super().__init__(model_path, provider, kind="MiniFASNet liveness")
        if self.contract.get("output_type") != "logits":
            raise ValueError("MiniFASNet sidecar must declare output_type=logits")
        self.live_class_index = int(self.contract["live_class_index"])
        self.model_version = self.sha256[:16]

    def predict_live_probability(self, face_crop_bgr: np.ndarray) -> float:
        logits = self.run(face_crop_bgr)
        if self.live_class_index < 0 or self.live_class_index >= logits.size:
            raise ValueError("Configured live_class_index is outside the ONNX output")
        logits = logits.astype(np.float64)
        logits -= np.max(logits)
        probs = np.exp(logits)
        probs /= np.sum(probs)
        return float(probs[self.live_class_index])



class OnnxQualityScorer(OnnxTensorModel):
    def __init__(self, model_path: str, provider: str):
        super().__init__(model_path, provider, kind="learned FIQA")
        if self.contract.get("output_type") != "quality_score":
            raise ValueError("FIQA sidecar must declare output_type=quality_score")
        self.model_version = self.sha256[:16]
        self.activation = str(self.contract.get("score_activation", "none")).lower()
        if self.activation not in {"none", "sigmoid"}:
            raise ValueError("FIQA score_activation must be none or sigmoid")

    def score(self, aligned_face_bgr: np.ndarray) -> float:
        values = self.run(aligned_face_bgr).astype(np.float64)
        if values.size != 1:
            raise ValueError("FIQA model must return one scalar quality score")
        value = float(values[0])
        if self.activation == "sigmoid":
            value = 1.0 / (1.0 + np.exp(-np.clip(value, -80.0, 80.0)))
        if not np.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError("FIQA quality score must be finite and in [0, 1]")
        return value


_REFERENCE_5PTS = np.array([
    [38.2946, 51.6963],
    [73.5318, 51.5014],
    [56.0252, 71.7366],
    [41.5493, 92.3655],
    [70.7299, 92.2041],
], dtype=np.float32)


def norm_crop(img: np.ndarray, landmark: np.ndarray, image_size: int = 112) -> np.ndarray:
    """Align and crop face using 5 facial landmarks and reference 112x112 coordinates."""
    pts = np.asarray(landmark, dtype=np.float32)
    ref_pts = _REFERENCE_5PTS if image_size == 112 else _REFERENCE_5PTS * (float(image_size) / 112.0)
    tform, _ = cv2.estimateAffinePartial2D(pts, ref_pts)
    if tform is None:
        return cv2.resize(img, (image_size, image_size))
    return cv2.warpAffine(img, tform, (image_size, image_size), borderValue=0.0)


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, 0] + distance[:, i]
        py = points[:, 1] + distance[:, i + 1]
        preds.extend([px, py])
    stacked = np.stack(preds, axis=-1)
    return stacked.reshape((stacked.shape[0], -1, 2))


class SCRFDDetector:
    """Pure ONNX runtime implementation of SCRFD face detector."""

    def __init__(self, model_file: str | Path, provider: str = "CPUExecutionProvider", det_size: int = 640):
        self.model_file = str(Path(model_file).resolve())
        self.session = ort.InferenceSession(self.model_file, providers=[provider])
        self.center_cache: dict[tuple[int, int, int], np.ndarray] = {}
        self.fmc = 3
        self._feat_stride_fpn = [8, 16, 32]
        self._num_anchors = 2
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = (det_size, det_size)

    def prepare(self, ctx_id: int = -1, det_size: tuple[int, int] = (640, 640)) -> None:
        self.input_size = det_size

    def detect(
        self,
        img: np.ndarray,
        thresh: float = 0.5,
        max_num: int = 0,
        metric: str = "default",
    ) -> tuple[np.ndarray, np.ndarray]:
        input_size = self.input_size
        im_ratio = float(img.shape[0]) / img.shape[1]
        model_ratio = float(input_size[1]) / input_size[0]
        if im_ratio > model_ratio:
            new_height = input_size[1]
            new_width = int(new_height / im_ratio)
        else:
            new_width = input_size[0]
            new_height = int(new_width * im_ratio)
        det_scale = float(new_height) / img.shape[0]
        resized_img = cv2.resize(img, (new_width, new_height))
        det_img = np.zeros((input_size[1], input_size[0], 3), dtype=np.uint8)
        det_img[:new_height, :new_width, :] = resized_img

        scores_list = []
        bboxes_list = []
        kpss_list = []
        blob = cv2.dnn.blobFromImage(det_img, 1.0 / 128.0, input_size, (127.5, 127.5, 127.5), swapRB=True)
        net_outs = self.session.run(None, {self.input_name: blob})

        input_height = blob.shape[2]
        input_width = blob.shape[3]
        fmc = self.fmc
        for idx, stride in enumerate(self._feat_stride_fpn):
            score = net_outs[idx]
            bbox = net_outs[idx + fmc] * stride
            kps = net_outs[idx + fmc * 2] * stride
            height = input_height // stride
            width = input_width // stride
            key = (height, width, stride)
            if key in self.center_cache:
                anchor_centers = self.center_cache[key]
            else:
                anchor_centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
                anchor_centers = (anchor_centers * stride).reshape((-1, 2))
                if self._num_anchors > 1:
                    anchor_centers = np.stack([anchor_centers] * self._num_anchors, axis=1).reshape((-1, 2))
                if len(self.center_cache) < 100:
                    self.center_cache[key] = anchor_centers

            pos_inds = np.where(score >= thresh)[0]
            if len(pos_inds) > 0:
                bboxes = _distance2bbox(anchor_centers[pos_inds], bbox[pos_inds])
                scores_list.append(score[pos_inds])
                bboxes_list.append(bboxes)

                kpss = _distance2kps(anchor_centers[pos_inds], kps[pos_inds])
                kpss_list.append(kpss)

        if not scores_list:
            return np.empty((0, 5), dtype=np.float32), np.empty((0, 5, 2), dtype=np.float32)

        scores = np.vstack(scores_list)
        bboxes = np.vstack(bboxes_list) / det_scale
        kpss = np.vstack(kpss_list) / det_scale

        bboxes = np.hstack([bboxes, scores])
        # cv2.dnn.NMSBoxes expects boxes in [x, y, w, h] format, not [x1, y1, x2, y2]
        nms_boxes = bboxes[:, :4].copy()
        nms_boxes[:, 2] -= nms_boxes[:, 0]
        nms_boxes[:, 3] -= nms_boxes[:, 1]
        indices = cv2.dnn.NMSBoxes(nms_boxes.tolist(), bboxes[:, 4].tolist(), thresh, 0.4)
        if len(indices) == 0:
            return np.empty((0, 5), dtype=np.float32), np.empty((0, 5, 2), dtype=np.float32)

        flat_idx = np.array(indices).flatten()
        if max_num > 0 and len(flat_idx) > max_num:
            flat_idx = flat_idx[:max_num]
        return bboxes[flat_idx], kpss[flat_idx]


class ArcFaceRecognizer:
    """Pure ONNX runtime implementation of ArcFace feature recognizer."""

    def __init__(self, model_file: str | Path, provider: str = "CPUExecutionProvider"):
        self.model_file = str(Path(model_file).resolve())
        self.session = ort.InferenceSession(self.model_file, providers=[provider])
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        self.input_size = (112, 112)

    def prepare(self, ctx_id: int = -1) -> None:
        pass

    def get_feat(self, aligned_bgr: np.ndarray) -> np.ndarray:
        blob = cv2.dnn.blobFromImage(aligned_bgr, 1.0 / 128.0, (112, 112), (127.5, 127.5, 127.5), swapRB=True)
        return self.session.run([self.output_name], {self.input_name: blob})[0][0]

