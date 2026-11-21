"""Uyarı API'si (ADR-0009 D6, §8.2): olay listesi, geçişler, toplu okundu, hesap eşikleri, kullanıcı tercihleri.

Uçlar (`/v1` altında):

- `GET  /marketplace-accounts/{account_id}/alert-events`            (owner, admin, viewer)
- `GET  /marketplace-accounts/{account_id}/alert-events/{event_id}`  (owner, admin, viewer) olay + geçiş geçmişi
- `POST /marketplace-accounts/{account_id}/alert-events/{event_id}/transitions`
    `read`/`open`: owner, admin, viewer; `muted` ve `muted -> open`: yalnız owner, admin
- `POST /marketplace-accounts/{account_id}/alert-events/read-all`   (owner, admin, viewer; en çok 500)
  Yazma uçları (geçiş, toplu okundu, eşik PUT) doğrulanmış e-posta ister (403 email-not-verified).
- `GET/PUT /marketplace-accounts/{account_id}/alert-settings`       GET herkes; PUT owner/admin (doğrulanmış e-posta)
- `GET/PUT /me/notification-preferences`                            oturumdaki kullanıcı, yalnız kendi tercihi

Güvenlik:

- Başka kiracının ya da başka hesabın hesap/olay kimliği 404 döner (403 değil; varlık sızdırılmaz, ASVS V4 / API1).
  Her sorguda açık `tenant_id` süzgeci + RLS (çift kilit).
- Durum değişikliği YALNIZ `alert_event_transitions` defterine ekleme ile olur; kullanıcı `resolved` yazamaz (şema),
  viewer `muted` yazamaz (rol denetimi + tetikleyici), `muted_until` en çok 90 gün (şema + tetikleyici).
- Hesap eşikleri ETag/`If-Match` ile korunur (sürüm sayacı yok: sunucu `updated_at` damgası sürüm işlevi görür);
  eşleşmezse 412 `alert-settings-changed`, başlık yoksa 428. Yazım `audit_log`'a düşer (tutar yok: yalnız alan adları).
- İç ayrıntı (SQL, SQLSTATE metni, sürücü iletisi) yanıta ve loga girmez; veritabanı reddi sabit iletiyle eşlenir.
- Hız sınırı: kiracı başına okuma (dakikalık) ve yazma (saatlik), mevcut kâr ayarı sayaç ayarlarıyla ama AYRI sayaç
  anahtarlarıyla; kullanıcı tercihleri için kullanıcı başına sabit sınırlar.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.exc import DBAPIError

from app.api.deps import DbDep, RateLimiterDep, SettingsDep, ip_hash_for, require_role
from app.api.v1.alerts_schemas import (
    AlertEventDetailOut,
    AlertEventListOut,
    AlertEventOut,
    AlertSettingsIn,
    AlertSettingsOut,
    ChannelModes,
    EventStatus,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
    PreferenceMatrix,
    ReadAllOut,
    RuleName,
    TransitionIn,
    TransitionOut,
    TransitionResultOut,
)
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.models import AlertEvent, AlertEventTransition, Role
from app.profit.schema_v1 import ISTANBUL
from app.services import alert_api as svc
from app.services import product_costs as costs
from app.services import profit_views as views
from app.services.audit import record_audit
from app.services.auth import AuthContext
from app.worker.queue import request_alert_evaluation

router = APIRouter(prefix="/marketplace-accounts/{account_id}", tags=["alerts"])
me_router = APIRouter(prefix="/me", tags=["alerts"])

AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]
# Tüm yazma uçları (geçiş, toplu okundu, eşik): e-postası doğrulanmamış hesap 403 email-not-verified alır
# (kâr ayarı yazımıyla aynı kapı; test_email_verification.py her yazma ucunun kapıda olduğunu zorlar).
WriteAnyRoleDep = Annotated[
    AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER, verified=True))
]
AdminDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, verified=True))]

EVENT_FINGERPRINT = "alert-events"
_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_MINUTE = 60
_HOURLY = 60 * 60
# Kullanıcı tercihleri: kullanıcı başına sabit sınırlar (yapılandırma anahtarı eklenmedi).
# Geçişler: kullanıcı başına alt sınır ve kiracı tavanı (yapılandırma anahtarı eklenmedi).
_TRANSITION_USER_PER_HOUR = 300
_TRANSITION_TENANT_PER_HOUR = 1200
_PREFS_READ_PER_MINUTE = 120
_PREFS_WRITE_PER_HOUR = 60


def _not_found() -> ProblemError:
    return ProblemError(404, "Bulunamadı", "not-found")


def _invalid(field: str, code: str, detail: str) -> ProblemError:
    """RequestValidationError ile aynı gövde biçimi: alan yolu ve kural kodu (girdi değeri yansıtılmaz)."""
    return ProblemError(
        422,
        "Doğrulama hatası",
        "validation-error",
        detail,
        extra={"errors": [{"field": field, "code": code}]},
    )


# --------------------------------------------------------------------------- korumalar
async def _require_account(db: DbDep, ctx: AuthContext, account_id: UUID) -> None:
    """Hesap başka kiracıya aitse (veya yoksa) 404; sayaca girmez."""
    if not await costs.account_exists(db, ctx.tenant_id, account_id):
        raise _not_found()


def _tenant_key(settings: SettingsDep, name: str, ctx: AuthContext) -> str:
    return f"{name}:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}"


async def _read_guard(
    db: DbDep,
    ctx: AuthContext,
    account_id: UUID,
    limiter: RateLimiterDep,
    settings: SettingsDep,
    name: str = "alerts-read",
) -> None:
    """Okuma sayacı kiracı başınadır; eşik GET'i liste ve detaydan AYRI sayaç kullanır (`name`)."""
    await _require_account(db, ctx, account_id)
    await limiter.hit(
        _tenant_key(settings, name, ctx), settings.rate_limit_profit_settings_read_tenant, _MINUTE
    )


