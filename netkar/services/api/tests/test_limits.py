"""Gövde boyut sınırı ara katmanı: saf ASGI düzeyinde birim testleri."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.limits import BodyLimitMiddleware, BodyTooLargeError


def _scope(path: str = "/v1/auth/login", headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {"type": "http", "method": "POST", "path": path, "headers": headers or [], "query_string": b""}


class Recorder:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)

    @property
    def status(self) -> int | None:
        for m in self.messages:
            if m["type"] == "http.response.start":
                return int(m["status"])
        return None


def _receiver(chunks: list[bytes]) -> Receive:
    queue = list(chunks)

    async def receive() -> Message:
        if not queue:
            return {"type": "http.disconnect"}
        body = queue.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    return receive


async def _drain(scope: Scope, receive: Receive, send: Send) -> None:
    more = True
    while more:
        message = await receive()
        more = message.get("more_body", False)
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def test_declared_content_length_over_limit_never_reaches_app() -> None:
    called = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True

    out = Recorder()
    mw = BodyLimitMiddleware(app, default_limit=100)
    await mw(_scope(headers=[(b"content-length", b"101")]), _receiver([]), out)
    assert out.status == 413 and called is False


async def test_invalid_content_length_is_400() -> None:
    out = Recorder()
    await BodyLimitMiddleware(_drain, default_limit=100)(
        _scope(headers=[(b"content-length", b"-5")]), _receiver([]), out
    )
    assert out.status == 400


async def test_stream_over_limit_without_content_length_gets_413_when_app_does_not_catch() -> None:
    out = Recorder()
    await BodyLimitMiddleware(_drain, default_limit=10)(_scope(), _receiver([b"a" * 6, b"a" * 6]), out)
    assert out.status == 413


async def test_stream_within_limit_passes() -> None:
    out = Recorder()
    await BodyLimitMiddleware(_drain, default_limit=12)(_scope(), _receiver([b"a" * 6, b"a" * 6]), out)
    assert out.status == 204


async def test_overflow_after_response_started_is_reraised() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    out = Recorder()
    with pytest.raises(BodyTooLargeError):
        await BodyLimitMiddleware(app, default_limit=3)(_scope(), _receiver([b"abcdef"]), out)


async def test_longest_prefix_wins_and_non_http_scopes_pass_through() -> None:
    seen: list[str] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append(scope["type"])

    mw = BodyLimitMiddleware(app, default_limit=1000, prefix_limits={"/v1/": 50, "/v1/auth/": 10})
    out = Recorder()
    await mw(_scope("/v1/auth/x", [(b"content-length", b"11")]), _receiver([]), out)
    assert out.status == 413
    out2 = Recorder()
    await mw(_scope("/v1/other", [(b"content-length", b"11")]), _receiver([]), out2)
    assert out2.status is None and seen == ["http"]  # 50 sınırı altında
    await mw({"type": "lifespan"}, _receiver([]), out2)
    assert seen == ["http", "lifespan"]


def test_body_too_large_error_carries_limit() -> Any:
    err = BodyTooLargeError(42)
    assert err.status_code == 413 and err.limit == 42
