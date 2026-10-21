import pytest
from pydantic import ValidationError

from app.schemas.contracts import (
    BoundingBox,
    DecisionResult,
    DecisionState,
    DetectionResult,
    DetectionState,
    QualityResult,
    QualityState,
    SecurityResult,
    SecurityState,
)


def test_detection_contract_requires_explicit_status_and_versioned_model() -> None:
    result = DetectionResult(
        status=DetectionState.OK,
        detector_id="SCRFD",
        detector_version="sha256:example",
        frame_id="session:0001",
        boxes=[BoundingBox(x=10, y=20, width=100, height=120, confidence=0.99)],
        face_count=1,
        latency_ms=3.25,
        preprocessing_id="scrfd-640-v1",
    )
    assert result.status is DetectionState.OK
    assert result.boxes[0].confidence == 0.99
    with pytest.raises(ValidationError):
        DetectionResult(
            status="OK",
            detector_id="SCRFD",
            detector_version="unknown",
            frame_id="frame",
            face_count=1,
            latency_ms=-0.1,
            preprocessing_id="v1",
        )


def test_quality_contract_bounds_clipping_and_fiqa_score() -> None:
    good = QualityResult(
        status=QualityState.GOOD,
        face_size_px=150,
        blur_score=82.3,
        mean_luminance=110.0,
        clipped_pixel_ratio=0.01,
        fiqa_score=0.87,
        route_hint="FAST",
        latency_ms=0.8,
    )
    assert good.fiqa_score == 0.87
    with pytest.raises(ValidationError):
        QualityResult(
            status=QualityState.GOOD,
            face_size_px=150,
            blur_score=82.3,
            mean_luminance=110.0,
            clipped_pixel_ratio=2.0,
            fiqa_score=1.8,
            route_hint="FAST",
            latency_ms=0.8,
        )


def test_security_uncertain_is_a_first_class_state() -> None:
    result = SecurityResult(
        liveness_model="MiniFASNet",
        model_version="sha256:example",
        state=SecurityState.UNCERTAIN,
        score=0.53,
        risk_flags=["LOW_CONFIDENCE"],
        challenge_state="RECAPTURE_REQUESTED",
        latency_ms=2.1,
    )
    assert result.state is SecurityState.UNCERTAIN


def test_decision_contract_does_not_collapse_unknown_into_accept() -> None:
    result = DecisionResult(
        final_state=DecisionState.REJECT_UNKNOWN,
        reason_codes=["NO_MATCH_ABOVE_CALIBRATED_THRESHOLD"],
        evidence_refs=["evidence:session:frame-0"],
        confidence_evidence={"top1": 0.22, "threshold": 0.5},
        policy_version="frs-v5-policy-1",
        model_versions=["SCRFD:sha256:a", "ArcFace:sha256:b"],
        timestamp="2026-10-19T10:00:00Z",
        audit_id="audit-001",
    )
    assert result.final_state is DecisionState.REJECT_UNKNOWN
    assert result.final_state is not DecisionState.ACCEPT


def test_model_provenance_contract_validates_and_rejects_malformed_hashes() -> None:
    from app.schemas.contracts import ModelProvenanceContract

    record = ModelProvenanceContract(
        model_id="ArcFace",
        model_version="4c06341c33c2ca1f",
        file="w600k_r50.onnx",
        sha256="4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43",
        source_url="https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip",
        publisher="DeepInsight / InsightFace",
        training_dataset="WebFace600K",
        license_name="Non-commercial Research License (InsightFace / WebFace600K)",
        permitted_use="Academic research and evaluation only",
        preprocessing_id="five-point-norm-crop-112-v1",
        output_type="embedding",
    )
    assert record.model_id == "ArcFace"
    assert record.training_dataset == "WebFace600K"
    assert record.publisher == "DeepInsight / InsightFace"

    # Reject non-64-char sha256
    with pytest.raises(ValidationError):
        ModelProvenanceContract(
            model_id="ArcFace",
            model_version="4c06341c",
            file="w600k_r50.onnx",
            sha256="too_short_sha",
            source_url="https://example.invalid",
            license_name="MIT",
            permitted_use="Research",
        )
