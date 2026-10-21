from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings
from app.security import authenticate_admin, authenticate_device

_bearer = HTTPBearer(auto_error=False)

# Role definitions
ROLE_SUPER_ADMIN = "super_admin"
ROLE_DEAN = "dean"
ROLE_FACULTY = "faculty"
ROLE_KIOSK = "kiosk"

ALL_ROLES = {ROLE_SUPER_ADMIN, ROLE_DEAN, ROLE_FACULTY, ROLE_KIOSK}


class TokenClaims(BaseModel):
    sub: str
    email: str = ""
    role: str = ROLE_FACULTY
    department_id: str | None = None
    class_group_ids: list[str] = Field(default_factory=list)
    exp: int
    iat: int
    iss: str = "frs-auth"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def create_access_token(
    sub: str,
    role: str,
    secret: str,
    email: str = "",
    department_id: str | None = None,
    class_group_ids: list[str] | None = None,
    expires_delta_seconds: int = 3600,
    issuer: str = "frs-auth",
) -> str:
    """Create a cryptographically signed HMAC-SHA256 JWT access token."""
    if role not in ALL_ROLES:
        raise ValueError(f"Invalid role: {role}")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": sub,
        "email": email,
        "role": role,
        "department_id": department_id,
        "class_group_ids": class_group_ids or [],
        "iat": now,
        "exp": now + expires_delta_seconds,
        "iss": issuer,
    }

    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    signing_input = f"{_b64url_encode(header_bytes)}.{_b64url_encode(payload_bytes)}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()

    return f"{signing_input.decode('ascii')}.{_b64url_encode(signature)}"


def verify_access_token(
    token: str,
    secret: str,
    expected_issuer: str = "frs-auth",
) -> TokenClaims:
    """Verify signature, format, and expiration of an access token."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed JWT bearer token format.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        provided_sig = _b64url_decode(parts[2])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT signature encoding.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    if not hmac.compare_digest(expected_sig, provided_sig):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT signature.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    try:
        payload_data = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT payload encoding.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    now = int(time.time())
    if payload_data.get("exp", 0) < now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT bearer token has expired.",
            headers={"WWW-Authenticate": "Bearer error=\"token_expired\""},
        )

    if expected_issuer and payload_data.get("iss") != expected_issuer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token issuer.",
            headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
        )

    return TokenClaims(**payload_data)


def get_current_actor(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> TokenClaims:
    """Resolve authenticated caller into validated TokenClaims.
    
    Supports:
    1. Cryptographically verified JWT bearer tokens.
    2. Static admin API key (mapped to ROLE_SUPER_ADMIN for development).
    3. Scoped kiosk device tokens (mapped to ROLE_KIOSK).
    """
    token = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else None
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authorization credentials are required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Device key check
    if authenticate_device(token, settings):
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        now = int(time.time())
        return TokenClaims(
            sub=f"device:{fingerprint}",
            email=f"kiosk-{fingerprint}@device.local",
            role=ROLE_KIOSK,
            exp=now + 86400,
            iat=now,
            iss="frs-device-auth",
        )

    # 2. Legacy admin key check
    if authenticate_admin(token, settings):
        now = int(time.time())
        return TokenClaims(
            sub="admin:configured-key",
            email="admin@campus.local",
            role=ROLE_SUPER_ADMIN,
            exp=now + 86400,
            iat=now,
            iss="frs-admin-auth",
        )

    # 3. JWT verification
    secret = settings.effective_jwt_secret
    return verify_access_token(token, secret, expected_issuer=settings.jwt_issuer)


def require_role(*allowed_roles: str) -> Callable[[TokenClaims], TokenClaims]:
    """Dependency that enforces role-based access control (RBAC)."""
    def _role_checker(actor: TokenClaims = Depends(get_current_actor)) -> TokenClaims:
        if actor.role not in allowed_roles and actor.role != ROLE_SUPER_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: role '{actor.role}' lacks required permissions ({', '.join(allowed_roles)}).",
            )
        return actor
    return _role_checker


def check_department_access(actor: TokenClaims, department_id: str) -> None:
    """Ensure actor has authority over a specific department."""
    if actor.role == ROLE_SUPER_ADMIN:
        return
    if actor.role == ROLE_DEAN and actor.department_id == department_id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Forbidden: actor does not have authority over department '{department_id}'.",
    )


def check_class_access(actor: TokenClaims, class_group_id: str, department_id: str | None = None) -> None:
    """Ensure actor has authority over a specific class group."""
    if actor.role == ROLE_SUPER_ADMIN:
        return
    if actor.role == ROLE_DEAN and department_id and actor.department_id == department_id:
        return
    if actor.role == ROLE_FACULTY and class_group_id in actor.class_group_ids:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Forbidden: actor does not have authority over class group '{class_group_id}'.",
    )
