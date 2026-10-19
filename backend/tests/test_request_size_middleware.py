from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.main import RequestSizeMiddleware
from app.core.config import Settings


def run_asgi(middleware, scope, chunks):
    sent = []
    remaining = iter(chunks)

    async def receive():
        try:
            body, more_body = next(remaining)
            return {"type": "http.request", "body": body, "more_body": more_body}
        except StopIteration:
            return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent


def make_scope(headers=()):
    settings = Settings(_env_file=None, env="test", max_request_bytes=1024)
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": "POST",
        "path": "/upload",
        "headers": list(headers),
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
    }


def test_declared_oversized_request_is_rejected_before_application() -> None:
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    sent = run_asgi(
        RequestSizeMiddleware(app),
        make_scope([(b"content-length", str(1024 + 1024 * 1024 + 1).encode())]),
        [],
    )

    assert not called
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_chunked_request_is_limited_without_content_length() -> None:
    async def app(scope, receive, send):
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            if message["type"] == "http.request" and not message.get("more_body", False):
                break
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send({"type": "http.response.body", "body": b"unexpected success"})

    sent = run_asgi(
        RequestSizeMiddleware(app),
        make_scope(),
        [
            (b"x" * (700 * 1024), True),
            (b"x" * (400 * 1024), False),
        ],
    )

    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 413
    bodies = [message for message in sent if message["type"] == "http.response.body"]
    assert b"".join(message.get("body", b"") for message in bodies).find(b"configured limit") >= 0
