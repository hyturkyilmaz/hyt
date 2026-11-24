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
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import derive_key
from app.models import Order, OrderLine, Product
from app.profit.aggregate import summarize_certainty
from app.profit.enums import Certainty, MissingItem, Status, WarningCode
from app.profit.results import LineComparison, LineResult, ProductTotals, ProfitResult
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
LossReason = Literal["net_profit", "contribution_before_cost", "known_expenses"]


def loss_reason(t: ProductTotals) -> LossReason | None:
    """Ürün zararda mı ve neden biliniyor (K37 "kesin zarar": eksik kalemler negatif olamaz).

    `net_profit`: net kâr hesaplandı ve negatif. Net kâr null ise (eksik kalem var) ve eksik giderler hariç
    kâr negatifse zarar kesindir: yalnız maliyet eksikse `contribution_before_cost` (docs/12 §7.4), kargo
    ya da hizmet bedeli de eksikse `known_expenses`. Eksik giderler hariç kâr negatif değilse belirsizdir.
    """
    if t.net_profit is not None:
        return "net_profit" if t.net_profit < 0 else None
    if t.known_expenses_profit >= 0:
        return None
    counts = t.missing_line_counts
    if counts.product_cost and not counts.outbound_shipping and not counts.platform_service_fee:
        return "contribution_before_cost"
    return "known_expenses"


@dataclass(frozen=True, slots=True)
class ProductRow:
    """Ürün toplamı + liste için türetilmiş alanlar."""

    totals: ProductTotals
    # Eksik kalem varsa None (toplam gider ürün maliyetini ve eksik kalemleri de içerir).
    total_expenses: Decimal | None
    # Ekstreli satır oranı (K40: kesinlik DEĞİL); kesinlik `totals.certainty`'dedir.
    basis: Basis
    estimated_lines: int
    settled_lines: int
    adjusted_lines: int

    @property
    def shipping_missing(self) -> bool:
        """En az bir aktif satırda gönderi kargosu eksik (motor sayımı, K37)."""
        return self.totals.missing_line_counts.outbound_shipping > 0

    @property
    def certainty(self) -> Certainty:
        return self.totals.certainty

    @property
    def missing_items(self) -> list[MissingItem]:
        """Ürünün aktif satırlarında eksik olan kalemler (kanonik sıra; motor sayımı)."""
        counts = self.totals.missing_line_counts
        present = {
            MissingItem.PRODUCT_COST: counts.product_cost,
            MissingItem.OUTBOUND_SHIPPING: counts.outbound_shipping,
            MissingItem.PLATFORM_SERVICE_FEE: counts.platform_service_fee,
        }
        return [item for item in MissingItem if present[item] > 0]

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
    """Ürün giderlerinin toplamı (KDV hariç): net satış - toplam gider = net kâr özdeşliği testlidir.

    Eksik kalem (maliyet, kargo, hizmet bedeli) varsa toplam gider bilinemez: None (K37)."""
    if p.net_profit is None or p.product_cost is None:
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


def build_product_rows(result: ProfitResult) -> list[ProductRow]:
    counts: dict[str, Counter[Status]] = {}
    for line in result.lines:
        if line.status is not Status.CANCELLED:
            counts.setdefault(line.barcode, Counter())[line.status] += 1
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
    """Sıralama değeri; hesaplanamayan (maliyet eksik, net satış 0) None'dır ve her yönde SONA gider.

    `net_profit` (denetim AD-04): net kâr null ama zarar kesinse (`loss_reason` dolu: eksik giderler hariç kâr
    negatif, eksik kalemler kârı yalnız düşürür) bilinen değer (eksik giderler hariç kâr) kullanılır; böylece
    kesin zararlı ürün `asc` sıralamada belirsiz (null, kârı pozitif ya da 0) ürünlerden önce gelir.
    Belirsizler sonda kalır. İmleç anahtarı bu değerden türer, kararlıdır.
    """
    t = row.totals
    if sort == "net_profit":
        if t.net_profit is None and row.loss_reason is not None:
            return t.known_expenses_profit
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


