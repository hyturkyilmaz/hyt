"""RFC 9457 (application/problem+json) hata yanıtları."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_PREFIX = "urn:netkar:problem:"


class ProblemError(Exception):
    """Uygulama içinde fırlatılan, problem+json'a çevrilen hata."""

    def __init__(
        self,
        status: int,
        title: str,
        slug: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.slug = slug
        self.detail = detail
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(
    request: Request | None,
    status: int,
    title: str,
    slug: str,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    """Problem belgesi üretir. İç ayrıntı ve stack trace asla içermez."""
    body: dict[str, Any] = {
        "type": f"{_TYPE_PREFIX}{slug}",
        "title": title,
        "status": status,
    }
    if detail:
        body["detail"] = detail
    if request is not None:
        body["instance"] = request.url.path
        request_id = getattr(request.state, "request_id", None)
        if request_id:
            body["request_id"] = request_id
    body.update(extra or {})
    return JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=headers)


_STATUS_TITLES = {
    400: ("Geçersiz istek", "bad-request"),
    401: ("Kimlik doğrulama gerekli", "unauthorized"),
    403: ("Erişim reddedildi", "forbidden"),
    404: ("Bulunamadı", "not-found"),
    405: ("Yöntem desteklenmiyor", "method-not-allowed"),
    409: ("Çakışma", "conflict"),
    429: ("Çok fazla istek", "rate-limited"),
}


def install_error_handlers(app: FastAPI) -> None:
    """Tüm hata türlerini problem+json biçimine bağlar."""

    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(request, exc.status, exc.title, exc.slug, exc.detail, exc.headers, exc.extra)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        title, slug = _STATUS_TITLES.get(exc.status_code, ("Hata", "error"))
        return problem_response(request, exc.status_code, title, slug)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Girdi değerleri (parola vb.) yanıta yansıtılmaz; yalnız alan yolu ve kural kodu.
        errors = [
            {"field": ".".join(str(p) for p in err["loc"][1:]), "code": err["type"]} for err in exc.errors()
        ]
        return problem_response(
            request,
            422,
            "Doğrulama hatası",
            "validation-error",
            "İstek gövdesi geçersiz.",
            extra={"errors": errors},
        )
