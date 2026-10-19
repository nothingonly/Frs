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
        for required in ("license_name", "source_url", "preprocessing_id", "output_type"):
            value = self.contract.get(required)
            if not isinstance(value, str) or not value.strip() or value.lower().startswith("replace"):
                raise ValueError(f"{kind} sidecar must declare a real {required}")
        self.license_name = self.contract["license_name"]
        self.source_url = self.contract["source_url"]
        self.preprocessing_id = self.contract["preprocessing_id"]
        self.sha256 = sha256_file(self.path)
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
