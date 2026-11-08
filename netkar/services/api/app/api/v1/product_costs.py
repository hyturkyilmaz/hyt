"""/v1/marketplace-accounts/{account_id}: ürün birim maliyeti girişi ve toplu içe aktarma (CSV, XLSX).

Her uç nokta kiracı kontrolü (hesap kiracıya ait değilse 404) ve RLS ile çalışır. Yazma yalnız owner/admin,
okuma tüm rollerdir. Maliyet satırı SİLİNMEZ: değişiklik aynı (barkod, geçerlilik tarihi) üzerine upsert'tir
ve eski değer denetim kaydına yazılmaz (yalnız barkod ve tarih). Motor sipariş gününde geçerli en son
maliyeti kullanır (`app.profit.costs.apply_product_cost`); bu uçlar aynı tarih kuralını izler.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.deps import DbDep, ImportGateDep, RateLimiterDep, SettingsDep, ip_hash_for, require_role
from app.api.v1.product_cost_schemas import (
    CostHistoryOut,
    CostOut,
    CostUpsertIn,
    CostUpsertOut,
    ImportIssueOut,
    ImportReportOut,
    ProductItemOut,
    ProductListOut,
)
from app.core.clock import today_istanbul
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.db.rls import set_rls_context
from app.models import Role
from app.services import product_costs as costs
from app.services.audit import record_audit
from app.services.auth import AuthContext
from app.services.cost_import import (
    ImportFileError,
    ImportLimits,
    ImportParse,
    build_template_csv,
    parse_import,
)

router = APIRouter(prefix="/marketplace-accounts/{account_id}", tags=["product-costs"])

# Gövde sınırı ara katmanı için: yalnız bu yol 2 MiB dosya kabul eder (BodyLimitMiddleware pattern_limits).
# Hesap kimliği gerçek UUID biçiminde (8-4-4-4-12 onaltılık) olmalı; başka biçim 8 KiB sınırına düşer.
COST_IMPORT_PATH_PATTERN = (
    r"/v1/marketplace-accounts/"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"
    r"/product-costs/import"
)
TEMPLATE_MAX_ROWS = 10_000  # içe aktarma satır sınırıyla aynı: daha büyük şablon yüklenemezdi

AdminDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN))]
AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]
BarcodePath = Annotated[str, Path(min_length=1, max_length=200, pattern=f"^{costs.BARCODE_PATTERN}$")]

_HOURLY = 60 * 60


def _not_found() -> ProblemError:
    return ProblemError(404, "Bulunamadı", "not-found")


async def _require_account(db: DbDep, ctx: AuthContext, account_id: UUID) -> None:
    """Hesap başka kiracıya aitse (veya yoksa) 404: varlığı sızdırılmaz (IDOR)."""
    if not await costs.account_exists(db, ctx.tenant_id, account_id):
        raise _not_found()


def _out(view: costs.CostView) -> CostOut:
    return CostOut(
        valid_from=view.valid_from, unit_cost_excl_vat=view.unit_cost_excl_vat, vat_rate=int(view.vat_rate)
    )


async def _limit(limiter: RateLimiterDep, settings: SettingsDep, name: str, tenant: UUID, limit: int) -> None:
    await limiter.hit(
        f"{name}:tenant:{digest(settings.master_key, 'rl-tenant', str(tenant))}", limit, _HOURLY
    )


@router.get("/products", response_model=ProductListOut)
async def list_products(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    after: Annotated[str | None, Query(max_length=200)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
) -> ProductListOut:
    """Hesabın ürünleri (barkoda göre) ve bugün geçerli maliyet; `after` önceki sayfanın `next_cursor`'ıdır."""
    await _require_account(db, ctx, account_id)
    items, next_cursor = await costs.list_products(
        db, ctx.tenant_id, account_id, today_istanbul(), search=q, after=after, limit=limit
    )
    return ProductListOut(
        items=[
            ProductItemOut(
                barcode=item.barcode,
                title=item.title,
                stock_code=item.stock_code,
                current_cost=None if item.current_cost is None else _out(item.current_cost),
                cost_missing=item.current_cost is None,
            )
            for item in items
        ],
        next_cursor=next_cursor,
    )


@router.get("/products/{barcode}/costs", response_model=CostHistoryOut)
async def cost_history(account_id: UUID, barcode: BarcodePath, ctx: AnyRoleDep, db: DbDep) -> CostHistoryOut:
    """Maliyet geçmişi (geçerlilik tarihi azalan). Ürün de maliyet kaydı da yoksa 404."""
    await _require_account(db, ctx, account_id)
    history = await costs.cost_history(db, ctx.tenant_id, account_id, barcode)
    known = await costs.product_known(db, ctx.tenant_id, account_id, barcode)
    if not history and not known:
        raise _not_found()
    return CostHistoryOut(barcode=barcode, product_known=known, items=[_out(view) for view in history])


