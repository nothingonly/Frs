from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes.admin import router as admin_router
from app.api.routes.attendance import router as attendance_router
from app.api.routes.enrollment import router as enrollment_router
from app.core.config import get_settings
from app.database import SessionLocal, create_schema, engine
from app.schemas.contracts import HealthResponse
from app.services.pipeline import AttendancePipeline
from app.vision.engine import VisionEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("frs")


class RequestSizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        settings = request.app.state.settings
        if length:
            try:
                if int(length) > settings.max_request_bytes + 1024 * 1024:
                    return JSONResponse(status_code=413, content={"detail": "Request body exceeds configured limit."})
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
        return await call_next(request)


def _has_threshold(settings, model_id: str) -> bool:
    try:
        settings.threshold_for(model_id)
        return True
    except ValueError:
        return False


def _register_runtime_models(db, vision: VisionEngine) -> None:
    import json
    from pathlib import Path
    from app.db.entities import ModelRegistryEntry
    from app.vision.onnx_models import sha256_file

    candidates: list[tuple[str, str, str, str, str, dict, dict]] = []
    for model_id, model in (("SCRFD", vision.detector), ("ArcFace", vision.recognizer)):
        path_value = getattr(model, "model_file", None)
        if not path_value or not Path(str(path_value)).is_file():
            continue
        path = Path(str(path_value)).resolve()
        digest = vision._model_version(model)
        candidates.append((
            model_id, digest, str(path), "InsightFace model-zoo weights: non-commercial research unless separately licensed",
            "five-point-norm-crop-112-v1" if model_id == "ArcFace" else f"scrfd-det-size-{vision.settings.detect_size}",
            {"path": str(path), "provider": vision.settings.model_provider},
            {"task": "face_embedding" if model_id == "ArcFace" else "face_detection"},
        ))
    if vision.recovery_detector is not None:
        path = Path(vision.settings.retinaface_onnx_path).expanduser().resolve()
        candidates.append((
            "RetinaFace", vision.recovery_detector_version, str(path),
            str(vision.recovery_contract["license_name"]),
            str(vision.recovery_contract["preprocessing_id"]),
            {"path": str(path), "provider": vision.settings.model_provider},
            {"task": "face_detection"},
        ))
    for model_id, model in (("AdaFace", vision.adaface), ("MobileFaceNet", vision.mobilefacenet)):
        if model is not None:
            contract = model.contract
            candidates.append((
                model_id, model.model_version, str(model.path),
                str(contract.get("license_name", "License metadata in model sidecar")),
                f"{model_id}:{model.model_version}:configured-input-contract",
                {"layout": model.layout, "width": model.width, "height": model.height,
                 "color_order": model.color_order, "mean": model.mean, "std": model.std},
                {"task": "face_embedding", "output_type": contract.get("output_type")},
            ))
    if vision.liveness is not None:
        model = vision.liveness
        candidates.append((
            "MiniFASNet", model.model_version, str(model.path),
            str(model.contract.get("license_name", "License metadata in model sidecar")),
            "MiniFASNet:configured-input-contract",
            {"layout": model.layout, "width": model.width, "height": model.height,
             "color_order": model.color_order, "mean": model.mean, "std": model.std},
            {"task": "presentation_attack_detection", "output_type": model.contract.get("output_type"),
             "live_class_index": model.live_class_index},
        ))
    if vision.fiqa is not None:
        model = vision.fiqa
        candidates.append((
            "FIQA", model.model_version, str(model.path), model.license_name,
            model.preprocessing_id,
            {"layout": model.layout, "width": model.width, "height": model.height,
             "color_order": model.color_order, "mean": model.mean, "std": model.std},
            {"task": "face_quality_estimation", "output_type": model.contract.get("output_type")},
        ))
    for model_id, version, path, license_name, preprocessing_id, input_contract, output_contract in candidates:
        row = db.query(ModelRegistryEntry).filter_by(model_id=model_id, model_version=version).one_or_none()
        if row is None:
            full_digest = sha256_file(Path(path)) if Path(path).is_file() else ""
            if len(full_digest) != 64:
                raise ValueError(f"Cannot register model {model_id}:{version} without a verified SHA-256")
            row = ModelRegistryEntry(
                model_id=model_id, model_version=version, artifact_sha256=full_digest, artifact_path=path,
                license_name=license_name, preprocessing_id=preprocessing_id,
                input_contract_json=json.dumps(input_contract),
                output_contract_json=json.dumps(output_contract),
                benchmark_json="{}", active=True,
            )
            db.add(row)
        else:
            full_digest = sha256_file(Path(path)) if Path(path).is_file() else ""
            if len(full_digest) != 64:
                raise ValueError(f"Cannot register model {model_id}:{version} without a verified SHA-256")
            row.active = True
            row.artifact_sha256 = full_digest
            row.artifact_path = path
            row.license_name = license_name
            row.preprocessing_id = preprocessing_id
            row.input_contract_json = json.dumps(input_contract)
            row.output_contract_json = json.dumps(output_contract)
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate_startup_security()
    create_schema()
    # Loading the real model pack is mandatory: do not report ready if inference weights fail to load.
    vision = VisionEngine(settings)
    app.state.settings = settings
    app.state.vision = vision
    app.state.pipeline = AttendancePipeline(settings, vision)
    with SessionLocal() as db:
        _register_runtime_models(db, vision)
    logger.info("FRS model components loaded: %s", vision.component_status)
    yield
    engine.dispose()


