"""Trendyol yanıt modelleri: YALNIZ kâr hesabı için gereken alanlar.

PII KURALI (docs/10_mimari.md §3.5, docs/50_guvenlik.md G16, EK-6): son müşteriye ait ad, soyad,
adres, telefon, TCKN, e-posta, müşteri kimliği, kullanıcı adı, vergi no/dairesi, koordinat,
fatura bağlantısı (örnekte TCKN içerebiliyor) ve serbest metin müşteri notları BURADA TANIMLI
DEĞİLDİR. Modeller `extra="ignore"` olduğundan bu alanlar ayrıştırma sırasında hiçbir nesneye
girmeden atılır; ham gövde yalnız istemci içinde, doğrulamadan önceki ara değerdir ve hiçbir yere
yazılmaz/loglanmaz. İl bilgisi gerekirse yalnız il adı ve il kodu (`ProvinceOnly`).
`tests/test_trendyol_models_pii.py` yasaklı takma adların hiçbir modelde bulunmadığını doğrular.

Alan adları yalnız resmi dokümanın ÖRNEK yanıtlarından alınmıştır (docs__*.md). OpenAPI
referans sayfalarının (reference__*.md) sipariş şeması örnek yanıtla çelişir (eski adlar: `id`,
`grossAmount`, `lines[].price`); örnek yanıt esas alınmıştır, paket kimliği için iki ad da kabul
edilir (doğrulanmadı, ADR-0003 K-N07). Parasal alanlar Decimal'dir (JSON ayrıştırmada float
kullanılmaz). Zaman damgaları ham milisaniye bırakılır: `orderDate` "GMT+3" etiketli, epoch mı
kaydırılmış mı belirsiz (doğrulanmadı), bu yüzden dönüşüm tüketicinin kararıdır.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field
from pydantic.alias_generators import to_camel


def _to_str(value: object) -> object:
    """Sayı olarak gelen kimlikleri (örn. cargoTrackingNumber) metne çevirir."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    return value


IdStr = Annotated[str, BeforeValidator(_to_str)]