@router.put("/products/{barcode}/costs", response_model=CostUpsertOut)
async def upsert_cost(
    account_id: UUID,
    barcode: BarcodePath,
    body: CostUpsertIn,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> CostUpsertOut:
    """Maliyet ekler veya aynı geçerlilik tarihli kaydı günceller. Barkod henüz senkronlanmamış olabilir."""
    await _require_account(db, ctx, account_id)
    await _limit(limiter, settings, "cost-write", ctx.tenant_id, settings.rate_limit_cost_write_tenant)
    row = costs.CostRow(barcode, body.valid_from, body.unit_cost_excl_vat, body.vat_rate)
    created, _updated = await costs.upsert_costs(db, ctx.tenant_id, account_id, ctx.user_id, [row])
    known = await costs.product_known(db, ctx.tenant_id, account_id, barcode)
    # Denetim kaydına eski/yeni tutar YAZILMAZ: yalnız barkod ve geçerlilik tarihi.
    await record_audit(
        db,
        ctx.tenant_id,
        "product_cost.upserted",
        user_id=ctx.user_id,
        target=str(account_id),
        ip_hash=ip_hash_for(request, settings),
        meta={"barcode": barcode, "valid_from": body.valid_from.isoformat()},
    )
    await db.commit()
    return CostUpsertOut(
        barcode=barcode,
        product_known=known,
        created=created == 1,
        cost=_out(costs.CostView(row.valid_from, row.unit_cost_excl_vat, row.vat_rate)),
    )


def _report(
    parsed: ImportParse,
    *,
    dry_run: bool,
    committed: bool,
    unknown: int,
    created: int | None,
    updated: int | None,
) -> ImportReportOut:
    return ImportReportOut(
        dry_run=dry_run,
        committed=committed,
        format=parsed.file_format,
        total=parsed.total,
        valid=parsed.valid,
        invalid=parsed.invalid,
        skipped=parsed.skipped,
        unknown_barcodes=unknown,
        created=created,
        updated=updated,
        errors=[
            ImportIssueOut(row=i.row, column=i.column, message=i.message, value=i.value)
            for i in parsed.issues
        ],
        errors_truncated=parsed.errors_truncated,
        ignored_columns=parsed.ignored_columns,
    )


_IMPORT_OPENAPI = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {"file": {"type": "string", "format": "binary"}},
                }
            }
        },
    }
}


async def _read_upload(request: Request, settings: Settings) -> tuple[str | None, bytes]:
    """Multipart gövdesinden `file` parçasını okur. Çağrıldığında kimlik ve rol zaten doğrulanmıştır.

    Dosya parametresi imzada DEĞİL burada okunur: FastAPI imzadaki `UploadFile`'ı bağımlılıklardan
    (oturum, rol) ÖNCE ayrıştırırdı ve kimliksiz istekler için de 2 MiB'lik multipart çözülürdü (D-01).
    """
    limit = settings.max_cost_import_file_bytes
    async with request.form(max_files=1, max_fields=8, max_part_size=64 * 1024) as form:
        part = form.get("file")
        if not isinstance(part, UploadFile):
            raise ProblemError(
                422,
                "Doğrulama hatası",
                "validation-error",
                "İstek gövdesi geçersiz.",
                extra={"errors": [{"field": "file", "code": "missing"}]},
            )
        data = await part.read(limit + 1)
        filename = part.filename
    if len(data) > limit:
        raise ProblemError(
            413,
            "İstek gövdesi çok büyük",
            "payload-too-large",
            f"Dosya en fazla {limit // (1024 * 1024)} MB olabilir.",
        )
    return filename, data


