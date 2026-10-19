from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

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


class RequestSizeMiddleware:
    """Enforce request-size limits for both Content-Length and streamed/chunked bodies."""

    def __init__(self, app):
        self.app = app

    @staticmethod
    async def _send_error(send, status_code: int, detail: str) -> None:
        import json

        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        settings = scope["app"].state.settings
        max_body_bytes = settings.max_request_bytes + 1024 * 1024
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                declared_length_value = int(declared_length)
                if declared_length_value < 0:
                    raise ValueError
            except ValueError:
                await self._send_error(send, 400, "Invalid Content-Length header.")
                return
            if declared_length_value > max_body_bytes:
                await self._send_error(send, 413, "Request body exceeds configured limit.")
                return

        received_bytes = 0
        request_too_large = False

        async def limited_receive():
            nonlocal received_bytes, request_too_large
            if request_too_large:
                return {"type": "http.disconnect"}

            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_body_bytes:
                    request_too_large = True
                    await self._send_error(send, 413, "Request body exceeds configured limit.")
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            # The body-limit response has already been sent; suppress downstream writes.
            if not request_too_large:
                await send(message)

        await self.app(scope, limited_receive, guarded_send)


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

    candidates: list[tuple[str, str, str, str, str, str, str, dict, dict]] = []
    for model_id, model in (("SCRFD", vision.detector), ("ArcFace", vision.recognizer)):
        path_value = getattr(model, "model_file", None)
        if not path_value or not Path(str(path_value)).is_file():
            raise ValueError(f"Primary {model_id} artifact path is unavailable; cannot register provenance.")
        path = Path(str(path_value)).resolve()
        provenance = vision.primary_model_provenance[model_id]
        candidates.append((
            model_id, vision._model_version(model), str(path),
            provenance["license_name"],
            str(provenance["source_url"]),
            str(provenance["permitted_use"]),
            "five-point-norm-crop-112-v1" if model_id == "ArcFace" else f"scrfd-det-size-{vision.settings.detect_size}",
            {"path": str(path), "provider": vision.settings.model_provider,
             "verified_sha256": provenance["sha256"]},
            {"task": "face_embedding" if model_id == "ArcFace" else "face_detection"},
        ))
    if vision.recovery_detector is not None:
        path = Path(vision.settings.retinaface_onnx_path).expanduser().resolve()
        candidates.append((
            "RetinaFace", vision.recovery_detector_version, str(path),
            str(vision.recovery_contract["license_name"]),
            str(vision.recovery_contract["source_url"]),
            str(vision.recovery_contract.get("permitted_use", "must be verified by operator")),
            str(vision.recovery_contract["preprocessing_id"]),
            {"path": str(path), "provider": vision.settings.model_provider},
            {"task": "face_detection"},
        ))
    for model_id, model in (("AdaFace", vision.adaface), ("MobileFaceNet", vision.mobilefacenet)):
        if model is not None:
            contract = model.contract
            candidates.append((
                model_id, model.model_version, str(model.path),
                model.license_name, model.source_url,
                str(contract.get("permitted_use", "must be verified by operator")),
                model.preprocessing_id,
                {"layout": model.layout, "width": model.width, "height": model.height,
                 "color_order": model.color_order, "mean": model.mean, "std": model.std},
                {"task": "face_embedding", "output_type": contract.get("output_type")},
            ))
    if vision.liveness is not None:
        model = vision.liveness
        candidates.append((
            "MiniFASNet", model.model_version, str(model.path),
            model.license_name,
            model.source_url,
            str(model.contract.get("permitted_use", "must be verified by operator")),
            model.preprocessing_id,
            {"layout": model.layout, "width": model.width, "height": model.height,
             "color_order": model.color_order, "mean": model.mean, "std": model.std},
            {"task": "presentation_attack_detection", "output_type": model.contract.get("output_type"),
             "live_class_index": model.live_class_index},
        ))
    if vision.fiqa is not None:
        model = vision.fiqa
        candidates.append((
            "FIQA", model.model_version, str(model.path), model.license_name,
            model.source_url,
            str(model.contract.get("permitted_use", "must be verified by operator")),
            model.preprocessing_id,
            {"layout": model.layout, "width": model.width, "height": model.height,
             "color_order": model.color_order, "mean": model.mean, "std": model.std},
            {"task": "face_quality_estimation", "output_type": model.contract.get("output_type")},
        ))
    for model_id, version, path, license_name, source_url, permitted_use, preprocessing_id, input_contract, output_contract in candidates:
        row = db.query(ModelRegistryEntry).filter_by(model_id=model_id, model_version=version).one_or_none()
        if row is None:
            full_digest = sha256_file(Path(path)) if Path(path).is_file() else ""
            if len(full_digest) != 64:
                raise ValueError(f"Cannot register model {model_id}:{version} without a verified SHA-256")
            row = ModelRegistryEntry(
                model_id=model_id, model_version=version, artifact_sha256=full_digest, artifact_path=path,
                license_name=license_name, source_url=source_url, permitted_use=permitted_use,
                preprocessing_id=preprocessing_id,
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
            row.source_url = source_url
            row.permitted_use = permitted_use
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
    version="0.1.0-dev",
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



_ADMIN_HEADERS = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
}


@app.get("/admin", include_in_schema=False)
def admin_console():
    page = __import__("pathlib").Path(__file__).parent / "web" / "admin.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Administrator console assets are not installed.")
    return FileResponse(page, media_type="text/html; charset=utf-8", headers=_ADMIN_HEADERS)


@app.get("/admin.js", include_in_schema=False)
def admin_script():
    script = __import__("pathlib").Path(__file__).parent / "web" / "admin.js"
    if not script.is_file():
        raise HTTPException(status_code=404, detail="Administrator console script is not installed.")
    return FileResponse(
        script,
        media_type="text/javascript; charset=utf-8",
        headers={**_ADMIN_HEADERS, "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'"},
    )

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
