"""Kâr raporu görünümleri: dönem çözümü, ürün listesi (sıralama, imleç), sipariş özeti, uyarılar.

Bu modül motor çıktısını (`ProfitResult`) panelin ihtiyaç duyduğu biçime çevirir. YENİ İŞ KURALI YOKTUR:
her sayı motorun çıktısından seçilir ya da motorun yuvarlanmış tutarlarının toplamıdır (Decimal, float
yok). Uyarılar motorun ürettiği kodlardır; motorun üretmediği uyarılar `UNAVAILABLE_ALERTS` ile dürüstçe
"henüz yok" diye bildirilir. HTTP bilgisi yoktur (hatalar `PeriodError` ve `CursorError` ile döner).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import derive_key
from app.models import Order, OrderLine, Product
from app.profit.enums import Status, WarningCode
from app.profit.results import LineResult, ProductTotals, ProfitResult
from app.profit.schema_v1 import ISTANBUL

ZERO = Decimal("0.00")

# --------------------------------------------------------------------------- dönem

MAX_PERIOD_DAYS = 92
MIN_DAY = date(2000, 1, 1)
MAX_DAY = date(2100, 12, 31)
RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30}
DEFAULT_RANGE = "30d"
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class PeriodError(ValueError):
    """Dönem parametresi geçersiz: alan adı ve makine kodu (girdi değeri iletiye konmaz)."""

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message


def _parse_day(field: str, value: str) -> date:
    if not _ISO_DATE.fullmatch(value):
        raise PeriodError(field, "date_invalid", "Tarih YYYY-AA-GG biçiminde olmalıdır.")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise PeriodError(field, "date_invalid", "Geçerli bir takvim günü olmalıdır.") from None
    if not MIN_DAY <= day <= MAX_DAY:
        raise PeriodError(field, "date_out_of_range", "Tarih 2000-01-01 ile 2100-12-31 arasında olmalıdır.")
    return day


def resolve_period(
    start: str | None,
    end: str | None,
    range_name: str | None,
    today: date,
    default_range: str | None = DEFAULT_RANGE,
) -> tuple[date, date] | None:
    """`start`+`end` ya da `range` (today, 7d, 30d; İstanbul günü, bugün dahil) -> uçlar dahil gün aralığı.

    Hiçbiri verilmezse `default_range` uygulanır (None ise sonuç None: çağıran kendi kuralını seçer).
    İkisi birden verilemez; tek uç verilemez; en fazla `MAX_PERIOD_DAYS` gün (uçlar dahil).
    """
    if range_name is not None and (start is not None or end is not None):
        raise PeriodError("range", "period_conflict", "range ile start/end birlikte verilemez.")
    if range_name is None and start is None and end is None:
        if default_range is None:
            return None
        range_name = default_range
    if range_name is not None:
        return today - timedelta(days=RANGE_DAYS[range_name] - 1), today
    if start is None or end is None:
        missing = "end" if end is None else "start"
        raise PeriodError(missing, "period_incomplete", "start ve end birlikte verilmelidir.")
    first, last = _parse_day("start", start), _parse_day("end", end)
    if last < first:
        raise PeriodError("end", "period_reversed", "end, start tarihinden önce olamaz.")
    if (last - first).days + 1 > MAX_PERIOD_DAYS:
        raise PeriodError(
            "end", "period_too_long", f"Dönem en fazla {MAX_PERIOD_DAYS} gün (uçlar dahil) olabilir."
        )
    return first, last


def default_order_period(days: tuple[date, date]) -> tuple[date, date]:
    """Sipariş ucunda dönem verilmediğinde siparişin kendi günleri; aralık yine `MAX_PERIOD_DAYS` ile
    sınırlıdır (D-01).

    Aşılırsa kullanıcı start/end vermelidir (motor hiç çalışmaz).
    """
    first, last = days
    if (last - first).days + 1 > MAX_PERIOD_DAYS:
        raise PeriodError(
            "end",
            "period_too_long",
            f"Siparişin paketleri {MAX_PERIOD_DAYS} günden uzun bir aralığa yayılmış; start ve end verin.",
        )
    return first, last


# --------------------------------------------------------------------------- imleç (keyset sayfalama)


class CursorError(ValueError):
    """İmleç bozuk, başka bir sorguya (sıralama, süzgeç, dönem) ya da başka kiracıya/hesaba ait."""


_NONCE_BYTES = 12


class CursorCodec:
    """İmleci mühürler: AES-256-GCM (şifreleme + doğrulama etiketi), amaca özel anahtar, kiracı/hesap bağlı.

    - Opak: son öğenin sıralama değeri (net kâr) ve barkodu URL'de düz metin görünmez.
    - Bütünlük: etiket doğrulanmadan içerik ayrıştırılmaz; uydurma ya da değiştirilmiş imleç reddedilir.
    - Bağlama: kiracı, hesap ve sorgu parmak izi AAD'dir; başka kiracı/hesap/sorgunun imleci çözülemez.
    Anahtar `derive_key(master, "report-cursor")` ile türetilir (alan şifreleme anahtarından ayrı).
    """

    def __init__(self, master: bytes, tenant_id: UUID, account_id: UUID) -> None:
        self._aead = AESGCM(derive_key(master, "report-cursor"))
        self._binding = f"{tenant_id}|{account_id}|".encode()

    def encode(self, fingerprint: str, parts: Sequence[str]) -> str:
        """Son öğenin sıralama anahtarı; opak, URL güvenli, dolgusuz."""
        nonce = os.urandom(_NONCE_BYTES)
        payload = json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False).encode()
        sealed = self._aead.encrypt(nonce, payload, self._binding + fingerprint.encode())
        return base64.urlsafe_b64encode(nonce + sealed).decode().rstrip("=")

    def decode(self, cursor: str, fingerprint: str, size: int) -> list[str]:
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            data = json.loads(
                self._aead.decrypt(
                    raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], self._binding + fingerprint.encode()
                )
            )
        except (binascii.Error, ValueError, InvalidTag):
            raise CursorError from None
        if (
            not isinstance(data, list)
            or len(data) != size
            or not all(isinstance(p, str) and len(p) <= 200 for p in data)
        ):
            raise CursorError
        return data


def page_after[T](
    ordered: Sequence[T],
    key: Callable[[T], tuple[object, ...]],
    cursor_key: tuple[object, ...] | None,
    limit: int,
) -> tuple[list[T], bool]:
    """Anahtarı `cursor_key`'den BÜYÜK ilk `limit` öğe ve devamı var mı (`ordered` anahtara göre artan)."""
    remaining = [item for item in ordered if cursor_key is None or key(item) > cursor_key]
    return remaining[:limit], len(remaining) > limit


