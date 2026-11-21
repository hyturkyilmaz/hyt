"""Tek tık bildirim kapatma ucu (ADR-0009 §7.5, RFC 8058): oturum gerektirmez, imzalı token ile çalışır.

`POST /v1/notifications/unsubscribe?token=...`. Yetki YALNIZ token'dan gelir; uç çerez ve oturum OKUMAZ ve
YAZMAZ (bu yüzden `CsrfMiddleware` bu tam yolu muaf tutar, `app.core.middleware.CSRF_EXEMPT`). Gövde yoksa kabul
edilir (web onay sayfası); varsa YALNIZ `application/x-www-form-urlencoded` ve tam olarak
`List-Unsubscribe=One-Click` (RFC 8058) olabilir, aksi 400. GET hiçbir şey değiştirmez (uç yalnız POST).

Token kullanıcıya, kiracıya, kurala ve kanala bağlıdır (`app.services.notify_unsubscribe`); uç yalnız `mode = 'off'`
yazar, token'daki kullanıcı kiracının ÜYESİ değilse yazılmaz. Bozuk, imzası uyuşmayan, süresi dolmuş ve üye olmayan
kullanıcının token'ı aynı 400 yanıtını verir (ayrım sızdırılmaz).

Hız sınırı: IP sınırı yalnız doğrulaması BAŞARISIZ denemelere uygulanır (paylaşılan IP'li geçerli kullanıcılar
birbirini kilitlemez, tahmin denemesi kesilir); geçerli token için token özeti başına ayrı saatlik sınır vardır.

Token iptali yalnız anahtar döndürmeyle (DATA_ENCRYPTION_KEY) olur; sorgu dizesi token taşıdığından vekil/CDN
erişim loglarında maskelenmelidir (README "Bildirim dağıtıcısı"). Yanıtta e-posta adresi ve token yoktur.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from app.api.deps import DbDep, RateLimiterDep, SettingsDep, client_ip, ip_hash_for
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.db.rls import set_rls_context
from app.services.audit import record_audit
from app.services.notify_unsubscribe import UnsubscribeSigner

router = APIRouter(prefix="/notifications", tags=["notifications"])

_WINDOW_HOURLY = 60 * 60

# Yalnız `off` yönü: tercih satırı yoksa eklenir, varsa kapatılır (başka sütun değişmez).
_ONE_CLICK_BODY = {"List-Unsubscribe": ["One-Click"]}
_FORM = "application/x-www-form-urlencoded"
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


async def _check_body(request: Request) -> None:
    """Gövde yoksa serbest; varsa yalnız RFC 8058 biçimi (form + `List-Unsubscribe=One-Click`)."""
    body = await request.body()
    if not body:
        return
    kind = request.headers.get("content-type", "").split(";")[0].strip().lower()
    try:
        parsed = parse_qs(body.decode("ascii"), keep_blank_values=True, strict_parsing=True)
    except (UnicodeDecodeError, ValueError):
        raise _invalid() from None
    if kind != _FORM or parsed != _ONE_CLICK_BODY:
        raise _invalid()


@router.post("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    token: Annotated[str, Query(min_length=1, max_length=512)],
) -> UnsubscribeResponse:
    """Token'daki kullanıcı için ilgili kural(lar)ın bildirimini `off` yapar."""
    await _check_body(request)
    claim = UnsubscribeSigner.from_settings(settings).verify(token, datetime.now(UTC))
    if claim is None:
        # Yalnız başarısız doğrulamalar IP sayacına işler (429 burada da fırlayabilir).
        await limiter.hit(
            f"notify-unsub:ip:{digest(settings.master_key, 'notify-unsub-ip', client_ip(request))}",
            settings.rate_limit_notify_unsubscribe_ip,
            _WINDOW_HOURLY,
        )
        raise _invalid()
    await limiter.hit(
        f"notify-unsub:token:{digest(settings.master_key, 'notify-unsub-token', token)}",
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
