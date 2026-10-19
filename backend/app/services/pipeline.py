from __future__ import annotations

import json
import math
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.entities import AttendanceEvent, AuditEvent, EmbeddingRecord, Person
from app.schemas.contracts import (
    DecisionState,
    RetrievalCandidate,
    SecurityState,
)
from app.security import decrypt_embedding, encrypt_embedding
from app.vision.engine import FrameObservation, VisionEngine, VisionError
from app.vision.enhancement import ENHANCED_PREPROCESSING, ORIGINAL_PREPROCESSING, conditional_enhance
from app.schemas.contracts import DetectionState, QualityState


PREPROCESSING_VERSION = "five-point-norm-crop-112-v1"


def _preprocessing_id(model_id: str, model_version: str, branch: str) -> str:
    return f"{model_id}:{model_version}:{PREPROCESSING_VERSION}:{branch}"


def _choose_preprocessing(obs: FrameObservation, model_id: str, model_version: str) -> tuple[np.ndarray, str, dict[str, Any]]:
    if obs.aligned_face_bgr is None or obs.quality is None:
        raise VisionError("Aligned crop and quality evidence are required before recognition")
    # Keep the primary baseline on the original aligned crop. Only route an exposure
    # problem through enhancement when a calibrated non-primary specialist is selected.
    use_enhancement = model_id != "ArcFace" and any(
        code in obs.quality.result.failure_codes for code in ("UNDEREXPOSED", "OVEREXPOSED")
    )
    if use_enhancement:
        route = conditional_enhance(obs.aligned_face_bgr, obs.quality.result)
        if route.applied:
            return route.image_bgr, _preprocessing_id(model_id, model_version, route.preprocessing_id), {
                "preprocessing_id": route.preprocessing_id,
                "enhancement_applied": True,
                "enhancement_reason": route.reason,
            }
    return obs.aligned_face_bgr, _preprocessing_id(model_id, model_version, ORIGINAL_PREPROCESSING), {
        "preprocessing_id": ORIGINAL_PREPROCESSING,
        "enhancement_applied": False,
        "enhancement_reason": "REFERENCE_BRANCH",
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalise(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    if value.size == 0 or not np.all(np.isfinite(value)) or norm <= 1e-12:
        raise ValueError("Embedding is empty, non-finite, or has zero norm")
    return value / norm


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    a, b = _normalise(left), _normalise(right)
    if a.shape != b.shape:
        raise ValueError(f"Embedding dimensions differ: {a.size} versus {b.size}")
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


class AttendancePipeline:
    """V5 orchestration layer. Decisions are based only on real model outputs and stored templates."""

    def __init__(self, settings: Settings, vision: VisionEngine):
        self.settings = settings
        self.vision = vision

    def _audit(
        self,
        db: Session,
        *,
        session_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        state: str,
        reasons: list[str],
        evidence: dict[str, Any],
    ) -> str:
        audit_id = str(uuid.uuid4())
        event = AuditEvent(
            audit_id=audit_id,
            session_id=session_id,
            occurred_at=_utcnow(),
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            decision_state=state,
            reason_codes_json=json.dumps(reasons, separators=(",", ":")),
            # Only versioned decision evidence and hashes are stored; no image bytes or embeddings.
            evidence_json=json.dumps(evidence, separators=(",", ":"), default=str),
        )
        db.add(event)
        db.commit()
        return audit_id

    def _fail(
        self,
        db: Session,
        *,
        session_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        state: DecisionState,
        reasons: list[str],
        evidence: dict[str, Any],
        status_code: int,
        detail: str | dict[str, Any],
    ) -> None:
        try:
            self._audit(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id,
                action=action, state=state.value, reasons=reasons, evidence=evidence,
            )
        except Exception:
            db.rollback()
            # Do not convert an audit-storage outage into a biometric acceptance.
            raise HTTPException(status_code=503, detail="Audit persistence failed; decision was not accepted")
        raise HTTPException(status_code=status_code, detail=detail)

    def _read_gallery(
        self,
        db: Session,
        *,
        recognizer_id: str,
        model_version: str,
        preprocessing_id: str,
        employee_id: str | None,
    ) -> tuple[list[tuple[Person, np.ndarray]], int]:
        statement = (
            select(EmbeddingRecord, Person)
            .join(Person, Person.person_id == EmbeddingRecord.person_id)
            .where(
                EmbeddingRecord.accepted.is_(True),
                EmbeddingRecord.recognizer_id == recognizer_id,
                EmbeddingRecord.model_version == model_version,
                EmbeddingRecord.preprocessing_id == preprocessing_id,
                EmbeddingRecord.enrollment_version == Person.enrollment_version,
                Person.is_active.is_(True),
            )
        )
        if employee_id is not None:
            statement = statement.where(Person.employee_id == employee_id)
        rows = db.execute(statement).all()
        vectors_by_person: dict[str, list[np.ndarray]] = defaultdict(list)
        people_by_id: dict[str, Person] = {}
        for record, person in rows:
            raw = decrypt_embedding(record.ciphertext, record.nonce, self.settings)
            vector = np.frombuffer(raw, dtype=np.float32)
            if vector.size != record.embedding_dim:
                raise RuntimeError(f"Encrypted embedding integrity failure for record {record.embedding_id}")
            vectors_by_person[person.person_id].append(_normalise(vector.copy()))
            people_by_id[person.person_id] = person

        profiles: list[tuple[Person, np.ndarray]] = []
        for person_id, vectors in vectors_by_person.items():
            dimension_set = {vector.size for vector in vectors}
            if len(dimension_set) != 1:
                raise RuntimeError(f"Mixed embedding dimensions in profile for person {person_id}")
            prototype = _normalise(np.mean(np.stack(vectors, axis=0), axis=0))
            profiles.append((people_by_id[person_id], prototype))
        return profiles, len(rows)

    def _retrieve(
        self,
        db: Session,
        query: np.ndarray,
        *,
        recognizer_id: str,
        model_version: str,
        preprocessing_id: str,
        employee_id: str | None = None,
    ) -> tuple[list[RetrievalCandidate], int, float]:
        started = time.perf_counter()
        profiles, row_count = self._read_gallery(
            db, recognizer_id=recognizer_id, model_version=model_version,
            preprocessing_id=preprocessing_id, employee_id=employee_id,
        )
        query_vector = _normalise(query)
        scored: list[RetrievalCandidate] = []
        for person, profile in profiles:
            score = _cosine(query_vector, profile)
            scored.append(RetrievalCandidate(
                person_id=person.person_id,
                employee_id=person.employee_id,
                full_name=person.full_name,
                similarity=score,
            ))
        scored.sort(key=lambda item: item.similarity, reverse=True)
        return scored[: self.settings.recognition_top_k], len(profiles), (time.perf_counter() - started) * 1000.0

    def _model_version(self, model_id: str) -> str:
        if model_id == "ArcFace":
            return self.vision.recognizer_version
        if model_id == "AdaFace" and self.vision.adaface is not None:
            return self.vision.adaface.model_version
        if model_id == "MobileFaceNet" and self.vision.mobilefacenet is not None:
            return self.vision.mobilefacenet.model_version
        raise VisionError(f"Recognizer {model_id} is not configured")

    def _embed_for_model(
        self, obs: FrameObservation, model_id: str, image_bgr: np.ndarray | None = None
    ) -> tuple[np.ndarray, str]:
        crop = image_bgr if image_bgr is not None else obs.aligned_face_bgr
        if crop is None:
            raise VisionError("Aligned face crop is unavailable")
        if model_id == "ArcFace":
            return self.vision.primary_embedding(crop), self.vision.recognizer_version
        embedding, _name, version = self.vision.secondary_embedding(model_id, crop)
        return embedding, version

    def _model_options(self) -> list[str]:
        return [
            name for name, exists in (
                ("AdaFace", self.vision.adaface is not None),
                ("MobileFaceNet", self.vision.mobilefacenet is not None),
                ("ArcFace", True),
            ) if exists
        ]

    def _secondary_check(
        self,
        db: Session,
        observations: list[tuple[FrameObservation, str, np.ndarray, str, list[RetrievalCandidate], int]],
        primary_person_id: str | None,
        employee_id: str | None,
    ) -> dict[str, Any] | None:
        primary_models = {model for _obs, model, _emb, _preproc, _top, _count in observations}
        for model_id in self._model_options():
            if model_id in primary_models or not self.settings.is_model_calibrated(model_id):
                continue
            try:
                threshold = self.settings.threshold_for(model_id)
            except ValueError:
                continue
            # A secondary result is meaningful only when that same model/version has enrolled templates.
            votes: list[str] = []
            evidence_by_frame: list[tuple[str, float, float | None]] = []
            margins: list[float | None] = []
            usable = 0
            version = self._model_version(model_id)
            for obs, _route_model, _embedding, _original_preprocessing_id, _top, _count in observations:
                if obs.aligned_face_bgr is None or obs.quality is None:
                    continue
                try:
                    crop, _preprocessing_hint, branch_info = _choose_preprocessing(obs, model_id, version)
                    embedding, version = self._embed_for_model(obs, model_id, crop)
                    preprocessing_id = _preprocessing_id(model_id, version, branch_info["preprocessing_id"])
                    top, candidate_count, _latency = self._retrieve(
                        db, embedding, recognizer_id=model_id, model_version=version,
                        preprocessing_id=preprocessing_id, employee_id=employee_id,
                    )
                except (VisionError, RuntimeError, ValueError):
                    continue
                if candidate_count == 0 or not top:
                    continue
                usable += 1
                first = top[0]
                second = top[1] if len(top) > 1 else None
                margin = first.similarity - second.similarity if second else None
                margins.append(margin)
                evidence_by_frame.append((first.person_id, first.similarity, margin))
                if first.similarity >= threshold and (margin is None or margin >= self.settings.ambiguity_margin):
                    votes.append(first.person_id)
            if usable < self.settings.minimum_identification_frames or not votes:
                continue
            winner, count = Counter(votes).most_common(1)[0]
            required_votes = math.ceil(usable * self.settings.temporal_min_vote_fraction)
            winning_scores = [score for person_id, score, _margin in evidence_by_frame
                              if person_id == winner and score >= threshold]
            winning_margins = [margin for person_id, _score, margin in evidence_by_frame
                               if person_id == winner]
            mean_score = float(np.mean(winning_scores)) if winning_scores else -1.0
            margin_ok = all(m is None or m >= self.settings.ambiguity_margin for m in winning_margins)
            if winner == primary_person_id and count >= required_votes and mean_score >= threshold and margin_ok:
                return {
                    "model_id": model_id,
                    "person_id": winner,
                    "mean_score": mean_score,
                    "threshold": threshold,
                    "votes": count,
                    "frames": usable,
                    "agrees_with_primary": primary_person_id is None or winner == primary_person_id,
                }
        return None

    def _analyze_burst(
        self,
        db: Session,
        image_payloads: list[bytes],
        *,
        session_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        employee_id: str | None,
    ) -> tuple[list[tuple[FrameObservation, str, np.ndarray, list[RetrievalCandidate], int]], list[str], dict[str, Any]]:
        evidence: dict[str, Any] = {"pipeline_version": self.vision.pipeline_version, "frames": []}
        reasons: list[str] = []
        if len(image_payloads) < self.settings.minimum_identification_frames:
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.RECAPTURE, reasons=["INSUFFICIENT_TEMPORAL_FRAMES"], evidence=evidence,
                status_code=422,
                detail=f"At least {self.settings.minimum_identification_frames} separate camera frames are required.",
            )
        if len(image_payloads) > self.settings.maximum_identification_frames:
            raise HTTPException(
                status_code=413,
                detail=f"At most {self.settings.maximum_identification_frames} frames are accepted per request.",
            )
        payload_total = sum(len(payload) for payload in image_payloads)
        if payload_total > self.settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="Total frame-burst payload exceeds the configured limit.")
        if any(not payload or len(payload) > self.settings.max_upload_bytes for payload in image_payloads):
            raise HTTPException(status_code=413, detail="A frame is empty or exceeds the image payload limit.")

        processed: list[tuple[FrameObservation, str, np.ndarray, list[RetrievalCandidate], int]] = []
        for frame_index, payload in enumerate(image_payloads):
            frame_id = f"{session_id}:{frame_index:02d}"
            try:
                obs = self.vision.analyze(payload, frame_id)
            except (VisionError, ValueError) as exc:
                evidence["frames"].append({"frame_id": frame_id, "state": "ERROR", "reason": str(exc)})
                reasons.append("FRAME_DECODE_OR_INFERENCE_ERROR")
                continue

            frame_evidence: dict[str, Any] = {
                "frame_id": frame_id,
                "sha256": obs.frame_sha256,
                "detector_id": obs.detector_id,
                "detector_version": obs.detector_version,
                "detection_state": obs.detection_state.value,
                "detection_latency_ms": obs.detection_latency_ms,
            }
            if obs.bbox is not None:
                frame_evidence["bbox"] = [float(v) for v in obs.bbox[:4]]
                frame_evidence["detection_confidence"] = obs.detection_confidence
            if obs.quality is not None:
                frame_evidence["quality"] = obs.quality.result.model_dump(mode="json")
            evidence["frames"].append(frame_evidence)

            if obs.detection_state == DetectionState.MULTIPLE_FACES:
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=DecisionState.RECAPTURE, reasons=["MULTIPLE_FACES"], evidence=evidence,
                    status_code=422, detail="Multiple faces detected. Ensure only the intended person is in frame.",
                )
            if obs.detection_state == DetectionState.NO_FACE or obs.quality is None:
                reasons.append("NO_FACE_IN_FRAME")
                continue
            if obs.quality.result.status == QualityState.RECAPTURE:
                reasons.extend(obs.quality.result.failure_codes)
                continue

            if obs.quality.result.status == QualityState.DEGRADED:
                model_id = "AdaFace"
                if self.vision.adaface is None:
                    reasons.append("ADAFACE_REQUIRED_BUT_UNAVAILABLE")
                    continue
                if not self.settings.is_model_calibrated(model_id):
                    reasons.append("ADAFACE_THRESHOLD_NOT_CALIBRATED")
                    continue
                version = self._model_version(model_id)
                try:
                    crop, _preprocessing_hint, branch_info = _choose_preprocessing(obs, model_id, version)
                    embedding, version = self._embed_for_model(obs, model_id, crop)
                    preprocessing_id = _preprocessing_id(model_id, version, branch_info["preprocessing_id"])
                    frame_evidence["preprocessing"] = branch_info
                except (VisionError, ValueError) as exc:
                    reasons.append(f"ADAFACE_INFERENCE_FAILED:{type(exc).__name__}")
                    continue
            else:
                model_id = "ArcFace"
                if not self.settings.is_model_calibrated(model_id):
                    self._fail(
                        db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                        state=DecisionState.REVIEW, reasons=["ARCFACE_THRESHOLD_NOT_CALIBRATED"],
                        evidence=evidence, status_code=503,
                        detail="ArcFace threshold has not been calibrated against the project's validation protocol.",
                    )
                embedding = obs.primary_embedding
                version = obs.recognizer_version
                preprocessing_id = _preprocessing_id(model_id, version, ORIGINAL_PREPROCESSING)
                frame_evidence["preprocessing"] = {
                    "preprocessing_id": ORIGINAL_PREPROCESSING,
                    "enhancement_applied": False,
                    "enhancement_reason": "PRIMARY_BASELINE_ORIGINAL",
                }
                if embedding is None:
                    reasons.append("PRIMARY_EMBEDDING_UNAVAILABLE")
                    continue

            try:
                top, candidate_count, retrieval_latency = self._retrieve(
                    db, embedding, recognizer_id=model_id, model_version=version,
                    preprocessing_id=preprocessing_id, employee_id=employee_id,
                )
                threshold = self.settings.threshold_for(model_id)
            except (RuntimeError, ValueError) as exc:
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=DecisionState.REVIEW, reasons=["RETRIEVAL_OR_KEY_CONFIGURATION_ERROR"],
                    evidence=evidence, status_code=503,
                    detail=f"Retrieval cannot safely continue: {exc}",
                )
            if not top:
                frame_evidence["retrieval"] = {"recognizer_id": model_id, "candidate_count": candidate_count}
                processed.append((obs, model_id, embedding, preprocessing_id, [], candidate_count))
                reasons.append(f"NO_ENROLLED_TEMPLATES_FOR:{model_id}:{version}")
                continue

            first = top[0]
            second = top[1] if len(top) > 1 else None
            margin = first.similarity - second.similarity if second else None
            frame_evidence["recognition"] = {
                "recognizer_id": model_id,
                "model_version": version,
                "top1": {"employee_id": first.employee_id, "person_id": first.person_id, "similarity": first.similarity},
                "top2_similarity": second.similarity if second else None,
                "margin": margin,
                "threshold": threshold,
                "candidate_count": candidate_count,
                "retrieval_latency_ms": retrieval_latency,
                "embedding_dimension": int(embedding.size),
            }
            processed.append((obs, model_id, embedding, preprocessing_id, top, candidate_count))

        evidence["reasons"] = reasons
        if len(processed) < self.settings.minimum_identification_frames:
            state = DecisionState.RECAPTURE
            detail = (
                f"Only {len(processed)} usable frames remain. Capture at least "
                f"{self.settings.minimum_identification_frames} clear, single-face frames."
            )
            if any("ADAFACE_REQUIRED_BUT_UNAVAILABLE" in reason for reason in reasons):
                detail = "Image quality requires the AdaFace specialist, but no compatible AdaFace ONNX model is configured."
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=state, reasons=list(dict.fromkeys(reasons or ["INSUFFICIENT_USABLE_FRAMES"])),
                evidence=evidence, status_code=422, detail=detail,
            )
        return processed, reasons, evidence

    def identify(
        self,
        db: Session,
        image_payloads: list[bytes],
        *,
        punch_type: str,
        client_device_id: str,
        actor_id: str,
        employee_id_claim: str | None = None,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        action = "attendance.verify" if employee_id_claim else "attendance.identify"
        actor_type = "kiosk_device"
        if punch_type not in {"CHECK_IN", "CHECK_OUT"}:
            raise HTTPException(status_code=422, detail="punch_type must be CHECK_IN or CHECK_OUT")
        if self.settings.require_liveness and self.vision.liveness is None:
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.REVIEW, reasons=["REQUIRED_LIVENESS_MODEL_UNAVAILABLE"],
                evidence={"pipeline_version": self.vision.pipeline_version},
                status_code=503,
                detail="Attendance is disabled because policy requires a configured, compatible MiniFASNet ONNX liveness model.",
            )

        try:
            processed, reasons, evidence = self._analyze_burst(
                db, image_payloads, session_id=session_id, actor_type=actor_type, actor_id=actor_id,
                action=action, employee_id=employee_id_claim,
            )
        except HTTPException:
            raise

        # Liveness is independent evidence and is required according to the configured policy.
        security_scores: list[float] = []
        if self.settings.require_liveness:
            for obs, _model_id, _embedding, _preprocessing_id, _top, _count in processed:
                try:
                    security_scores.append(self.vision.liveness_probability(obs))
                except (VisionError, ValueError) as exc:
                    self._fail(
                        db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                        state=DecisionState.REVIEW, reasons=["LIVENESS_INFERENCE_FAILED"],
                        evidence=evidence, status_code=503,
                        detail=f"Liveness inference failed; attendance was not recorded ({type(exc).__name__}).",
                    )
            evidence["security"] = {
                "model": "MiniFASNet",
                "model_version": self.vision.liveness.model_version if self.vision.liveness else None,
                "scores": security_scores,
                "required_score": self.settings.required_liveness_score,
            }
            below = [score for score in security_scores if score < self.settings.required_liveness_score]
            if below:
                state = DecisionState.REJECT_UNKNOWN if min(below) < self.settings.required_liveness_score - 0.05 else DecisionState.RECAPTURE
                status = 403 if state == DecisionState.REJECT_UNKNOWN else 409
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=state, reasons=["LIVENESS_FAILED" if status == 403 else "LIVENESS_UNCERTAIN"],
                    evidence=evidence, status_code=status,
                    detail={"message": "Presentation-attack/liveness policy did not pass.", "state": "FAIL" if status == 403 else "UNCERTAIN"},
                )

        # Evidence is already restricted to calibrated model IDs and their compatible versions.
        per_frame_winners: list[tuple[str, float, float, float | None, str]] = []
        best_unmatched: tuple[float, float] | None = None
        gallery_count = 0
        for obs, model_id, embedding, preprocessing_id, top, candidate_count in processed:
            gallery_count += candidate_count
            if not top:
                continue
            threshold = self.settings.threshold_for(model_id)
            first = top[0]
            second = top[1] if len(top) > 1 else None
            margin = first.similarity - second.similarity if second else None
            if best_unmatched is None or first.similarity > best_unmatched[0]:
                best_unmatched = (first.similarity, threshold)
            if first.similarity >= threshold:
                per_frame_winners.append((first.person_id, first.similarity, threshold, margin, model_id))

        if not per_frame_winners:
            if employee_id_claim is not None:
                max_score, threshold = best_unmatched if best_unmatched else (-1.0, self.settings.similarity_threshold)
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=DecisionState.REJECT_UNKNOWN, reasons=["BIOMETRIC_IDENTITY_MISMATCH"],
                    evidence=evidence, status_code=401,
                    detail={"message": "The face does not match the claimed employee.", "similarity_score": max_score, "required_threshold": threshold},
                )
            max_score, threshold = best_unmatched if best_unmatched else (-1.0, self.settings.similarity_threshold)
            detail = (
                {"message": "No matching active employee template found for the submitted face.",
                 "similarity_score": max_score, "required_threshold": threshold}
                if gallery_count > 0 else "No enrolled templates exist for the configured model version."
            )
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.REJECT_UNKNOWN, reasons=["NO_MATCH_ABOVE_CALIBRATED_THRESHOLD"],
                evidence=evidence, status_code=404, detail=detail,
            )

        votes = Counter(item[0] for item in per_frame_winners)
        primary_person_id, vote_count = votes.most_common(1)[0]
        usable_frames = len(processed)
        required_votes = math.ceil(usable_frames * self.settings.temporal_min_vote_fraction)
        winning_model, _winning_model_votes = Counter(
            item[4] for item in per_frame_winners if item[0] == primary_person_id
        ).most_common(1)[0]
        winner_scores = [
            item[1] for item in per_frame_winners
            if item[0] == primary_person_id and item[4] == winning_model
        ]
        primary_mean = float(np.mean(winner_scores)) if winner_scores else -1.0
        margins_close = any(
            top and len(top) > 1 and (top[0].similarity - top[1].similarity) < self.settings.ambiguity_margin
            for _obs, _model, _embedding, _preprocessing_id_value, top, _count in processed
        )
        temporally_stable = vote_count >= required_votes
        secondary_evidence = None

        if not temporally_stable or margins_close:
            secondary_evidence = self._secondary_check(
                db, processed, primary_person_id=primary_person_id, employee_id=employee_id_claim,
            )
            evidence["secondary_check"] = secondary_evidence
            if not secondary_evidence:
                state = DecisionState.SECONDARY_CHECK if not temporally_stable else DecisionState.REVIEW
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=state, reasons=["TEMPORAL_DISAGREEMENT" if not temporally_stable else "SMALL_TOP1_TOP2_MARGIN"],
                    evidence=evidence, status_code=409,
                    detail={
                        "message": "The biometric evidence is ambiguous; no attendance was recorded.",
                        "ambiguity_margin": self.settings.ambiguity_margin,
                        "first_candidate": primary_person_id,
                        "second_candidate": next((pid for pid, _count in votes.most_common(2)[1:]), "UNKNOWN"),
                    },
                )
            if not secondary_evidence["agrees_with_primary"]:
                self._fail(
                    db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                    state=DecisionState.REVIEW, reasons=["INDEPENDENT_RECOGNIZERS_DISAGREE"],
                    evidence=evidence, status_code=409,
                    detail={"message": "Independent recognizers disagree; review or recapture is required."},
                )

        # Lock the selected identity before cooldown checking and persisting attendance.
        person = db.execute(
            select(Person).where(Person.person_id == primary_person_id).with_for_update()
        ).scalar_one_or_none()
        if person is None or not person.is_active:
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.REJECT_UNKNOWN, reasons=["EMPLOYEE_INACTIVE_OR_MISSING"],
                evidence=evidence, status_code=403, detail="Employee is inactive or no longer available.",
            )
        if employee_id_claim is not None and person.employee_id != employee_id_claim:
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.REJECT_UNKNOWN, reasons=["BIOMETRIC_IDENTITY_MISMATCH"],
                evidence=evidence, status_code=401,
                detail={"message": "The face does not match the claimed employee.", "similarity_score": primary_mean,
                        "required_threshold": self.settings.threshold_for(per_frame_winners[0][4])},
            )

        now = _utcnow()
        cooldown_start = now - timedelta(seconds=self.settings.attendance_cooldown_seconds)
        last_event = db.execute(
            select(AttendanceEvent)
            .where(
                AttendanceEvent.person_id == person.person_id,
                AttendanceEvent.punch_type == punch_type,
                AttendanceEvent.timestamp >= cooldown_start,
            )
            .order_by(AttendanceEvent.timestamp.desc())
            .limit(1)
            .with_for_update()
        ).scalar_one_or_none()
        if last_event is not None and self.settings.attendance_cooldown_seconds > 0:
            last_time = last_event.timestamp
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            remaining = max(0, int(self.settings.attendance_cooldown_seconds - (now - last_time).total_seconds()))
            self._fail(
                db, session_id=session_id, actor_type=actor_type, actor_id=actor_id, action=action,
                state=DecisionState.REVIEW, reasons=["ATTENDANCE_COOLDOWN_ACTIVE"], evidence=evidence,
                status_code=409,
                detail={"message": "Attendance already recorded within the cooldown window.",
                        "remaining_seconds": remaining, "last_punch_time": last_time.isoformat()},
            )

        matched_model = secondary_evidence["model_id"] if secondary_evidence else winning_model
        matched_threshold = secondary_evidence["threshold"] if secondary_evidence else self.settings.threshold_for(matched_model)
        matched_score = secondary_evidence["mean_score"] if secondary_evidence else primary_mean
        evidence["decision"] = {
            "employee_id": person.employee_id,
            "person_id": person.person_id,
            "enrollment_version": person.enrollment_version,
            "matched_model": matched_model,
            "mean_similarity": matched_score,
            "threshold": matched_threshold,
            "temporal_votes": vote_count,
            "required_temporal_votes": required_votes,
            "liveness_state": "PASS" if self.settings.require_liveness else "NOT_REQUIRED",
        }
        audit_id = str(uuid.uuid4())
        attendance = AttendanceEvent(
            attendance_id=str(uuid.uuid4()),
            person_id=person.person_id,
            employee_id=person.employee_id,
            punch_type=punch_type,
            timestamp=now,
            similarity_score=matched_score,
            threshold=matched_threshold,
            client_device_id=client_device_id,
            pipeline_version=self.vision.pipeline_version,
            evidence_id=audit_id,
        )
        audit = AuditEvent(
            audit_id=audit_id,
            session_id=session_id,
            occurred_at=now,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            decision_state=DecisionState.ACCEPT.value,
            reason_codes_json=json.dumps(["TEMPORAL_CONFIRMATION_PASSED"], separators=(",", ":")),
            evidence_json=json.dumps(evidence, separators=(",", ":"), default=str),
        )
        try:
            db.add_all([attendance, audit])
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="Attendance transaction failed; no success was reported") from exc

        return {
            "status": "success",
            "attendance_id": attendance.attendance_id,
            "user_id": person.person_id,
            "employee_id": person.employee_id,
            "full_name": person.full_name,
            "department": person.department,
            "punch_type": punch_type,
            "timestamp": now.isoformat(),
            "similarity_score": matched_score,
            "threshold": matched_threshold,
            "message": "Attendance recorded after calibrated recognition and temporal confirmation.",
            "audit_id": audit_id,
        }

    def enroll(
        self,
        db: Session,
        image_payloads: list[bytes],
        *,
        employee_id: str,
        full_name: str,
        department: str | None,
        admin_actor_id: str,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        action = "biometrics.enroll"
        employee_id = employee_id.strip()
        full_name = full_name.strip()
        if not employee_id or not full_name:
            raise HTTPException(status_code=422, detail="employee_id and full_name are required")
        if self.settings.require_liveness and self.vision.liveness is None:
            raise HTTPException(status_code=503, detail="Enrollment requires a configured liveness model by current policy")
        if len(image_payloads) < self.settings.minimum_identification_frames:
            raise HTTPException(
                status_code=422,
                detail=f"Enrollment requires at least {self.settings.minimum_identification_frames} separate frames/views.",
            )
        if len(image_payloads) > self.settings.maximum_identification_frames:
            raise HTTPException(status_code=413, detail="Too many enrollment frames.")
        if sum(map(len, image_payloads)) > self.settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="Enrollment burst exceeds total upload limit.")
        if any(not item or len(item) > self.settings.max_upload_bytes for item in image_payloads):
            raise HTTPException(status_code=413, detail="A frame is empty or exceeds the image upload limit.")

        observations: list[FrameObservation] = []
        frame_evidence: list[dict[str, Any]] = []
        liveness_scores: list[float] = []
        for index, payload in enumerate(image_payloads):
            try:
                obs = self.vision.analyze(payload, f"{session_id}:{index:02d}")
            except (VisionError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=f"Enrollment frame {index + 1} failed decoding/inference: {exc}") from exc
            if obs.detection_state == DetectionState.MULTIPLE_FACES:
                raise HTTPException(status_code=422, detail=f"Enrollment frame {index + 1} contains multiple faces.")
            if obs.detection_state != DetectionState.OK or obs.quality is None:
                frame_evidence.append({"frame_id": obs.frame_id, "sha256": obs.frame_sha256, "state": "NO_FACE"})
                continue
            if obs.quality.result.status == QualityState.RECAPTURE:
                frame_evidence.append({
                    "frame_id": obs.frame_id, "sha256": obs.frame_sha256,
                    "state": "RECAPTURE", "quality": obs.quality.result.model_dump(mode="json"),
                })
                continue
            if self.settings.require_liveness:
                score = self.vision.liveness_probability(obs)
                liveness_scores.append(score)
                if score < self.settings.required_liveness_score:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Enrollment frame {index + 1} did not pass the configured liveness policy.",
                    )
            observations.append(obs)
            frame_evidence.append({
                "frame_id": obs.frame_id, "sha256": obs.frame_sha256,
                "quality": obs.quality.result.model_dump(mode="json"),
                "detector_id": obs.detector_id, "detector_version": obs.detector_version,
            })
        if len(observations) < self.settings.minimum_identification_frames:
            raise HTTPException(
                status_code=422,
                detail=f"Only {len(observations)} usable enrollment views; at least "
                       f"{self.settings.minimum_identification_frames} are required.",
            )

        db.rollback()
        existing = db.execute(select(Person).where(Person.employee_id == employee_id).with_for_update()).scalar_one_or_none()
        if existing is not None and not existing.is_active:
            raise HTTPException(
                status_code=409,
                detail="This employee is inactive. An authorized administrator must reactivate the identity before re-enrollment.",
            )
        if existing is None:
            person = Person(employee_id=employee_id, full_name=full_name, department=department, enrollment_version=1, is_active=True)
            db.add(person)
            db.flush()
            enrollment_version = 1
        else:
            person = existing
            enrollment_version = existing.enrollment_version + 1
            person.enrollment_version = enrollment_version
            person.full_name = full_name
            person.department = department
            person.updated_at = _utcnow()

        model_rows = 0
        model_counts: dict[str, int] = defaultdict(int)
        try:
            for obs in observations:
                if obs.aligned_face_bgr is None or obs.quality is None:
                    raise RuntimeError("Accepted enrollment frame has no aligned face or quality record")
                embeddings: list[tuple[str, str, np.ndarray]] = [
                    ("ArcFace", self.vision.recognizer_version, self.vision.primary_embedding(obs.aligned_face_bgr)),
                ]
                if self.vision.adaface is not None:
                    vec, _name, ver = self.vision.secondary_embedding("AdaFace", obs.aligned_face_bgr)
                    embeddings.append(("AdaFace", ver, vec))
                if self.vision.mobilefacenet is not None:
                    vec, _name, ver = self.vision.secondary_embedding("MobileFaceNet", obs.aligned_face_bgr)
                    embeddings.append(("MobileFaceNet", ver, vec))
                for model_id, version, vector in embeddings:
                    ciphertext, nonce = encrypt_embedding(_normalise(vector).astype(np.float32).tobytes(), self.settings)
                    db.add(EmbeddingRecord(
                        person_id=person.person_id,
                        enrollment_version=enrollment_version,
                        recognizer_id=model_id,
                        model_version=version,
                        preprocessing_id=f"{model_id}:{version}:{PREPROCESSING_VERSION}",
                        embedding_dim=int(vector.size),
                        ciphertext=ciphertext,
                        nonce=nonce,
                        sample_sha256=obs.frame_sha256,
                        quality_json=json.dumps(obs.quality.result.model_dump(mode="json"), separators=(",", ":")),
                        accepted=True,
                    ))
                    model_rows += 1
                    model_counts[model_id] += 1

            audit_id = str(uuid.uuid4())
            audit = AuditEvent(
                audit_id=audit_id,
                session_id=session_id,
                occurred_at=_utcnow(),
                actor_type="administrator",
                actor_id=admin_actor_id,
                action=action,
                decision_state="ENROLLED",
                reason_codes_json=json.dumps(["MULTI_SAMPLE_ENROLLMENT_PROFILE_CREATED"]),
                evidence_json=json.dumps({
                    "person_id": person.person_id,
                    "employee_id": employee_id,
                    "enrollment_version": enrollment_version,
                    "accepted_sample_count": len(observations),
                    "model_embedding_counts": dict(model_counts),
                    "frames": frame_evidence,
                    "liveness_scores": liveness_scores,
                    "pipeline_version": self.vision.pipeline_version,
                }, separators=(",", ":"), default=str),
            )
            db.add(audit)
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="Enrollment transaction failed; no success was reported") from exc

        sharpness = [obs.quality.result.blur_score for obs in observations if obs.quality is not None]
        return {
            "status": "success",
            "person_id": person.person_id,
            "employee_id": person.employee_id,
            "full_name": person.full_name,
            "department": person.department,
            "enrollment_version": enrollment_version,
            "accepted_sample_count": len(observations),
            "embedding_records_created": model_rows,
            "models": dict(model_counts),
            "quality_metrics": {
                "mean_sharpness": float(np.mean(sharpness)) if sharpness else None,
                "minimum_face_size_px": min(obs.quality.result.face_size_px for obs in observations if obs.quality),
                "model_embedding_counts": dict(model_counts),
            },
            "audit_id": audit_id,
        }