# --------------------------------------------------------------------------- ürün listesi

SortField = Literal["net_profit", "net_margin", "sales", "units"]
SortOrder = Literal["asc", "desc"]
ProductFilter = Literal["all", "loss", "missing_cost"]
Basis = Literal["estimated", "settled", "mixed", "none"]
LossReason = Literal["net_profit", "contribution_before_cost"]


def loss_reason(t: ProductTotals) -> LossReason | None:
    """Ürün zararda mı ve neden biliniyor.

    `net_profit`: net kâr hesaplandı ve negatif. `contribution_before_cost`: maliyet girilmediği için net kâr
    hesaplanamıyor ama maliyet hariç katkı zaten negatif; ürün maliyeti negatif olamayacağından zarar kesindir
    (docs/12 §7.4).
    """
    if t.net_profit is not None:
        return "net_profit" if t.net_profit < 0 else None
    return "contribution_before_cost" if t.contribution_before_cost < 0 else None


@dataclass(frozen=True, slots=True)
class ProductRow:
    """Ürün toplamı + liste için türetilmiş alanlar."""

    totals: ProductTotals
    # Maliyet bilinmiyorsa None (toplam gider ürün maliyetini de içerir).
    total_expenses: Decimal | None
    basis: Basis
    estimated_lines: int
    settled_lines: int
    adjusted_lines: int
    # KARGO_TARIFESI_EKSIK uyarılı aktif satır sayısı (motor çıktısından sayım; yeni kural değil).
    tariff_missing_lines: int = 0

    @property
    def shipping_missing(self) -> bool:
        """En az bir aktif satırda kargo tarifesi tanımsız (gönderi kargosu 0 ve `eksik` kaynaklı)."""
        return self.tariff_missing_lines > 0

    @property
    def loss_reason(self) -> LossReason | None:
        return loss_reason(self.totals)


