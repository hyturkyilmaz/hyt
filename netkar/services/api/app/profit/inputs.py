"""Kâr motoru girdi alan modeli.

Motor I/O yapmaz; veritabanı, ağ ve saat bağımlılığı yoktur. Tarihler girdi olarak gelir (sipariş günü
Europe/Istanbul takvim günüdür; dönüşümü içeri alım katmanı yapar, bkz. `schema_v1.istanbul_day`).
Tüm para alanları Decimal'dir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.profit.constants import CANCELLED_STATUSES, CARGO_INVOICE_TEXTS
from app.profit.settings import ProfitSettings


class ProfitInputError(ValueError):
    """Girdi tutarsız: motor tahminle devam etmez, çağıran düzeltmelidir."""


@dataclass(frozen=True, slots=True)
class OrderItem:
    """Satırın tek kalemi (`discountDetails[]`); gerçek indirimler kalem bazındadır (K03)."""

    item_id: str
    seller_discount: Decimal
    ty_discount: Decimal


@dataclass(frozen=True, slots=True)
class OrderLine:
    """Sipariş satırı (`lines[]`). `unit_gross`: birim brüt fiyat (KDV dahil)."""

    line_id: int
    barcode: str
    quantity: int
    unit_gross: Decimal
    vat_rate: Decimal
    commission_rate: Decimal
    items: tuple[OrderItem, ...]
    # Ürün kartındaki birim desi (kargo dağıtım ağırlığı, K09); yoksa None.
    unit_desi: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ProfitInputError(f"lineId {self.line_id}: adet en az 1 olmalı")
        if len(self.items) != self.quantity:
            raise ProfitInputError(f"lineId {self.line_id}: kalem sayısı adede eşit olmalı")


@dataclass(frozen=True, slots=True)
class Order:
    """Sipariş paketi (`getShipmentPackages` alt kümesi). `order_day`: İstanbul takvim günü."""

    order_number: str
    package_id: int
    order_day: date
    status: str
    carrier: str
    lines: tuple[OrderLine, ...]
    cargo_deci: Decimal | None = None
    deci: Decimal | None = None
    who_pays: int | None = None

    @property
    def is_cancelled(self) -> bool:
        """K26: Cancelled ve UnSupplied iptal sayılır."""
        return self.status in CANCELLED_STATUSES


@dataclass(frozen=True, slots=True)
class CostRecord:
    """K16: ürün maliyeti (KDV hariç birim) ve geçerlilik başlangıcı."""

    barcode: str
    valid_from: date
    unit_cost_excl_vat: Decimal
    vat_rate: Decimal


@dataclass(frozen=True, slots=True)
class SettlementRow:
    """Cari hesap ekstresi `settlements` satırı. `request_type`: motorun çektiği istek tipi (K05)."""

    row_id: str
    request_type: str
    order_number: str
    barcode: str
    debt: Decimal
    credit: Decimal
    package_id: int | None = None
    commission_amount: Decimal | None = None
    commission_rate: Decimal | None = None
    seller_revenue: Decimal | None = None
    payment_order_id: int | None = None


@dataclass(frozen=True, slots=True)
class OtherFinancialRow:
    """Cari hesap ekstresi `otherfinancials` satırı (K13, K14, K18, K19)."""

    row_id: str
    request_type: str
    debt: Decimal
    credit: Decimal
    request_sub_type: str | None = None
    # Yanıttaki Türkçe `transactionType` metni (kargo faturası satırını tanımak için).
    type_text: str | None = None
    order_number: str | None = None
    payment_order_id: int | None = None
    # NetKâr eşleme tablosunun verdiği sınıf (`ceza`, `erken_odeme_bedeli`) ve KDV oranı (K14).
    category: str | None = None
    vat_rate: Decimal | None = None

    @property
    def is_cargo_invoice(self) -> bool:
        return self.type_text in CARGO_INVOICE_TEXTS


@dataclass(frozen=True, slots=True)
class CargoInvoiceItem:
    """Kargo faturası kalemi (`cargo-invoice/{seri}/items`)."""

    package_type: str
    order_number: str
    amount: Decimal
    desi: int


@dataclass(frozen=True, slots=True)
class CargoInvoice:
    serial_number: str
    items: tuple[CargoInvoiceItem, ...]


@dataclass(frozen=True, slots=True)
class ClaimItem:
    """İade kalemi (`claimItems[]`). `returned_to_stock`: False ise ürün satılamaz (K10)."""

    order_line_item_id: str
    status: str
    returned_to_stock: bool = True


@dataclass(frozen=True, slots=True)
class Claim:
    order_number: str
    items: tuple[ClaimItem, ...]


@dataclass(frozen=True, slots=True)
class AdRecord:
    """K15: panel Excel'inden NetKâr iç şemasına aktarılmış reklam kaydı."""

    record_id: str
    start: date
    end: date
    spend: Decimal
    spend_includes_vat: bool
    barcode: str | None = None
    ad_revenue: Decimal | None = None


@dataclass(frozen=True, slots=True)
class CompensationTicket:
    """K31 (düşük güven, yer tutucu): kargo tazmini kaydı. Motor hesaba katmaz, yalnız teyit bayrağı koyar."""

    order_number: str
    status: str
    amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ProfitInput:
    """Motorun tek girdisi. Dönem seçimi (hangi siparişlerin dahil olduğu) çağıranındır."""

    orders: tuple[Order, ...]
    settings: ProfitSettings = field(default_factory=ProfitSettings)
    costs: tuple[CostRecord, ...] = ()
    # Satışı olmayan ürünler dahil katalog barkodları (K15 eşleme: barkod katalogda mı).
    catalog_barcodes: tuple[str, ...] = ()
    settlements: tuple[SettlementRow, ...] = ()
    other_financials: tuple[OtherFinancialRow, ...] = ()
    cargo_invoices: tuple[CargoInvoice, ...] = ()
    claims: tuple[Claim, ...] = ()
    ad_records: tuple[AdRecord, ...] = ()
    compensation_tickets: tuple[CompensationTicket, ...] = ()
