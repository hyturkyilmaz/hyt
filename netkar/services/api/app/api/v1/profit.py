"""/v1/marketplace-accounts/{account_id}/profit: kâr raporu uçları (panel S4). Salt okuma, tüm roller.

Her uç nokta: kimlik ve rol, hesap kiracıya ait değilse 404 (IDOR) ve RLS, girdi doğrulama (RFC 9457),
kiracı başına dakikada sınırlı istek. Bir istek kâr motorunu dönem için EN FAZLA BİR KEZ çalıştırır
(`app.services.profit_report`); ortak giderler (kargo, hizmet bedeli, reklam) dönemin TÜM satırlarına
dağıtıldığı için ürün, sipariş ve uyarı görünümleri dönem sonucundan seçilir. Denetim izi gerekmez (okuma).

Dönem: `start`+`end` (YYYY-AA-GG, İstanbul günü, uçlar dahil) ya da `range=today|7d|30d` (bugün dahil);
hiçbiri verilmezse `30d`. En fazla 92 gün. Kâr ayarları (kargo tarifesi, hizmet bedeli) henüz kiracı tablosunda
değildir: motorun varsayılanları kullanılır (tarifesiz satır `KARGO_TARIFESI_EKSIK` uyarısı alır).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import DbDep, RateLimiterDep, SettingsDep
from app.api.v1.product_costs import AnyRoleDep, BarcodePath
from app.api.v1.profit_schemas import (
    AlertCountOut,
    AlertOut,
    AlertsOut,
    ComparisonSummaryOut,
    FeedNotesOut,
    LineOut,
    OrderDetailOut,
    OrderTotalsOut,
    PeriodOut,
    PeriodTotalsOut,
    ProductProfitDetailOut,
    ProductProfitItemOut,
    ProductProfitListOut,
    ProductTotalsOut,
    StatusCountsOut,
    SummaryOut,
    UnavailableAlertOut,
)
from app.core.clock import today_istanbul
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.profit import ProfitInputError, ProfitSettings
from app.profit.enums import WarningCode
from app.services import product_costs as costs
from app.services import profit_views as views
from app.services.auth import AuthContext
from app.services.profit_report import PeriodReport, period_profit

router = APIRouter(prefix="/marketplace-accounts/{account_id}/profit", tags=["profit"])
log = logging.getLogger(__name__)

_MINUTE = 60
_DATE_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
OrderNumberPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


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


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date

    def out(self) -> PeriodOut:
        return PeriodOut(start=self.start, end=self.end, days=(self.end - self.start).days + 1)


StartQuery = Annotated[
    str | None,
    Query(pattern=_DATE_PATTERN, max_length=10, description="Dönem başı, YYYY-AA-GG (İstanbul günü)."),
]
EndQuery = Annotated[
    str | None,
    Query(pattern=_DATE_PATTERN, max_length=10, description="Dönem sonu (dahil), YYYY-AA-GG."),
]
RangeQuery = Annotated[
    Literal["today", "7d", "30d"] | None,
    Query(alias="range", description="Hazır aralık (İstanbul günü, bugün dahil); start/end yerine."),
]


def _period(start: str | None, end: str | None, range_name: str | None, default: str | None) -> Period | None:
    try:
        resolved = views.resolve_period(start, end, range_name, today_istanbul(), default)
    except views.PeriodError as exc:
        raise _invalid(exc.field, exc.code, exc.message) from None
    return None if resolved is None else Period(*resolved)


def period_dep(start: StartQuery = None, end: EndQuery = None, range_: RangeQuery = None) -> Period:
    """Dönem zorunlu; verilmezse son 30 gün."""
    period = _period(start, end, range_, views.DEFAULT_RANGE)
    assert period is not None  # varsayılan aralık varken None dönmez
    return period


def optional_period_dep(
    start: StartQuery = None, end: EndQuery = None, range_: RangeQuery = None
) -> Period | None:
    """Sipariş ucu için: dönem verilmediyse None (siparişin kendi günleri kullanılır)."""
    return _period(start, end, range_, None)


PeriodDep = Annotated[Period, Depends(period_dep)]
OptionalPeriodDep = Annotated[Period | None, Depends(optional_period_dep)]


async def _guard(
    db: DbDep, ctx: AuthContext, account_id: UUID, limiter: RateLimiterDep, settings: SettingsDep
) -> None:
    """Hesap başka kiracıya aitse (veya yoksa) 404, sonra kiracı başına dakikalık rapor sınırı."""
    if not await costs.account_exists(db, ctx.tenant_id, account_id):
        raise _not_found()
    key = f"profit-report:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}"
    await limiter.hit(key, settings.rate_limit_profit_report_tenant, _MINUTE)


def profit_settings_for(tenant_id: UUID, account_id: UUID) -> ProfitSettings:
    """Hesabın kâr ayarları. Kiracı ayar tablosu henüz yok (ADR-0005 §10): motorun varsayılanları.

    Ayar tablosu gelince tek değişiklik noktası burasıdır (tarife, hizmet bedeli, değişken giderler).
    """
    return ProfitSettings()


async def _report(db: DbDep, ctx: AuthContext, account_id: UUID, period: Period) -> PeriodReport:
    """Motoru dönem için bir kez çalıştırır. Girdi tutarsızlığı iç ayrıntı sızdırmadan 500 olur."""
    try:
        settings = profit_settings_for(ctx.tenant_id, account_id)
        return await period_profit(db, ctx.tenant_id, account_id, period.start, period.end, settings)
    except ProfitInputError as exc:
        # Ayrıntı (sipariş no, tutar) log'a yazılmaz: yalnız hesap kimliği ve hata sınıfı.
        log.error("profit_calculation_failed account=%s error=%s", account_id, type(exc).__name__)
        raise ProblemError(
            500, "Rapor hesaplanamadı", "profit-calculation-failed", "Kayıtlar tutarsız; rapor üretilemedi."
        ) from None


def _check_cursor(cursor: str | None, fingerprint: str, size: int) -> None:
    """İmleç motor çalışmadan doğrulanır: bozuk ya da yabancı imleç CPU harcatmaz."""
    if cursor is None:
        return
    try:
        views.decode_cursor(cursor, fingerprint, size)
    except views.CursorError:
        raise _cursor_error() from None


def _cursor_error() -> ProblemError:
    return _invalid("cursor", "cursor_invalid", "İmleç geçersiz ya da bu sorguya ait değil.")


@router.get("/summary", response_model=SummaryOut)
async def summary(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    period: PeriodDep,
) -> SummaryOut:
    """Dönem toplamları (motorun dönem toplamı), durum dağılımı, maliyeti eksik satırlar ve besleyici notları."""
    await _guard(db, ctx, account_id, limiter, settings)
    report = await _report(db, ctx, account_id, period)
    return SummaryOut(
        period=period.out(),
        totals=PeriodTotalsOut.model_validate(report.totals),
        status_counts=StatusCountsOut(**views.status_counts(report.result.lines)),
        missing_cost_line_count=report.totals.missing_cost_line_count,
        feed_notes=FeedNotesOut.model_validate(report.notes),
    )


@router.get("/products", response_model=ProductProfitListOut)
async def list_products(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    period: PeriodDep,
    sort: views.SortField = "net_profit",
    order: views.SortOrder = "desc",
    filter: Annotated[views.ProductFilter, Query()] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> ProductProfitListOut:
    """Ürün kârlılık listesi. Sıralama kararlıdır (eşitlikte barkod artan); hesaplanamayan değerler sona gider.

    `cursor` önceki sayfanın `next_cursor`'ıdır ve aynı sort/order/filter/dönem ile kullanılmalıdır.
    """
    await _guard(db, ctx, account_id, limiter, settings)
    fingerprint = f"products|{sort}|{order}|{filter}|{period.start}|{period.end}"
    _check_cursor(cursor, fingerprint, 3)
    report = await _report(db, ctx, account_id, period)
    rows = views.filter_rows(views.build_product_rows(report.result), filter)
    try:
        page, next_cursor = views.product_page(rows, sort, order, limit, cursor, fingerprint)
    except views.CursorError:
        raise _cursor_error() from None
    titles = await views.product_titles(db, ctx.tenant_id, account_id, [r.totals.barcode for r in page])
    return ProductProfitListOut(
        period=period.out(),
        sort=sort,
        order=order,
        filter=filter,
        total_count=len(rows),
        items=[
            ProductProfitItemOut(
                barcode=r.totals.barcode,
                title=titles.get(r.totals.barcode),
                line_count=r.totals.line_count,
                quantity=r.totals.quantity,
                refunded_quantity=r.totals.refunded_quantity,
                net_sales_excl_vat=r.totals.net_sales_excl_vat,
                product_cost=r.totals.product_cost,
                total_expenses=r.total_expenses,
                net_profit=r.totals.net_profit,
                net_margin_percent=r.totals.net_margin_percent,
                advertising_spend=r.totals.advertising_spend,
                advertising_revenue=r.totals.advertising_revenue,
                roas=r.totals.roas,
                breakeven_roas=r.totals.breakeven_roas,
                cost_missing=r.totals.cost_missing,
                basis=r.basis,
                estimated_line_count=r.estimated_lines,
                settled_line_count=r.settled_lines,
                adjusted_line_count=r.adjusted_lines,
            )
            for r in page
        ],
        next_cursor=next_cursor,
    )


@router.get("/products/{barcode}", response_model=ProductProfitDetailOut)
async def product_detail(
    account_id: UUID,
    barcode: BarcodePath,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    period: PeriodDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> ProductProfitDetailOut:
    """Tek ürünün dönem kırılımı: ürün toplamı, tahmini-kesin karşılaştırması ve satırlar (sayfalı). Ürün yoksa 404."""
    await _guard(db, ctx, account_id, limiter, settings)
    if not await views.barcode_known(db, ctx.tenant_id, account_id, barcode):
        raise _not_found()
    fingerprint = f"lines|{barcode}|{period.start}|{period.end}"
    _check_cursor(cursor, fingerprint, 3)
    report = await _report(db, ctx, account_id, period)
    mine = [line for line in report.result.lines if line.barcode == barcode]
    product = next((p for p in report.result.products if p.barcode == barcode), None)
    try:
        page, next_cursor = views.lines_page(mine, limit, cursor, fingerprint)
    except views.CursorError:
        raise _cursor_error() from None
    row = next((r for r in views.build_product_rows(report.result) if r.totals.barcode == barcode), None)
    titles = await views.product_titles(db, ctx.tenant_id, account_id, [barcode])
    return ProductProfitDetailOut(
        period=period.out(),
        barcode=barcode,
        title=titles.get(barcode),
        product=None if product is None else ProductTotalsOut.model_validate(product),
        basis=row.basis if row else "none",
        comparison=ComparisonSummaryOut.model_validate(views.comparison_summary(mine)),
        total_lines=len(mine),
        lines=[LineOut.model_validate(line) for line in page],
        next_cursor=next_cursor,
    )


@router.get("/orders/{order_number}", response_model=OrderDetailOut)
async def order_detail(
    account_id: UUID,
    order_number: OrderNumberPath,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    period: OptionalPeriodDep,
) -> OrderDetailOut:
    """Sipariş kırılımı (satırlar ve kalemler). Dönem verilmezse siparişin kendi günleri kullanılır.

    Ortak giderler dönemin satırlarına dağıtıldığı için dönem verilmezse bu dağıtım yalnız siparişin
    günlerindeki satırlar üzerinden yapılır; bir liste ekranıyla birebir aynı sayı için aynı start/end verin.
    """
    await _guard(db, ctx, account_id, limiter, settings)
    days = await views.order_days(db, ctx.tenant_id, account_id, order_number)
    if days is None:
        raise _not_found()
    used = period or Period(*days)
    report = await _report(db, ctx, account_id, used)
    lines = views.sort_lines(line for line in report.result.lines if line.order_number == order_number)
    if not lines:
        raise _not_found()  # sipariş var ama seçilen dönemde değil (ya da motora verilmedi)
    return OrderDetailOut(
        period=used.out(),
        order_number=order_number,
        ordered_on=days[0],
        totals=OrderTotalsOut.model_validate(views.order_totals(lines)),
        status_counts=StatusCountsOut(**views.status_counts(lines)),
        lines=[LineOut.model_validate(line) for line in lines],
    )


@router.get("/alerts", response_model=AlertsOut)
async def alerts(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    period: PeriodDep,
    code: Annotated[WarningCode | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> AlertsOut:
    """Motorun ürettiği dönem ve satır uyarıları. Yeni kural yoktur; motorun üretmediği uyarılar
    `not_yet_available` içinde bildirilir. `counts` süzgeç ve sayfalamadan bağımsız tüm dönemi sayar."""
    await _guard(db, ctx, account_id, limiter, settings)
    fingerprint = f"alerts|{code.value if code else ''}|{period.start}|{period.end}"
    _check_cursor(cursor, fingerprint, 5)
    report = await _report(db, ctx, account_id, period)
    everything = views.build_alerts(report.result)
    selected = [a for a in everything if code is None or a.code is code]
    try:
        page, next_cursor = views.alerts_page(selected, limit, cursor, fingerprint)
    except views.CursorError:
        raise _cursor_error() from None
    return AlertsOut(
        period=period.out(),
        counts=[
            AlertCountOut(code=c, count=n, message=views.ALERT_MESSAGES[c])
            for c, n in views.alert_counts(everything).items()
        ],
        total_count=len(selected),
        items=[AlertOut(message=views.ALERT_MESSAGES[a.code], **asdict(a)) for a in page],
        next_cursor=next_cursor,
        not_yet_available=[UnavailableAlertOut(code=c, reason=r) for c, r in views.UNAVAILABLE_ALERTS],
    )