def _basis(estimated: int, settled: int, adjusted: int) -> Basis:
    if estimated + settled + adjusted == 0:
        return "none"
    if estimated == 0:
        return "settled"  # tüm aktif satırlar ekstreden gelmiş (settled ya da adjusted)
    if settled + adjusted == 0:
        return "estimated"
    return "mixed"


def _total_expenses(p: ProductTotals) -> Decimal | None:
    """Ürün giderlerinin toplamı (KDV hariç): net satış - toplam gider = net kâr özdeşliği testlidir."""
    if p.product_cost is None:
        return None
    return (
        p.product_cost
        + p.commission
        + p.shipping_outbound
        + p.shipping_return
        + p.platform_service_fee
        + p.penalty
        + p.advertising_spend
        + p.variable_expenses
    )


def tariff_missing_line_count(lines: Iterable[LineResult]) -> int:
    """KARGO_TARIFESI_EKSIK uyarısı taşıyan aktif (iptal olmayan) satır sayısı."""
    return sum(
        1
        for line in lines
        if line.status is not Status.CANCELLED and WarningCode.CARGO_TARIFF_MISSING in line.warnings
    )


def build_product_rows(result: ProfitResult) -> list[ProductRow]:
    counts: dict[str, Counter[Status]] = {}
    tariff_missing: Counter[str] = Counter()
    for line in result.lines:
        if line.status is not Status.CANCELLED:
            counts.setdefault(line.barcode, Counter())[line.status] += 1
            if WarningCode.CARGO_TARIFF_MISSING in line.warnings:
                tariff_missing[line.barcode] += 1
    rows = []
    for product in result.products:
        c = counts.get(product.barcode, Counter())
        estimated, settled, adjusted = c[Status.ESTIMATED], c[Status.SETTLED], c[Status.ADJUSTED]
        rows.append(
            ProductRow(
                totals=product,
                total_expenses=_total_expenses(product),
                basis=_basis(estimated, settled, adjusted),
                estimated_lines=estimated,
                settled_lines=settled,
                adjusted_lines=adjusted,
                tariff_missing_lines=tariff_missing[product.barcode],
            )
        )
    return rows


def filter_rows(rows: Iterable[ProductRow], name: ProductFilter) -> list[ProductRow]:
    if name == "loss":
        return [r for r in rows if r.loss_reason is not None]
    if name == "missing_cost":
        return [r for r in rows if r.totals.cost_missing]
    return list(rows)


def sort_value(row: ProductRow, sort: SortField) -> Decimal | None:
    """Sıralama değeri; hesaplanamayan (maliyet eksik, net satış 0) None'dır ve her yönde SONA gider."""
    t = row.totals
    if sort == "net_profit":
        return t.net_profit
    if sort == "net_margin":
        return t.net_margin_percent
    if sort == "sales":
        return t.net_sales_excl_vat
    return Decimal(t.quantity)


def _key(value: Decimal | None, barcode: str, order: SortOrder) -> tuple[object, ...]:
    """(boş mu, yöne göre değer, barkod): eşitlikte barkod HER ZAMAN artan (kararlı sayfalama)."""
    if value is None:
        return (1, Decimal(0), barcode)
    return (0, -value if order == "desc" else value, barcode)


