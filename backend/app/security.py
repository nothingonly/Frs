from __future__ import annotations

import hashlib
import hmac
import secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import Settings, get_settings


def _fingerprint(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def authenticate_device(token: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not token or not settings.device_keys:
        return False
    supplied = _fingerprint(token)
    return any(hmac.compare_digest(supplied, _fingerprint(candidate)) for candidate in settings.device_keys)


def authenticate_admin(token: str | None, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    if not token or not settings.admin_api_key:
        return False
    return secrets.compare_digest(_fingerprint(token), _fingerprint(settings.admin_api_key))


def encrypt_embedding(embedding: bytes, settings: Settings | None = None) -> tuple[bytes, bytes]:
    settings = settings or get_settings()
    nonce = secrets.token_bytes(12)
    cipher = AESGCM(settings.encryption_key_bytes()).encrypt(nonce, embedding, b"frs-embedding-v1")
    return cipher, nonce


def decrypt_embedding(ciphertext: bytes, nonce: bytes, settings: Settings | None = None) -> bytes:
    settings = settings or get_settings()
    return AESGCM(settings.encryption_key_bytes()).decrypt(nonce, ciphertext, b"frs-embedding-v1")
