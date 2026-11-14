"""RFC 9457 (application/problem+json) hata yanıtları."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

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
    413: ("İstek gövdesi çok büyük", "payload-too-large"),
    429: ("Çok fazla istek", "rate-limited"),
}


def install_error_handlers(app: FastAPI) -> None:
    """Tüm hata türlerini problem+json biçimine bağlar."""

    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(request, exc.status, exc.title, exc.slug, exc.detail, exc.headers, exc.extra)

    @app.exception_handler(PoolTimeoutError)
    async def _pool_timeout(request: Request, exc: PoolTimeoutError) -> JSONResponse:
        # Ana bağlantı havuzu tükendi (denetim S4 Y-01): ayrıntı (havuz boyutu) yalnız logda; istemciye 503.
        log.warning("db_pool_timeout path=%s", request.url.path)
        retry_after = str(max(1, request.app.state.settings.db_busy_retry_after_seconds))
        return problem_response(
            request,
            503,
            "Hizmet yoğun",
            "db-busy",
            "Şu an çok sayıda istek işleniyor. Kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": retry_after},
        )

    @app.exception_handler(DBAPIError)
    async def _db_error(request: Request, exc: DBAPIError) -> JSONResponse:
        # DK-11: önbellek isabeti yolunda `_report` sonrasında aynı işlemde çalışan sorgular (ürün başlıkları
        # vb.) `statement_timeout` ile 57014 alabilir ve `_report` sarmalayıcısının dışında kalır. Yalnız bu
        # sqlstate merkezi olarak 503'e çevrilir; SQL, parametre ve sürücü iletisi ne yanıta ne loga girer.
        if getattr(exc.orig, "sqlstate", None) != "57014":
            raise exc  # diğer veritabanı hataları eskisi gibi yayılır (düz 500, ayrıntı sızmaz)
        log.error("db_statement_timeout path=%s", request.url.path)
        retry_after = str(max(1, request.app.state.settings.profit_report_retry_after_seconds))
        # DK-13: slug yola göre; /profit altı rapor zaman aşımı, diğer uçlar genel db-timeout.
        if "profit" in request.url.path.split("/"):
            return problem_response(
                request,
                503,
                "Rapor hesaplanamadı",
                "report-compute-timeout",
                "Rapor belirlenen sürede hazırlanamadı. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": retry_after},
            )
        return problem_response(
            request,
            503,
            "Veritabanı zaman aşımı",
            "db-timeout",
            "İşlem belirlenen sürede tamamlanamadı. Kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": retry_after},
        )

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