def order_rows(rows: Sequence[ProductRow], sort: SortField, order: SortOrder) -> list[ProductRow]:
    return sorted(rows, key=lambda r: _key(sort_value(r, sort), r.totals.barcode, order))


def product_page(
    rows: Sequence[ProductRow],
    sort: SortField,
    order: SortOrder,
    limit: int,
    cursor: str | None,
    fingerprint: str,
    codec: CursorCodec,
) -> tuple[list[ProductRow], str | None]:
    """Sıralı ürün sayfası ve sonraki imleç. `rows` süzülmüş olmalıdır; imleç parmak izine bağlıdır."""
    ordered = order_rows(rows, sort, order)
    cursor_key: tuple[object, ...] | None = None
    if cursor is not None:
        flag, text, barcode = codec.decode(cursor, fingerprint, 3)
        raw: Decimal | None = None
        if flag not in ("0", "1"):
            raise CursorError
        if flag == "0":
            try:
                raw = Decimal(text)
            except InvalidOperation:
                raise CursorError from None
            if not raw.is_finite():
                raise CursorError
        cursor_key = _key(raw, barcode, order)

    def key(row: ProductRow) -> tuple[object, ...]:
        return _key(sort_value(row, sort), row.totals.barcode, order)

    page, has_more = page_after(ordered, key, cursor_key, limit)
    next_cursor = None
    if has_more:
        last = page[-1]
        value = sort_value(last, sort)
        next_cursor = codec.encode(
            fingerprint,
            ["1", "", last.totals.barcode] if value is None else ["0", str(value), last.totals.barcode],
        )
    return page, next_cursor


async def product_titles(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, barcodes: Sequence[str]
) -> dict[str, str | None]:
    """Katalog başlıkları (yalnız istenen barkodlar); katalogda olmayan barkod sözlükte yoktur."""
    if not barcodes:
        return {}
    found = await db.execute(
        select(Product.barcode, Product.title).where(
            Product.tenant_id == tenant_id,
            Product.marketplace_account_id == account_id,
            Product.barcode.in_(list(barcodes)),
        )
    )
    return {barcode: title for barcode, title in found.all()}


# --------------------------------------------------------------------------- satır kümeleri


def line_key(line: LineResult) -> tuple[object, ...]:
    return (line.order_number, line.package_id, line.line_id)


def sort_lines(lines: Iterable[LineResult]) -> list[LineResult]:
    return sorted(lines, key=line_key)


def lines_page(
    lines: Sequence[LineResult], limit: int, cursor: str | None, fingerprint: str, codec: CursorCodec
) -> tuple[list[LineResult], str | None]:
    """Satırlar (sipariş no, paket, satır kimliği) sırasıyla; imleç son satırın anahtarıdır."""
    ordered = sort_lines(lines)
    cursor_key: tuple[object, ...] | None = None
    if cursor is not None:
        number, package, line = codec.decode(cursor, fingerprint, 3)
        try:
            cursor_key = (number, int(package), int(line))
        except ValueError:
            raise CursorError from None
    page, has_more = page_after(ordered, line_key, cursor_key, limit)
    next_cursor = None
    if has_more:
        last = page[-1]
        next_cursor = codec.encode(fingerprint, [last.order_number, str(last.package_id), str(last.line_id)])
    return page, next_cursor


@dataclass(frozen=True, slots=True)
class ComparisonSummary:
    """Tahmini-kesin karşılaştırması (K23) olan satırların toplamı; fark = kesin - tahmini."""

    compared_line_count: int
    estimated_total: Decimal
    actual_total: Decimal
    difference: Decimal


def comparison_summary(lines: Iterable[LineResult]) -> ComparisonSummary:
    compared = [line.comparison for line in lines if line.comparison is not None]
    return ComparisonSummary(
        compared_line_count=len(compared),
        estimated_total=sum((c.compared_estimated_total for c in compared), ZERO),
        actual_total=sum((c.compared_actual_total for c in compared), ZERO),
        difference=sum((c.difference for c in compared), ZERO),
    )


