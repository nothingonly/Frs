from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.vision.engine import VisionEngine
from app.vision.onnx_models import OnnxTensorModel


def test_vision_engine_fails_when_weights_are_missing(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        env="test",
        model_root=str(tmp_path),
        model_pack="buffalo_l",
    )
    with pytest.raises(FileNotFoundError, match="Real SCRFD/ArcFace weights are missing"):
        VisionEngine(settings)


def test_vision_engine_fails_when_manifest_is_missing(tmp_path: Path) -> None:
    pack_dir = tmp_path / "models" / "buffalo_l"
    pack_dir.mkdir(parents=True)
    (pack_dir / "det_10g.onnx").write_bytes(b"dummy-scrfd-weights")
    (pack_dir / "w600k_r50.onnx").write_bytes(b"dummy-arcface-weights")

    settings = Settings(
        _env_file=None,
        env="test",
        model_root=str(tmp_path),
        model_pack="buffalo_l",
    )
    with pytest.raises(FileNotFoundError, match="Missing primary model provenance manifest"):
        VisionEngine(settings)


def test_vision_engine_rejects_placeholder_manifest_fields(tmp_path: Path) -> None:
    pack_dir = tmp_path / "models" / "buffalo_l"
    pack_dir.mkdir(parents=True)
    scrfd_bytes = b"dummy-scrfd-weights"
    arcface_bytes = b"dummy-arcface-weights"
    (pack_dir / "det_10g.onnx").write_bytes(scrfd_bytes)
    (pack_dir / "w600k_r50.onnx").write_bytes(arcface_bytes)

    manifest = {
        "manifest_version": 1,
        "models": {
            "SCRFD": {
                "file": "det_10g.onnx",
                "sha256": "REPLACE_WITH_ACTUAL_SHA256",
                "source_url": "https://example.invalid",
                "license_name": "InsightFace Research",
                "permitted_use": "Research",
            },
            "ArcFace": {
                "file": "w600k_r50.onnx",
                "sha256": hashlib.sha256(arcface_bytes).hexdigest(),
                "source_url": "https://example.invalid",
                "license_name": "InsightFace Research",
                "permitted_use": "Research",
            },
        },
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    settings = Settings(
        _env_file=None,
        env="test",
        model_root=str(tmp_path),
        model_pack="buffalo_l",
    )
    with pytest.raises(ValueError, match="Primary model manifest requires a real sha256 for SCRFD"):
        VisionEngine(settings)


def test_vision_engine_rejects_sha256_mismatch(tmp_path: Path) -> None:
    pack_dir = tmp_path / "models" / "buffalo_l"
    pack_dir.mkdir(parents=True)
    scrfd_bytes = b"dummy-scrfd-weights"
    arcface_bytes = b"dummy-arcface-weights"
    (pack_dir / "det_10g.onnx").write_bytes(scrfd_bytes)
    (pack_dir / "w600k_r50.onnx").write_bytes(arcface_bytes)

    manifest = {
        "manifest_version": 1,
        "models": {
            "SCRFD": {
                "file": "det_10g.onnx",
                "sha256": "0" * 64,
                "source_url": "https://example.invalid/scrfd",
                "license_name": "InsightFace Research",
                "permitted_use": "Research",
            },
            "ArcFace": {
                "file": "w600k_r50.onnx",
                "sha256": hashlib.sha256(arcface_bytes).hexdigest(),
                "source_url": "https://example.invalid/arcface",
                "license_name": "InsightFace Research",
                "permitted_use": "Research",
            },
        },
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    settings = Settings(
        _env_file=None,
        env="test",
        model_root=str(tmp_path),
        model_pack="buffalo_l",
    )
    with pytest.raises(ValueError, match="Primary model SHA-256 mismatch for SCRFD"):
        VisionEngine(settings)


def test_onnx_tensor_model_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="ONNX artifact does not exist"):
        OnnxTensorModel(str(tmp_path / "missing.onnx"), "CPUExecutionProvider", kind="test")


def test_onnx_tensor_model_rejects_missing_sidecar(tmp_path: Path) -> None:
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"dummy-onnx")
    with pytest.raises(FileNotFoundError, match="Missing model contract sidecar"):
        OnnxTensorModel(str(model_file), "CPUExecutionProvider", kind="test")


def test_onnx_tensor_model_rejects_placeholder_sidecar_fields(tmp_path: Path) -> None:
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"dummy-onnx")
    sidecar_file = tmp_path / "model.onnx.json"
    sidecar_file.write_text(
        json.dumps({
            "sha256": "REPLACE_WITH_ACTUAL_SHA256",
            "license_name": "MIT",
            "permitted_use": "Commercial",
            "source_url": "https://example.invalid",
            "preprocessing_id": "v1",
            "output_type": "embedding",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="test sidecar must declare a real sha256"):
        OnnxTensorModel(str(model_file), "CPUExecutionProvider", kind="test")


def test_onnx_tensor_model_rejects_checksum_mismatch(tmp_path: Path) -> None:
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"dummy-onnx")
    sidecar_file = tmp_path / "model.onnx.json"
    sidecar_file.write_text(
        json.dumps({
            "sha256": "0" * 64,
            "license_name": "MIT",
            "permitted_use": "Commercial",
            "source_url": "https://example.invalid",
            "preprocessing_id": "v1",
            "output_type": "embedding",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="model SHA-256 differs from its sidecar"):
        OnnxTensorModel(str(model_file), "CPUExecutionProvider", kind="test")