class _TyModel(BaseModel):
    """Ortak taban: camelCase takma adlar, bilinmeyen alanlar atılır, değişmez."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore", frozen=True)


class PageResponse[T](_TyModel):
    """Sayfa tabanlı yanıt zarfı (siparişler, iadeler, finans, ürünler, sorular)."""

    page: int | None = None
    size: int | None = None
    total_pages: int | None = None
    total_elements: int | None = None
    next_page_token: str | None = None
    content: list[T] = Field(default_factory=list)


class StreamResponse[T](_TyModel):
    """Cursor tabanlı akış yanıtı (orders/stream)."""

    has_more: bool = False
    next_cursor: str | None = None
    size: int | None = None
    content: list[T] = Field(default_factory=list)


# --- Siparişler (v2/orders ve orders/stream) -------------------------------------------------


class ProvinceOnly(_TyModel):
    """Teslimat adresinden yalnız il adı ve il kodu. Diğer tüm adres alanları atılır."""

    city: str | None = None
    city_code: int | None = None


class DiscountDisplay(_TyModel):
    """Kampanya adı ve tutarı (paket düzeyi indirim gösterimi)."""

    display_name: str | None = None
    discount_amount: Decimal | None = None


class DiscountDetail(_TyModel):
    """Her adet (item) için indirim kırılımı."""

    line_item_id: IdStr | None = None
    line_item_price: Decimal | None = None
    line_item_seller_discount: Decimal | None = None
    line_item_ty_discount: Decimal | None = None


class OrderLine(_TyModel):
    """Sipariş satırı. Komisyon yalnız ORAN olarak gelir (tutar finans ekstresindedir)."""

    line_id: int | None = None
    barcode: str | None = None
    stock_code: str | None = None
    content_id: int | None = None
    product_name: str | None = None
    product_category_id: int | None = None
    quantity: int = 1
    line_gross_amount: Decimal | None = None
    line_total_discount: Decimal | None = None
    line_seller_discount: Decimal | None = None
    line_ty_discount: Decimal | None = None
    line_unit_price: Decimal | None = None
    vat_rate: Decimal | None = None
    commission: Decimal | None = None
    discount_details: list[DiscountDetail] = Field(default_factory=list)
    order_line_item_status_name: str | None = None
    cancelled_by: str | None = None
    cancel_reason: str | None = None
    cancel_reason_code: int | None = None
    business_unit: str | None = None
    sales_campaign_id: int | None = None
    currency_code: str | None = None


class ShipmentPackage(_TyModel):
    """Sipariş paketi (kâr hesabı alanları). Müşteri ve adres verisi YOKTUR."""

    shipment_package_id: int = Field(validation_alias=AliasChoices("shipmentPackageId", "id"))
    order_number: str
    status: str | None = None
    created_by: str | None = None
    origin_package_ids: list[int] | None = None
    order_date: int | None = None
    last_modified_date: int | None = None
    currency_code: str | None = None
    payment_method: str | None = None
    channel_id: int | None = None
    package_gross_amount: Decimal | None = None
    package_seller_discount: Decimal | None = None
    package_ty_discount: Decimal | None = None
    package_total_discount: Decimal | None = None
    package_total_price: Decimal | None = None
    discount_displays: list[DiscountDisplay] = Field(default_factory=list)
    cargo_provider_name: str | None = None
    # Kargo faturasındaki parcelUniqueId ile eşleşmesi doğrulanmadı (research/01 §2.4d).
    cargo_tracking_number: IdStr | None = None
    cargo_deci: Decimal | None = None
    deci: Decimal | None = None
    box_quantity: int | None = None
    who_pays: int | None = None
    commercial: bool | None = None
    micro: bool | None = None
    is_4p: bool | None = Field(default=None, alias="is4P")
    three_p_by_trendyol: bool | None = Field(default=None, alias="3pByTrendyol")
    # shipmentAddress yalnız il bilgisine indirgenir.
    shipment_province: ProvinceOnly | None = Field(default=None, alias="shipmentAddress")
    lines: list[OrderLine] = Field(default_factory=list)


# --- İadeler (claims) ------------------------------------------------------------------------


class ClaimOrderLine(_TyModel):
    """İade kalemindeki sipariş satırı özeti."""

    id: int | None = None
    barcode: str | None = None
    merchant_sku: str | None = None
    price: Decimal | None = None
    vat_base_amount: Decimal | None = None
    vat_rate: Decimal | None = None
    sales_campaign_id: int | None = None
    product_category: str | None = None


class ClaimReason(_TyModel):
    """İade nedeni (müşteri veya Trendyol)."""

    id: IdStr | None = None
    name: str | None = None
    code: str | None = None


class ClaimItemStatus(_TyModel):
    """İade kalemi durumu."""

    name: str | None = None


class ClaimItem(_TyModel):
    """İade kalemi. Serbest metin notlar (`note`, `customerNote`) PII içerebileceği için YOKTUR."""

    id: str | None = None
    order_line_item_id: int | None = None
    customer_claim_item_reason: ClaimReason | None = None
    trendyol_claim_item_reason: ClaimReason | None = None
    claim_item_status: ClaimItemStatus | None = None
    resolved: bool | None = None
    auto_accepted: bool | None = None
    accepted_by_seller: bool | None = None


class ClaimLine(_TyModel):
    """İade paketindeki bir ürün satırı ve kalemleri."""

    order_line: ClaimOrderLine | None = None
    claim_items: list[ClaimItem] = Field(default_factory=list)


class Claim(_TyModel):
    """İade paketi. Müşteri adı ve iade red paketindeki adres YOKTUR."""

    claim_id: str
    order_number: str | None = None
    order_shipment_package_id: int | None = None
    order_date: int | None = None
    claim_date: int | None = None
    last_modified_date: int | None = None
    channel_id: int | None = None
    cargo_provider_name: str | None = None
    items: list[ClaimLine] = Field(default_factory=list)


# --- Finans (cari hesap ekstresi) -----------------------------------------------------------


class FinancialTransaction(_TyModel):
    """settlements ve otherfinancials satırı (ortak şema). İşaretler dokümandaki tabloya göredir.

    `id` bir kaydı tekil tanımlar: pencere sınırında yinelenen kayıtlar bu alanla tekilleştirilir.
    DeductionInvoices kargo faturası satırında `id` kargo faturası seri numarasıdır.
    """

    id: IdStr
    transaction_date: int | None = None
    barcode: str | None = None
    transaction_type: str | None = None
    receipt_id: int | None = None
    description: str | None = None
    debt: Decimal | None = None
    credit: Decimal | None = None
    payment_period: int | None = None
    commission_rate: Decimal | None = None
    commission_amount: Decimal | None = None
    commission_invoice_serial_number: str | None = None
    seller_revenue: Decimal | None = None
    order_number: str | None = None
    payment_order_id: int | None = None
    payment_date: int | None = None
    order_date: int | None = None
    affiliate: str | None = None
    shipment_package_id: int | None = None


class PaymentOrder(_TyModel):
    """Hakediş ödeme emri (payment-order)."""

    id: int
    status: str | None = None
    amount: Decimal | None = None
    payout_date: int | None = None
    payment_type: str | None = None
    region_code: str | None = None


class CargoInvoiceItem(_TyModel):
    """Kargo faturası kalemi (sipariş numarası düzeyinde)."""

    shipment_package_type: str | None = None
    parcel_unique_id: int | None = None
    order_number: str | None = None
    amount: Decimal | None = None
    desi: int | None = None


# --- Ürünler ---------------------------------------------------------------------------------


class IdName(_TyModel):
    """Marka ve kategori özeti."""

    id: int | None = None
    name: str | None = None


class VariantPrice(_TyModel):
    """Varyant fiyatı."""

    sale_price: Decimal | None = None
    list_price: Decimal | None = None
    price_seen_by_customer: Decimal | None = None


class VariantStock(_TyModel):
    """Varyant stoğu."""

    quantity: int | None = None


class ApprovedVariant(_TyModel):
    """Onaylı ürün varyantı. `commission` oran olarak gelir; KDV dahil mi doğrulanmadı."""

    variant_id: int | None = None
    barcode: str | None = None
    stock_code: str | None = None
    commission: Decimal | None = None
    vat_rate: Decimal | None = None
    on_sale: bool | None = None
    price: VariantPrice | None = None
    stock: VariantStock | None = None
    channels: list[str] = Field(default_factory=list)


class ApprovedProduct(_TyModel):
    """Onaylı ürün (content) ve varyantları. Açıklama ve görseller alınmaz."""

    content_id: int
    product_main_id: str | None = None
    title: str | None = None
    brand: IdName | None = None
    category: IdName | None = None
    variants: list[ApprovedVariant] = Field(default_factory=list)


class InventoryVariant(_TyModel):
    """Stok ve fiyat odaklı v2 yanıtındaki varyant (bağlantı doğrulamasında kullanılan hafif yanıt)."""

    variant_id: int | None = None
    barcode: str | None = None
    sale_price: Decimal | None = None
    list_price: Decimal | None = None
    quantity: int | None = None
    stock_code: str | None = None


class InventoryContent(_TyModel):
    """Stok ve fiyat yanıtındaki content."""

    content_id: int
    product_main_id: str | None = None
    variants: list[InventoryVariant] = Field(default_factory=list)


# --- Müşteri soruları ------------------------------------------------------------------------


class QuestionAnswer(_TyModel):
    """Soruya verilen cevap."""

    text: str | None = None
    creation_date: int | None = None
    has_private_info: bool | None = None


class Question(_TyModel):
    """Müşteri sorusu. `customerId` ve `userName` (müşteri adı) YOKTUR.

    `text` serbest metindir ve müşteri kişisel veri yazmış olabilir: loglanmaz; saklama kararı
    sonraki turda (yalnız çekme kapsamı) verilecektir.
    """

    id: int
    text: str | None = None
    status: str | None = None
    creation_date: int | None = None
    product_name: str | None = None
    product_main_id: str | None = None
    public: bool | None = None
    answer: QuestionAnswer | None = None


# --- Bağlantı doğrulama sonucu ---------------------------------------------------------------


class ConnectionCheck(BaseModel):
    """Bağlantı doğrulama özeti: yalnız ürün sayısı (kişisel veri değil)."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    total_products: int | None = None
