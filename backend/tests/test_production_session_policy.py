from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.routes.attendance import identify_attendance, verify_attendance
from app.core.config import Settings


class MustNotRunPipeline:
    def identify(self, *_args, **_kwargs):
        raise AssertionError("The legacy unscoped route must reject before inference.")


@pytest.mark.parametrize("endpoint_name", ["identify", "verify"])
def test_legacy_unscoped_attendance_routes_are_disabled_in_production(endpoint_name: str) -> None:
    settings = Settings(_env_file=None, env="production")
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=settings, pipeline=MustNotRunPipeline()),
        ),
    )
    endpoint = identify_attendance if endpoint_name == "identify" else verify_attendance
    kwargs = {
        "request": request,
        "actor_id": "device:test",
        "db": None,
        "punch_type": "CHECK_IN",
        "client_device_id": "kiosk:test",
        "images": None,
        "image": None,
    }
    if endpoint_name == "verify":
        kwargs["employee_id"] = "STUDENT-001"

    with pytest.raises(HTTPException) as caught:
        asyncio.run(endpoint(**kwargs))

    assert caught.value.status_code == 409
    assert caught.value.detail == (
        "Session-scoped attendance is required in production; use an open attendance session."
    )
