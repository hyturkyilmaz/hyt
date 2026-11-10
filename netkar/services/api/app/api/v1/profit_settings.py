"""/v1/marketplace-accounts/{account_id}/profit-settings: kâr ayarları (ADR-0006 §3.3, docs/12 K33-K36).

Okuma owner, admin ve viewer; yazma yalnız owner ve admin (viewer 403). Hesap kiracıya ait değilse 404 (IDOR) ve
RLS. Her yazım aynı işlemde `profit_settings.revision`'ı artırır; isteğe bağlı `expected_revision` uyuşmazsa
409 `settings-revision-conflict` (iki yönetici aynı anda düzenlerse sessiz ezme yok). Her yazım `audit_log`'a
düşer; tutarlar denetim kaydına ve log'a YAZILMAZ (ticari bilgi). Doğrulama hataları girdi değerini yansıtmaz.

ADR-0007 (K42-K44): ayar satırları DEĞİŞMEZDİR, hiçbir uç satır silmez ya da yerinde ezmez. PUT aynı anahtarlı
etkin satırı kapatıp yeni satır ekler (`action = replaced`), yoksa ekler (`created`), aynı içerikse hiçbir şey
yazmaz (`changed = false`); DELETE satırı geri çeker (`retracted`, satır tabloda kalır). Her yazım ayar günlüğüne
(`GET /history`) tek kayıt düşer. Geçmişi etkileyen yazım (etki tarihi bugünden önce ya da tarihsiz) açık onay
ister (`confirm_past_change`); onaysızsa 409 `settings-past-change-unconfirmed` ve hiçbir şey yazılmaz, yalnız
"eksik"i dolduran ilk giriş istisnadır. Kapanmış satıra yazım 409 `settings-record-ended`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, RateLimiterDep, SettingsDep, ip_hash_for, require_role
from app.api.v1.profit_settings_schemas import (
    BracketOut,
    CargoTariffIn,
    CargoTariffOut,
    CarrierOut,
    CarriersOut,
    ChangedByOut,
    CompletenessOut,
    DefaultsIn,
    DefaultsOut,
    DeleteOut,
    ExpenseWriteOut,
    HistoryItemOut,
    HistoryOut,
    ServiceFeeIn,
    ServiceFeeOut,
    ServiceFeeWriteOut,
    SettingsOut,
    TariffWriteOut,
    VariableExpenseIn,
    VariableExpenseOut,
)
from app.core.clock import today_istanbul
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.models import (
    CargoTariffRecord,
    Role,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
)
from app.profit.money import rnd
from app.profit.settings import ProfitSettings
from app.services import product_costs as costs
from app.services import profit_settings as ps
from app.services.audit import record_audit
from app.services.auth import AuthContext

router = APIRouter(prefix="/marketplace-accounts/{account_id}/profit-settings", tags=["profit-settings"])

AdminDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN))]
AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]
ExpectedRevisionQuery = Annotated[
    int | None, Query(ge=0, le=2**62, description="Beklenen ayar sürümü (409 için).")
]
ConfirmQuery = Annotated[
    bool, Query(description="Geçmiş raporların değişeceğini onaylar (K43); onaysız geçmiş etkili yazım 409.")
]
HistoryLimit = Annotated[int, Query(ge=1, le=100)]
HistoryCursor = Annotated[int | None, Query(ge=1, le=2**62, description="Önceki sayfanın `next_cursor`'ı.")]

_HOURLY = 60 * 60
_MINUTE = 60
_BASE = ProfitSettings()


def _not_found() -> ProblemError:
    return ProblemError(404, "Bulunamadı", "not-found")


def _limit_error(exc: ps.LimitError) -> ProblemError:
    """Hesap başına sayı sınırı (durum kontrolü): doğrulama hatasıyla aynı gövde biçimi, girdi yansıtılmaz."""
    return ProblemError(
        422,
        "Doğrulama hatası",
        "validation-error",
        exc.message,
        extra={"errors": [{"field": exc.field, "code": exc.code}]},
    )


def _past_unconfirmed(exc: ps.PastChangeUnconfirmed) -> ProblemError:
    """K43: geçmişi etkileyen yazım onaysız; hiçbir şey yazılmadı (sürüm, günlük ve denetim kaydı yok)."""
    return ProblemError(
        409,
        "Onay gerekli",
        "settings-past-change-unconfirmed",
        "Bu değişiklik geçmiş dönemlerin kâr hesabını değiştirir; onaylamak için confirm_past_change=true gönderin.",
        extra={
            "affects_from": None if exc.affects_from is None else exc.affects_from.isoformat(),
            "affects_past": True,
            "current_revision": exc.current_revision,
        },
    )


def _record_ended(exc: ps.RecordEnded) -> ProblemError:
    """Kapanmış satıra yazım: `current_id` yerini alan etkin satır (geri çekilmişse null)."""
    return ProblemError(
        409,
        "Çakışma",
        "settings-record-ended",
        "Bu kayıt başka bir değişiklikle güncellendi ya da geri çekildi; ayarları yenileyip tekrar deneyin.",
        extra={"current_id": None if exc.current_id is None else str(exc.current_id)},
    )


def _conflict(exc: ps.RevisionConflict) -> ProblemError:
    return ProblemError(
        409,
        "Çakışma",
        "settings-revision-conflict",
        "Ayarlar siz düzenlerken başka biri tarafından değiştirildi; sayfayı yenileyip tekrar deneyin.",
        extra={"current_revision": exc.current},
    )


async def _require_account(db: DbDep, ctx: AuthContext, account_id: UUID) -> None:
    """Hesap başka kiracıya aitse (veya yoksa) 404: varlığı sızdırılmaz (IDOR)."""
    if not await costs.account_exists(db, ctx.tenant_id, account_id):
        raise _not_found()


async def _read_guard(
    db: DbDep,
    ctx: AuthContext,
    account_id: UUID,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> None:
    """Hesap kontrolü (404, sayaca girmez), sonra kiracı başına dakikalık okuma sınırı (ayrı sayaç anahtarı)."""
    await _require_account(db, ctx, account_id)
    key = f"profit-settings-read:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}"
    await limiter.hit(key, settings.rate_limit_profit_settings_read_tenant, _MINUTE)


async def _write_guard(
    db: DbDep,
    ctx: AuthContext,
    account_id: UUID,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> None:
    """Hesap kontrolü (404), sonra kiracı başına saatlik yazma sınırı (ayrı sayaç havuzu, sayaç anahtarı)."""
    await _require_account(db, ctx, account_id)
    key = f"profit-settings-write:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}"
    await limiter.hit(key, settings.rate_limit_profit_settings_write_tenant, _HOURLY)


# --------------------------------------------------------------------------- çıktı kurucuları
def _tariff_out(record: CargoTariffRecord) -> CargoTariffOut:
    return CargoTariffOut(
        id=str(record.id),
        agreement=record.agreement,
        carrier=record.carrier,
        valid_from=record.valid_from,
        price_includes_vat=record.price_includes_vat,
        brackets=[
            BracketOut(
                max_desi=desi,
                price=price,
                price_excl_vat=ps.to_excl_vat(price, record.price_includes_vat, _BASE.shipping_vat_rate),
            )
            for desi, price in ps.bracket_pairs(record)
        ],
    )


def _fee_out(record: ServiceFeeEstimateRecord) -> ServiceFeeOut:
    return ServiceFeeOut(
        id=str(record.id),
        valid_from=record.valid_from,
        amount=rnd(record.amount),
        amount_includes_vat=record.amount_includes_vat,
        amount_excl_vat=ps.to_excl_vat(record.amount, record.amount_includes_vat, _BASE.service_fee_vat_rate),
    )


def _expense_out(record: VariableExpenseRecord) -> VariableExpenseOut:
    return VariableExpenseOut(
        id=str(record.id),
        name=record.name,
        kind=record.kind,
        amount_excl_vat=None if record.amount_excl_vat is None else rnd(record.amount_excl_vat),
        percent=None if record.percent is None else format(record.percent.normalize(), "f"),
        vat_rate=int(record.vat_rate),
        valid_from=record.valid_from,
        valid_to=record.valid_to,
    )


def _completeness_out(value: ps.Completeness) -> CompletenessOut:
    return CompletenessOut(
        cargo_tariff_defined=value.cargo_tariff_defined,
        seller_cargo_tariff_defined=value.seller_cargo_tariff_defined,
        service_fee_estimate_defined=value.service_fee_estimate_defined,
        variable_expenses_defined=value.variable_expenses_defined,
        default_desi_defined=value.default_desi_defined,
    )


async def _audit(
    db: AsyncSession,
    ctx: AuthContext,
    request: Request,
    settings: SettingsDep,
    action: str,
    target: UUID,
    meta: dict[str, object],
) -> None:
    """Denetim izi: tutarlar YAZILMAZ; yalnız kayıt kimliği, sürüm ve tarih/tip gibi tanımlayıcılar."""
    await record_audit(
        db,
        ctx.tenant_id,
        f"profit_settings.{action}",
        user_id=ctx.user_id,
        target=str(target),
        ip_hash=ip_hash_for(request, settings),
        meta=meta,
    )


# --------------------------------------------------------------------------- okuma
@router.get("", response_model=SettingsOut)
async def read_settings(
    account_id: UUID, ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> SettingsOut:
    """Hesabın tüm kâr ayarları, sürüm ve tamlık bayrakları (tüm roller; kiracı başına dakikalık sınır)."""
    await _read_guard(db, ctx, account_id, limiter, settings)
    bundle = await ps.load_bundle(db, ctx.tenant_id, account_id)
    return SettingsOut(
        revision=bundle.revision,
        default_desi=bundle.default_desi,
        cargo_tariffs=[_tariff_out(t) for t in bundle.tariffs],
        service_fee_estimates=[_fee_out(f) for f in bundle.fees],
        variable_expenses=[_expense_out(e) for e in bundle.expenses],
        completeness=_completeness_out(ps.completeness_of(bundle, today_istanbul())),
    )


@router.get("/carriers", response_model=CarriersOut)
async def carriers(
    account_id: UUID, ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> CarriersOut:
    """Son 92 günün siparişlerinde görülen firma x anlaşma çiftleri ve bugün geçerli tarifeyle kapsanma durumu.

    Okuma sınırı `read_settings` ile aynı kiracı sayacını paylaşır (her istek 92 günlük birleştirme sorgusudur).
    """
    await _read_guard(db, ctx, account_id, limiter, settings)
    today = today_istanbul()
    bundle = await ps.load_bundle(db, ctx.tenant_id, account_id)
    usage = await ps.carrier_usage(db, ctx.tenant_id, account_id, today, bundle)
    return CarriersOut(
        lookback_days=ps.CARRIER_LOOKBACK_DAYS,
        items=[
            CarrierOut(
                carrier=u.carrier,
                agreement=u.agreement,
                line_count=u.line_count,
                covered=u.covered,
            )
            for u in usage
        ],
    )


# --------------------------------------------------------------------------- yazım ortak akışı
def _info(outcome: ps.WriteOutcome) -> dict[str, object]:
    """Yazım yanıtlarının ortak alanları (`WriteInfo`)."""
    return {
        "revision": outcome.revision,
        "changed": outcome.changed,
        "action": outcome.action,
        "replaced_id": None if outcome.replaced_id is None else str(outcome.replaced_id),
        "affects_from": outcome.affects_from,
        "affects_past": outcome.affects_past,
    }


_AUDIT_VERB = {"created": "create", "replaced": "replace", "retracted": "retract"}


def _identity(item: str, record: Any) -> dict[str, object]:
    """Denetim meta'sına giren kalem kimlikleri (anlaşma, firma, başlangıç ya da ad, tip, tarihler): TUTAR YOK."""
    if item == "cargo_tariff":
        return {
            "agreement": record.agreement,
            "carrier": record.carrier,
            "valid_from": record.valid_from.isoformat(),
        }
    if item == "service_fee_estimate":
        return {"valid_from": record.valid_from.isoformat()}
    return {
        "name": record.name,
        "kind": record.kind,
        "valid_from": record.valid_from.isoformat(),
        "valid_to": None if record.valid_to is None else record.valid_to.isoformat(),
    }


