"""Motorun iç çalışma durumu: satır başına değişebilir birikim nesnesi.

Bu modül dışarıya sızmaz; `engine.calculate_profit` her çağrıda yeni `LineWork` nesneleri üretir ve
sonunda değişmez çıktı modeline çevirir (saf fonksiyon davranışı korunur).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction

from app.profit.enums import Source, WarningCode
from app.profit.inputs import AdRecord, Order, OrderLine, SettlementRow

ZERO = Decimal("0.00")


@dataclass(slots=True, eq=False)
class LineWork:
    """Bir sipariş satırının hesap boyunca biriken değerleri (kalemler KDV hariç, satış alanları ayrı)."""

    order: Order
    line: OrderLine
    cancelled: bool
    # K03: kalem toplamlarından brüt ve indirimler (KDV dahil).
    gross: Decimal
    seller_discount: Decimal
    ty_discount: Decimal
    # K27: bu satıra eşleşen ekstre satırları ve payları (aynı barkod birden çok satırdaysa adet oranı).
    matched: list[tuple[SettlementRow, Fraction]] = field(default_factory=list)
    has_sale: bool = False
    has_adjustment: bool = False
    # K04, K06: tam hassasiyetli (yuvarlanmamış) satış, iade ve komisyon (KDV dahil).
    sales_incl: Fraction = Fraction(0)
    refund_incl: Fraction = Fraction(0)
    # K41: yalnız `Return` satırlarından gelen iade (KDV dahil, tam hassasiyet).
    refund_return_incl: Fraction = Fraction(0)
    commission_exact: Fraction = Fraction(0)
    commission_estimated_excl: Decimal = ZERO
    commission_actual_sales_excl: Decimal = ZERO
    sales_excl: Decimal = ZERO
    sales_vat: Decimal = ZERO
    refund_excl: Decimal = ZERO
    refund_vat: Decimal = ZERO
    net_sales: Decimal = ZERO
    commission_excl: Decimal = ZERO
    commission_vat: Decimal = ZERO
    # K10, K16: iade adetleri ve ürün maliyeti (maliyet yoksa None).
    refunded_in_stock: int = 0
    refunded_scrapped: int = 0
    cost_excl: Decimal | None = ZERO
    cost_vat: Decimal | None = ZERO
    # K41: iade kaydı (claim) gelmemiş `Return` için bekleyen adet ve stoğa dönerse geri gelecek maliyet.
    pending_refund_quantity: int = 0
    suspended_cost: Decimal | None = None
    # K08, K12, K13, K14, K15, K17: diğer kalemler (KDV hariç ve KDV).
    ship_out_excl: Decimal = ZERO
    ship_out_vat: Decimal = ZERO
    # K23, K38: tahmini tutar tanımsızsa (tarife yok) None; 0 değildir.
    ship_out_estimated_excl: Decimal | None = None
    ship_out_actual: bool = False
    ship_ret_excl: Decimal = ZERO
    ship_ret_vat: Decimal = ZERO
    fee_excl: Decimal = ZERO
    fee_vat: Decimal = ZERO
    fee_estimated_excl: Decimal | None = None
    fee_actual: bool = False
    penalty_excl: Decimal = ZERO
    penalty_vat: Decimal = ZERO
    ad_excl: Decimal = ZERO
    ad_vat: Decimal = ZERO
    var_excl: Decimal = ZERO
    var_vat: Decimal = ZERO
    var_details: list[tuple[str, Decimal]] = field(default_factory=list)
    ad_details: list[tuple[str, Source, Decimal]] = field(default_factory=list)
    # Kaynak etiketleri.
    src_sales: Source = Source.ESTIMATED
    src_commission: Source = Source.ESTIMATED
    src_cost: Source = Source.USER
    src_ship_out: Source = Source.NONE
    src_ship_ret: Source = Source.NONE
    src_fee: Source = Source.NONE
    src_penalty: Source = Source.NONE
    src_var: Source = Source.NONE
    src_ad: Source = Source.NONE
    warnings: list[WarningCode] = field(default_factory=list)
    pending: set[str] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return not self.cancelled

    @property
    def quantity(self) -> int:
        return self.line.quantity


def group_by[K](works: Iterable[LineWork], key: Callable[[LineWork], K]) -> dict[K, list[LineWork]]:
    """Ekleme sırasını koruyarak gruplar."""
    groups: dict[K, list[LineWork]] = {}
    for w in works:
        groups.setdefault(key(w), []).append(w)
    return groups


def active_only(works: Iterable[LineWork]) -> list[LineWork]:
    return [w for w in works if w.active]


def distribution_weights(group: Sequence[LineWork]) -> list[Decimal]:
    """K09: grup içi dağıtım ağırlığı: tümünde ürün desisi varsa `desi x adet`, yoksa satış KDV hariç."""
    if all(w.line.unit_desi is not None for w in group):
        return [(w.line.unit_desi or Decimal(0)) * w.quantity for w in group]
    return [w.sales_excl for w in group]


def sales_weights(group: Sequence[LineWork]) -> list[Decimal]:
    """K13, K14, K17: sipariş düzeyi tutarlar satırlara KDV hariç satış oranıyla dağıtılır."""
    return [w.sales_excl for w in group]


def ad_in_period(work: LineWork, record: AdRecord) -> bool:
    """K15: sipariş günü kayıt dönemine düşüyor mu (uç günler dahil)."""
    return record.start <= work.order.order_day <= record.end