@router.post("/product-costs/import", response_model=ImportReportOut, openapi_extra=_IMPORT_OPENAPI)
async def import_costs(
    account_id: UUID,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    gate: ImportGateDep,
    dry_run: bool = True,
    allow_partial: bool = False,
) -> ImportReportOut:
    """CSV/XLSX maliyet dosyası (multipart, alan adı `file`). `dry_run=true` (varsayılan) yalnız doğrulama
    raporu verir, hiçbir şey yazmaz.

    `dry_run=false`: geçerli satırlar TEK işlemde upsert edilir; hatalı satır varsa ve `allow_partial=false`
    ise hiçbir şey yazılmaz (422 ve rapor).

    Sıra: kimlik ve rol, hesap, hız sınırı, kiracı kilidi, dosyayı oku ve ayrıştır (veritabanı bağlantısı
    TUTULMAZ), RLS bağlamını yeniden kur, yaz. Kiracı başına tek içe aktarma ve süreç başına sınırlı
    ayrıştırma vardır; doluysa beklemeden 429/503 ve Retry-After döner.
    """
    await _require_account(db, ctx, account_id)
    # Her deneme (kuru deneme dahil) sayılır: ayrıştırma CPU işidir.
    await _limit(limiter, settings, "cost-import", ctx.tenant_id, settings.rate_limit_cost_import_tenant)
    with gate.tenant(ctx.tenant_id):
        # Dosya okuma ve ayrıştırma sırasında veritabanı bağlantısını/işlemini tutmayız (O-01); bağlam sonra kurulur.
        await db.rollback()
        filename, data = await _read_upload(request, settings)
        try:
            # Zip denetimi ve ayrıştırma CPU işidir: olay döngüsünü bloklamamak için iş parçacığı havuzunda.
            async with gate.parse_slot():
                parsed = await run_in_threadpool(
                    parse_import, filename, data, today_istanbul(), ImportLimits.from_settings(settings)
                )
        except ImportFileError as exc:
            raise ProblemError(exc.status, exc.title, exc.slug, exc.detail) from None
        await set_rls_context(db, ctx.tenant_id, ctx.user_id)
        return await _store_import(
            request, db, settings, ctx, account_id, parsed, dry_run=dry_run, allow_partial=allow_partial
        )


async def _store_import(
    request: Request,
    db: DbDep,
    settings: Settings,
    ctx: AuthContext,
    account_id: UUID,
    parsed: ImportParse,
    *,
    dry_run: bool,
    allow_partial: bool,
) -> ImportReportOut:
    """Ayrıştırma sonrası veritabanı aşaması: bilinmeyen barkodlar, upsert ve denetim kaydı."""
    barcodes = {row.barcode for row in parsed.rows}
    unknown = len(barcodes - await costs.known_barcodes(db, ctx.tenant_id, account_id, sorted(barcodes)))
    if dry_run:
        return _report(parsed, dry_run=True, committed=False, unknown=unknown, created=None, updated=None)
    if parsed.invalid and not allow_partial:
        report = _report(parsed, dry_run=False, committed=False, unknown=unknown, created=None, updated=None)
        raise ProblemError(
            422,
            "İçe aktarma doğrulanamadı",
            "import-validation-failed",
            "Hatalı satırlar var; hiçbir şey kaydedilmedi. Düzeltin veya allow_partial=true ile yalnız geçerli satırları kaydedin.",
            extra={"report": report.model_dump(mode="json")},
        )
    created, updated = await costs.upsert_costs(db, ctx.tenant_id, account_id, ctx.user_id, parsed.rows)
    await record_audit(
        db,
        ctx.tenant_id,
        "product_cost.imported",
        user_id=ctx.user_id,
        target=str(account_id),
        ip_hash=ip_hash_for(request, settings),
        meta={
            "format": parsed.file_format,
            "total": parsed.total,
            "valid": parsed.valid,
            "invalid": parsed.invalid,
            "skipped": parsed.skipped,
            "created": created,
            "updated": updated,
            "partial": bool(parsed.invalid),
        },
    )
    await db.commit()
    return _report(parsed, dry_run=False, committed=True, unknown=unknown, created=created, updated=updated)


@router.get("/product-costs/template.csv")
async def template_csv(
    account_id: UUID, ctx: AnyRoleDep, db: DbDep, settings: SettingsDep, limiter: RateLimiterDep
) -> Response:
    """Şablon: hesabın ürünleriyle (barkod, başlık) dolu, maliyet sütunları boş. Hücrelerde formül kaçışı vardır."""
    await _require_account(db, ctx, account_id)
    await _limit(limiter, settings, "cost-template", ctx.tenant_id, settings.rate_limit_cost_template_tenant)
    products, truncated = await costs.template_products(db, ctx.tenant_id, account_id, TEMPLATE_MAX_ROWS)
    headers = {"Content-Disposition": 'attachment; filename="maliyet_sablonu.csv"'}
    if truncated:
        headers["X-Template-Truncated"] = "true"
    # Şablon üretimi (ürün sayısı büyük olabilir) CPU işidir: olay döngüsünü bloklamamak için iş parçacığı havuzunda (YK-03).
    content = await run_in_threadpool(build_template_csv, products)
    return Response(content, media_type="text/csv; charset=utf-8", headers=headers)
