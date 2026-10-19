from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import admin_actor
from app.database import get_db

router = APIRouter(prefix="/api/v1/biometrics", tags=["enrollment"])


@router.post("/enroll/admin", status_code=201)
async def enroll_person(
    request: Request,
    admin_id: Annotated[str, Depends(admin_actor)],
    db: Annotated[Session, Depends(get_db)],
    employee_id: Annotated[str, Form(min_length=1, max_length=80)],
    full_name: Annotated[str, Form(min_length=1, max_length=200)],
    department: Annotated[str | None, Form(max_length=160)] = None,
    images: Annotated[list[UploadFile] | None, File()] = None,
    image: Annotated[UploadFile | None, File()] = None,
):
    if images and image is not None:
        raise HTTPException(status_code=422, detail="Send either repeated 'images' parts or legacy 'image', not both.")
    uploads = images or ([image] if image is not None else [])
    if not uploads:
        raise HTTPException(status_code=422, detail="Multi-frame enrollment evidence is required.")

    settings = request.app.state.settings
    payloads: list[bytes] = []
    total_bytes = 0
    for part in uploads:
        content_type = (part.content_type or "").lower()
        if content_type and content_type not in {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}:
            raise HTTPException(status_code=415, detail=f"Unsupported enrollment image content type: {content_type}")
        payload = await part.read(settings.max_upload_bytes + 1)
        if len(payload) > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="An enrollment image exceeds the configured upload limit.")
        total_bytes += len(payload)
        if total_bytes > settings.max_request_bytes:
            raise HTTPException(status_code=413, detail="Enrollment burst exceeds the configured upload limit.")
        payloads.append(payload)

    return request.app.state.pipeline.enroll(
        db,
        payloads,
        employee_id=employee_id,
        full_name=full_name,
        department=department,
        admin_actor_id=admin_id,
    )
