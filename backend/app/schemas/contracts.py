from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class DetectionState(StrEnum):
    OK = "OK"
    NO_FACE = "NO_FACE"
    MULTIPLE_FACES = "MULTIPLE_FACES"
    ERROR = "ERROR"


class QualityState(StrEnum):
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    RECAPTURE = "RECAPTURE"


class SecurityState(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNCERTAIN = "UNCERTAIN"
    NOT_REQUIRED = "NOT_REQUIRED"


class DecisionState(StrEnum):
    ACCEPT = "ACCEPT"
    RECAPTURE = "RECAPTURE"
    SECONDARY_CHECK = "SECONDARY_CHECK"
    REVIEW = "REVIEW"
    REJECT_UNKNOWN = "REJECT_UNKNOWN"


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float
    confidence: float = Field(ge=0.0, le=1.0)


class Keypoint(BaseModel):
    x: float
    y: float
    name: str


class DetectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: DetectionState
    detector_id: str
    detector_version: str
    frame_id: str
    boxes: list[BoundingBox] = Field(default_factory=list)
    keypoints: list[Keypoint] = Field(default_factory=list)
    face_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    preprocessing_id: str
    failure_codes: list[str] = Field(default_factory=list)


class PoseResult(BaseModel):
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None


class QualityResult(BaseModel):
    status: QualityState
    face_size_px: int
    blur_score: float
    mean_luminance: float
    clipped_pixel_ratio: float
    pose: PoseResult = Field(default_factory=PoseResult)
    alignment_score: float | None = None
    fiqa_score: float | None = Field(default=None, ge=0.0, le=1.0)
    temporal_stability: float | None = None
    route_hint: str
    latency_ms: float = Field(ge=0.0)
    failure_codes: list[str] = Field(default_factory=list)


class EmbeddingResult(BaseModel):
    recognizer_id: str
    model_version: str
    embedding_dimension: int = Field(gt=0)
    embedding_ref: str
    preprocessing_id: str
    normalization: str = "L2"
    latency_ms: float = Field(ge=0.0)
    quality_state: QualityState
    failure_codes: list[str] = Field(default_factory=list)


class RetrievalCandidate(BaseModel):
    person_id: str
    employee_id: str
    full_name: str
    similarity: float = Field(ge=-1.0, le=1.0)


class RetrievalResult(BaseModel):
    roster_scope: str
    metric: str = "cosine"
    top_k: list[RetrievalCandidate] = Field(default_factory=list)
    top1_similarity: float | None = None
    top2_similarity: float | None = None
    margin: float | None = None
    candidate_count: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    index_version: str


class SecurityResult(BaseModel):
    liveness_model: str | None = None
    model_version: str | None = None
    state: SecurityState
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    risk_flags: list[str] = Field(default_factory=list)
    challenge_state: str = "NOT_REQUESTED"
    latency_ms: float = Field(ge=0.0)


class DecisionResult(BaseModel):
    final_state: DecisionState
    reason_codes: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    top_candidate: RetrievalCandidate | None = None
    confidence_evidence: dict[str, Any] = Field(default_factory=dict)
    policy_version: str
    model_versions: list[str] = Field(default_factory=list)
    timestamp: datetime
    audit_id: str


class HealthResponse(BaseModel):
    status: str
    environment: str
    database: str
    model_version: str
    model_components: dict[str, str]
    similarity_threshold: float
    threshold_status: str
    liveness_required: bool
    ready_for_attendance: bool
