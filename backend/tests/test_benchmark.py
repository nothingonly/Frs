import pytest

from app.benchmark import _choose_far_threshold


def test_threshold_meets_empirical_far_and_reports_frr() -> None:
    threshold, metrics = _choose_far_threshold(
        genuine=[0.89, 0.91, 0.83, 0.86],
        impostor=[0.11, 0.23, 0.37, 0.42],
        target_far=0.25,
    )
    assert threshold > 0.37
    assert metrics["empirical_far"] <= 0.25
    assert 0.0 <= metrics["empirical_frr"] <= 1.0


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
