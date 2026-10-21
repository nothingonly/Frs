from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar
from typing import Any

from starlette.datastructures import Headers

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return correlation_id_var.get() or "no-corr-id"


def set_correlation_id(value: str) -> None:
    correlation_id_var.set(value)


_REDACTION_PATTERNS = [
    # Bearer tokens
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{8,}"), "Bearer [REDACTED]"),
    # Base64 image data URIs
    (re.compile(r"data:image\/[a-zA-Z0-9\+\-\.]+;base64,[A-Za-z0-9+/=]{20,}"), "data:image/...;base64,[REDACTED]"),
    # General raw base64 payloads (>80 chars)
    (re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b"), "[REDACTED_PAYLOAD]"),
    # API key / Secret key assignments
    (re.compile(r"(?i)(api[_-]?key|secret[_-]?key|device[_-]?key|admin[_-]?key|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{8,}['\"]?"), r"\1=[REDACTED]"),
    # Biometric float vector patterns
    (re.compile(r"\[(?:\s*-?\d+\.\d+[\s,]+){5,}\s*-?\d+\.\d+\s*\]"), "[REDACTED_VECTOR]"),
]


def redact_sensitive_text(text: str) -> str:
    """Redact tokens, credentials, base64 payloads, and vectors from a string."""
    if not isinstance(text, str):
        return text
    result = text
    for pattern, replacement in _REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class RedactingFilter(logging.Filter):
    """Logging filter that scrubs sensitive biometric and credential data and injects correlation_id."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()

        if isinstance(record.msg, str):
            record.msg = redact_sensitive_text(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: redact_sensitive_text(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_sensitive_text(v) if isinstance(v, str) else v for v in record.args)

        return True


class CorrelationIdFormatter(logging.Formatter):
    """Log formatter that includes correlation_id in a standardized format."""

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id()
        return super().format(record)


class CorrelationIdMiddleware:
    """ASGI middleware to capture or generate X-Correlation-ID and inject it into the context and response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming_id = headers.get("x-correlation-id") or headers.get("x-request-id")
        cid = incoming_id if incoming_id and len(incoming_id) <= 128 else str(uuid.uuid4())
        set_correlation_id(cid)

        async def send_with_correlation(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                header_list = list(message.get("headers", []))
                header_list.append((b"x-correlation-id", cid.encode("latin-1")))
                message["headers"] = header_list
            await send(message)

        await self.app(scope, receive, send_with_correlation)


def setup_logging(level: str = "INFO") -> None:
    """Configure root and frs loggers with redacting filter and correlation ID formatter."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if already configured
    if not any(isinstance(f, RedactingFilter) for h in root_logger.handlers for f in h.filters):
        redacting_filter = RedactingFilter()
        formatter = CorrelationIdFormatter(
            "%(asctime)s [%(levelname)s] [corr=%(correlation_id)s] %(name)s: %(message)s"
        )
        for handler in root_logger.handlers:
            handler.setFormatter(formatter)
            handler.addFilter(redacting_filter)

        if not root_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(formatter)
            handler.addFilter(redacting_filter)
            root_logger.addHandler(handler)
