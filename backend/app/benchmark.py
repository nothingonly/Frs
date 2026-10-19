from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.core.config import Settings
from app.schemas.contracts import QualityState
from app.services.pipeline import (
    PREPROCESSING_VERSION,
    _choose_preprocessing,
    _normalise,
    _preprocessing_id,
)
from app.vision.engine import VisionEngine, VisionError
from app.vision.enhancement import ENHANCED_PREPROCESSING, ORIGINAL_PREPROCESSING, conditional_enhance


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        required = {"image_path", "person_id", "split"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Manifest CSV must have columns: image_path,person_id,split")
        for index, row in enumerate(reader, start=2):
            image_value = (row.get("image_path") or "").strip()
            person_id = (row.get("person_id") or "").strip()
            split = (row.get("split") or "").strip().lower()
            if not image_value or not person_id or split not in {"enroll", "probe_known", "probe_unknown"}:
                raise ValueError(f"Invalid manifest row {index}; check image_path/person_id/split")
            image_path = Path(image_value)
            if not image_path.is_absolute():
                image_path = (path.parent / image_path).resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"Manifest row {index} points to a missing image: {image_path}")
            rows.append({"image_path": str(image_path), "person_id": person_id, "split": split})
    if not rows:
        raise ValueError("The manifest contains no rows")
    splits = {row["split"] for row in rows}
    if "enroll" not in splits or "probe_known" not in splits or "probe_unknown" not in splits:
        raise ValueError("Manifest needs enroll, probe_known and probe_unknown splits")
    enrolled = {row["person_id"] for row in rows if row["split"] == "enroll"}
    if not enrolled:
        raise ValueError("No enrollment identities found")
    if not any(row["person_id"] not in enrolled for row in rows if row["split"] == "probe_unknown"):
        raise ValueError("probe_unknown rows must use identities absent from the enrollment split")
    if not any(row["person_id"] in enrolled for row in rows if row["split"] == "probe_known"):
        raise ValueError("probe_known rows must refer to an enrolled identity")
    return rows


def _extract_branch_embeddings(
    engine: VisionEngine,
    model_id: str,
    row: dict[str, str],
    split: str,
) -> tuple[list[tuple[str, np.ndarray, dict[str, Any]]], dict[str, Any]]:
    path = Path(row["image_path"])
    payload = path.read_bytes()
    obs = engine.analyze(payload, frame_id=f"benchmark:{_sha256_file(path)[:16]}")
    meta = {
        "sha256": _sha256_file(path),
        "detection_state": obs.detection_state.value,
        "quality_state": obs.quality.result.status.value if obs.quality else "NO_FACE",
        "quality_codes": obs.quality.result.failure_codes if obs.quality else [],
    }
    if obs.quality is None or obs.aligned_face_bgr is None or obs.detection_state.value != "OK":
        return [], meta
    if obs.quality.result.status == QualityState.RECAPTURE:
        return [], meta

    result: list[tuple[str, np.ndarray, dict[str, Any]]] = []
    if model_id == "ArcFace":
        # Runtime identification is deliberately strict: degraded probe frames should
        # take the configured difficult-quality route, not silently run the primary model.
        if split != "enroll" and (
            obs.quality.result.status != QualityState.GOOD or obs.primary_embedding is None
        ):
            return [], meta
        vector = engine.primary_embedding(obs.aligned_face_bgr)
        preprocessing_id = _preprocessing_id(model_id, engine.recognizer_version, ORIGINAL_PREPROCESSING)
        result.append((preprocessing_id, _normalise(vector), meta))
        return result, meta

    vector, _name, version = engine.secondary_embedding(model_id, obs.aligned_face_bgr)
    original_id = _preprocessing_id(model_id, version, ORIGINAL_PREPROCESSING)
    result.append((original_id, _normalise(vector), meta))
    # Enrollment creates an explicit enhanced comparison branch; probe inference
    # selects it only when deterministic exposure measurements request it.
    enhanced = conditional_enhance(
        obs.aligned_face_bgr, obs.quality.result,
        force_enhanced_reference=(split == "enroll"),
    )
    exposure_required = any(code in obs.quality.result.failure_codes for code in ("UNDEREXPOSED", "OVEREXPOSED"))
    if enhanced.applied and (split == "enroll" or exposure_required):
        enhanced_vector, _name, enhanced_version = engine.secondary_embedding(model_id, enhanced.image_bgr)
        enhanced_id = _preprocessing_id(model_id, enhanced_version, ENHANCED_PREPROCESSING)
        result.append((enhanced_id, _normalise(enhanced_vector), {**meta, "enhancement_reason": enhanced.reason}))
    return result, meta


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        raise ValueError(f"Incompatible embeddings: {a.size} and {b.size} dimensions")
    return float(np.clip(np.dot(_normalise(a), _normalise(b)), -1.0, 1.0))