async def _settings_write_guard(
    db: DbDep, ctx: AuthContext, account_id: UUID, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Eşik PUT'u kendi sayacına sahiptir: viewer'ın geçiş yükü owner'ın eşik yazımını 429'a düşüremez."""
    await _require_account(db, ctx, account_id)
    await limiter.hit(
        _tenant_key(settings, "alerts-settings-write", ctx),
        settings.rate_limit_profit_settings_write_tenant,
        _HOURLY,
    )


async def _transition_guard(
    db: DbDep, ctx: AuthContext, account_id: UUID, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Geçiş ve toplu okundu: önce kullanıcı başına alt sınır, sonra daha geniş kiracı tavanı."""
    await _require_account(db, ctx, account_id)
    who = digest(settings.master_key, "rl-user", str(ctx.user_id))
    await limiter.hit(f"alerts-transition:user:{who}", _TRANSITION_USER_PER_HOUR, _HOURLY)
    await limiter.hit(_tenant_key(settings, "alerts-transition", ctx), _TRANSITION_TENANT_PER_HOUR, _HOURLY)


# --------------------------------------------------------------------------- çıktı kurucuları
def _event_out(event: AlertEvent) -> AlertEventOut:
    return AlertEventOut(
        id=str(event.id),
        rule=event.rule,
        scope=event.scope,
        subject=event.subject,
        severity=event.severity,
        status=event.status,
        first_seen_at=event.first_seen_at,
        last_seen_at=event.last_seen_at,
        occurrence_count=event.occurrence_count,
        muted_until=event.muted_until,
        resolved_at=event.resolved_at,
        payload=event.payload,
        payload_version=event.payload_version,
        data_revision=event.data_revision,
        settings_revision=event.settings_revision,
    )


def _transition_out(row: AlertEventTransition) -> TransitionOut:
    return TransitionOut(
        id=str(row.id),
        from_status=row.from_status,
        to_status=row.to_status,
        actor=row.actor,
        actor_user_id=None if row.actor_user_id is None else str(row.actor_user_id),
        muted_until=row.muted_until,
        created_at=row.created_at,
    )


def _settings_out(state: svc.SettingsState) -> AlertSettingsOut:
    v = state.values
    return AlertSettingsOut(
        loss_min_amount=v.loss_min_amount,
        ad_share_percent=v.ad_share_percent,
        ad_min_spend=v.ad_min_spend,
        deduction_notify_min=v.deduction_notify_min,
        return_min_diff_points=v.return_min_diff_points,
        rules_enabled=list(v.rules_enabled),
        is_default=state.is_default,
        updated_at=state.updated_at,
    )


def _preferences_out(values: svc.PreferencesValues) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        matrix=PreferenceMatrix(**{rule: ChannelModes(**modes) for rule, modes in values.matrix.items()}),
        quiet_start=values.quiet_start,
        quiet_end=values.quiet_end,
        digest_hour=values.digest_hour,
        show_amounts_email=values.show_amounts_email,
        show_amounts_push=values.show_amounts_push,
    )


