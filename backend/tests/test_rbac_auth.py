from __future__ import annotations

import time
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.auth import (
    ROLE_DEAN,
    ROLE_FACULTY,
    ROLE_SUPER_ADMIN,
    TokenClaims,
    check_class_access,
    check_department_access,
    create_access_token,
    require_role,
    verify_access_token,
)
from app.core.config import Settings, get_settings

_TEST_SECRET = "super-secret-test-jwt-key-minimum-32-chars-long"


def test_jwt_generation_and_verification() -> None:
    token = create_access_token(
        sub="user-123",
        role=ROLE_DEAN,
        secret=_TEST_SECRET,
        email="dean.smith@campus.edu",
        department_id="dept-cse",
        expires_delta_seconds=3600,
    )
    assert isinstance(token, str)
    assert len(token.split(".")) == 3

    claims = verify_access_token(token, _TEST_SECRET)
    assert claims.sub == "user-123"
    assert claims.role == ROLE_DEAN
    assert claims.email == "dean.smith@campus.edu"
    assert claims.department_id == "dept-cse"


def test_expired_jwt_token_is_rejected() -> None:
    token = create_access_token(
        sub="user-expired",
        role=ROLE_FACULTY,
        secret=_TEST_SECRET,
        expires_delta_seconds=-10,  # Already expired
    )
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(token, _TEST_SECRET)
    assert exc_info.value.status_code == 401
    assert "expired" in str(exc_info.value.detail).lower()


def test_tampered_jwt_token_signature_is_rejected() -> None:
    token = create_access_token(
        sub="user-valid",
        role=ROLE_FACULTY,
        secret=_TEST_SECRET,
        expires_delta_seconds=3600,
    )
    # Alter the payload segment
    parts = token.split(".")
    tampered = f"{parts[0]}.eyJyZXBsYWNlZCI6InRydWUifQ.{parts[2]}"
    with pytest.raises(HTTPException) as exc_info:
        verify_access_token(tampered, _TEST_SECRET)
    assert exc_info.value.status_code == 401


def test_rbac_endpoint_access_control() -> None:
    app = FastAPI()
    test_settings = Settings(jwt_secret=_TEST_SECRET, admin_api_key="admin-key-32-chars-long-abcdef")
    app.dependency_overrides[get_settings] = lambda: test_settings

    @app.get("/super-admin-only")
    def super_admin_endpoint(actor: TokenClaims = Depends(require_role(ROLE_SUPER_ADMIN))):
        return {"status": "ok", "actor": actor.sub}

    @app.get("/academic-oversight")
    def academic_endpoint(actor: TokenClaims = Depends(require_role(ROLE_SUPER_ADMIN, ROLE_DEAN))):
        return {"status": "ok", "role": actor.role}

    client = TestClient(app)


    # 1. Faculty token trying to access super admin -> 403 Forbidden
    faculty_token = create_access_token(sub="faculty-1", role=ROLE_FACULTY, secret=_TEST_SECRET)
    resp = client.get("/super-admin-only", headers={"Authorization": f"Bearer {faculty_token}"})
    assert resp.status_code == 403

    # 2. Dean token trying to access super admin -> 403 Forbidden
    dean_token = create_access_token(sub="dean-1", role=ROLE_DEAN, secret=_TEST_SECRET)
    resp = client.get("/super-admin-only", headers={"Authorization": f"Bearer {dean_token}"})
    assert resp.status_code == 403

    # 3. Super admin token accessing super admin -> 200 OK
    admin_token = create_access_token(sub="admin-1", role=ROLE_SUPER_ADMIN, secret=_TEST_SECRET)
    resp = client.get("/super-admin-only", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # 4. Dean accessing academic oversight -> 200 OK
    resp = client.get("/academic-oversight", headers={"Authorization": f"Bearer {dean_token}"})
    assert resp.status_code == 200
    assert resp.json()["role"] == ROLE_DEAN


def test_cross_department_and_class_negative_authorization() -> None:
    dean_cse = TokenClaims(
        sub="dean-cse-id",
        role=ROLE_DEAN,
        department_id="dept-cse",
        exp=int(time.time()) + 3600,
        iat=int(time.time()),
    )
    faculty_cse = TokenClaims(
        sub="prof-john",
        role=ROLE_FACULTY,
        department_id="dept-cse",
        class_group_ids=["cg-cs-101", "cg-cs-102"],
        exp=int(time.time()) + 3600,
        iat=int(time.time()),
    )

    # CSE Dean can access CSE dept
    check_department_access(dean_cse, "dept-cse")

    # CSE Dean CANNOT access Mechanical Engineering dept -> 403
    with pytest.raises(HTTPException) as exc:
        check_department_access(dean_cse, "dept-mech")
    assert exc.value.status_code == 403

    # Faculty can access assigned class
    check_class_access(faculty_cse, "cg-cs-101")

    # Faculty CANNOT access unassigned class -> 403
    with pytest.raises(HTTPException) as exc:
        check_class_access(faculty_cse, "cg-cs-999")
    assert exc.value.status_code == 403
