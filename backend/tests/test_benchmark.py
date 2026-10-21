from __future__ import annotations

import csv
from pathlib import Path
import pytest

from app.benchmark import (
    _choose_far_threshold,
    _load_manifest,
    compute_roc_det_curves,
    compute_score_distribution,
    rule_of_three_upper_bound,
    wilson_score_interval,
)


def test_threshold_meets_empirical_far_and_reports_frr() -> None:
    threshold, metrics = _choose_far_threshold(
        genuine=[0.89, 0.91, 0.83, 0.86],
        impostor=[0.11, 0.23, 0.37, 0.42],
        target_far=0.25,
    )
    assert threshold > 0.37
    assert metrics["empirical_far"] <= 0.25
    assert 0.0 <= metrics["empirical_frr"] <= 1.0
    assert "empirical_far_ci_95" in metrics
    assert "empirical_frr_ci_95" in metrics
    assert "statistical_warnings" in metrics


def test_calibration_refuses_missing_genuine_or_impostor_trials() -> None:
    with pytest.raises(ValueError, match="No genuine"):
        _choose_far_threshold([], [0.1, 0.2], 0.001)
    with pytest.raises(ValueError, match="No impostor"):
        _choose_far_threshold([0.8, 0.9], [], 0.001)


def test_target_far_must_be_respected_by_selected_threshold() -> None:
    threshold, metrics = _choose_far_threshold(
        genuine=[0.4, 0.6, 0.8],
        impostor=[0.3, 0.4, 0.5, 0.6],
        target_far=0.25,
    )
    assert metrics["empirical_far"] <= 0.25
    assert threshold >= 0.5


def test_wilson_score_interval_properties() -> None:
    # 0 successes out of 100 trials
    lower_0, upper_0 = wilson_score_interval(0, 100, 0.95)
    assert lower_0 == 0.0
    assert 0.0 < upper_0 < 0.05

    # 50 successes out of 100 trials (symmetric around 0.5)
    lower_50, upper_50 = wilson_score_interval(50, 100, 0.95)
    assert 0.39 < lower_50 < 0.41
    assert 0.59 < upper_50 < 0.61

    # 100 successes out of 100 trials
    lower_100, upper_100 = wilson_score_interval(100, 100, 0.95)
    assert 0.95 < lower_100 < 1.0
    assert upper_100 == 1.0

    # Bounds checking
    with pytest.raises(ValueError, match="Invalid successes"):
        wilson_score_interval(105, 100)


def test_rule_of_three_upper_bound_nist_scaling() -> None:
    # NIST SP 500-xxx perspective: ~300,000 impostor trials needed for 10^-5 bound
    bound_300k = rule_of_three_upper_bound(300_000, 0.95)
    assert 9e-6 < bound_300k < 1.1e-5

    # Small campus sample: 3,000 trials can only substantiate ~10^-3
    bound_3k = rule_of_three_upper_bound(3_000, 0.95)
    assert 9e-4 < bound_3k < 1.1e-3

    # Smallest samples return bounded float
    assert rule_of_three_upper_bound(0) == 1.0


def test_compute_score_distribution() -> None:
    scores = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    dist = compute_score_distribution(scores)
    assert dist["count"] == 9
    assert dist["min"] == 0.1
    assert dist["max"] == 0.9
    assert abs(dist["mean"] - 0.5) < 1e-5
    assert "percentiles" in dist
    assert dist["percentiles"]["p50"] == 0.5
    assert len(dist["histogram"]) == 10

    empty = compute_score_distribution([])
    assert empty["count"] == 0
    assert empty["min"] is None


def test_compute_roc_det_curves_monotonicity() -> None:
    genuine = [0.6, 0.7, 0.8, 0.85, 0.9, 0.95]
    impostor = [0.1, 0.15, 0.2, 0.3, 0.35, 0.4, 0.5]
    curve = compute_roc_det_curves(genuine, impostor)
    assert len(curve) > 0

    prev_far = 1.1
    for point in curve:
        assert 0.0 <= point["threshold"] <= 1.0
        assert 0.0 <= point["far"] <= 1.0
        assert 0.0 <= point["frr"] <= 1.0
        assert abs(point["far"] + (1.0 - point["tar"])) < 1e-5 or abs(point["tar"] - (1.0 - point["frr"])) < 1e-5
        # As threshold increases, FAR must be non-increasing (monotonic)
        assert point["far"] <= prev_far + 1e-6
        prev_far = point["far"]


def test_choose_far_threshold_emits_nist_sample_size_warning() -> None:
    # A small evaluation sample of 200 impostor comparisons
    genuine = [0.8, 0.85, 0.9]
    impostor = [0.1 + i * 0.001 for i in range(200)]
    threshold, metrics = _choose_far_threshold(genuine, impostor, 0.01)

    assert "statistical_warnings" in metrics
    warnings = " ".join(metrics["statistical_warnings"])
    assert "cannot establish an operational FAR <= 10^-5" in warnings
    assert "NIST" in warnings


def test_load_manifest_rejects_overlapping_unknown_probes(tmp_path: Path) -> None:
    img_file = tmp_path / "face.jpg"
    img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

    manifest_csv = tmp_path / "manifest.csv"
    with manifest_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["image_path", "person_id", "split"])
        writer.writeheader()
        writer.writerow({"image_path": str(img_file), "person_id": "STUDENT_1", "split": "enroll"})
        writer.writerow({"image_path": str(img_file), "person_id": "STUDENT_1", "split": "probe_known"})
        # Intentionally invalid: probe_unknown identity is present in enroll
        writer.writerow({"image_path": str(img_file), "person_id": "STUDENT_1", "split": "probe_unknown"})

    with pytest.raises(ValueError, match="probe_unknown rows must use identities absent from the enrollment split"):
        _load_manifest(manifest_csv)