def _choose_far_threshold(
    genuine: list[float],
    impostor: list[float],
    target_far: float,
) -> tuple[float, dict[str, Any]]:
    if not genuine:
        raise ValueError("No genuine comparisons could be evaluated; cannot calibrate a threshold")
    if not impostor:
        raise ValueError("No impostor comparisons could be evaluated; cannot calibrate a threshold")
    candidates = sorted({1.000001, *genuine, *impostor})
    # Similarity acceptance is >= threshold. Choose the lowest observed threshold
    # which meets the requested empirical FAR on the explicitly supplied test split.
    acceptable: list[tuple[float, float, float]] = []
    for threshold in candidates:
        far = sum(score >= threshold for score in impostor) / len(impostor)
        if far <= target_far:
            frr = sum(score < threshold for score in genuine) / len(genuine)
            acceptable.append((threshold, far, frr))
    if not acceptable:
        raise ValueError("No threshold satisfies target FAR for this protocol")
    threshold, far, frr = min(acceptable, key=lambda item: (item[0], item[2]))
    return float(threshold), {
        "target_far": target_far,
        "empirical_far": far,
        "empirical_frr": frr,
        "genuine_trials": len(genuine),
        "impostor_trials": len(impostor),
        "operating_threshold_rule": "lowest observed similarity threshold satisfying empirical FAR target",
    }