def value_page[T](
    rows: Sequence[T],
    value_of: Callable[[T], Decimal | None],
    id_of: Callable[[T], str],
    order: SortOrder,
    limit: int,
    cursor: str | None,
    fingerprint: str,
    codec: CursorCodec,
) -> tuple[list[T], str | None]:
    """Genel keyset sayfası: (boş mu, yöne göre değer, kimlik) sırası; imleç parmak izine bağlıdır.

    Hesaplanamayan değer (None) her yönde sona gider; eşitlikte kimlik HER ZAMAN artan (kararlı sayfalama).
    """
    ordered = sorted(rows, key=lambda r: _key(value_of(r), id_of(r), order))
    cursor_key: tuple[object, ...] | None = None
    if cursor is not None:
        flag, text, ident = codec.decode(cursor, fingerprint, 3)
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
        cursor_key = _key(raw, ident, order)

    def key(row: T) -> tuple[object, ...]:
        return _key(value_of(row), id_of(row), order)

    page, has_more = page_after(ordered, key, cursor_key, limit)
    next_cursor = None
    if has_more:
        last = page[-1]
        value = value_of(last)
        next_cursor = codec.encode(
            fingerprint, ["1", "", id_of(last)] if value is None else ["0", str(value), id_of(last)]
        )
    return page, next_cursor


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
    return value_page(
        rows,
        lambda r: sort_value(r, sort),
        lambda r: r.totals.barcode,
        order,
        limit,
        cursor,
        fingerprint,
        codec,
    )


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
    # Aktif satırlardan biri eksik kalemliyse None (motorun ürün toplamıyla aynı ilke, K37).
    total_expenses: Decimal | None
    net_profit: Decimal | None
    # Bilinen giderlerle kâr (K37): eksik kalem 0 sayılmaz, hariç tutulur; eksik yoksa net kâra eşittir.
    known_expenses_profit: Decimal
    # Yalnız ürün maliyeti eksik mi (kargo ve hizmet bedeli eksikliği `missing_items`'tadır).
    cost_missing: bool
    missing_items: list[MissingItem]


