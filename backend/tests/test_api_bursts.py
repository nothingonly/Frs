from __future__ import annotations

import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.api.routes.attendance import identify_attendance, verify_attendance
from app.api.routes.enrollment import enroll_person
from app.core.auth import ROLE_SUPER_ADMIN, TokenClaims
from app.core.config import Settings


def make_upload(payload: bytes) -> UploadFile:
    return UploadFile(
        file=BytesIO(payload),
        filename="frame.jpg",
        headers=Headers({"content-type": "image/jpeg"}),
    )


class FakePipeline:
    def __init__(self) -> None:
        self.call: tuple[tuple[object, ...], dict[str, object]] | None = None

    def identify(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.call = (args, kwargs)
        return {"status": "test-double-only"}

    def enroll(self, *args: object, **kwargs: object) -> dict[str, str]:
        self.call = (args, kwargs)
        return {"status": "test-double-only"}


def make_request(pipeline: FakePipeline):
    settings = Settings(
        _env_file=None,
        env="test",
        max_upload_bytes=1024,
        max_request_bytes=4096,
        minimum_identification_frames=3,
        maximum_identification_frames=8,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=settings, pipeline=pipeline))
    )


def test_verify_route_passes_frame_burst_and_policy_arguments() -> None:
    pipeline = FakePipeline()
    request = make_request(pipeline)
    files = [make_upload(b"frame-one"), make_upload(b"frame-two"), make_upload(b"frame-three")]

    result = asyncio.run(verify_attendance(
        request=request, actor_id="device-test", db=None,
        employee_id="EMP-001", punch_type="CHECK_IN", client_device_id="kiosk-test",
        images=files, image=None,
    ))

    assert result["status"] == "test-double-only"
    assert pipeline.call is not None
    args, kwargs = pipeline.call
    assert args[1] == [b"frame-one", b"frame-two", b"frame-three"]
    assert kwargs == {
        "punch_type": "CHECK_IN",
        "client_device_id": "kiosk-test",
        "actor_id": "device-test",
        "employee_id_claim": "EMP-001",
    }


def test_identification_route_passes_frame_burst() -> None:
    pipeline = FakePipeline()
    request = make_request(pipeline)
    files = [make_upload(b"frame-one"), make_upload(b"frame-two"), make_upload(b"frame-three")]

    result = asyncio.run(identify_attendance(
        request=request, actor_id="device-test", db=None,
        punch_type="CHECK_OUT", client_device_id="kiosk-test",
        images=files, image=None,
    ))

    assert result["status"] == "test-double-only"
    assert pipeline.call is not None
    args, kwargs = pipeline.call
    assert args[1] == [b"frame-one", b"frame-two", b"frame-three"]
    assert kwargs == {
        "punch_type": "CHECK_OUT",
        "client_device_id": "kiosk-test",
        "actor_id": "device-test",
    }


def test_attendance_route_rejects_short_burst_before_pipeline() -> None:
    pipeline = FakePipeline()
    request = make_request(pipeline)
    files = [make_upload(b"frame-one"), make_upload(b"frame-two")]

    with pytest.raises(HTTPException) as caught:
        asyncio.run(verify_attendance(
            request=request, actor_id="device-test", db=None,
            employee_id="EMP-001", punch_type="CHECK_IN", client_device_id="kiosk-test",
            images=files, image=None,
        ))

    assert caught.value.status_code == 422
    assert pipeline.call is None


def test_enrollment_route_passes_burst_and_admin_identity() -> None:
    pipeline = FakePipeline()
    request = make_request(pipeline)
    files = [make_upload(b"frame-one"), make_upload(b"frame-two"), make_upload(b"frame-three")]

    actor = TokenClaims(
        sub="admin-test", role=ROLE_SUPER_ADMIN, exp=4102444800, iat=1,
    )
    result = asyncio.run(enroll_person(
        request=request, actor=actor, db=None,
        employee_id="EMP-001", full_name="Example Person", department="Operations",
        images=files, image=None,
    ))

    assert result["status"] == "test-double-only"
    assert pipeline.call is not None
    args, kwargs = pipeline.call
    assert args[1] == [b"frame-one", b"frame-two", b"frame-three"]
    assert kwargs == {
        "employee_id": "EMP-001",
        "full_name": "Example Person",
        "department": "Operations",
        "admin_actor_id": "admin:admin-test",
    }