def status_counts(lines: Iterable[LineResult]) -> dict[str, int]:
    counter = Counter(line.status for line in lines)
    return {status.value: counter[status] for status in Status}


@dataclass(frozen=True, slots=True)
class OrderTotals:
    """Siparişin aktif (iptal olmayan) satırlarının toplamı. Dönem düzeyi giderler dahil DEĞİLDİR."""

    line_count: int
    net_sales_excl_vat: Decimal
    # Aktif satırlardan biri maliyetsizse None (motorun ürün toplamıyla aynı ilke: maliyet uydurulmaz).
    total_expenses: Decimal | None
    net_profit: Decimal | None
    cost_missing: bool


def order_totals(lines: Iterable[LineResult]) -> OrderTotals:
    active = [line for line in lines if line.status is not Status.CANCELLED]
    missing = any(line.items.net_profit is None for line in active)
    return OrderTotals(
        line_count=len(active),
        net_sales_excl_vat=sum((line.items.net_sales_excl_vat for line in active), ZERO),
        total_expenses=None if missing else sum((line.items.total_expenses or ZERO for line in active), ZERO),
        net_profit=None if missing else sum((line.items.net_profit or ZERO for line in active), ZERO),
        cost_missing=missing,
    )


async def order_days(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, order_number: str
) -> tuple[date, date] | None:
    """Siparişin paketlerinin ilk ve son İstanbul günü; sipariş yoksa None."""
    row = (
        await db.execute(
            select(func.min(Order.ordered_at), func.max(Order.ordered_at)).where(
                Order.tenant_id == tenant_id,
                Order.marketplace_account_id == account_id,
                Order.order_number == order_number,
            )
        )
    ).one()
    first: datetime | None = row[0]
    last: datetime | None = row[1]
    if first is None or last is None:
        return None
    return first.astimezone(ISTANBUL).date(), last.astimezone(ISTANBUL).date()


# --------------------------------------------------------------------------- uyarılar

# Motorun ürettiği her uyarı kodu için kısa Türkçe açıklama (docs/12 K05, K08, K14, K16, K18, K23, K28).
ALERT_MESSAGES: dict[WarningCode, str] = {
    WarningCode.MISSING_COST: "Ürün maliyeti girilmemiş; bu satırın net kârı hesaplanamıyor.",
    WarningCode.LOSS: "Zararına satış: satırın net kârı sıfırın altında.",
    WarningCode.CARGO_DESI_MISMATCH: "Kargo faturasındaki desi, siparişteki desiden farklı.",
    WarningCode.UNEXPECTED_DEDUCTION: "Beklenmeyen kesinti: ekstredeki kesinti tahmini aşıyor.",
    WarningCode.COMMISSION_RATE_DIFFERENT: "Ekstredeki komisyon oranı sipariş satırındakinden farklı.",
    WarningCode.STATEMENT_INCONSISTENT: "Ekstre satırının iç tutarları birbirini tutmuyor.",
    WarningCode.UNMATCHED_PAYOUT_ADJUSTMENT: "Hakediş düzeltmesi bir satışla eşleşmedi.",
    WarningCode.CARGO_INVOICE_VAT_UNCERTAIN: "Kargo faturasının KDV durumu belirlenemedi.",
    WarningCode.CARGO_TARIFF_MISSING: "Kargo tarifesi tanımlı değil; tahmini kargo bedeli hesaplanamadı.",
    WarningCode.UNCLASSIFIED_DEDUCTION: "Sınıflandırılamayan kesinti var; ihtiyatla kâra yansıtıldı.",
    WarningCode.MISSING_COST_LINES: "Dönemde maliyeti girilmemiş satırlar var; dönem net kârı kısmi.",
    WarningCode.WITHHOLDING_STATEMENT_DIFF: "Hesaplanan stopaj ile ekstredeki stopaj farklı.",
}