# --------------------------------------------------------------------------- olay listesi
def _day_bounds(start: str | None, end: str | None) -> tuple[datetime | None, datetime | None]:
    """İstanbul günü aralığı: başlangıç dahil, bitiş günü dahil (üst sınır ertesi gün 00:00, hariç)."""
    try:
        first = None if start is None else date.fromisoformat(start)
    except ValueError:
        raise _invalid("start", "date_invalid", "Tarih geçerli bir YYYY-AA-GG olmalıdır.") from None
    try:
        last = None if end is None else date.fromisoformat(end)
        until = None if last is None else datetime.combine(last + timedelta(days=1), time.min, ISTANBUL)
    except (ValueError, OverflowError):
        raise _invalid("end", "date_invalid", "Tarih geçerli bir YYYY-AA-GG olmalıdır.") from None
    if first is not None and last is not None and first > last:
        raise _invalid("end", "period_invalid", "Bitiş tarihi başlangıçtan önce olamaz.")
    since = None if first is None else datetime.combine(first, time.min, ISTANBUL)
    return since, until


def _cursor_error() -> ProblemError:
    return _invalid("cursor", "cursor_invalid", "İmleç geçersiz ya da bu sorguya ait değil.")


def _decode_cursor(codec: views.CursorCodec, cursor: str, fingerprint: str) -> tuple[datetime, UUID]:
    try:
        stamp, event_id = codec.decode(cursor, fingerprint, 2)
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, UUID(event_id)
    except (views.CursorError, ValueError):
        raise _cursor_error() from None


