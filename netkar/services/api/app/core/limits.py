"""Saf ASGI ara katmanları: gövde boyut sınırı ve IP bazlı rate limit.

İkisi de FastAPI'nin gövdeyi okuyup ayrıştırmasından ÖNCE çalışır (denetim O-04):
  1. Gövde sınırı: Content-Length ve akış sayacı; aşımda 413 problem+json, işleyici çağrılmaz.
  2. IP rate limit: 429 alacak istekler gövdesi hiç okunmadan reddedilir.
E-posta ve kullanıcı bazlı sayaçlar gövdedeki alanlara bağlı olduğundan işleyicide kalır.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import ProblemError, problem_response
from app.core.ratelimit import digest


class BodyTooLargeError(HTTPException):
    """Akış sırasında gövde sınırı aşıldı (FastAPI bunu 413 problem+json'a çevirir)."""

    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, detail=f"gövde sınırı: {limit} bayt")
        self.limit = limit


def _too_large(scope: Scope, receive: Receive, limit: int) -> Response:
    return problem_response(
        Request(scope, receive),
        413,
        "İstek gövdesi çok büyük",
        "payload-too-large",
        f"İstek gövdesi en fazla {limit} bayt olabilir.",
        headers={"Connection": "close"},
    )


class BodyLimitMiddleware:
    """Content-Length ve akış bazlı gövde boyut sınırı."""

    def __init__(
        self,
        app: ASGIApp,
        default_limit: int,
        prefix_limits: Mapping[str, int] | None = None,
        pattern_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self._default = default_limit
        # Yol ortasında kimlik geçen uç noktalar için tam eşleşen kalıplar (önekten ÖNCE denenir).
        self._patterns = [(re.compile(pattern), limit) for pattern, limit in (pattern_limits or {}).items()]
        # En uzun önek kazanır.
        self._prefixes = sorted((prefix_limits or {}).items(), key=lambda item: len(item[0]), reverse=True)

    def _limit_for(self, path: str) -> int:
        for pattern, limit in self._patterns:
            if pattern.fullmatch(path):
                return limit
        for prefix, limit in self._prefixes:
            if path.startswith(prefix):
                return limit
        return self._default

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope["path"])
        declared = Headers(scope=scope).get("content-length")
        if declared is not None:
            if not declared.isascii() or not declared.isdigit():
                response = problem_response(
                    Request(scope, receive),
                    400,
                    "Geçersiz istek",
                    "bad-request",
                    headers={"Connection": "close"},
                )
                await response(scope, receive, send)
                return
            if int(declared) > limit:
                await _too_large(scope, receive, limit)(scope, receive, send)
                return

        received = 0
        started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise BodyTooLargeError(limit)
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLargeError:
            if started:
                raise
            await _too_large(scope, receive, limit)(scope, receive, send)


@dataclass(frozen=True)
class IpRule:
    """Bir uç nokta için IP başına sınır (anahtar öneki, eşik, pencere saniye)."""

    prefix: str
    limit: int
    window_seconds: int


class IpRateLimitMiddleware:
    """Seçili POST uç noktalarında IP sınırını gövde okunmadan uygular."""

    def __init__(self, app: ASGIApp, rules: Mapping[str, IpRule]) -> None:
        self.app = app
        self._rules = dict(rules)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_post = scope["type"] == "http" and scope["method"] == "POST"
        rule = self._rules.get(scope["path"]) if is_post else None
        if rule is None:
            await self.app(scope, receive, send)
            return
        state = scope["app"].state
        headers = Headers(scope=scope)
        client = scope.get("client")
        ip = state.client_ip_resolver.resolve(client[0] if client else None, headers.get("x-forwarded-for"))
        try:
            await state.rate_limiter.hit(
                f"{rule.prefix}:ip:{digest(state.settings.master_key, 'rl-ip', ip)}",
                rule.limit,
                rule.window_seconds,
            )
        except ProblemError as exc:
            response = problem_response(
                Request(scope, receive), exc.status, exc.title, exc.slug, exc.detail, exc.headers, exc.extra
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