async def _write[T](
    db: AsyncSession,
    ctx: AuthContext,
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    account_id: UUID,
    expected_revision: int | None,
    item: str,
    operation: Callable[[ps.WriteTicket], Awaitable[ps.WriteOutcome | None]],
    build: Callable[[ps.WriteOutcome], T],
) -> T:
    """Ortak yazım akışı (ADR-0007 §5.1 kontrol sırası): rol ve hesap -> hız sınırı -> kilit ve beklenen sürüm
    -> işlem türü ve etki tarihi -> onay -> yazım -> günlük -> denetim -> commit.

    Değişiklik yoksa (aynı içerik) hiçbir şey yazılmaz: işlem geri alınır, sürüm, günlük ve denetim kaydı olmaz.
    Hata durumlarında commit edilmez (sürüm artışı ve hesap satırı oluşturma geri alınır).
    """
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        ticket = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, expected_revision)
        outcome = await operation(ticket)
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    except ps.LimitError as exc:
        raise _limit_error(exc) from None
    except ps.PastChangeUnconfirmed as exc:
        raise _past_unconfirmed(exc) from None
    except ps.RecordEnded as exc:
        raise _record_ended(exc) from None
    if outcome is None:
        raise _not_found()
    out = build(outcome)  # commit ya da geri alma öncesi: sonrasında nesne öznitelikleri süresi dolmuş olur
    if not outcome.changed:
        await db.rollback()
        return out
    meta: dict[str, object] = {
        "account_id": str(account_id),
        "revision": outcome.revision,
        "record_id": None if outcome.record is None else str(outcome.record.id),
        "replaced_id": None if outcome.replaced_id is None else str(outcome.replaced_id),
        "affects_from": None if outcome.affects_from is None else outcome.affects_from.isoformat(),
        "affects_past": outcome.affects_past,
        "past_change_confirmed": outcome.past_change_confirmed,
    }
    if outcome.record is not None:
        meta.update(_identity(item, outcome.record))
    action = "defaults.update" if item == "defaults" else f"{item}.{_AUDIT_VERB[outcome.action]}"
    target = outcome.record.id if outcome.record is not None else ticket.row.id  # desi: hesap ayar satırı
    await _audit(db, ctx, request, settings, action, target, meta)
    await db.commit()
    return out


