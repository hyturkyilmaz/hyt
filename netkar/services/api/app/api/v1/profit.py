"""/v1/marketplace-accounts/{account_id}/profit: kâr raporu uçları (panel S4). Salt okuma, tüm roller.

Her uç nokta: kimlik ve rol, hesap kiracıya ait değilse 404 (IDOR) ve RLS, girdi doğrulama (RFC 9457),
kiracı başına dakikada sınırlı istek. Bir istek kâr motorunu dönem için EN FAZLA BİR KEZ çalıştırır
(`app.services.profit_report`); ortak giderler (kargo, hizmet bedeli, reklam) dönemin TÜM satırlarına
dağıtıldığı için ürün, sipariş ve uyarı görünümleri dönem sonucundan seçilir. Denetim izi gerekmez (okuma).

Dönem: `start`+`end` (YYYY-AA-GG, İstanbul günü, uçlar dahil) ya da `range=today|7d|30d` (bugün dahil);
hiçbiri verilmezse `30d`. En fazla 92 gün (sipariş ucunda dönemsiz istekte siparişin kendi günleri de dahil).

Yük sınırları: kiracı başına dakikalık sayaç (ayrı küçük havuz), kiracı ve süreç başına beklemeyen eşzamanlılık
kapısı (429/503 + Retry-After) ve motor çalışırken veritabanı bağlantısı TUTULMAZ (denetim S4 Y-01, O-01).
Kâr ayarları (kargo tarifesi, hizmet bedeli, değişken gider, varsayılan desi) hesap düzeyinde veritabanından
okunur (`app.services.profit_settings.load_profit_settings`, ADR-0006); okunan ayar sürümü her yanıtta
`settings_revision` olarak döner (K44); ayar yoksa motor "tanımsız" çalışır:
eksik kalem 0 sayılmaz, net kâr null olur (K33-K37).
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbDep, RateLimiterDep, ReportCacheDep, ReportGateDep, SettingsDep
from app.api.v1.product_costs import AnyRoleDep, BarcodePath
from app.api.v1.profit_schemas import (
    AlertCountOut,
    AlertOut,
    AlertsOut,
    ComparisonSummaryOut,
    FeedNotesOut,
    LineOut,
    OrderDetailOut,
    OrderListItemOut,
    OrderListOut,
    OrderProductOut,
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
from app.api.v1.profit_settings_schemas import CompletenessOut
from app.core.clock import today_istanbul
from app.core.config import Settings
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.db.rls import set_rls_context
from app.profit import ProfitInputError
from app.profit.enums import Certainty, Status, WarningCode
from app.profit.schema_v1 import ISTANBUL
from app.services import product_costs as costs
from app.services import profit_views as views
from app.services.auth import AuthContext
from app.services.profit_feed import period_bounds
from app.services.profit_report import PeriodReport, period_profit
from app.services.profit_settings import LoadedSettings, completeness_of, load_profit_settings
from app.services.report_cache import ReportCache, ReportKey, report_data_version
from app.services.report_gate import ReportGate

router = APIRouter(prefix="/marketplace-accounts/{account_id}/profit", tags=["profit"])
log = logging.getLogger(__name__)

# PostgreSQL "query_canceled" (statement_timeout aşımı).
_QUERY_CANCELED = "57014"
# Deyim sınırı, hesap üst süresinden bu kadar sn kısa kurulur (DK-05).
_STATEMENT_MARGIN = 5.0

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
    """Hesap başka kiracıya aitse (veya yoksa) 404, sonra kiracı başına dakikalık rapor sınırı.

    Sayaç ayrı havuzdan yazılır (oturum bağlantısı tutulurken ikinci bağlantı istenmez, kilitlenme yok);
    sayaca ulaşan her istek sayılır, ardından gelen eşzamanlılık kapısı tarafından reddedilenler de.
    """
    if not await costs.account_exists(db, ctx.tenant_id, account_id):
        raise _not_found()
    key = f"profit-report:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}"
    await limiter.hit(key, settings.rate_limit_profit_report_tenant, _MINUTE)


async def _report(
    db: AsyncSession,
    ctx: AuthContext,
    account_id: UUID,
    period: Period,
    gate: ReportGate,
    cache: ReportCache,
) -> tuple[PeriodReport, LoadedSettings]:
    """Rapor hesabı; veritabanı deyim sınırı (`statement_timeout`, sqlstate 57014) aşılırsa HER sorguda (ayar
    ve sürüm okumaları, besleyici, bekleme sonrası bağlam kurulumu) aynı 503 `report-compute-timeout` (OK-05,
    DK-04). Log'a SQL ve parametre yazılmaz: yalnız hesap kimliği."""
    try:
        return await _report_inner(db, ctx, account_id, period, gate, cache)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) != _QUERY_CANCELED:
            raise
        log.error("profit_statement_timeout account=%s", account_id)
        raise ProblemError(
            503,
            "Rapor hesaplanamadı",
            "report-compute-timeout",
            "Rapor belirlenen sürede hazırlanamadı. Kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": cache.retry_after},
        ) from None


