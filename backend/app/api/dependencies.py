from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.security import authenticate_admin, authenticate_device

_bearer = HTTPBearer(auto_error=False)


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
    # Never use or log the submitted token as the actor identifier.
    import hashlib
    return "device:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


def admin_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> str:
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not authenticate_admin(token, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator bearer credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return "administrator:configured-admin-key"
