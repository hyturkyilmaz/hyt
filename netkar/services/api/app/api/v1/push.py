"""Web push abonelik uçları (ADR-0009 §8.2, D8 birinci yarı). GÖNDERİM YOKTUR; yalnız abonelik kaydı.

Uçlar (`/v1` altında, oturum gerekir; üç rol de kullanır):

- `GET    /push/vapid-public-key`         genel anahtar ve `key_id`; bayrak kapalıyken `{enabled: false}`
- `POST   /me/push-subscriptions`         abonelik (idempotent: aynı uç nokta aynı kullanıcıdan 200 ile aynı satır)
- `GET    /me/push-subscriptions`         kendi etkin abonelikleri (maskeli)
- `DELETE /me/push-subscriptions/{id}`    kendi aboneliğini iptal eder (`revoked_at`, silme yok)
- `POST   /me/push-subscriptions/check`   bu uç noktada kendi etkin aboneliğim var mı (204/404)
- `POST   /me/push-subscriptions/release` uç noktayla bırakma (çıkış ve kapatma); her durumda 204

Kararlar:

- Bayrak (`WEB_PUSH_ENABLED`) kapalıyken POST 409 `push-disabled` döner. ADR §7.2 "kapalıyken abonelik kaydı
  çalışır" der; bu uç bilerek daha dardır: genel anahtar yokken `vapid_key_id` üretilemez ve kullanılmayan bir cihaz
  tanımlayıcısı saklamak veri minimizasyonuna (KVKK) aykırıdır. 403 değil 409: kullanıcı yetkilidir, çakışan şey
  sistem durumudur. DELETE ve GET bayrağa bağlı DEĞİLDİR (kullanıcı kendi cihazını her zaman silebilir).
- Bu uçlar `notification-preferences` gibi doğrulanmış e-posta kapısı dışındadır: yalnız kullanıcının KENDİ cihazı
  yazılır, kiracı verisi yazılmaz.
- Başka kullanıcının (ya da kiracının) abonelik kimliği 404 (varlık sızdırılmaz; ASVS V4, API1). RLS kiracı VE kullanıcı
  koşulu ile çift kilittir; sorgularda açık süzgeç de vardır.
- Uç nokta URL'si ve anahtarlar log'a ve `audit_log`'a yazılmaz; denetime yalnız abonelik kimliği ve ana bilgisayar
  adı girer (izin listesindeki sabit bir değer).
- Aynı uç nokta başka kullanıcının etkin aboneliğindeyse (paylaşılan cihazda çıkış yapılmadan hesap değişti) 409
  `push-endpoint-in-use`: RLS yüzünden o satır görünmez ve kullanıcılar arası devralma yapılmaz.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import DbDep, EnvelopeDep, RateLimiterDep, SettingsDep, ip_hash_for, require_role
from app.api.v1.push_schemas import (
    PushEndpointIn,
    PushSubscriptionIn,
    PushSubscriptionListOut,
    PushSubscriptionOut,
    VapidKeyOut,
)
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.models import PushSubscription, Role
from app.services import push as svc
from app.services.audit import record_audit
from app.services.auth import AuthContext

router = APIRouter(tags=["push"])

AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]

_MINUTE = 60
_HOURLY = 60 * 60
# Kullanıcı başına sabit sınırlar (yapılandırma anahtarı eklenmedi; alerts.py tercih uçlarıyla aynı desen).
_KEY_READ_PER_MINUTE = 60
_SUBSCRIBE_PER_HOUR = 20
_LIST_PER_MINUTE = 60
_DELETE_PER_HOUR = 60
# Bırakma ucu abone olma kotasından AYRI anahtar kullanır (çıkış, abone olma hakkını tüketmesin).
_RELEASE_PER_HOUR = 60


def _not_found() -> ProblemError:
    return ProblemError(404, "Bulunamadı", "not-found")


def _push_ready(settings: Settings) -> bool:
    """Bayrak açık VE genel anahtar tanımlı (anahtarsız abonelik anlamsızdır)."""
    return settings.web_push_enabled and settings.web_push_vapid_public_key is not None


async def _limit(
    limiter: RateLimiterDep, settings: Settings, ctx: AuthContext, name: str, limit: int, window: int
) -> None:
    who = digest(settings.master_key, "rl-user", str(ctx.user_id))
    await limiter.hit(f"{name}:user:{who}", limit, window)


def _out(row: PushSubscription) -> PushSubscriptionOut:
    return PushSubscriptionOut(
        id=row.id,
        endpoint_host=row.endpoint_host,
        vapid_key_id=row.vapid_key_id,
        created_at=row.created_at,
        last_success_at=row.last_success_at,
    )


@router.get("/push/vapid-public-key", response_model=VapidKeyOut)
async def vapid_public_key(ctx: AnyRoleDep, settings: SettingsDep, limiter: RateLimiterDep) -> VapidKeyOut:
    """VAPID genel anahtarı (gizli değildir). Bayrak kapalıyken yalnız `enabled: false`; özel anahtar hiç dönmez."""
    await _limit(limiter, settings, ctx, "push-key", _KEY_READ_PER_MINUTE, _MINUTE)
    public_key = settings.web_push_vapid_public_key
    if not _push_ready(settings) or public_key is None:
        return VapidKeyOut(enabled=False)
    return VapidKeyOut(enabled=True, public_key=public_key, key_id=svc.vapid_key_id(public_key))


@router.post("/me/push-subscriptions", response_model=PushSubscriptionOut)
async def subscribe(
    body: PushSubscriptionIn,
    request: Request,
    response: Response,
    ctx: AnyRoleDep,
    db: DbDep,
    envelope: EnvelopeDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> PushSubscriptionOut:
    """Aboneliği kaydeder: 201 yeni, 200 aynı uç noktanın mevcut (etkin) aboneliği (idempotent)."""
    await _limit(limiter, settings, ctx, "push-subscribe", _SUBSCRIBE_PER_HOUR, _HOURLY)
    public_key = settings.web_push_vapid_public_key
    if not _push_ready(settings) or public_key is None:
        raise ProblemError(
            409,
            "Anlık bildirim kapalı",
            "push-disabled",
            "Anlık bildirim şu an etkin değil; abonelik kaydedilmedi.",
        )
    digest_value = svc.endpoint_digest(settings.master_key, body.endpoint)
    # Sınır sayımı ve ekleme kullanıcı başına sıralanır (eşzamanlı POST sınırı aşamaz).
    await svc.lock_user_subscriptions(db, ctx.tenant_id, ctx.user_id)
    existing = await svc.find_active_by_digest(db, ctx.tenant_id, ctx.user_id, digest_value)
    if existing is not None:
        if existing.created_session_id == ctx.session_id:
            response.status_code = 200
            return _out(existing)
        # Aynı cihaz, başka (eski) oturumda açılmış: eski satır iptal edilir, yenisi bu oturuma bağlanır (H11:
        # çıkış yalnız o oturumda açılan abonelikleri iptal eder).
        await svc.revoke_own(db, ctx.tenant_id, ctx.user_id, existing.id)
        await record_audit(
            db,
            ctx.tenant_id,
            "push.unsubscribe",
            user_id=ctx.user_id,
            target=str(existing.id),
            ip_hash=ip_hash_for(request, settings),
            meta={"rebind": True, "endpoint_host": existing.endpoint_host},
        )
    if await svc.count_active(db, ctx.tenant_id, ctx.user_id) >= svc.MAX_ACTIVE_PER_USER:
        raise ProblemError(
            409,
            "Abonelik sınırı",
            "push-subscription-limit",
            f"En çok {svc.MAX_ACTIVE_PER_USER} etkin cihaz abone olabilir; önce birini kapatın.",
        )
    host = svc.validate_endpoint(body.endpoint)
    subscription_id = await svc.insert_subscription(
        db,
        envelope,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        endpoint=body.endpoint,
        host=host,
        digest=digest_value,
        p256dh=body.keys.p256dh,
        auth=body.keys.auth,
        key_id=svc.vapid_key_id(public_key),
    )
    if subscription_id is None:
        # Yarış ya da başka kullanıcının etkin satırı: kendi satırı varsa idempotent yanıt, yoksa devralma yok.
        mine = await svc.find_active_by_digest(db, ctx.tenant_id, ctx.user_id, digest_value)
        if mine is None:
            raise ProblemError(
                409,
                "Cihaz kullanımda",
                "push-endpoint-in-use",
                "Bu cihaz başka bir kullanıcıya abone görünüyor; o kullanıcı çıkış yapınca tekrar deneyin.",
            )
        response.status_code = 200
        return _out(mine)
    # Satır commit'ten ÖNCE okunur: commit işlem yerel RLS bağlamını sıfırlar.
    row = await svc.get_own(db, ctx.tenant_id, ctx.user_id, subscription_id)
    if row is None:  # pragma: no cover - aynı işlemde eklenen satır kendi bağlamında her zaman okunur
        raise _not_found()
    created = _out(row)
    await record_audit(
        db,
        ctx.tenant_id,
        "push.subscribe",
        user_id=ctx.user_id,
        target=str(subscription_id),
        ip_hash=ip_hash_for(request, settings),
        meta={"endpoint_host": host},
    )
    await db.commit()
    response.status_code = 201
    return created


@router.post("/me/push-subscriptions/check", status_code=204)
async def check_subscription(
    body: PushEndpointIn, ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> Response:
    """Bu uç noktada KENDİ etkin aboneliğim var mı: 204 evet, 404 hayır (başkasınınki de 404; varlık sızmaz).

    Servis çalışanı `pushsubscriptionchange`'de, başka kullanıcının oturumunda rızasız yeniden kayıt
    yapmamak için bunu sorar.
    """
    await _limit(limiter, settings, ctx, "push-check", _SUBSCRIBE_PER_HOUR, _HOURLY)
    digest_value = svc.endpoint_digest(settings.master_key, body.endpoint)
    if await svc.find_active_by_digest(db, ctx.tenant_id, ctx.user_id, digest_value) is None:
        raise _not_found()
    return Response(status_code=204)


@router.post("/me/push-subscriptions/release", status_code=204)
async def release_subscription(
    body: PushEndpointIn,
    request: Request,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> Response:
    """Uç noktayla tanımlanan KENDİ etkin aboneliğimi iptal eder (çıkış ve kapatma akışı).

    Her durumda 204: abonelik yoksa, başkasınınsa ya da zaten iptalse de aynı yanıt (varlık sızmaz). Denetim
    kaydı yalnız gerçekten bir satır iptal edildiyse yazılır. Bayrağa bağlı DEĞİLDİR.
    """
    await _limit(limiter, settings, ctx, "push-release", _RELEASE_PER_HOUR, _HOURLY)
    digest_value = svc.endpoint_digest(settings.master_key, body.endpoint)
    row = await svc.find_active_by_digest(db, ctx.tenant_id, ctx.user_id, digest_value)
    if row is not None and await svc.revoke_own(db, ctx.tenant_id, ctx.user_id, row.id):
        await record_audit(
            db,
            ctx.tenant_id,
            "push.unsubscribe",
            user_id=ctx.user_id,
            target=str(row.id),
            ip_hash=ip_hash_for(request, settings),
            meta={"endpoint_host": row.endpoint_host},
        )
        await db.commit()
    return Response(status_code=204)


@router.get("/me/push-subscriptions", response_model=PushSubscriptionListOut)
async def list_subscriptions(
    ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> PushSubscriptionListOut:
    """Kendi etkin abonelikleri (maskeli: uç nokta ve anahtarlar dönmez)."""
    await _limit(limiter, settings, ctx, "push-list", _LIST_PER_MINUTE, _MINUTE)
    rows = await svc.list_active(db, ctx.tenant_id, ctx.user_id)
    return PushSubscriptionListOut(items=[_out(row) for row in rows])


@router.delete("/me/push-subscriptions/{subscription_id}", status_code=204)
async def unsubscribe(
    subscription_id: UUID,
    request: Request,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> Response:
    """Kendi aboneliğini iptal eder (silme yok). Başkasının ya da olmayan kimlik 404; zaten iptal edilmiş 204."""
    await _limit(limiter, settings, ctx, "push-delete", _DELETE_PER_HOUR, _HOURLY)
    row = await svc.get_own(db, ctx.tenant_id, ctx.user_id, subscription_id)
    if row is None:
        raise _not_found()
    if await svc.revoke_own(db, ctx.tenant_id, ctx.user_id, subscription_id):
        await record_audit(
            db,
            ctx.tenant_id,
            "push.unsubscribe",
            user_id=ctx.user_id,
            target=str(subscription_id),
            ip_hash=ip_hash_for(request, settings),
            meta={"endpoint_host": row.endpoint_host},
        )
        await db.commit()
    return Response(status_code=204)