app = FastAPI(
    title="FRS Biometric Attendance API",
    version="1.0.0",
    description="Modular, evidence-driven FRS V4/V5 backend. Production decisions require calibrated thresholds and configured policy-required models.",
    lifespan=lifespan,
)
app.add_middleware(RequestSizeMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.include_router(attendance_router)
app.include_router(enrollment_router)
app.include_router(admin_router)


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled FRS request error; path=%s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal processing error. Check server-side diagnostic logs."})


@app.get("/", tags=["health"])
def root():
    return {
        "service": "FRS Biometric Attendance API",
        "api_version": "1.0.0",
        "health": "/health",
        "readiness": "/health/ready",
        "docs": "/docs",
    }


@app.get("/health/live", tags=["health"])
def liveness_probe():
    return {"status": "alive"}


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health(request: Request):
    settings = request.app.state.settings
    vision = request.app.state.vision
    database_state = "healthy"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        database_state = "unavailable"

    try:
        settings.encryption_key_bytes()
        encryption_ready = True
    except ValueError:
        encryption_ready = False

    ready = (
        database_state == "healthy"
        and bool(settings.device_keys)
        and len(settings.admin_api_key) >= 32
        and encryption_ready
        and settings.is_model_calibrated("ArcFace")
        and (not settings.require_liveness or vision.liveness is not None)
        and (
            not settings.require_all_specialists
            or all((vision.recovery_detector, vision.adaface, vision.mobilefacenet, vision.liveness, vision.fiqa))
        )
        and all(
            settings.is_model_calibrated(model_id) and _has_threshold(settings, model_id)
            for model_id in (("ArcFace", "AdaFace", "MobileFaceNet") if settings.require_all_specialists else ("ArcFace",))
        )
    )
    threshold_status = "CALIBRATED" if settings.is_model_calibrated("ArcFace") else "UNRECALIBRATED_BASELINE"
    return HealthResponse(
        status="online" if database_state == "healthy" else "degraded",
        environment=settings.env,
        database=database_state,
        model_version=vision.pipeline_version,
        model_components=vision.component_status,
        similarity_threshold=settings.threshold_for("ArcFace"),
        threshold_status=threshold_status,
        liveness_required=settings.require_liveness,
        ready_for_attendance=ready,
    )


@app.get("/health/ready", tags=["health"])
def readiness(request: Request):
    response = health(request)
    if not response.ready_for_attendance:
        raise HTTPException(status_code=503, detail={
            "message": "FRS is not ready to record attendance.",
            "database": response.database,
            "threshold_status": response.threshold_status,
            "model_components": response.model_components,
            "liveness_required": response.liveness_required,
        })
    return {"status": "ready", "model_version": response.model_version}