# --------------------------------------------------------------------------- yazma
@router.put("/cargo-tariffs", response_model=TariffWriteOut)
async def put_cargo_tariff(
    account_id: UUID,
    body: CargoTariffIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> TariffWriteOut:
    """(anlaşma, firma, başlangıç) anahtarıyla tarife ekler, değiştirir (eski sürüm kapanır) ya da aynıysa değişmez."""
    data = ps.TariffInput(
        body.agreement,
        body.carrier,
        body.valid_from,
        body.price_includes_vat,
        tuple((b.max_desi, b.price) for b in body.brackets),
    )
    today = today_istanbul()

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome:
        return await ps.write_cargo_tariff(
            db, ctx.tenant_id, account_id, ctx.user_id, ticket, data, today, body.confirm_past_change
        )

    def build(outcome: ps.WriteOutcome) -> TariffWriteOut:
        return TariffWriteOut(
            **_info(outcome), created=outcome.action == "created", tariff=_tariff_out(outcome.record)
        )

    return await _write(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        body.expected_revision,
        "cargo_tariff",
        operation,
        build,
    )


@router.delete("/cargo-tariffs/{item_id}", response_model=DeleteOut)
async def delete_cargo_tariff(
    account_id: UUID,
    item_id: UUID,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    expected_revision: ExpectedRevisionQuery = None,
    confirm_past_change: ConfirmQuery = False,
) -> DeleteOut:
    """Tarife sürümünü geri çeker (satır silinmez, `geri_cekildi` ile kapanır); diğer sürümler korunur."""
    return await _retract(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
        confirm_past_change,
        CargoTariffRecord,
        "cargo_tariff",
    )


@router.put("/service-fee-estimates", response_model=ServiceFeeWriteOut)
async def put_service_fee(
    account_id: UUID,
    body: ServiceFeeIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> ServiceFeeWriteOut:
    """Başlangıç tarihiyle hizmet bedeli tahmini ekler, değiştirir ya da aynıysa değişmez (0 geçerli bir tahmindir)."""
    today = today_istanbul()

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome:
        return await ps.write_service_fee(
            db,
            ctx.tenant_id,
            account_id,
            ctx.user_id,
            ticket,
            body.valid_from,
            body.amount,
            body.amount_includes_vat,
            today,
            body.confirm_past_change,
        )

    def build(outcome: ps.WriteOutcome) -> ServiceFeeWriteOut:
        return ServiceFeeWriteOut(
            **_info(outcome), created=outcome.action == "created", estimate=_fee_out(outcome.record)
        )

    return await _write(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        body.expected_revision,
        "service_fee_estimate",
        operation,
        build,
    )


@router.delete("/service-fee-estimates/{item_id}", response_model=DeleteOut)
async def delete_service_fee(
    account_id: UUID,
    item_id: UUID,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    expected_revision: ExpectedRevisionQuery = None,
    confirm_past_change: ConfirmQuery = False,
) -> DeleteOut:
    """Hizmet bedeli sürümünü geri çeker."""
    return await _retract(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
        confirm_past_change,
        ServiceFeeEstimateRecord,
        "service_fee_estimate",
    )


def _expense_input(body: VariableExpenseIn) -> ps.ExpenseInput:
    return ps.ExpenseInput(
        body.name,
        body.kind,
        body.amount_excl_vat,
        body.percent,
        body.vat_rate,
        body.valid_from,
        body.valid_to,
    )


@router.post("/variable-expenses", response_model=ExpenseWriteOut, status_code=201)
async def create_variable_expense(
    account_id: UUID,
    body: VariableExpenseIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> ExpenseWriteOut:
    """Değişken gider tanımı ekler (hesap başına etkin en çok 50). İlk giriş istisnası yoktur (K43)."""
    today = today_istanbul()

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome:
        return await ps.create_expense(
            db,
            ctx.tenant_id,
            account_id,
            ctx.user_id,
            ticket,
            _expense_input(body),
            today,
            body.confirm_past_change,
        )

    def build(outcome: ps.WriteOutcome) -> ExpenseWriteOut:
        return ExpenseWriteOut(**_info(outcome), expense=_expense_out(outcome.record))

    return await _write(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        body.expected_revision,
        "variable_expense",
        operation,
        build,
    )


@router.put("/variable-expenses/{item_id}", response_model=ExpenseWriteOut)
async def update_variable_expense(
    account_id: UUID,
    item_id: UUID,
    body: VariableExpenseIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> ExpenseWriteOut:
    """Değişken gider tanımını değiştirir: eski satır kapanır, YENİ kimlikle yeni satır eklenir (`replaces_id`)."""
    today = today_istanbul()

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome | None:
        return await ps.replace_expense(
            db,
            ctx.tenant_id,
            account_id,
            ctx.user_id,
            ticket,
            item_id,
            _expense_input(body),
            today,
            body.confirm_past_change,
        )

    def build(outcome: ps.WriteOutcome) -> ExpenseWriteOut:
        return ExpenseWriteOut(**_info(outcome), expense=_expense_out(outcome.record))

    return await _write(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        body.expected_revision,
        "variable_expense",
        operation,
        build,
    )


@router.delete("/variable-expenses/{item_id}", response_model=DeleteOut)
async def delete_variable_expense(
    account_id: UUID,
    item_id: UUID,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    expected_revision: ExpectedRevisionQuery = None,
    confirm_past_change: ConfirmQuery = False,
) -> DeleteOut:
    """Değişken gider tanımını geri çeker."""
    return await _retract(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
        confirm_past_change,
        VariableExpenseRecord,
        "variable_expense",
    )


@router.put("/defaults", response_model=DefaultsOut)
async def put_defaults(
    account_id: UUID,
    body: DefaultsIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> DefaultsOut:
    """Hesabın varsayılan desisi (`null` = tanımsız). Siparişte desi yoksa tarife aramasında kullanılır (K34).

    Tarihsizdir ("tüm dönemler"): `null`'dan değere ilk giriş dışında her değişiklik onay ister (K43). Yerinde
    güncellenir; önceki ve yeni değer ayar günlüğündedir.
    """

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome:
        return await ps.write_default_desi(
            db, ctx.tenant_id, account_id, ctx.user_id, ticket, body.default_desi, body.confirm_past_change
        )

    def build(outcome: ps.WriteOutcome) -> DefaultsOut:
        return DefaultsOut(**_info(outcome), default_desi=body.default_desi)

    return await _write(
        db, ctx, request, settings, limiter, account_id, body.expected_revision, "defaults", operation, build
    )


async def _retract(
    db: AsyncSession,
    ctx: AuthContext,
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    account_id: UUID,
    item_id: UUID,
    expected_revision: int | None,
    confirm: bool,
    model: type[CargoTariffRecord] | type[ServiceFeeEstimateRecord] | type[VariableExpenseRecord],
    item: str,
) -> DeleteOut:
    today = today_istanbul()

    async def operation(ticket: ps.WriteTicket) -> ps.WriteOutcome | None:
        return await ps.retract_record(
            db, model, item, ctx.tenant_id, account_id, ctx.user_id, ticket, item_id, today, confirm
        )

    def build(outcome: ps.WriteOutcome) -> DeleteOut:
        return DeleteOut(**_info(outcome))

    return await _write(
        db, ctx, request, settings, limiter, account_id, expected_revision, item, operation, build
    )


# --------------------------------------------------------------------------- ayar geçmişi
def _history_record(item: str, record: Any) -> CargoTariffOut | ServiceFeeOut | VariableExpenseOut | None:
    if record is None:
        return None
    if item == "cargo_tariff":
        return _tariff_out(record)
    if item == "service_fee_estimate":
        return _fee_out(record)
    return _expense_out(record)


@router.get("/history", response_model=HistoryOut)
async def read_history(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    limit: HistoryLimit = 50,
    cursor: HistoryCursor = None,
) -> HistoryOut:
    """Ayar günlüğü (ayar geçmişi), yeniden eskiye, imleçli. Her kayıt satırın tam içeriğini taşır; fark panelde
    `record` ile `replaced_record` karşılaştırılarak hesaplanır. Okuma sınırı diğer okumalarla aynı sayaçtadır."""
    await _read_guard(db, ctx, account_id, limiter, settings)
    page = await ps.read_history(db, ctx.tenant_id, account_id, cursor, limit)
    return HistoryOut(
        items=[
            HistoryItemOut(
                revision=int(e.change.revision),
                changed_at=e.change.changed_at,
                changed_by=None
                if e.change.changed_by is None
                else ChangedByOut(user_id=str(e.change.changed_by), role=e.role),
                item=e.change.item,
                action=e.change.action,
                affects_from=e.change.affects_from,
                affects_past=e.change.affects_past,
                past_change_confirmed=e.change.past_change_confirmed,
                record=_history_record(e.change.item, e.record),
                replaced_record=_history_record(e.change.item, e.replaced_record),
                default_desi_before=e.change.default_desi_before,
                default_desi_after=e.change.default_desi_after,
            )
            for e in page.entries
        ],
        next_cursor=None if page.next_cursor is None else str(page.next_cursor),
    )
