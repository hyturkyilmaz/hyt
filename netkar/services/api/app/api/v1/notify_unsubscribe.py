"""Tek tık bildirim kapatma ucu (ADR-0009 §7.5, RFC 8058): oturum gerektirmez, imzalı token ile çalışır.

`POST /v1/notifications/unsubscribe?token=...`. Yetki YALNIZ token'dan gelir; uç çerez ve oturum OKUMAZ ve
YAZMAZ (bu yüzden `CsrfMiddleware` bu tam yolu muaf tutar, `app.core.middleware.CSRF_EXEMPT`). Gövde yoksa kabul
edilir (web onay sayfası); varsa YALNIZ `application/x-www-form-urlencoded` ya da TEK alanlı
`multipart/form-data` olabilir ve alan tam olarak `List-Unsubscribe=One-Click` (RFC 8058) olmalıdır, aksi 400. GET hiçbir şey değiştirmez (uç yalnız POST).

Token kullanıcıya, kiracıya, kurala ve kanala bağlıdır (`app.services.notify_unsubscribe`); uç yalnız `mode = 'off'`
yazar, token'daki kullanıcı kiracının ÜYESİ değilse yazılmaz. Bozuk, imzası uyuşmayan, süresi dolmuş ve üye olmayan
kullanıcının token'ı aynı 400 yanıtını verir (ayrım sızdırılmaz).

Hız sınırı: IP sınırı yalnız doğrulaması BAŞARISIZ denemelere uygulanır (paylaşılan IP'li geçerli kullanıcılar
birbirini kilitlemez, tahmin denemesi kesilir); geçerli token için token özeti başına ayrı saatlik sınır vardır.

Token iptali yalnız anahtar döndürmeyle (DATA_ENCRYPTION_KEY) olur; sorgu dizesi token taşıdığından vekil/CDN
erişim loglarında maskelenmelidir (README "Bildirim dağıtıcısı"). Yanıtta e-posta adresi ve token yoktur.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from app.api.deps import DbDep, RateLimiterDep, SettingsDep, client_ip, ip_hash_for
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.ratelimit import RateLimiter, digest
from app.db.rls import set_rls_context
from app.services.audit import record_audit
from app.services.notify_unsubscribe import UnsubscribeSigner

router = APIRouter(prefix="/notifications", tags=["notifications"])

_WINDOW_HOURLY = 60 * 60

# Yalnız `off` yönü: tercih satırı yoksa eklenir, varsa kapatılır (başka sütun değişmez).
_ONE_CLICK_BODY = {"List-Unsubscribe": ["One-Click"]}
_FORM = "application/x-www-form-urlencoded"
_MULTIPART = "multipart/form-data"
# RFC 8058 gövdesi tek kısa alandır: 1 KiB üstü hiç ayrıştırılmaz (CPU/yığın tüketimi, kimlik doğrulamadan önce).
_MAX_BODY_BYTES = 1024
_BOUNDARY = re.compile(r'boundary="?([A-Za-z0-9\'()+_,\-./:=?]{1,70})"?', re.IGNORECASE)
_DISPOSITION = re.compile(rb'content-disposition: ?form-data; ?name="([A-Za-z0-9_\-]{1,64})"', re.IGNORECASE)
_SQL_IS_MEMBER = text("SELECT 1 FROM memberships WHERE user_id = :user_id AND tenant_id = :tenant_id")
_SQL_TURN_OFF = text(
    "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) "
    "VALUES (:tenant_id, :user_id, :rule, :channel, 'off') "
    "ON CONFLICT ON CONSTRAINT pk_notification_preferences DO UPDATE SET mode = 'off'"
)


class UnsubscribeResponse(BaseModel):
    """Kapatılan kural(lar) ve kanal."""

    rules: list[str]
    channel: str
    mode: str = "off"


def _invalid() -> ProblemError:
    return ProblemError(
        400,
        "Geçersiz bağlantı",
        "invalid-unsubscribe-token",
        "Bağlantı geçersiz ya da süresi dolmuş. Bildirim tercihlerini panelden değiştirebilirsiniz.",
    )


async def _read_small_body(request: Request) -> bytes | None:
    """Gövdeyi en çok `_MAX_BODY_BYTES` bayta kadar okur; fazlası varsa None (AYRIŞTIRMA yapılmaz, akış kesilir)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > _MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _body_is_valid(content_type: str, body: bytes) -> bool:
    """Gövde RFC 8058 biçiminde mi (urlencoded ya da TEK alanlı multipart; alan `List-Unsubscribe=One-Click`).

    Hiçbir koşulda istisna fırlatmaz (savunmacı): bozuk girdi False'tur.
    """
    try:
        kind = content_type.split(";")[0].strip().lower()
        if kind == _MULTIPART:
            return _multipart_fields(content_type, body) == _ONE_CLICK_BODY
        if kind != _FORM:
            return False
        return parse_qs(body.decode("ascii"), keep_blank_values=True, strict_parsing=True) == _ONE_CLICK_BODY
    except Exception:
        return False


