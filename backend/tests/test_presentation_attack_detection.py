from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pytest

from app.core.config import Settings
from app.services.pipeline import AttendancePipeline


@dataclass(frozen=True)
class PadEvaluationResult:
    """ISO/IEC 30107-3 Presentation Attack Detection evaluation metrics."""
    threshold: float
    total_bona_fide: int
    total_attack: int
    apcer: float  # Attack Presentation Classification Error Rate (False Accept of Spoof)
    bpcer: float  # Bona Fide Presentation Classification Error Rate (False Reject of Live)
    acer: float   # Average Classification Error Rate: (APCER + BPCER) / 2


def calculate_pad_metrics(
    bona_fide_scores: Sequence[float],
    attack_scores: Sequence[float],
    threshold: float = 0.5,
) -> PadEvaluationResult:
    """Calculate APCER, BPCER, and ACER per ISO/IEC 30107-3 standards."""
    total_bf = len(bona_fide_scores)
    total_att = len(attack_scores)

    if total_bf == 0 or total_att == 0:
        raise ValueError("Must provide at least one bona fide and one attack presentation score.")

    # In liveness scoring, score >= threshold means classified as BONA FIDE (live)
    # APCER: attacks that scored >= threshold (falsely accepted as live)
    false_accepts = sum(1 for s in attack_scores if s >= threshold)
    apcer = false_accepts / float(total_att)

    # BPCER: bona fide presentations that scored < threshold (falsely rejected as attack)
    false_rejects = sum(1 for s in bona_fide_scores if s < threshold)
    bpcer = false_rejects / float(total_bf)

    acer = (apcer + bpcer) / 2.0

    return PadEvaluationResult(
        threshold=threshold,
        total_bona_fide=total_bf,
        total_attack=total_att,
        apcer=apcer,
        bpcer=bpcer,
        acer=acer,
    )


def calibrate_pad_threshold_at_bpcer(
    bona_fide_scores: Sequence[float],
    attack_scores: Sequence[float],
    target_bpcer: float = 0.05,
) -> PadEvaluationResult:
    """Find the optimal decision threshold that achieves target BPCER (e.g., <= 5% false rejections)."""
    # Sort bona fide scores to determine cutoff
    sorted_bf = sorted(bona_fide_scores)
    idx = int(len(sorted_bf) * target_bpcer)
    threshold = float(sorted_bf[idx])
    return calculate_pad_metrics(bona_fide_scores, attack_scores, threshold=threshold)


class MockLivenessEngine:
    """Mock vision engine for testing presentation attack detection pipeline policies."""
    def __init__(self, liveness_score: float = 0.95):
        self.liveness_score = liveness_score
        self.component_status = {"detection_primary": "READY", "liveness_minifasnet": "READY:v1-mock"}
        self.liveness = type("LivenessMock", (), {"model_version": "minifasnet-v1-mock"})()

    def liveness_probability(self, observation) -> float:
        return self.liveness_score


def test_pad_metrics_calculation_perfect_separation():
    # 10 live presentations with high liveness probabilities [0.85 - 0.99]
    bona_fide = [0.85, 0.88, 0.91, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99, 0.99]
    # 10 presentation attacks (print, screen replay) with low probabilities [0.01 - 0.25]
    attacks = [0.01, 0.03, 0.05, 0.07, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]

    res = calculate_pad_metrics(bona_fide, attacks, threshold=0.50)
    assert res.apcer == 0.0  # 0% spoofs accepted
    assert res.bpcer == 0.0  # 0% live students rejected
    assert res.acer == 0.0   # 0% average error


def test_pad_metrics_calculation_with_crossover_errors():
    # Live presentations: one student in harsh lighting scored low (0.35)
    bona_fide = [0.35, 0.75, 0.82, 0.90, 0.95]
    # Attacks: one high-res 4K screen replay scored slightly high (0.55)
    attacks = [0.05, 0.10, 0.20, 0.30, 0.55]

    res = calculate_pad_metrics(bona_fide, attacks, threshold=0.50)
    # Attack 0.55 >= 0.50 -> 1 false accept out of 5 = 0.20
    assert res.apcer == 0.20
    # Bona fide 0.35 < 0.50 -> 1 false reject out of 5 = 0.20
    assert res.bpcer == 0.20
    assert res.acer == 0.20


def test_calibrate_pad_threshold_at_target_bpcer():
    bona_fide = [0.60, 0.70, 0.80, 0.85, 0.90, 0.92, 0.95, 0.96, 0.97, 0.98]
    attacks = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55]

    # Target <= 10% BPCER
    result = calibrate_pad_threshold_at_bpcer(bona_fide, attacks, target_bpcer=0.10)
    assert result.bpcer <= 0.20
    assert result.threshold >= 0.55
    # Attacks are all <= 0.55, so APCER is very low
    assert result.apcer <= 0.10


def test_pipeline_rejects_spoof_attack_presentation(monkeypatch):
    """Verify that when liveness score is below required threshold, attendance is rejected with LIVENESS_FAILED."""
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    from app.schemas.contracts import RetrievalCandidate

    settings = Settings(
        _env_file=None,
        require_liveness=True,
        required_liveness_score=0.70,
    )

    mock_vision = MockLivenessEngine(liveness_score=0.15)  # Spoof print attack
    pipeline = AttendancePipeline(settings=settings, vision=mock_vision)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)

    mock_obs = type("ObsMock", (), {
        "box": [10, 10, 100, 100],
        "aligned_face_bgr": np.zeros((112, 112, 3), dtype=np.uint8),
        "embedding": np.ones((512,), dtype=np.float32),
        "quality": None,
    })()

    cand = RetrievalCandidate(person_id="p1", employee_id="E01", full_name="Student", similarity=0.95)
    mock_processed = [(mock_obs, "ArcFace", np.ones((512,)), "pre_id", [cand], 1)]

    monkeypatch.setattr(pipeline, "_analyze_burst", lambda *args, **kwargs: (mock_processed, [], {"pipeline_version": "v5"}))

    with TestingSession() as db:
        with pytest.raises(HTTPException) as exc_info:
            pipeline.identify(
                db,
                image_payloads=[b"fakeframe1", b"fakeframe2", b"fakeframe3"],
                punch_type="CHECK_IN",
                client_device_id="kiosk-1",
                actor_id="device:1",
            )
        assert exc_info.value.status_code == 403
        detail = exc_info.value.detail
        assert "Presentation-attack/liveness policy did not pass" in detail["message"]
        assert detail["state"] == "FAIL"
