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
    _normalise,
    _preprocessing_id,
)
from app.vision.engine import VisionEngine
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


def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> tuple[float, float]:
    """Calculate the Wilson score confidence interval for a binomial proportion.

    Standard method recommended by ISO/IEC 19795 and NIST for biometric error rates.
    """
    if total <= 0:
        return (0.0, 1.0)
    if successes < 0 or successes > total:
        raise ValueError(f"Invalid successes {successes} for total {total}")
    z_map = {0.90: 1.64485, 0.95: 1.95996, 0.99: 2.57583}
    z = z_map.get(confidence, 1.95996)

    p = float(successes) / float(total)
    z2 = z * z
    denom = 1.0 + z2 / total
    center = (p + z2 / (2.0 * total)) / denom
    margin = (z / denom) * math.sqrt((p * (1.0 - p) / total) + (z2 / (4.0 * total * total)))
    lower = 0.0 if successes == 0 else max(0.0, float(center - margin))
    upper = 1.0 if successes == total else min(1.0, float(center + margin))
    return (lower, upper)


def rule_of_three_upper_bound(total: int, confidence: float = 0.95) -> float:
    """One-sided binomial upper confidence bound when 0 errors are observed in N independent trials.

    Under NIST guidelines, observing 0 false accepts in N ~ 300,000 independent comparisons
    is mathematically required to establish an upper 95% bound of -ln(0.05) / 300,000 ≈ 3 / 300,000 = 1e-5.
    """
    if total <= 0:
        return 1.0
    return float(1.0 - (1.0 - confidence) ** (1.0 / total))


def compute_score_distribution(scores: list[float]) -> dict[str, Any]:
    """Calculate empirical distribution metrics and percentiles for a score list."""
    if not scores:
        return {"count": 0, "min": None, "max": None, "mean": None, "std": None, "percentiles": {}}
    arr = np.asarray(scores, dtype=np.float64)
    percentile_keys = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    percentile_vals = np.percentile(arr, percentile_keys)
    percentiles = {f"p{k}": round(float(v), 6) for k, v in zip(percentile_keys, percentile_vals)}

    hist_counts, bin_edges = np.histogram(
        arr, bins=10, range=(-1.0, 1.0) if float(arr.min()) < 0.0 else (0.0, 1.0)
    )
    histogram = [
        {"bin_start": round(float(bin_edges[i]), 4), "bin_end": round(float(bin_edges[i + 1]), 4), "count": int(hist_counts[i])}
        for i in range(len(hist_counts))
    ]

    return {
        "count": len(scores),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
        "mean": round(float(np.mean(arr)), 6),
        "std": round(float(np.std(arr)), 6),
        "percentiles": percentiles,
        "histogram": histogram,
    }


