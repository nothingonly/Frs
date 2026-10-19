from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import device_actor
from app.database import get_db

router = APIRouter(prefix="/api/v1/attendance", tags=["attendance"])


async def _read_burst(
    images: list[UploadFile] | None,
    image: UploadFile | None,
    max_image_bytes: int,
    max_total_bytes: int,
) -> list[bytes]:
    if images and image is not None:
        raise HTTPException(status_code=422, detail="Send either repeated 'images' parts or legacy 'image', not both.")
    uploads = images or ([image] if image is not None else [])
    if not uploads:
        raise HTTPException(status_code=422, detail="Camera frame burst is required.")
    payloads: list[bytes] = []
    total = 0
    for part in uploads:
        content_type = (part.content_type or "").lower()
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail=f"Unsupported image content type: {content_type}")
        payload = await part.read(max_image_bytes + 1)
        if len(payload) > max_image_bytes:
            raise HTTPException(status_code=413, detail="A camera frame exceeds the configured upload limit.")
        total += len(payload)
        if total > max_total_bytes:
            raise HTTPException(status_code=413, detail="Total camera burst exceeds the configured upload limit.")
        payloads.append(payload)
    return payloads


@router.post("/identify")
async def identify_attendance(
    request: Request,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
    punch_type: Annotated[str, Form()],
    client_device_id: Annotated[str, Form(min_length=1, max_length=120)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    settings = request.app.state.settings
    payloads = await _read_burst(images, image, settings.max_upload_bytes, settings.max_request_bytes)
    return request.app.state.pipeline.identify(
        db,
        payloads,
        punch_type=punch_type.strip().upper(),
        client_device_id=client_device_id.strip(),
        actor_id=actor_id,
    )


@router.post("/verify")
async def verify_attendance(
    request: Request,
    actor_id: Annotated[str, Depends(device_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: Annotated[str, Form(min_length=1, max_length=80)],
    punch_type: Annotated[str, Form()],
    client_device_id: Annotated[str, Form(min_length=1, max_length=120)],
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    settings = request.app.state.settings
    payloads = await _read_burst(images, image, settings.max_upload_bytes, settings.max_request_bytes)
    return request.app.state.pipeline.identify(
        db,
        payloads,
        punch_type=punch_type.strip().upper(),
        client_device_id=client_device_id.strip(),
        actor_id=actor_id,
        employee_id_claim=employee_id.strip(),
    )