@router.get("/alert-events", response_model=AlertEventListOut)
async def list_events(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    status: Annotated[EventStatus | None, Query()] = None,
    rule: Annotated[RuleName | None, Query()] = None,
    start: Annotated[
        str | None, Query(pattern=_DATE_PATTERN, description="Son görülme günü, dahil (İstanbul).")
    ] = None,
    end: Annotated[
        str | None, Query(pattern=_DATE_PATTERN, description="Son görülme günü, dahil (İstanbul).")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> AlertEventListOut:
    """Hesabın uyarı olayları, son görülmeye göre yeniden eskiye; imleç mühürlü (kiracı + hesap + süzgeç bağlı)."""
    await _read_guard(db, ctx, account_id, limiter, settings)
    since, until = _day_bounds(start, end)
    fingerprint = f"{EVENT_FINGERPRINT}|{status or ''}|{rule or ''}|{start or ''}|{end or ''}"
    codec = views.CursorCodec(settings.master_key, ctx.tenant_id, account_id)
    after = None if cursor is None else _decode_cursor(codec, cursor, fingerprint)
    rows, more = await svc.list_events(
        db, ctx.tenant_id, account_id, svc.EventFilter(status, rule, since, until), limit, after
    )
    next_cursor = None
    if more and rows:
        last = rows[-1]
        next_cursor = codec.encode(fingerprint, [last.last_seen_at.isoformat(), str(last.id)])
    evaluation = await svc.last_evaluation(db, ctx.tenant_id, account_id)
    return AlertEventListOut(
        items=[_event_out(e) for e in rows],
        next_cursor=next_cursor,
        open_count=await svc.open_count(db, ctx.tenant_id, account_id),
        last_evaluated_at=None if evaluation is None else evaluation.finished_at,
        data_revision=None if evaluation is None else evaluation.data_revision,
        settings_revision=None if evaluation is None else evaluation.settings_revision,
    )


@router.get("/alert-events/{event_id}", response_model=AlertEventDetailOut)
async def read_event(
    account_id: UUID,
    event_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> AlertEventDetailOut:
    """Tek olay ve geçiş geçmişi. Başka kiracı/hesabın ya da olmayan olay kimliği 404."""
    await _read_guard(db, ctx, account_id, limiter, settings)
    event = await svc.get_event(db, ctx.tenant_id, account_id, event_id)
    if event is None:
        raise _not_found()
    transitions, truncated = await svc.list_transitions(db, ctx.tenant_id, event.id)
    return AlertEventDetailOut(
        event=_event_out(event), transitions=[_transition_out(t) for t in transitions], truncated=truncated
    )


# --------------------------------------------------------------------------- geçişler
def _db_rejection(exc: DBAPIError) -> ProblemError:
    """Veritabanı tetikleyicisinin reddini sabit iletiyle eşler (SQLSTATE sınıflandırır, ayrıntı sızmaz)."""
    state = svc.sqlstate(exc)
    if state == "42501":
        return ProblemError(403, "Erişim reddedildi", "forbidden")
    if state in ("40001", "40P01"):
        return ProblemError(
            409,
            "Çakışma",
            "alert-event-changed",
            "Uyarı başka bir işlemle değişti; yenileyip tekrar deneyin.",
        )
    if state == "23514":
        return ProblemError(
            409, "Çakışma", "alert-transition-invalid", "Bu uyarı için bu durum geçişi yapılamaz."
        )
    if state == "23503":
        return _not_found()
    raise exc


def _preferences_rejection(exc: DBAPIError) -> ProblemError:
    """Tercih yazımında veritabanı reddi: geçişle ilgisiz, ayrı sabit iletiler (ayrıntı sızmaz)."""
    state = svc.sqlstate(exc)
    if state == "42501":
        return ProblemError(403, "Erişim reddedildi", "forbidden")
    if state in ("23514", "23503", "23502"):
        return ProblemError(
            409, "Çakışma", "preferences-rejected", "Tercihler kaydedilemedi; değerleri kontrol edin."
        )
    raise exc


@router.post("/alert-events/read-all", response_model=ReadAllOut)
async def read_all(
    account_id: UUID,
    request: Request,
    ctx: WriteAnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> ReadAllOut:
    """Hesabın açık olaylarına `read` geçişi ekler (en çok `READ_ALL_LIMIT`; kalan varsa tekrar çağrılır)."""
    await _transition_guard(db, ctx, account_id, limiter, settings)
    try:
        updated = await svc.mark_open_events_read(db, ctx.tenant_id, account_id)
    except DBAPIError as exc:
        raise _db_rejection(exc) from None
    remaining = await svc.open_count(db, ctx.tenant_id, account_id)
    if updated:
        await record_audit(
            db,
            ctx.tenant_id,
            "alert_event.read_all",
            user_id=ctx.user_id,
            target=str(account_id),
            ip_hash=ip_hash_for(request, settings),
            meta={"account_id": str(account_id), "count": updated},
        )
        await db.commit()
    return ReadAllOut(updated=updated, remaining_open=remaining)


@router.post("/alert-events/{event_id}/transitions", response_model=TransitionResultOut)
async def add_transition(
    account_id: UUID,
    event_id: UUID,
    body: TransitionIn,
    request: Request,
    ctx: WriteAnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> TransitionResultOut:
    """Durum geçişi ekler (`read | open | muted`); geçiş defterine tek INSERT, durumu tetikleyici uygular.

    Önce olay 404 denetimi (rol sırasından bağımsız: IDOR), sonra ADR matrisi (409), sonra rol (403).
    """
    await _transition_guard(db, ctx, account_id, limiter, settings)
    event = await svc.get_event(db, ctx.tenant_id, account_id, event_id)
    if event is None:
        raise _not_found()
    from_status = event.status
    if body.to not in svc.USER_TRANSITIONS.get(from_status, frozenset()):
        raise ProblemError(
            409, "Çakışma", "alert-transition-invalid", "Bu uyarı için bu durum geçişi yapılamaz."
        )
    if svc.transition_needs_admin(from_status, body.to) and ctx.role is Role.VIEWER:
        raise ProblemError(403, "Erişim reddedildi", "forbidden")
    try:
        transition_id = await svc.add_transition(db, ctx.tenant_id, event.id, body.to, body.muted_days)
        refreshed = await svc.get_event(db, ctx.tenant_id, account_id, event_id)
    except DBAPIError as exc:
        raise _db_rejection(exc) from None
    if refreshed is None:  # pragma: no cover (aynı işlemde olay silinemez)
        raise _not_found()
    out = _event_out(refreshed)
    await record_audit(
        db,
        ctx.tenant_id,
        "alert_event.transition",
        user_id=ctx.user_id,
        target=str(event_id),
        ip_hash=ip_hash_for(request, settings),
        meta={
            "account_id": str(account_id),
            "from": from_status,
            "to": body.to,
            "muted_days": body.muted_days,
        },
    )
    await db.commit()
    return TransitionResultOut(event=out, transition_id=str(transition_id))


# --------------------------------------------------------------------------- hesap eşikleri
IfMatchHeader = Annotated[
    str | None,
    Header(alias="If-Match", max_length=64, description="GET yanıtındaki ETag (eşzamanlılık denetimi)."),
]


@router.get("/alert-settings", response_model=AlertSettingsOut)
async def read_settings(
    account_id: UUID,
    response: Response,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> AlertSettingsOut:
    """Hesap eşikleri ve etkin kurallar (kayıt yoksa varsayılanlar). `ETag` başlığı PUT için `If-Match` olur."""
    await _read_guard(db, ctx, account_id, limiter, settings, "alerts-settings-read")
    state = await svc.load_settings(db, ctx.tenant_id, account_id)
    response.headers["ETag"] = state.etag
    return _settings_out(state)


def _precondition_failed(current_etag: str) -> ProblemError:
    return ProblemError(
        412,
        "Önkoşul sağlanamadı",
        "alert-settings-changed",
        "Eşikler siz düzenlerken başka biri tarafından değiştirildi; sayfayı yenileyip tekrar deneyin.",
        headers={"ETag": current_etag},
    )


@router.put("/alert-settings", response_model=AlertSettingsOut)
async def put_settings(
    account_id: UUID,
    body: AlertSettingsIn,
    request: Request,
    response: Response,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    if_match: IfMatchHeader = None,
) -> AlertSettingsOut:
    """Eşikleri tam değiştirir (owner/admin, doğrulanmış e-posta). `If-Match` zorunlu: 428 yok, 412 uyuşmaz.

    İçerik aynıysa hiçbir şey yazılmaz (ETag değişmez, denetim ve yeniden değerlendirme yok). Yazım sonrası uyarı
    değerlendirmesi en iyi çabayla istenir (eşik özeti değerlendirme anahtarına girer).
    """
    await _settings_write_guard(db, ctx, account_id, limiter, settings)
    if if_match is None:
        raise ProblemError(
            428,
            "Önkoşul gerekli",
            "precondition-required",
            "Eşik güncellemesi için GET yanıtındaki ETag If-Match başlığıyla gönderilmelidir.",
        )
    current = await svc.load_settings(db, ctx.tenant_id, account_id)
    if if_match != current.etag:
        raise _precondition_failed(current.etag)
    new_values = svc.SettingsValues(
        loss_min_amount=body.loss_min_amount.quantize(svc.TWO_PLACES),
        ad_share_percent=body.ad_share_percent.quantize(svc.TWO_PLACES),
        ad_min_spend=body.ad_min_spend.quantize(svc.TWO_PLACES),
        deduction_notify_min=body.deduction_notify_min.quantize(svc.TWO_PLACES),
        return_min_diff_points=body.return_min_diff_points.quantize(svc.TWO_PLACES),
        rules_enabled=tuple(body.rules_enabled),
    )
    if new_values == current.values and not current.is_default:
        await db.rollback()
        response.headers["ETag"] = current.etag
        return _settings_out(current)
    try:
        written_at = await svc.write_settings(db, ctx.tenant_id, account_id, new_values, current.updated_at)
    except DBAPIError as exc:
        raise _db_rejection(exc) from None
    if written_at is None:
        # Yazım yarışı: güncel ETag'i istemciye vermek için durum yeniden okunur.
        raise _precondition_failed((await svc.load_settings(db, ctx.tenant_id, account_id)).etag)
    changed: list[str] = [
        name
        for name in (
            "loss_min_amount",
            "ad_share_percent",
            "ad_min_spend",
            "deduction_notify_min",
            "return_min_diff_points",
            "rules_enabled",
        )
        if getattr(new_values, name) != getattr(current.values, name)
    ]
    await record_audit(
        db,
        ctx.tenant_id,
        "alert_settings.update",
        user_id=ctx.user_id,
        target=str(account_id),
        ip_hash=ip_hash_for(request, settings),
        meta={"account_id": str(account_id), "created": current.is_default, "changed_fields": changed},
    )
    await db.commit()
    # Eşik değişti: uyarılar yeniden değerlendirilir (en iyi çaba; kuyruk hatası yanıtı etkilemez).
    await request_alert_evaluation(request.app.state.job_queue, account_id)
    state = svc.SettingsState(new_values, written_at)
    response.headers["ETag"] = state.etag
    return _settings_out(state)


# --------------------------------------------------------------------------- kullanıcı tercihleri
async def _prefs_guard(ctx: AuthContext, limiter: RateLimiterDep, settings: SettingsDep, write: bool) -> None:
    who = digest(settings.master_key, "rl-user", str(ctx.user_id))
    if write:
        await limiter.hit(f"alert-prefs-write:user:{who}", _PREFS_WRITE_PER_HOUR, _HOURLY)
    else:
        await limiter.hit(f"alert-prefs-read:user:{who}", _PREFS_READ_PER_MINUTE, _MINUTE)


@me_router.get("/notification-preferences", response_model=NotificationPreferencesOut)
async def read_preferences(
    ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> NotificationPreferencesOut:
    """Oturumdaki kullanıcının kanal matrisi, sessiz saatleri, özet saati ve tutar tercihleri (eksikler varsayılan)."""
    await _prefs_guard(ctx, limiter, settings, write=False)
    values = await svc.load_preferences(db, ctx.tenant_id, ctx.user_id, ctx.role.value)
    return _preferences_out(values)


@me_router.put("/notification-preferences", response_model=NotificationPreferencesOut)
async def put_preferences(
    body: NotificationPreferencesIn,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> NotificationPreferencesOut:
    """Tercihleri tam değiştirir. Yalnız oturumdaki kullanıcının satırları yazılır (kimlik gövdeden alınmaz)."""
    await _prefs_guard(ctx, limiter, settings, write=True)
    matrix: dict[str, dict[str, str]] = {
        rule: {"email": modes.email, "push": modes.push} for rule, modes in body.matrix
    }
    values = svc.PreferencesValues(
        matrix=matrix,
        quiet_start=body.quiet_start,
        quiet_end=body.quiet_end,
        digest_hour=body.digest_hour,
        show_amounts_email=body.show_amounts_email,
        show_amounts_push=body.show_amounts_push,
    )
    try:
        await svc.save_preferences(db, ctx.tenant_id, ctx.user_id, values)
    except DBAPIError as exc:
        raise _preferences_rejection(exc) from None
    await db.commit()
    return _preferences_out(values)
