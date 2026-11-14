"""Hata izleyici (Sentry) hazırlığı: kişisel veri ve sır süzgeci (denetim D-01, G16).

Sentry kendisi bu projeye EKLENMEDİ. Eklendiğinde `sentry_sdk.init(**sentry_init_options())`
kullanılmalıdır; böylece:

  - çerçeve yerelleri (`include_local_variables`) gönderilmez: ham Trendyol yanıtı ve sırlar
    traceback çerçevelerinde bulunabilir,
  - istek gövdesi ve çerezler gönderilmez,
  - `before_send` olay yükünden kalan riskli alanları ayrıca siler (savunma derinliği).

Süzgeç saftır (sözlük alır, sözlük döndürür), SDK'ya bağımlı değildir ve test edilir.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# İstek başlıklarından atılanlar (küçük harfle karşılaştırılır). Yalnız zararsız başlıklar kalır.
_SENSITIVE_HEADERS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-csrf-token", "proxy-authorization", "x-api-key"}
)


def _scrub_exception(exception: Any) -> None:
    for value in (exception or {}).get("values") or []:
        for frame in (value.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)


def _scrub_request(request: dict[str, Any]) -> None:
    for key in ("data", "cookies", "query_string"):
        request.pop(key, None)
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = {k: v for k, v in headers.items() if k.lower() not in _SENSITIVE_HEADERS}


def scrub_event(event: dict[str, Any], hint: Any) -> dict[str, Any] | None:
    """Sentry `before_send`: kişisel veri ve sır taşıyabilecek alanları olaydan siler.

    Silinenler: çerçeve `vars` değerleri, istek gövdesi/çerezi/sorgu dizesi, kimlik doğrulama
    başlıkları, kullanıcı e-postası/IP'si/adı (yalnız `id` kalır), breadcrumb `data`, serbest
    `extra` alanı.
    """
    _scrub_exception(event.get("exception"))
    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {k: v for k, v in user.items() if k == "id"}
    crumbs = event.get("breadcrumbs")
    if isinstance(crumbs, dict):
        for crumb in crumbs.get("values") or []:
            crumb.pop("data", None)
    event.pop("extra", None)
    return event


def scrub_breadcrumb(crumb: dict[str, Any], hint: Any) -> dict[str, Any] | None:
    """Sentry `before_breadcrumb`: ek veri alanını atar (mesaj ve kategori kalır)."""
    crumb.pop("data", None)
    return crumb


def sentry_init_options() -> dict[str, Any]:
    """`sentry_sdk.init` için zorunlu gizlilik ayarları (DSN ve ortam çağıranın)."""
    before_breadcrumb: Callable[[dict[str, Any], Any], dict[str, Any] | None] = scrub_breadcrumb
    return {
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "before_send": scrub_event,
        "before_breadcrumb": before_breadcrumb,
    }
