from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from app.core.config import Settings
from app.vision.engine import VisionEngine
from app.vision.onnx_models import OnnxTensorModel
from scripts.provision_models import extract_and_verify


def test_model_provisioner_rejects_tar_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "malicious.tar.gz"
    target_dir = tmp_path / "models"
    outside_path = tmp_path / "escaped.txt"
    payload = b"must not escape target"

    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("../escaped.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    assert extract_and_verify(archive_path, target_dir) is False
    assert not outside_path.exists()


def test_model_provisioner_rejects_zip_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "malicious.zip"
    target_dir = tmp_path / "models"
    outside_path = tmp_path / "escaped.txt"

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escaped.txt", "must not escape target")

    assert extract_and_verify(archive_path, target_dir) is False
    assert not outside_path.exists()



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


def test_onnx_tensor_model_rejects_placeholder_publisher_or_dataset(tmp_path: Path) -> None:
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"dummy-onnx")
    actual_sha = hashlib.sha256(b"dummy-onnx").hexdigest()
    sidecar_file = tmp_path / "model.onnx.json"
    sidecar_file.write_text(
        json.dumps({
            "sha256": actual_sha,
            "license_name": "MIT",
            "permitted_use": "Commercial",
            "source_url": "https://example.invalid",
            "preprocessing_id": "v1",
            "output_type": "embedding",
            "publisher": "REPLACE_WITH_REAL_PUBLISHER",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="test sidecar must declare a real publisher or record 'unresolved'"):
        OnnxTensorModel(str(model_file), "CPUExecutionProvider", kind="test")


def test_vision_engine_rejects_placeholder_publisher(tmp_path: Path) -> None:
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
                "sha256": hashlib.sha256(scrfd_bytes).hexdigest(),
                "source_url": "https://example.invalid/scrfd",
                "license_name": "InsightFace Research",
                "permitted_use": "Research",
                "publisher": "REPLACE_WITH_REAL_PUBLISHER",
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
    with pytest.raises(ValueError, match="Primary model manifest requires a real publisher for SCRFD"):
        VisionEngine(settings)


def test_vision_engine_rejects_restrictive_weights_even_with_attestation(tmp_path: Path) -> None:
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
                "sha256": hashlib.sha256(scrfd_bytes).hexdigest(),
                "source_url": "https://example.invalid/scrfd",
                "license_name": "Non-commercial Research License",
                "permitted_use": "Academic research and evaluation only",
            },
            "ArcFace": {
                "file": "w600k_r50.onnx",
                "sha256": hashlib.sha256(arcface_bytes).hexdigest(),
                "source_url": "https://example.invalid/arcface",
                "license_name": "Non-commercial Research License",
                "permitted_use": "Academic research and evaluation only",
            },
        },
    }
    (pack_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    from app.vision.engine import VisionError

    settings = Settings(
        _env_file=None,
        env="production",
        model_license_attested=True,
        model_root=str(tmp_path),
        model_pack="buffalo_l",
    )
    with pytest.raises(VisionError, match="Production startup blocked:.*restrictive terms.*cannot override this check"):
        VisionEngine(settings)