async def _report_inner(
    db: AsyncSession,
    ctx: AuthContext,
    account_id: UUID,
    period: Period,
    gate: ReportGate,
    cache: ReportCache,
) -> tuple[PeriodReport, LoadedSettings]:
    """Dönem sonucunu önbellekten ya da motoru bir kez çalıştırarak verir; raporla birlikte hesaplandığı
    ayarları (sürüm damgası K44 ve tamlık için demet) döndürür. Girdi tutarsızlığı iç ayrıntı sızdırmadan 500 olur.

    Önbellek anahtarı (kiracı, hesap, dönem, ayar sürümü, veri sürümü) olduğundan ayar yazımı, maliyet içe
    aktarma ve senkron sonrası eski sonuç dönmez (SU-01). İsabet kapıya girmez ve motoru çalıştırmaz; yalnız
    ıskada kapı yuvası alınır (kapı beklemez, doluysa 429/503). Besleyici okumaları bitince bağlantı havuza iade
    edilir; veritabanına sonradan dokunan uçlar `_restore_context` çağırmalıdır.
    """
    await _bound_statements(db, cache)
    loaded = await load_profit_settings(db, ctx.tenant_id, account_id)
    # Veri sürümü (hesap başına tek sayaç satırı, OS-03) motor girdisi okunmadan ÖNCE alınır (okuma sırasında
    # veri değişirse sonuç eski sürümle saklanır; sonraki istek yeni sürümü görüp yeniden hesaplar).
    version = await report_data_version(db, ctx.tenant_id, account_id) if cache.enabled else 0
    key = ReportKey(ctx.tenant_id, account_id, period.start, period.end, loaded.revision, version)
    released = False

    async def release() -> None:
        nonlocal released
        await db.commit()
        released = True

    async def compute() -> PeriodReport:
        if released:  # bekleme sırasında işlem kapandı: RLS bağlamı ve deyim sınırı yeniden kurulur
            await _restore_context(db, ctx)
            await _bound_statements(db, cache)
        async with gate.slot(ctx.tenant_id) as slot:
            try:
                return await period_profit(
                    db,
                    ctx.tenant_id,
                    account_id,
                    period.start,
                    period.end,
                    loaded.settings,
                    release_connection=True,
                    slot=slot,
                )
            except ProfitInputError as exc:
                # Ayrıntı (sipariş no, tutar) log'a yazılmaz: yalnız hesap kimliği ve hata sınıfı.
                log.error("profit_calculation_failed account=%s error=%s", account_id, type(exc).__name__)
                raise ProblemError(
                    500,
                    "Rapor hesaplanamadı",
                    "profit-calculation-failed",
                    "Kayıtlar tutarsız; rapor üretilemedi.",
                ) from None

    report, _ = await cache.get_or_compute(key, compute, release)
    return report, loaded


async def _bound_statements(db: AsyncSession, cache: ReportCache) -> None:
    """Rapor işleminin her deyimine üst süre koyar (OK-05): `SET LOCAL statement_timeout` (işlem yerel).

    Değer hesaplama üst süresinden birkaç sn kısadır (`compute - 5 sn`, en az 1 sn; DK-05): deyim sınırı
    `asyncio.timeout`tan ÖNCE dolar, böylece veritabanı aşamasında temiz 57014 yolu (bağlantı geçersiz
    kılınmadan) çalışır; `asyncio.timeout` yalnız yedektir. Takılmış bir sorgu (kilit beklemesi, yavaş tarama) bağlantıyı
    süresiz tutamaz. İşlem commit ile biter ve değer sıfırlanır, bu yüzden bağlantı iade edildikten sonra
    yeniden kurulur. Süre sınırsızsa (None) hiçbir şey ayarlanmaz.
    """
    if cache.compute_timeout_seconds is None:
        return
    millis = math.ceil(max(1.0, cache.compute_timeout_seconds - _STATEMENT_MARGIN) * 1000)
    await db.execute(text("SELECT set_config('statement_timeout', :v, true)"), {"v": str(millis)})


