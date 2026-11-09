"""/v1/marketplace-accounts/{account_id}/profit-settings: kâr ayarları (ADR-0006 §3.3, docs/12 K33-K36).

Okuma owner, admin ve viewer; yazma yalnız owner ve admin (viewer 403). Hesap kiracıya ait değilse 404 (IDOR) ve
RLS. Her yazım aynı işlemde `profit_settings.revision`'ı artırır; isteğe bağlı `expected_revision` uyuşmazsa
409 `settings-revision-conflict` (iki yönetici aynı anda düzenlerse sessiz ezme yok). Her yazım `audit_log`'a
düşer; tutarlar denetim kaydına ve log'a YAZILMAZ (ticari bilgi). Doğrulama hataları girdi değerini yansıtmaz.

Sürümlü kayıtlarda (tarife, hizmet bedeli) PUT yalnız aynı anahtardaki (anlaşma, firma, başlangıç) kaydı
günceller; önceki sürümler korunur. DELETE yalnız istenen tek kaydı siler (yanlış girilmiş sürüm).
"""

from __future__ import annotations

from typing import Annotated
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
    CompletenessOut,
    DefaultsIn,
    DefaultsOut,
    DeleteOut,
    ExpenseWriteOut,
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

_HOURLY = 60 * 60
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
async def read_settings(account_id: UUID, ctx: AnyRoleDep, db: DbDep) -> SettingsOut:
    """Hesabın tüm kâr ayarları, sürüm ve tamlık bayrakları (tüm roller)."""
    await _require_account(db, ctx, account_id)
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
async def carriers(account_id: UUID, ctx: AnyRoleDep, db: DbDep) -> CarriersOut:
    """Son 92 günün siparişlerinde görülen firma x anlaşma çiftleri ve bugün geçerli tarifeyle kapsanma durumu."""
    await _require_account(db, ctx, account_id)
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
    """(anlaşma, firma, başlangıç) anahtarıyla tarife sürümü ekler ya da günceller; önceki sürümler korunur."""
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        _, revision = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, body.expected_revision)
        record, created = await ps.upsert_cargo_tariff(
            db,
            ctx.tenant_id,
            account_id,
            ctx.user_id,
            ps.TariffInput(
                body.agreement,
                body.carrier,
                body.valid_from,
                body.price_includes_vat,
                tuple((b.max_desi, b.price) for b in body.brackets),
            ),
        )
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    except ps.LimitError as exc:
        raise _limit_error(exc) from None
    await _audit(
        db,
        ctx,
        request,
        settings,
        "cargo_tariff.upsert",
        record.id,
        {
            "account_id": str(account_id),
            "revision": revision,
            "agreement": record.agreement,
            "carrier": record.carrier,
            "valid_from": record.valid_from.isoformat(),
        },
    )
    out = _tariff_out(record)
    await db.commit()
    return TariffWriteOut(revision=revision, created=created, tariff=out)


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
) -> DeleteOut:
    """Tek bir tarife sürümünü siler (yanlış girilmiş sürüm); diğer sürümler korunur."""
    return await _delete(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
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
    """Başlangıç tarihiyle platform hizmet bedeli tahmini ekler ya da günceller (0 geçerli bir tahmindir)."""
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        _, revision = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, body.expected_revision)
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    record, created = await ps.upsert_service_fee(
        db, ctx.tenant_id, account_id, ctx.user_id, body.valid_from, body.amount, body.amount_includes_vat
    )
    await _audit(
        db,
        ctx,
        request,
        settings,
        "service_fee_estimate.upsert",
        record.id,
        {"account_id": str(account_id), "revision": revision, "valid_from": record.valid_from.isoformat()},
    )
    out = _fee_out(record)
    await db.commit()
    return ServiceFeeWriteOut(revision=revision, created=created, estimate=out)


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
) -> DeleteOut:
    """Tek bir hizmet bedeli sürümünü siler."""
    return await _delete(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
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
    """Değişken gider tanımı ekler (hesap başına en çok 50)."""
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        _, revision = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, body.expected_revision)
        record = await ps.create_expense(db, ctx.tenant_id, account_id, ctx.user_id, _expense_input(body))
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    except ps.LimitError as exc:
        raise _limit_error(exc) from None
    await _audit(
        db,
        ctx,
        request,
        settings,
        "variable_expense.upsert",
        record.id,
        {"account_id": str(account_id), "revision": revision, "kind": record.kind},
    )
    out = _expense_out(record)
    await db.commit()
    return ExpenseWriteOut(revision=revision, expense=out)


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
    """Değişken gider tanımını günceller. Tutar değişikliği için eskinin bitişi + yeni tanım önerilir (K36)."""
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        _, revision = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, body.expected_revision)
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    record = await ps.update_expense(
        db, ctx.tenant_id, account_id, ctx.user_id, item_id, _expense_input(body)
    )
    if record is None:
        raise _not_found()  # işlem commit edilmez: sürüm artışı geri alınır
    await _audit(
        db,
        ctx,
        request,
        settings,
        "variable_expense.upsert",
        record.id,
        {"account_id": str(account_id), "revision": revision, "kind": record.kind},
    )
    out = _expense_out(record)
    await db.commit()
    return ExpenseWriteOut(revision=revision, expense=out)


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
) -> DeleteOut:
    """Tek bir değişken gider tanımını siler."""
    return await _delete(
        db,
        ctx,
        request,
        settings,
        limiter,
        account_id,
        item_id,
        expected_revision,
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
    """Hesabın varsayılan desisi (`null` = tanımsız). Siparişte desi yoksa tarife aramasında kullanılır (K34)."""
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        row, revision = await ps.begin_write(
            db, ctx.tenant_id, account_id, ctx.user_id, body.expected_revision
        )
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    row.default_desi = body.default_desi
    await db.flush()
    await _audit(
        db,
        ctx,
        request,
        settings,
        "defaults.upsert",
        row.id,
        {"account_id": str(account_id), "revision": revision},
    )
    await db.commit()
    return DefaultsOut(revision=revision, default_desi=body.default_desi)


async def _delete(
    db: AsyncSession,
    ctx: AuthContext,
    request: Request,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    account_id: UUID,
    item_id: UUID,
    expected_revision: int | None,
    model: type[CargoTariffRecord] | type[ServiceFeeEstimateRecord] | type[VariableExpenseRecord],
    item: str,
) -> DeleteOut:
    await _write_guard(db, ctx, account_id, limiter, settings)
    try:
        _, revision = await ps.begin_write(db, ctx.tenant_id, account_id, ctx.user_id, expected_revision)
    except ps.RevisionConflict as exc:
        raise _conflict(exc) from None
    if not await ps.delete_version(db, model, ctx.tenant_id, account_id, item_id):
        raise _not_found()  # işlem commit edilmez: sürüm artışı geri alınır
    await _audit(
        db,
        ctx,
        request,
        settings,
        f"{item}.delete",
        item_id,
        {"account_id": str(account_id), "revision": revision},
    )
    await db.commit()
    return DeleteOut(revision=revision)