def compute_roc_det_curves(
    genuine: list[float],
    impostor: list[float],
    thresholds: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Generate ROC/DET curve data points mapping thresholds to FAR, FRR, TAR and confidence intervals."""
    if not genuine or not impostor:
        return []
    if thresholds is None:
        all_scores = genuine + impostor
        min_score = min(all_scores)
        max_score = max(all_scores)
        thresholds = list(np.linspace(min_score, max_score, 25))

    n_gen = len(genuine)
    n_imp = len(impostor)
    curve = []
    for t in sorted(thresholds):
        thresh = float(t)
        fa_count = sum(score >= thresh for score in impostor)
        fr_count = sum(score < thresh for score in genuine)
        far = fa_count / n_imp
        frr = fr_count / n_gen
        tar = 1.0 - frr
        far_lower, far_upper = wilson_score_interval(fa_count, n_imp, 0.95)
        frr_lower, frr_upper = wilson_score_interval(fr_count, n_gen, 0.95)
        curve.append({
            "threshold": round(thresh, 6),
            "far": round(far, 6),
            "far_ci_95": [round(far_lower, 6), round(far_upper, 6)],
            "frr": round(frr, 6),
            "frr_ci_95": [round(frr_lower, 6), round(frr_upper, 6)],
            "tar": round(tar, 6),
            "tar_ci_95": [round(max(0.0, 1.0 - frr_upper), 6), round(min(1.0, 1.0 - frr_lower), 6)],
        })
    return curve


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
    acceptable: list[tuple[float, float, float, int, int]] = []
    n_imp = len(impostor)
    n_gen = len(genuine)
    for threshold in candidates:
        fa_count = sum(score >= threshold for score in impostor)
        far = fa_count / n_imp
        if far <= target_far:
            fr_count = sum(score < threshold for score in genuine)
            frr = fr_count / n_gen
            acceptable.append((threshold, far, frr, fa_count, fr_count))
    if not acceptable:
        raise ValueError("No threshold satisfies target FAR for this protocol")
    threshold, far, frr, fa_count, fr_count = min(acceptable, key=lambda item: (item[0], item[2]))

    far_ci_lower, far_ci_upper = wilson_score_interval(fa_count, n_imp, 0.95)
    frr_ci_lower, frr_ci_upper = wilson_score_interval(fr_count, n_gen, 0.95)

    warnings: list[str] = []
    if n_imp < 300000:
        rule_of_three = rule_of_three_upper_bound(n_imp, 0.95)
        warnings.append(
            f"Statistical sample limit: Observing zero or low errors across {n_imp:,} impostor trials "
            f"cannot establish an operational FAR <= 10^-5 with 95% confidence (NIST SP 500-xxx). "
            f"Current one-sided 95% upper bound on FAR (if 0 errors observed) is {rule_of_three:.6e}."
        )
    if n_gen < 100:
        warnings.append(
            f"Sample size warning: Only {n_gen} genuine trials evaluated; FRR confidence interval "
            f"[{frr_ci_lower:.4f}, {frr_ci_upper:.4f}] is wide."
        )

    return float(threshold), {
        "target_far": target_far,
        "empirical_far": far,
        "empirical_far_ci_95": [round(far_ci_lower, 6), round(far_ci_upper, 6)],
        "empirical_frr": frr,
        "empirical_frr_ci_95": [round(frr_ci_lower, 6), round(frr_ci_upper, 6)],
        "empirical_tar": 1.0 - frr,
        "empirical_tar_ci_95": [round(max(0.0, 1.0 - frr_ci_upper), 6), round(min(1.0, 1.0 - frr_ci_lower), 6)],
        "false_accept_count": fa_count,
        "false_reject_count": fr_count,
        "genuine_trials": n_gen,
        "impostor_trials": n_imp,
        "operating_threshold_rule": "lowest observed similarity threshold satisfying empirical FAR target",
        "statistical_warnings": warnings,
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
            raise ValueError("Inconsistent embedding dimensions for one enrollment profile")
        prototypes[key] = _normalise(np.mean(np.stack(vectors), axis=0))

    genuine: list[float] = []
    impostor: list[float] = []
    rank1_correct = 0
    known_total = 0
    unknown_total = 0
    known_correct_accepted: list[tuple[bool, float]] = []
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
            known_correct_accepted.append((top_person == person_id, top_score))
        else:
            impostor.extend(score for _candidate_id, score in scored)
            unknown_total += 1
            unknown_max_scores.append(top_score)

    threshold, calibration = _choose_far_threshold(genuine, impostor, target_far)
    calibration["recommended_threshold"] = threshold
    known_max_accepted = sum(score >= threshold for score in known_max_scores)
    known_correct_accepted_count = sum(correct and score >= threshold for correct, score in known_correct_accepted)
    genuine_acceptance_count = sum(score >= threshold for score in genuine)
    unknown_false_accepts = sum(score >= threshold for score in unknown_max_scores)
    data_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    model_path = None
    if model_id == "ArcFace":
        model_path = Path(str(getattr(engine.recognizer, "model_file", "")))
    elif model_id == "AdaFace":
        model_path = engine.adaface.path
    else:
        model_path = engine.mobilefacenet.path

    genuine_dist = compute_score_distribution(genuine)
    impostor_dist = compute_score_distribution(impostor)
    roc_det = compute_roc_det_curves(genuine, impostor)
    fta_count = sum(count for key, count in skipped.items() if "NO_FACE" in key or "LANDMARKS" in key)
    recapture_count = sum(count for key, count in skipped.items() if "RECAPTURE" in key)

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
            "is_synthetic_evaluation": False,
            "nist_guideline_reference": "NIST SP 500-xxx: ~300,000 independent impostor trials required for 95% confidence bound around FAR=10^-5",
            "warning": "Threshold is only as representative as this labeled dataset and the target deployment environment.",
        },
        "distributions": {
            "genuine_scores": genuine_dist,
            "impostor_scores": impostor_dist,
        },
        "roc_det_curves": roc_det,
        "data_quality": {
            "failure_to_acquire_count": fta_count,
            "failure_to_acquire_rate": round(fta_count / len(rows), 6) if rows else 0.0,
            "recapture_count": recapture_count,
            "recapture_rate": round(recapture_count / len(rows), 6) if rows else 0.0,
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
            "known_correct_identification_acceptance_rate": (known_correct_accepted_count / known_total) if known_total else None,
            "genuine_similarity_true_accept_rate": (genuine_acceptance_count / len(genuine)) if genuine else None,
            "unknown_probe_false_accept_rate": (unknown_false_accepts / unknown_total) if unknown_total else None,
            "open_set_unknown_rejection_rate": ((unknown_total - unknown_false_accepts) / unknown_total) if unknown_total else None,
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
