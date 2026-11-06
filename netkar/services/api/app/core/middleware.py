"""Ara katmanlar: güvenlik başlıkları, istek bağlamı (log, hata yakalama) ve CSRF."""

from __future__ import annotations

import logging
import re
import secrets
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import problem_response
from app.core.security import constant_time_equals

logger = logging.getLogger("netkar.request")

CSRF_COOKIE = "__Host-nk_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_CSRF_VALID = re.compile(r"^[A-Za-z0-9_\-]{32,128}$")

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    # API yalnız JSON döndürür; hiçbir kaynağa izin verilmez.
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-site",
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Her yanıta (hata yanıtları dahil) güvenlik başlıklarını ekler."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """İstek kimliği, süre logu ve yakalanmamış hataları 500 problem+json'a çevirme."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # İstemciye iç ayrıntı verilmez; ayrıntı yalnız (maskeli) log'a gider.
            logger.exception("yakalanmamış hata", extra={"request_id": request_id})
            response = problem_response(
                request, 500, "Sunucu hatası", "internal-error", "Beklenmeyen bir hata oluştu."
            )
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        # Sorgu dizesi token taşıyabileceği için yalnız yol loglanır.
        logger.info(
            "istek",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


class CsrfMiddleware:
    """Çift gönderim (double submit): durum değiştiren isteklerde çerez ile başlık eşleşmeli.

    Saf ASGI olarak yazılmıştır: BaseHTTPMiddleware gövde akışındaki istisnaları (ör. gövde sınırı
    aşımı) ExceptionGroup içine sarıp anlamını bozar; bu katman gövdeye hiç dokunmaz.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] not in SAFE_METHODS:
            request = Request(scope)
            cookie = request.cookies.get(CSRF_COOKIE, "")
            header = request.headers.get(CSRF_HEADER, "")
            if not (cookie and header and constant_time_equals(cookie, header)):
                response = problem_response(
                    request,
                    403,
                    "CSRF doğrulaması başarısız",
                    "csrf-failed",
                    "Geçerli bir X-CSRF-Token başlığı ve çerezi gerekli.",
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def new_csrf_token() -> str:
    """Yeni CSRF token'ı."""
    return secrets.token_urlsafe(32)


def is_valid_csrf_format(value: str) -> bool:
    """Çerezden gelen değerin beklenen biçimde olup olmadığını denetler."""
    return bool(_CSRF_VALID.match(value))