def order_totals(lines: Iterable[LineResult]) -> OrderTotals:
    active = [line for line in lines if line.status is not Status.CANCELLED]
    incomplete = any(line.missing_items for line in active)
    present = {item for line in active for item in line.missing_items}
    return OrderTotals(
        line_count=len(active),
        net_sales_excl_vat=sum((line.items.net_sales_excl_vat for line in active), ZERO),
        total_expenses=None
        if incomplete
        else sum((line.items.total_expenses or ZERO for line in active), ZERO),
        net_profit=None if incomplete else sum((line.items.net_profit or ZERO for line in active), ZERO),
        known_expenses_profit=sum((line.items.known_expenses_profit for line in active), ZERO),
        cost_missing=MissingItem.PRODUCT_COST in present,
        missing_items=[item for item in MissingItem if item in present],
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


# --------------------------------------------------------------------------- sipariş listesi

OrderSort = Literal["date", "net_profit"]
OrderFilter = Literal["all", "loss", "awaiting_payout", "unexpected_deduction"]
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


@dataclass(frozen=True, slots=True)
class OrderRow:
    """Sipariş kârlılık listesi satırı: motorun satırlarından türetilir (yeni kural yok).

    Müşteri bilgisi YOKTUR: yalnız sipariş no ve ürün barkodları (adlar katalogdan sonradan eklenir).
    """

    order_number: str
    # Tüm satırlar iptalse True: tutar gösterilmez (B-02), net kâr null'dır (0.00 değil).
    cancelled: bool
    cancelled_line_count: int
    # Aktif (iptal olmayan) satırların toplamı; sipariş tümüyle iptalse None.
    totals: OrderTotals | None
    certainty: Certainty
    loss_reason: LossReason | None
    # En az bir aktif satır ekstresiz (hakedişi gelmemiş: durum `estimated`).
    awaiting_payout: bool
    # En az bir aktif satırda motor BEKLENMEYEN_KESINTI üretmiş.
    unexpected_deduction: bool
    status_counts: dict[str, int]
    # Siparişin ürünleri (tekil barkodlar, satır sırasıyla; iptal satırlar dahil).
    barcodes: tuple[str, ...]

    @property
    def net_profit(self) -> Decimal | None:
        return None if self.totals is None else self.totals.net_profit


def order_loss_reason(totals: OrderTotals) -> LossReason | None:
    """Sipariş zararda mı (K37 kesin zarar, ürün kuralıyla aynı).

    Net kâr varsa o; yoksa bilinen giderlerle kâr negatifse zarar kesindir
    (eksik kalemler kârı yalnız düşürür).
    """
    if totals.net_profit is not None:
        return "net_profit" if totals.net_profit < 0 else None
    if totals.known_expenses_profit >= 0:
        return None
    if set(totals.missing_items) == {MissingItem.PRODUCT_COST}:
        return "contribution_before_cost"
    return "known_expenses"


def build_order_rows(result: ProfitResult) -> list[OrderRow]:
    by_order: dict[str, list[LineResult]] = {}
    for line in sort_lines(result.lines):
        by_order.setdefault(line.order_number, []).append(line)
    rows = []
    for number, lines in by_order.items():
        active = [line for line in lines if line.status is not Status.CANCELLED]
        totals = order_totals(active) if active else None
        rows.append(
            OrderRow(
                order_number=number,
                cancelled=not active,
                cancelled_line_count=len(lines) - len(active),
                totals=totals,
                certainty=summarize_certainty(active) if active else Certainty.CANCELLED,
                loss_reason=None if totals is None else order_loss_reason(totals),
                awaiting_payout=any(line.status is Status.ESTIMATED for line in active),
                unexpected_deduction=any(
                    WarningCode.UNEXPECTED_DEDUCTION in line.warnings for line in active
                ),
                status_counts=status_counts(lines),
                barcodes=tuple(dict.fromkeys(line.barcode for line in lines)),
            )
        )
    return rows


def filter_orders(rows: Iterable[OrderRow], name: OrderFilter, number: str | None) -> list[OrderRow]:
    """Süzgeç ve sipariş no ile TAM eşleşme araması (kısmi eşleşme yok)."""
    selected = [r for r in rows if number is None or r.order_number == number]
    if name == "loss":
        return [r for r in selected if r.loss_reason is not None]
    if name == "awaiting_payout":
        return [r for r in selected if r.awaiting_payout]
    if name == "unexpected_deduction":
        return [r for r in selected if r.unexpected_deduction]
    return selected


def order_sort_value(row: OrderRow, sort: OrderSort, ordered_at: datetime | None) -> Decimal | None:
    """Sıralama değeri; hesaplanamayan (None) her yönde SONA gider.

    `date`: sipariş anı (mikrosaniye, tam sayı). `net_profit`: net kâr; null ama zarar kesinse
    (AD-04 deseni, ürün listesindeki gibi) bilinen değer (eksik giderler hariç kâr) kullanılır,
    böylece kesin zararlı sipariş `asc` sıralamada belirsizlerden önce gelir.
    İptal sipariş her yönde sonda.
    """
    if sort == "date":
        return None if ordered_at is None else Decimal((ordered_at - _EPOCH) // _MICROSECOND)
    if row.totals is None:
        return None
    if row.totals.net_profit is None and row.loss_reason is not None:
        return row.totals.known_expenses_profit
    return row.totals.net_profit


def order_page(
    rows: Sequence[OrderRow],
    dates: dict[str, datetime],
    sort: OrderSort,
    order: SortOrder,
    limit: int,
    cursor: str | None,
    fingerprint: str,
    codec: CursorCodec,
) -> tuple[list[OrderRow], str | None]:
    return value_page(
        rows,
        lambda r: order_sort_value(r, sort, dates.get(r.order_number)),
        lambda r: r.order_number,
        order,
        limit,
        cursor,
        fingerprint,
        codec,
    )


async def order_dates(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    numbers: Sequence[str],
    lower: datetime,
    upper: datetime,
) -> dict[str, datetime]:
    """Siparişlerin DÖNEM İÇİNDEKİ ilk paket anı (SU-02).

    Motor dönemi paket düzeyinde seçer (`ordered_at` İstanbul günü [lower, upper) içinde); kart yalnız dönem
    içi paketlerin satırlarını topladığından tarih de aynı paketlerden gelir: dönem dışı paket tarihi dönem
    kartında görünmez. Tek sorgu, dizi parametresi (bağlayıcı sayısı sınırına takılmaz).
    """
    if not numbers:
        return {}
    found = await db.execute(
        select(Order.order_number, func.min(Order.ordered_at))
        .where(
            Order.tenant_id == tenant_id,
            Order.marketplace_account_id == account_id,
            Order.ordered_at >= lower,
            Order.ordered_at < upper,
            Order.order_number == any_(bindparam("numbers", list(numbers), type_=ARRAY(Text))),
        )
        .group_by(Order.order_number)
    )
    return {number: moment for number, moment in found.all()}


async def order_in_period(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, number: str, lower: datetime, upper: datetime
) -> bool:
    """Siparişin dönem içinde en az bir paketi var mı (SU-04: yoksa `q` araması motoru çalıştırmaz)."""
    found = await db.execute(
        select(Order.id)
        .where(
            Order.tenant_id == tenant_id,
            Order.marketplace_account_id == account_id,
            Order.order_number == number,
            Order.ordered_at >= lower,
            Order.ordered_at < upper,
        )
        .limit(1)
    )
    return found.first() is not None


# --------------------------------------------------------------------------- uyarılar

# Motorun ürettiği her uyarı kodu için kısa Türkçe açıklama (docs/12 K05, K08, K14, K16, K18, K23, K28).
ALERT_MESSAGES: dict[WarningCode, str] = {
    WarningCode.MISSING_COST: "Ürün maliyeti girilmemiş; bu satırın net kârı hesaplanamıyor.",
    WarningCode.LOSS: (
        "Zararına satış: satırın net kârı (eksik kalem varsa bilinen giderlerle kâr) sıfırın altında."
    ),
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
    WarningCode.SERVICE_FEE_ESTIMATE_MISSING: (
        "Platform hizmet bedeli tahmini tanımlı değil; bu satırın net kârı hesaplanamıyor."
    ),
    WarningCode.CARGO_DESI_DEFAULT: "Siparişte desi yok; hesabın varsayılan desisiyle tarife arandı.",
    WarningCode.REFUND_RECORD_PENDING: (
        "İade kaydı (claim) henüz gelmedi; ürün maliyeti ihtiyatla gider bırakıldı."
    ),
    WarningCode.CARGO_MISSING_LINES: "Dönemde gönderi kargosu eksik satırlar var; dönem net kârı kısmi.",
    WarningCode.SERVICE_FEE_MISSING_LINES: "Dönemde hizmet bedeli eksik satırlar var; dönem net kârı kısmi.",
    WarningCode.REFUND_RECORD_PENDING_LINES: "Dönemde iade kaydı beklenen satırlar var.",
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
class AlertBreakdownItem:
    """Karşılaştırma kalemi (KDV hariç). `compared`: kalem fark toplamına girdi mi (K38: kargo ve hizmet
    bedeli yalnız tahmini tanımlı VE kesin değeri gelmişse girer; komisyon her zaman girer). Giren kalemlerin
    `difference` toplamı uyarının `difference` değerine eşittir."""

    item: Literal["commission", "outbound_shipping", "platform_service_fee"]
    estimated: Decimal | None
    actual: Decimal | None
    compared: bool
    difference: Decimal | None


def alert_breakdown(comparison: LineComparison) -> tuple[AlertBreakdownItem, ...]:
    """Motorun karşılaştırma bloğundan kalem dökümü (yeni hesap yok; yalnız fark = kesin - tahmini)."""
    rows: list[AlertBreakdownItem] = [
        AlertBreakdownItem(
            "commission",
            comparison.commission_estimated,
            comparison.commission_actual,
            True,
            comparison.commission_actual - comparison.commission_estimated,
        )
    ]
    for item, estimated, actual in (
        ("outbound_shipping", comparison.shipping_outbound_estimated, comparison.shipping_outbound_actual),
        (
            "platform_service_fee",
            comparison.platform_service_fee_estimated,
            comparison.platform_service_fee_actual,
        ),
    ):
        compared = estimated is not None and actual is not None
        rows.append(
            AlertBreakdownItem(
                item,  # type: ignore[arg-type]
                estimated,
                actual,
                compared,
                actual - estimated if estimated is not None and actual is not None else None,
            )
        )
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class AlertItem:
    """Tek uyarı: satır uyarısı (`line`) ya da dönem uyarısı (`period`)."""

    code: WarningCode
    scope: Literal["period", "line"]
    order_number: str | None = None
    package_id: int | None = None
    line_id: int | None = None
    barcode: str | None = None
    # ZARAR için satırın net kârı (eksik kalem varsa null) ve bilinen giderlerle kâr (K37 kesin zarar);
    # BEKLENMEYEN_KESINTI için karşılaştırmanın farkı ve eşiği.
    net_profit: Decimal | None = None
    known_expenses_profit: Decimal | None = None
    difference: Decimal | None = None
    threshold: Decimal | None = None
    # BEKLENMEYEN_KESINTI için motorun `karsilastirma` bloğundan kalem dökümü (SU-05) ve kargo tahmininin
    # varsayılan desiyle yapılıp yapılmadığı (AD-05); diğer kodlarda None.
    breakdown: tuple[AlertBreakdownItem, ...] | None = None
    default_desi_used: bool | None = None


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
                    known_expenses_profit=line.items.known_expenses_profit
                    if code is WarningCode.LOSS
                    else None,
                    difference=line.comparison.difference
                    if code is WarningCode.UNEXPECTED_DEDUCTION and line.comparison
                    else None,
                    threshold=line.comparison.threshold
                    if code is WarningCode.UNEXPECTED_DEDUCTION and line.comparison
                    else None,
                    breakdown=alert_breakdown(line.comparison)
                    if code is WarningCode.UNEXPECTED_DEDUCTION and line.comparison
                    else None,
                    default_desi_used=line.comparison.shipping_estimate_default_desi
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