async def _restore_context(db: AsyncSession, ctx: AuthContext) -> None:
    """Bağlantı iade edildiğinde RLS bağlamı sıfırlanır (işlem yerel GUC); sonraki sorgular için yeniden kurulur."""
    await set_rls_context(db, ctx.tenant_id, ctx.user_id)


def _codec(settings: Settings, ctx: AuthContext, account_id: UUID) -> views.CursorCodec:
    """İmleç mühürleyicisi: kiracıya ve hesaba bağlı, amaca özel anahtarlı."""
    return views.CursorCodec(settings.master_key, ctx.tenant_id, account_id)


def _check_cursor(cursor: str | None, fingerprint: str, size: int, codec: views.CursorCodec) -> None:
    """İmleç motor çalışmadan doğrulanır: bozuk, yabancı kiracı/hesap/sorgu imleci CPU harcatmaz."""
    if cursor is None:
        return
    try:
        codec.decode(cursor, fingerprint, size)
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
    gate: ReportGateDep,
    cache: ReportCacheDep,
    period: PeriodDep,
) -> SummaryOut:
    """Dönem toplamları (motorun dönem toplamı), durum dağılımı, maliyeti eksik satırlar ve besleyici notları.

    Panel sunum alanları motor çıktısından türetilir (yeni kural yok): `completeness` (ayar tamlığı, bugün geçerli
    sürüm var mı), `settings_configured` (eski alan: kargo tarifesi VE hizmet bedeli tanımlı mı),
    `tariff_missing_line_count` (motorun `eksik_kalem_satir_sayilari.kargo_gonderi` sayımı) ve
    `estimated_line_count`. Eksik kalemli dönemde `totals.net_kar_kismi` doğrudur ve dönem marjı null'dır (K39).
    """
    await _guard(db, ctx, account_id, limiter, settings)
    report, loaded = await _report(db, ctx, account_id, period, gate, cache)
    # Tamlık motorla AYNI ayar demetinden hesaplanır (YT-01, AB-02): yanıtta damga, rakamlar ve tamlık tek sürümdür
    # ve bağlantı iade edildikten sonra ayrı bir ayar okuması yapılmaz.
    completeness = completeness_of(loaded.bundle, today_istanbul())
    counts = views.status_counts(report.result.lines)
    return SummaryOut(
        period=period.out(),
        settings_revision=loaded.revision,
        totals=PeriodTotalsOut.model_validate(report.totals),
        status_counts=StatusCountsOut(**counts),
        missing_cost_line_count=report.totals.missing_cost_line_count,
        completeness=CompletenessOut.model_validate(completeness, from_attributes=True),
        settings_configured=completeness.configured,
        tariff_missing_line_count=report.totals.missing_line_counts.outbound_shipping,
        estimated_line_count=counts[Status.ESTIMATED.value],
        feed_notes=FeedNotesOut.model_validate(report.notes),
    )