def run_benchmark(manifest: Path, model_id: str, target_far: float, output: Path) -> dict[str, Any]:
    if not 0.0 < target_far < 1.0:
        raise ValueError("--target-far must be strictly between 0 and 1")
    rows = _load_manifest(manifest)
    settings = Settings()
    engine = VisionEngine(settings)
    if model_id == "AdaFace" and engine.adaface is None:
        raise ValueError("AdaFace benchmark requested but no compatible, licensed AdaFace artifact is configured")
    if model_id == "MobileFaceNet" and engine.mobilefacenet is None:
        raise ValueError("MobileFaceNet benchmark requested but no compatible, licensed artifact is configured")
    if model_id not in {"ArcFace", "AdaFace", "MobileFaceNet"}:
        raise ValueError("Choose ArcFace, AdaFace, or MobileFaceNet")
    model_version = engine.recognizer_version if model_id == "ArcFace" else (
        engine.adaface.model_version if model_id == "AdaFace" else engine.mobilefacenet.model_version
    )

    profiles: dict[tuple[str, str], list[np.ndarray]] = defaultdict(list)
    enroll_ids: set[str] = set()
    probes: list[dict[str, Any]] = []
    skipped: dict[str, int] = defaultdict(int)
    quality_slices: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "usable": 0})
    per_image_audit: list[dict[str, Any]] = []

    for row in rows:
        embeddings, meta = _extract_branch_embeddings(engine, model_id, row, row["split"])
        quality_slices[meta["quality_state"]]["total"] += 1
        if embeddings:
            quality_slices[meta["quality_state"]]["usable"] += 1
        else:
            skipped[f'{row["split"]}:{meta["quality_state"]}'] += 1
        # Report only a digest and non-identifying metric strata; do not emit paths, photos,
        # names, person IDs, or per-person scores in the public report.
        per_image_audit.append({
            "image_sha256": meta["sha256"],
            "split": row["split"],
            "quality_state": meta["quality_state"],
            "usable": bool(embeddings),
        })
        if row["split"] == "enroll":
            if not embeddings:
                continue
            enroll_ids.add(row["person_id"])
            for preprocessing_id, vector, _meta in embeddings:
                profiles[(row["person_id"], preprocessing_id)].append(vector)
        else:
            if not embeddings:
                continue
            # The route produces one inference branch for probe frames, while enrollment
            # can return original + enhanced branches.
            chosen = embeddings[-1] if (
                model_id != "ArcFace"
                and any(code in meta["quality_codes"] for code in ("UNDEREXPOSED", "OVEREXPOSED"))
                and embeddings[-1][0].endswith(ENHANCED_PREPROCESSING)
            ) else embeddings[0]
            probes.append({
                "split": row["split"],
                "person_id": row["person_id"],
                "preprocessing_id": chosen[0],
                "embedding": chosen[1],
            })

    if len(enroll_ids) < 2:
        raise ValueError("At least two enrolled identities are required for meaningful identification calibration")
    if not probes:
        raise ValueError("No usable probe images after real detector/quality processing")

    prototypes: dict[tuple[str, str], np.ndarray] = {}
    for key, vectors in profiles.items():
        dimensions = {vector.size for vector in vectors}
        if len(dimensions) != 1:
            raise ValueError(f"Inconsistent embedding dimensions for one enrollment profile")
        prototypes[key] = _normalise(np.mean(np.stack(vectors), axis=0))

    genuine: list[float] = []
    impostor: list[float] = []
    rank1_correct = 0
    known_total = 0
    unknown_total = 0
    open_set_correct_reject = 0
    known_max_scores: list[float] = []
    unknown_max_scores: list[float] = []
    no_branch_profile = 0
    for probe in probes:
        query = probe["embedding"]
        branch_id = probe["preprocessing_id"]
        candidates = [
            (person_id, vector) for (person_id, branch), vector in prototypes.items()
            if branch == branch_id
        ]
        if not candidates:
            no_branch_profile += 1
            continue
        scored = sorted(
            ((person_id, _cosine(query, vector)) for person_id, vector in candidates),
            key=lambda item: item[1], reverse=True,
        )
        top_person, top_score = scored[0]
        if probe["split"] == "probe_known":
            person_id = probe["person_id"]
            exact_profile = prototypes.get((person_id, branch_id))
            if exact_profile is None:
                no_branch_profile += 1
                continue
            genuine.append(_cosine(query, exact_profile))
            wrong_scores = [score for candidate_id, score in scored if candidate_id != person_id]
            impostor.extend(wrong_scores)
            rank1_correct += int(top_person == person_id)
            known_total += 1
            known_max_scores.append(top_score)
        else:
            impostor.extend(score for _candidate_id, score in scored)
            unknown_total += 1
            unknown_max_scores.append(top_score)
            open_set_correct_reject += int(probe["person_id"] not in enroll_ids)

    threshold, calibration = _choose_far_threshold(genuine, impostor, target_far)
    known_max_accepted = sum(score >= threshold for score in known_max_scores)
    unknown_false_accepts = sum(score >= threshold for score in unknown_max_scores)
    data_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    model_path = None
    if model_id == "ArcFace":
        model_path = Path(str(getattr(engine.recognizer, "model_file", "")))
    elif model_id == "AdaFace":
        model_path = engine.adaface.path
    else:
        model_path = engine.mobilefacenet.path

    report = {
        "report_version": "frs-benchmark-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "manifest_sha256": data_digest,
            "model_id": model_id,
            "model_version": model_version,
            "model_artifact_sha256": _sha256_file(model_path) if model_path and model_path.is_file() else None,
            "primary_detector": engine.detector_id,
            "primary_detector_version": engine.detector_version,
            "pipeline_version": engine.pipeline_version,
            "preprocessing_base": PREPROCESSING_VERSION,
            "target_far": target_far,
            "gallery_search": "roster-scoped exact cosine; normalized embeddings; matching preprocessing branch only",
            "warning": "Threshold is only as representative as this labeled dataset and the target deployment environment.",
        },
        "samples": {
            "manifest_rows": len(rows),
            "enrolled_identities_in_manifest": len(enroll_ids),
            "usable_known_probes": known_total,
            "usable_unknown_probes": unknown_total,
            "skipped": dict(skipped),
            "probes_without_matching_preprocessing_profile": no_branch_profile,
            "quality_slices": dict(quality_slices),
        },
        "metrics": {
            **calibration,
            "rank1_identification_rate": (rank1_correct / known_total) if known_total else None,
            "known_probe_acceptance_rate_at_calibrated_threshold": (known_max_accepted / known_total) if known_total else None,
            "unknown_probe_false_accept_rate": (unknown_false_accepts / unknown_total) if unknown_total else None,
            "open_set_unknown_rejection_rate": (open_set_correct_reject / unknown_total) if unknown_total else None,
            "known_max_similarity_count": len(known_max_scores),
            "unknown_max_similarity_count": len(unknown_max_scores),
        },
        "recommended_environment_settings": {
            "FRS_MODEL_THRESHOLDS_JSON": json.dumps({model_id: round(threshold, 8)}, separators=(",", ":")),
            "FRS_CALIBRATED_MODELS_CSV": model_id,
            "FRS_THRESHOLD_CALIBRATED": "true" if model_id == "ArcFace" else "false",
            "note": "Review the report, dataset representativeness and false-accept risk before changing live configuration.",
        },
        "privacy": {
            "raw_images_in_report": False,
            "person_identifiers_in_report": False,
            "individual_similarity_scores_in_report": False,
            "image_hash_audit_entries": len(per_image_audit),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate an FRS recognizer using real images and labeled splits.")
    parser.add_argument("--manifest", type=Path, required=True, help="CSV with image_path,person_id,split")
    parser.add_argument("--model", choices=("ArcFace", "AdaFace", "MobileFaceNet"), default="ArcFace")
    parser.add_argument("--target-far", type=float, default=0.001)
    parser.add_argument("--output", type=Path, default=Path("reports/benchmark-report.json"))
    args = parser.parse_args()
    try:
        report = run_benchmark(args.manifest.resolve(), args.model, args.target_far, args.output.resolve())
    except Exception as exc:
        print(f"Benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "report": str(args.output.resolve()),
        "model": report["protocol"]["model_id"],
        "threshold": report["metrics"].get("recommended_threshold"),
        "rank1": report["metrics"]["rank1_identification_rate"],
        "empirical_far": report["metrics"]["empirical_far"],
        "empirical_frr": report["metrics"]["empirical_frr"],
        "samples": report["samples"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
