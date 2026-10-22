"""Provision and verify official InsightFace Buffalo_L model artifacts for FRS.

Validates exact SHA-256 integrity, extracts to the standard model layout,
and generates the authoritative manifest.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath
import zipfile

EXPECTED_SCRFD_SHA256 = "5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91"
EXPECTED_ARCFACE_SHA256 = "4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43"
EXPECTED_PACKAGE_SHA256 = "f9494992cf1fff0112d7f1a77905577a6e77873b6c6e81b51437bd7b3b1bec3c"


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def generate_manifest() -> dict:
    return {
        "manifest_version": 1,
        "models": {
            "SCRFD": {
                "file": "det_10g.onnx",
                "sha256": EXPECTED_SCRFD_SHA256,
                "source_url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
                "publisher": "DeepInsight / InsightFace",
                "training_dataset": "WIDER FACE",
                "license_name": "Non-commercial Research License (InsightFace)",
                "permitted_use": "Academic research and evaluation only",
            },
            "ArcFace": {
                "file": "w600k_r50.onnx",
                "sha256": EXPECTED_ARCFACE_SHA256,
                "source_url": "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
                "publisher": "DeepInsight / InsightFace",
                "training_dataset": "WebFace600K",
                "license_name": "Non-commercial Research License (InsightFace / WebFace600K)",
                "permitted_use": "Academic research and evaluation only",
            },
        },
    }


def find_archive(custom_path: str | None = None) -> Path | None:
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p

    candidates = [
        Path.cwd() / "frs_buffalo_l_verified.tar.gz",
        Path.cwd() / "backend" / "model-artifacts" / "frs_buffalo_l_verified.tar.gz",
        Path.home() / "Downloads" / "frs_buffalo_l_verified.tar.gz",
        Path.home() / "Downloads" / "buffalo_l.zip",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _validated_archive_path(root: Path, member_name: str) -> Path:
    """Reject absolute/traversal archive paths before writing any extracted data."""
    normalized_name = member_name.replace("\\", "/")
    relative = PurePosixPath(normalized_name)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ValueError(f"Unsafe archive member path: {member_name!r}")
    destination = (root / Path(*relative.parts)).resolve()
    resolved_root = root.resolve()
    if destination != resolved_root and resolved_root not in destination.parents:
        raise ValueError(f"Archive member escapes extraction directory: {member_name!r}")
    return destination


def _safe_extract_tar(archive: tarfile.TarFile, target_dir: Path) -> None:
    root = target_dir.resolve()
    members = archive.getmembers()
    for member in members:
        _validated_archive_path(root, member.name)
        # Model packages only need ordinary files/directories. Links and special files can
        # redirect writes outside the extraction root or alter later path resolution.
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise ValueError(f"Refusing link or special tar member: {member.name!r}")
        if not (member.isdir() or member.isfile()):
            raise ValueError(f"Unsupported tar member type: {member.name!r}")
    archive.extractall(path=root, members=members)


def _safe_extract_zip(archive: zipfile.ZipFile, target_dir: Path) -> None:
    root = target_dir.resolve()
    members = archive.infolist()
    for member in members:
        _validated_archive_path(root, member.filename)
        mode = (member.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if file_type == stat.S_IFLNK:
            raise ValueError(f"Refusing symbolic link in zip archive: {member.filename!r}")
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError(f"Refusing special file in zip archive: {member.filename!r}")
    archive.extractall(path=root, members=members)


def extract_and_verify(archive_path: Path, target_dir: Path) -> bool:
    print(f"-> Inspecting archive: {archive_path}")
    pkg_hash = compute_sha256(archive_path)
    print(f"-> Archive SHA-256: {pkg_hash}")
    # The project-produced tarball has a pinned package digest. The upstream zip is instead
    # authenticated by the exact SCRFD and ArcFace file hashes checked below.
    if archive_path.name == "frs_buffalo_l_verified.tar.gz" and pkg_hash != EXPECTED_PACKAGE_SHA256:
        print(f"ERROR: package SHA-256 mismatch; expected {EXPECTED_PACKAGE_SHA256}")
        return False

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        if archive_path.name.endswith(".tar.gz") or archive_path.name.endswith(".tgz"):
            print(f"-> Safely extracting tar archive to {target_dir}...")
            with tarfile.open(archive_path, "r:gz") as tar:
                _safe_extract_tar(tar, target_dir)
        elif archive_path.name.endswith(".zip"):
            print(f"-> Safely extracting zip archive to {target_dir}...")
            with zipfile.ZipFile(archive_path, "r") as z:
                _safe_extract_zip(z, target_dir)
        else:
            print(f"Unsupported archive format: {archive_path.name}")
            return False
    except (tarfile.TarError, zipfile.BadZipFile, OSError, ValueError) as exc:
        print(f"ERROR: archive extraction was rejected: {exc}")
        return False

    # Check if files extracted into a subfolder or directly
    det_path = None
    arc_path = None
    for p in target_dir.rglob("det_10g.onnx"):
        det_path = p
        break
    for p in target_dir.rglob("w600k_r50.onnx"):
        arc_path = p
        break

    if not det_path or not det_path.is_file():
        print("ERROR: det_10g.onnx not found in extracted files!")
        return False
    if not arc_path or not arc_path.is_file():
        print("ERROR: w600k_r50.onnx not found in extracted files!")
        return False

    # Standardize to target_dir/det_10g.onnx and target_dir/w600k_r50.onnx
    final_det = target_dir / "det_10g.onnx"
    final_arc = target_dir / "w600k_r50.onnx"
    if det_path != final_det:
        shutil.move(str(det_path), str(final_det))
    if arc_path != final_arc:
        shutil.move(str(arc_path), str(final_arc))

    print("-> Verifying SHA-256 hashes against cryptographic standard...")
    actual_det_sha = compute_sha256(final_det)
    actual_arc_sha = compute_sha256(final_arc)

    print(f"   SCRFD (det_10g.onnx):  {actual_det_sha}")
    if actual_det_sha != EXPECTED_SCRFD_SHA256:
        print(f"   MISMATCH! Expected:   {EXPECTED_SCRFD_SHA256}")
        return False
    print("   [PASS] SCRFD hash verified.")

    print(f"   ArcFace (w600k_r50):   {actual_arc_sha}")
    if actual_arc_sha != EXPECTED_ARCFACE_SHA256:
        print(f"   MISMATCH! Expected:   {EXPECTED_ARCFACE_SHA256}")
        return False
    print("   [PASS] ArcFace hash verified.")

    # Write manifest.json
    manifest_file = target_dir / "manifest.json"
    manifest_data = generate_manifest()
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    print(f"-> Manifest generated: {manifest_file}")

    print("\n============================================================")
    print("PROVISIONING SUCCESS: Buffalo_L pack is active and verified.")
    print(f"Pack Directory: {target_dir}")
    print("============================================================")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision Buffalo_L model weights")
    parser.add_argument("--archive", type=str, help="Path to frs_buffalo_l_verified.tar.gz or buffalo_l.zip")
    parser.add_argument(
        "--target",
        type=str,
        default=str(Path(__file__).parent.parent / "model-artifacts" / "insightface" / "models" / "buffalo_l"),
        help="Target model pack directory",
    )
    args = parser.parse_args()

    target_dir = Path(args.target).resolve()
    archive = find_archive(args.archive)

    if not archive:
        print("No verified model archive found in Downloads, backend/model-artifacts, or current directory.")
        print("Please download 'frs_buffalo_l_verified.tar.gz' from the Kaggle Output pane and run:")
        print(f"python {Path(__file__).name} --archive path/to/frs_buffalo_l_verified.tar.gz")
        return 1

    success = extract_and_verify(archive, target_dir)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
