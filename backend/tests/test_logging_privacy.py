from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.logging_config import (
    CorrelationIdMiddleware,
    RedactingFilter,
    get_correlation_id,
    redact_sensitive_text,
    set_correlation_id,
)


def test_redact_sensitive_text() -> None:
    # 1. Bearer token
    text1 = "Client sent Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xyz"
    redacted1 = redact_sensitive_text(text1)
    assert "Bearer [REDACTED]" in redacted1
    assert "eyJhbGciOi" not in redacted1

    # 2. Base64 payload
    text2 = "Received image: data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAAAAAAAD/2wBD..."
    redacted2 = redact_sensitive_text(text2)
    assert "data:image/...;base64,[REDACTED]" in redacted2
    assert "/9j/4AAQ" not in redacted2

    # 3. Vector
    vec_str = "[" + ", ".join([f"{0.0123 * i:.4f}" for i in range(20)]) + "]"
    text3 = f"Extracted vector: {vec_str}"
    redacted3 = redact_sensitive_text(text3)
    assert "[REDACTED_VECTOR]" in redacted3

    # 4. API / Secret key
    text4 = "Configured admin_key='secret-admin-token-1234567890'"
    redacted4 = redact_sensitive_text(text4)
    assert "admin_key=[REDACTED]" in redacted4
    assert "secret-admin-token" not in redacted4


def test_redacting_logging_filter() -> None:
    filter_instance = RedactingFilter()
    set_correlation_id("test-corr-123")

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Bearer supersecrettoken123456",
        args=(),
        exc_info=None,
    )
    filter_instance.filter(record)

    assert record.correlation_id == "test-corr-123"
    assert "Bearer [REDACTED]" in record.msg
    assert "supersecrettoken" not in record.msg


def test_correlation_id_middleware_and_header() -> None:
    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/ping")
    def ping():
        return {"corr_id": get_correlation_id()}

    client = TestClient(app)

    # With provided header
    resp = client.get("/ping", headers={"X-Correlation-ID": "custom-trace-999"})
    assert resp.status_code == 200
    assert resp.headers["x-correlation-id"] == "custom-trace-999"
    assert resp.json()["corr_id"] == "custom-trace-999"

    # Without provided header -> should generate a valid UUID
    resp2 = client.get("/ping")
    assert resp2.status_code == 200
    generated_id = resp2.headers.get("x-correlation-id")
    assert generated_id is not None
    assert len(generated_id) >= 32
    assert resp2.json()["corr_id"] == generated_id