@router.get("/products", response_model=ProductProfitListOut)
async def list_products(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    gate: ReportGateDep,
    cache: ReportCacheDep,
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
    codec = _codec(settings, ctx, account_id)
    _check_cursor(cursor, fingerprint, 3, codec)
    report, loaded = await _report(db, ctx, account_id, period, gate, cache)
    rows = views.filter_rows(views.build_product_rows(report.result), filter)
    try:
        page, next_cursor = views.product_page(rows, sort, order, limit, cursor, fingerprint, codec)
    except views.CursorError:
        raise _cursor_error() from None
    await _restore_context(db, ctx)
    titles = await views.product_titles(db, ctx.tenant_id, account_id, [r.totals.barcode for r in page])
    return ProductProfitListOut(
        period=period.out(),
        settings_revision=loaded.revision,
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
                certainty=r.certainty,
                missing_items=r.missing_items,
                contribution_excl_missing=r.totals.known_expenses_profit,
                loss_reason=r.loss_reason,
                shipping_missing=r.shipping_missing,
                basis=r.basis,
                statement_basis=r.basis,
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
    gate: ReportGateDep,
    cache: ReportCacheDep,
    period: PeriodDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> ProductProfitDetailOut:
    """Tek ürünün dönem kırılımı: ürün toplamı, tahmini-kesin karşılaştırması ve satırlar (sayfalı). Ürün yoksa 404."""
    await _guard(db, ctx, account_id, limiter, settings)
    if not await views.barcode_known(db, ctx.tenant_id, account_id, barcode):
        raise _not_found()
    fingerprint = f"lines|{barcode}|{period.start}|{period.end}"
    codec = _codec(settings, ctx, account_id)
    _check_cursor(cursor, fingerprint, 3, codec)
    report, loaded = await _report(db, ctx, account_id, period, gate, cache)
    mine = [line for line in report.result.lines if line.barcode == barcode]
    product = next((p for p in report.result.products if p.barcode == barcode), None)
    try:
        page, next_cursor = views.lines_page(mine, limit, cursor, fingerprint, codec)
    except views.CursorError:
        raise _cursor_error() from None
    row = next((r for r in views.build_product_rows(report.result) if r.totals.barcode == barcode), None)
    await _restore_context(db, ctx)
    titles = await views.product_titles(db, ctx.tenant_id, account_id, [barcode])
    return ProductProfitDetailOut(
        period=period.out(),
        settings_revision=loaded.revision,
        barcode=barcode,
        title=titles.get(barcode),
        product=None if product is None else ProductTotalsOut.model_validate(product),
        certainty=row.certainty if row else Certainty.NONE,
        basis=row.basis if row else "none",
        statement_basis=row.basis if row else "none",
        comparison=ComparisonSummaryOut.model_validate(views.comparison_summary(mine)),
        total_lines=len(mine),
        lines=[LineOut.model_validate(line) for line in page],
        next_cursor=next_cursor,
    )


@router.get("/orders", response_model=OrderListOut)
async def list_orders(
    account_id: UUID,
    ctx: AnyRoleDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    gate: ReportGateDep,
    cache: ReportCacheDep,
    period: PeriodDep,
    sort: views.OrderSort = "date",
    order: views.SortOrder = "desc",
    filter: Annotated[views.OrderFilter, Query()] = "all",
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
            description="Sipariş no ile TAM eşleşme araması.",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> OrderListOut:
    """Sipariş kârlılık listesi (varsayılan: tarihe göre yeni önce). Sıralama kararlıdır (eşitlikte sipariş no artan);
    hesaplanamayan değerler (null net kâr, iptal) sona gider. Zarar süzgecinde en büyük zarar önce için
    `sort=net_profit&order=asc`. `cursor` önceki sayfanın `next_cursor`'ıdır ve aynı sort/order/filter/q/dönem ile
    kullanılmalıdır. Tutarlar dönem düzeyi giderleri içermez (`summary` dönem rakamı onları da düşer).
    """
    await _guard(db, ctx, account_id, limiter, settings)
    fingerprint = f"orders|{sort}|{order}|{filter}|{q or ''}|{period.start}|{period.end}"
    codec = _codec(settings, ctx, account_id)
    _check_cursor(cursor, fingerprint, 3, codec)
    lower, upper = period_bounds(period.start, period.end)
    if q is not None and not await views.order_in_period(db, ctx.tenant_id, account_id, q, lower, upper):
        # SU-04: dönemde böyle bir sipariş yok; sonuç boş olacağı için motor ve kapı atlanır (yalnız ayar sürümü okunur).
        empty = await load_profit_settings(db, ctx.tenant_id, account_id)
        return OrderListOut(
            period=period.out(),
            settings_revision=empty.revision,
            sort=sort,
            order=order,
            filter=filter,
            q=q,
            total_count=0,
            items=[],
            next_cursor=None,
        )
    report, loaded = await _report(db, ctx, account_id, period, gate, cache)
    rows = views.filter_orders(views.build_order_rows(report.result), filter, q)
    await _restore_context(db, ctx)
    # Tarih sıralamasında tüm satırların dönem içi sipariş anı gerekir; net kâr sıralamasında yalnız sayfadakilerin
    # (SU-04). Tarih her iki durumda da dönemle sınırlıdır (SU-02).
    dates: dict[str, datetime] = {}
    if sort == "date":
        dates = await views.order_dates(
            db, ctx.tenant_id, account_id, [r.order_number for r in rows], lower, upper
        )
    try:
        page, next_cursor = views.order_page(rows, dates, sort, order, limit, cursor, fingerprint, codec)
    except views.CursorError:
        raise _cursor_error() from None
    if sort != "date":
        dates = await views.order_dates(
            db, ctx.tenant_id, account_id, [r.order_number for r in page], lower, upper
        )
    shown = {r.order_number: r.barcodes[:2] for r in page}
    titles = await views.product_titles(
        db, ctx.tenant_id, account_id, sorted({b for barcodes in shown.values() for b in barcodes})
    )
    items = []
    for r in page:
        moment = dates.get(r.order_number)
        t = r.totals
        items.append(
            OrderListItemOut(
                order_number=r.order_number,
                ordered_on=None if moment is None else moment.astimezone(ISTANBUL).date(),
                cancelled=r.cancelled,
                line_count=0 if t is None else t.line_count,
                cancelled_line_count=r.cancelled_line_count,
                products=[OrderProductOut(barcode=b, title=titles.get(b)) for b in shown[r.order_number]],
                more_product_count=max(len(r.barcodes) - 2, 0),
                net_sales_excl_vat=None if t is None else t.net_sales_excl_vat,
                net_profit=r.net_profit,
                known_expenses_profit=None if t is None else t.known_expenses_profit,
                certainty=r.certainty,
                missing_items=[] if t is None else t.missing_items,
                cost_missing=False if t is None else t.cost_missing,
                loss_reason=r.loss_reason,
                awaiting_payout=r.awaiting_payout,
                unexpected_deduction=r.unexpected_deduction,
                status_counts=StatusCountsOut(**r.status_counts),
            )
        )
    return OrderListOut(
        period=period.out(),
        settings_revision=loaded.revision,
        sort=sort,
        order=order,
        filter=filter,
        q=q,
        total_count=len(rows),
        items=items,
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
    gate: ReportGateDep,
    cache: ReportCacheDep,
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
    if period is None:
        try:
            used = Period(*views.default_order_period(days))
        except views.PeriodError as exc:  # paketler 92 günden uzun bir aralığa yayılmış (D-01)
            raise _invalid(exc.field, exc.code, exc.message) from None
    else:
        used = period
    report, loaded = await _report(db, ctx, account_id, used, gate, cache)
    lines = views.sort_lines(line for line in report.result.lines if line.order_number == order_number)
    if not lines:
        raise _not_found()  # sipariş var ama seçilen dönemde değil (ya da motora verilmedi)
    return OrderDetailOut(
        period=used.out(),
        settings_revision=loaded.revision,
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
    gate: ReportGateDep,
    cache: ReportCacheDep,
    period: PeriodDep,
    code: Annotated[WarningCode | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=400)] = None,
) -> AlertsOut:
    """Motorun ürettiği dönem ve satır uyarıları. Yeni kural yoktur; motorun üretmediği uyarılar
    `not_yet_available` içinde bildirilir. `counts` süzgeç ve sayfalamadan bağımsız tüm dönemi sayar."""
    await _guard(db, ctx, account_id, limiter, settings)
    fingerprint = f"alerts|{code.value if code else ''}|{period.start}|{period.end}"
    codec = _codec(settings, ctx, account_id)
    _check_cursor(cursor, fingerprint, 5, codec)
    report, loaded = await _report(db, ctx, account_id, period, gate, cache)
    everything = views.build_alerts(report.result)
    selected = [a for a in everything if code is None or a.code is code]
    try:
        page, next_cursor = views.alerts_page(selected, limit, cursor, fingerprint, codec)
    except views.CursorError:
        raise _cursor_error() from None
    return AlertsOut(
        period=period.out(),
        settings_revision=loaded.revision,
        counts=[
            AlertCountOut(code=c, count=n, message=views.ALERT_MESSAGES[c])
            for c, n in views.alert_counts(everything).items()
        ],
        total_count=len(selected),
        items=[AlertOut(message=views.ALERT_MESSAGES[a.code], **asdict(a)) for a in page],
        next_cursor=next_cursor,
        not_yet_available=[UnavailableAlertOut(code=c, reason=r) for c, r in views.UNAVAILABLE_ALERTS],
    )