def _multipart_fields(content_type: str, body: bytes) -> dict[str, list[str]] | None:
    """TEK alanlı `multipart/form-data` gövdesinin alanı (elle, doğrusal ve özyinelemesiz ayrıştırma).

    Biçim: `--B CRLF Content-Disposition: form-data; name="x" CRLF CRLF değer CRLF --B-- [CRLF]`. Başka başlık,
    ikinci parça, iç içe multipart ve sınır içeren değer reddedilir (None).
    """
    found = _BOUNDARY.search(content_type)
    if found is None:
        return None
    delimiter = b"--" + found.group(1).encode("ascii")
    if not body.startswith(delimiter + b"\r\n"):
        return None
    rest = body[len(delimiter) + 2 :]
    cut = rest.find(b"\r\n" + delimiter)
    if cut < 0 or rest[cut + 2 + len(delimiter) :] not in (b"--", b"--\r\n"):
        return None
    head, separator, value = rest[:cut].partition(b"\r\n\r\n")
    named = _DISPOSITION.fullmatch(head)
    if not separator or named is None:
        return None
    return {named.group(1).decode("ascii"): [value.decode("ascii")]}


async def _count_failure(request: Request, settings: Settings, limiter: RateLimiter) -> None:
    """Başarısız deneme (geçersiz gövde ya da token) IP sayacına işler (429 burada fırlayabilir)."""
    await limiter.hit(
        f"notify-unsub:ip:{digest(settings.master_key, 'notify-unsub-ip', client_ip(request))}",
        settings.rate_limit_notify_unsubscribe_ip,
        _WINDOW_HOURLY,
    )


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    token: Annotated[str, Query(min_length=1, max_length=512)],
) -> UnsubscribeResponse:
    """Token'daki kullanıcı için ilgili kural(lar)ın bildirimini `off` yapar."""
    # Gövde, kimlik doğrulamasından ve hız sınırından ÖNCE okunur ama 1 KiB üstü hiç ayrıştırılmaz; geçersiz gövde
    # de başarısız deneme sayılır (IP sayacı).
    body = await _read_small_body(request)
    if body is None or (body and not _body_is_valid(request.headers.get("content-type", ""), body)):
        await _count_failure(request, settings, limiter)
        raise _invalid()
    claim = UnsubscribeSigner.from_settings(settings).verify(token, datetime.now(UTC))
    if claim is None:
        await _count_failure(request, settings, limiter)  # yalnız başarısız denemeler IP sayacına işler
        raise _invalid()
    await limiter.hit(
        # Anahtar DOĞRULANMIŞ claim'den (kullanıcı|kiracı|kural|kanal) kurulur: token'ın biçimsel varyantları
        # (farklı kodlama) aynı sayacı paylaşır. Süre dolumu farkı sayacı bölmesin diye bitiş zamanı girmez.
        f"notify-unsub:claim:"
        f"{digest(settings.master_key, 'notify-unsub-token', f'{claim.user_id}|{claim.tenant_id}|{claim.rule}|{claim.channel}')}",
        settings.rate_limit_notify_unsubscribe_token,
        _WINDOW_HOURLY,
    )
    await set_rls_context(db, claim.tenant_id, claim.user_id)
    if (
        await db.execute(_SQL_IS_MEMBER, {"user_id": claim.user_id, "tenant_id": claim.tenant_id})
    ).first() is None:
        await db.rollback()
        raise _invalid()
    try:
        for rule in claim.rules:
            params: dict[str, Any] = {
                "tenant_id": claim.tenant_id,
                "user_id": claim.user_id,
                "rule": rule,
                "channel": claim.channel,
            }
            await db.execute(_SQL_TURN_OFF, params)
        await record_audit(
            db,
            claim.tenant_id,
            "notification.unsubscribe",
            user_id=claim.user_id,
            ip_hash=ip_hash_for(request, settings),
            meta={"rules": list(claim.rules), "channel": claim.channel},
        )
        await db.commit()
    except sa_exc.IntegrityError:
        # İmzalı ama artık var olmayan kiracı/kullanıcı: ayrım sızdırılmaz.
        await db.rollback()
        raise _invalid() from None
    return UnsubscribeResponse(rules=list(claim.rules), channel=claim.channel)