# Panelde beklenen ama motorun/besleyicinin BUGÜN üretmediği uyarılar (docs/30 S6, docs/research/05).
UNAVAILABLE_ALERTS: tuple[tuple[str, str], ...] = (
    (
        "REKLAM_KARI_YIYOR",
        "Reklam harcaması kayıtları (ad_spend) henüz yok; motor bu uyarıyı üretmiyor.",
    ),
    ("IADE_ORANI_ARTISI", "İade oranı uyarısı için motor çıktısı henüz yok (S6)."),
)


@dataclass(frozen=True, slots=True)
class AlertItem:
    """Tek uyarı: satır uyarısı (`line`) ya da dönem uyarısı (`period`)."""

    code: WarningCode
    scope: Literal["period", "line"]
    order_number: str | None = None
    package_id: int | None = None
    line_id: int | None = None
    barcode: str | None = None
    # ZARAR için satırın net kârı; BEKLENMEYEN_KESINTI için karşılaştırmanın farkı ve eşiği.
    net_profit: Decimal | None = None
    difference: Decimal | None = None
    threshold: Decimal | None = None


def _alert_key(alert: AlertItem) -> tuple[object, ...]:
    return (
        0 if alert.scope == "period" else 1,
        alert.code.value,
        alert.order_number or "",
        alert.package_id or 0,
        alert.line_id or 0,
    )


def build_alerts(result: ProfitResult) -> list[AlertItem]:
    """Motorun dönem ve satır uyarıları (iptal satırları hariç), kararlı sırayla."""
    alerts = [AlertItem(code=code, scope="period") for code in result.period.warnings]
    for line in result.lines:
        if line.status is Status.CANCELLED:
            continue
        for code in line.warnings:
            alerts.append(
                AlertItem(
                    code=code,
                    scope="line",
                    order_number=line.order_number,
                    package_id=line.package_id,
                    line_id=line.line_id,
                    barcode=line.barcode,
                    net_profit=line.items.net_profit if code is WarningCode.LOSS else None,
                    difference=line.comparison.difference
                    if code is WarningCode.UNEXPECTED_DEDUCTION and line.comparison
                    else None,
                    threshold=line.comparison.threshold
                    if code is WarningCode.UNEXPECTED_DEDUCTION and line.comparison
                    else None,
                )
            )
    return sorted(alerts, key=_alert_key)


def alert_counts(alerts: Iterable[AlertItem]) -> dict[WarningCode, int]:
    counter = Counter(a.code for a in alerts)
    return {code: counter[code] for code in sorted(counter, key=lambda c: c.value)}


def alerts_page(
    alerts: Sequence[AlertItem], limit: int, cursor: str | None, fingerprint: str, codec: CursorCodec
) -> tuple[list[AlertItem], str | None]:
    cursor_key: tuple[object, ...] | None = None
    if cursor is not None:
        scope, code, number, package, line = codec.decode(cursor, fingerprint, 5)
        try:
            cursor_key = (int(scope), code, number, int(package), int(line))
        except ValueError:
            raise CursorError from None
    page, has_more = page_after(alerts, _alert_key, cursor_key, limit)
    next_cursor = None
    if has_more:
        k = _alert_key(page[-1])
        next_cursor = codec.encode(fingerprint, [str(k[0]), str(k[1]), str(k[2]), str(k[3]), str(k[4])])
    return page, next_cursor


async def barcode_known(db: AsyncSession, tenant_id: UUID, account_id: UUID, barcode: str) -> bool:
    """Barkod katalogda ya da bir sipariş satırında varsa doğru (yazım hatasında motor çalışmasın)."""
    in_catalog = await db.execute(
        select(Product.id).where(
            Product.tenant_id == tenant_id,
            Product.marketplace_account_id == account_id,
            Product.barcode == barcode,
        )
    )
    if in_catalog.first() is not None:
        return True
    in_orders = await db.execute(
        select(OrderLine.id).where(
            OrderLine.tenant_id == tenant_id,
            OrderLine.marketplace_account_id == account_id,
            OrderLine.barcode == barcode,
        )
    )
    return in_orders.first() is not None
