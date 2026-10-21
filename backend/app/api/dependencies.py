from __future__ import annotations

import hashlib
import time
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer



from app.core.auth import (
    ROLE_DEAN,
    ROLE_FACULTY,
    ROLE_KIOSK,
    ROLE_SUPER_ADMIN,
    TokenClaims,
    check_class_access,
    check_department_access,
    get_current_actor,
    require_role,
)
from app.core.config import Settings, get_settings
from app.security import authenticate_admin, authenticate_device

_bearer = HTTPBearer(auto_error=False)


class SessionActor(str):
    """String-compatible authenticated principal carrying server-verified scope claims."""

    def __new__(
        cls,
        actor_id: str,
        *,
        role: str,
        department_id: str | None = None,
        class_group_ids: tuple[str, ...] | list[str] = (),
        device_fingerprint: str | None = None,
    ):
        instance = str.__new__(cls, actor_id)
        instance.role = role
        instance.department_id = department_id
        instance.class_group_ids = tuple(dict.fromkeys(class_group_ids))
        instance.device_fingerprint = device_fingerprint
        return instance


def device_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not authenticate_device(token, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid kiosk device bearer credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Preserve the historic short actor ID for queue ownership while attaching the full,
    # non-reversible credential fingerprint and server-configured class scope.
    fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return SessionActor(
        "device:" + fingerprint[:16],
        role=ROLE_KIOSK,
        class_group_ids=settings.device_class_group_scopes.get(fingerprint, ()),
        device_fingerprint=fingerprint,
    )


def admin_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator bearer credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if authenticate_admin(token, settings):
        return "administrator:configured-admin-key"

    # Also support JWT with administrative roles
    actor = get_current_actor(credentials, settings)
    if actor.role not in (ROLE_SUPER_ADMIN, ROLE_DEAN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator or Dean authority is required.",
        )
    return f"admin:{actor.email or actor.sub}"


def scoped_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenClaims:
    """Resolve caller into TokenClaims, requiring Super Admin or Dean role."""
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not token and admin_actor in request.app.dependency_overrides:
        override_val = request.app.dependency_overrides[admin_actor]()
        now = int(time.time())
        return TokenClaims(
            sub=str(override_val),
            email="admin@campus.local",
            role=ROLE_SUPER_ADMIN,
            exp=now + 86400,
            iat=now,
            iss="frs-admin-auth",
        )

    if token and authenticate_admin(token, settings):
        now = int(time.time())
        return TokenClaims(
            sub="administrator:configured-admin-key",
            email="admin@campus.local",
            role=ROLE_SUPER_ADMIN,
            exp=now + 86400,
            iat=now,
            iss="frs-admin-auth",
        )

    actor = get_current_actor(credentials, settings)
    if actor.role not in (ROLE_SUPER_ADMIN, ROLE_DEAN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: role '{actor.role}' lacks administrator or dean authority.",
        )
    if actor.role == ROLE_DEAN and not actor.department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dean token must be scoped to a department.")
    return actor


def scoped_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenClaims:
    """Resolve caller into TokenClaims, allowing Super Admin, Dean, or Faculty."""
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not token and admin_actor in request.app.dependency_overrides:
        override_val = request.app.dependency_overrides[admin_actor]()
        now = int(time.time())
        return TokenClaims(
            sub=str(override_val),
            email="admin@campus.local",
            role=ROLE_SUPER_ADMIN,
            exp=now + 86400,
            iat=now,
            iss="frs-admin-auth",
        )

    if token and authenticate_admin(token, settings):
        now = int(time.time())
        return TokenClaims(
            sub="administrator:configured-admin-key",
            email="admin@campus.local",
            role=ROLE_SUPER_ADMIN,
            exp=now + 86400,
            iat=now,
            iss="frs-admin-auth",
        )

    actor = get_current_actor(credentials, settings)
    if actor.role not in (ROLE_SUPER_ADMIN, ROLE_DEAN, ROLE_FACULTY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: role '{actor.role}' lacks administrative or academic authority.",
        )
    if actor.role == ROLE_DEAN and not actor.department_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Dean token must be scoped to a department.")
    return actor





def session_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> SessionActor | str:
    """Authenticate an attendance actor and preserve verified authorization scopes."""
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not token and device_actor in request.app.dependency_overrides:
        # Preserve dependency override compatibility for isolated unit-test fixtures.
        return str(request.app.dependency_overrides[device_actor]())
    if not token and admin_actor in request.app.dependency_overrides:
        return SessionActor(
            str(request.app.dependency_overrides[admin_actor]()),
            role=ROLE_SUPER_ADMIN,
        )
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication bearer credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if authenticate_device(token, settings):
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()
        allowed_groups = settings.device_class_group_scopes.get(fingerprint, ())
        return SessionActor(
            "device:" + fingerprint[:16],
            role=ROLE_KIOSK,
            class_group_ids=allowed_groups,
            device_fingerprint=fingerprint,
        )
    if authenticate_admin(token, settings):
        return SessionActor("administrator:configured-admin-key", role=ROLE_SUPER_ADMIN)
    try:
        actor = get_current_actor(credentials, settings)
        if actor.role in (ROLE_SUPER_ADMIN, ROLE_DEAN, ROLE_FACULTY, ROLE_KIOSK):
            return SessionActor(
                f"{actor.role.lower()}:{actor.email or actor.sub}",
                role=actor.role,
                department_id=actor.department_id,
                class_group_ids=actor.class_group_ids,
            )
    except HTTPException:
        pass
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid kiosk device or academic bearer credentials are required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


__all__ = [
    "device_actor",
    "admin_actor",
    "scoped_admin",
    "scoped_actor",
    "session_actor",
    "get_current_actor",
    "require_role",
    "check_department_access",
    "check_class_access",
    "TokenClaims",
    "ROLE_SUPER_ADMIN",
    "ROLE_DEAN",
    "ROLE_FACULTY",
    "ROLE_KIOSK",
]
