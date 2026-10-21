from __future__ import annotations

import json
import time
from collections.abc import Generator

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies import scoped_admin
import app.api.routes.integrations as integration_routes
import app.services.integrations as integration_services
from app.core.auth import ROLE_SUPER_ADMIN, TokenClaims, _b64url_encode
from app.core.config import Settings, get_settings
from app.database import Base, get_db
from app.db.entities import LtiLaunchNonce, LtiNonceUse
from app.api.routes.integrations import router as integrations_router
from app.services.integrations import LtiService


def _signed_lti_token(private_key, nonce: str) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": "https://lms.example.edu",
        "aud": "frs-client",
        "sub": "learner-123",
        "exp": now + 300,
        "iat": now,
        "nonce": nonce,
        "https://purl.imsglobal.org/spec/lti/claim/message_type": LtiService.LTI_MESSAGE_TYPE_LAUNCH,
        "https://purl.imsglobal.org/spec/lti/claim/version": LtiService.LTI_VERSION,
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id": "campus-prod",
        "https://purl.imsglobal.org/spec/lti/claim/context": {"id": "course-1", "title": "Course"},
        "https://purl.imsglobal.org/spec/lti/claim/resource_link": {"id": "link-1"},
        "https://purl.imsglobal.org/spec/lti/claim/roles": ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"],
    }
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header_segment}.{payload_segment}.{_b64url_encode(signature)}"


def _app_and_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_pem = private_key.public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    settings = Settings(
        _env_file=None,
        env="production",
        jwt_secret="jwt-secret-distinct-from-any-other-production-key-0001",
        database_url="postgresql://frs:password@localhost/frs",
        lti_client_id="frs-client",
        lti_issuer="https://lms.example.edu",
        lti_deployment_id="campus-prod",
        lti_platform_public_key_pem=public_key_pem,
    )
    monkeypatch.setattr(integration_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(integration_services, "get_settings", lambda: settings)

    app = FastAPI()
    app.include_router(integrations_router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[scoped_admin] = lambda: TokenClaims(
        sub="admin-1",
        role=ROLE_SUPER_ADMIN,
        exp=int(time.time()) + 3600,
        iat=int(time.time()),
        iss="frs-auth",
    )
    return app, engine, factory, private_key


def test_production_lti_requires_and_consumes_server_nonce_once(monkeypatch: pytest.MonkeyPatch) -> None:
    app, engine, factory, private_key = _app_and_db(monkeypatch)
    try:
        with TestClient(app) as client:
            issued = client.post("/api/v1/integrations/lti/launch/nonce")
            assert issued.status_code == 201
            nonce = issued.json()["nonce"]

            token = _signed_lti_token(private_key, nonce)
            payload = {"id_token": token, "nonce": nonce}
            verified = client.post("/api/v1/integrations/lti/launch/validate", json=payload)
            assert verified.status_code == 200
            assert verified.json()["cryptographically_verified"] is True
            assert verified.json()["nonce"] == nonce

            replay = client.post("/api/v1/integrations/lti/launch/validate", json=payload)
            assert replay.status_code == 409
            assert "not issued" in replay.json()["detail"]

        with factory() as db:
            challenge = db.get(LtiLaunchNonce, nonce)
            assert challenge is not None
            assert challenge.consumed_at is not None
            assert db.get(LtiNonceUse, nonce) is not None
    finally:
        engine.dispose()


def test_production_lti_rejects_caller_chosen_nonce_without_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    app, engine, _factory, private_key = _app_and_db(monkeypatch)
    try:
        token = _signed_lti_token(private_key, "attacker-chosen-nonce")
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/integrations/lti/launch/validate",
                json={"id_token": token, "nonce": "attacker-chosen-nonce"},
            )
        assert response.status_code == 409
    finally:
        engine.dispose()
