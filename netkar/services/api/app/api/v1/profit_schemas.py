"""Kâr raporu uç noktalarının yanıt şemaları (`/v1/marketplace-accounts/{id}/profit/*`).

İKİ ADLANDIRMA, TEK KURAL: motor bloklarının (satır kırılımı, ürün toplamı, dönem toplamı) alan adları
motorun KABLO adlarıdır (`app/profit/results.py` `wire(...)`, `schema_v1.render_result` ve altın testlerle
aynı: `net_satis_kdv_haric`, `kalemler`, `uyarilar`); bu sayede panel ve altın testler aynı anahtarlarla
konuşur. Uç noktanın kendi zarfı (dönem, sayfalama, listeler için türetilmiş alanlar) İngilizce snake_case'tir
(mevcut uçlarla aynı). Kablo adı eşlemesi `tests/test_profit_api_schemas.py` ile motor alanlarına karşı korunur.

Para ve oran alanları JSON'da KURUŞ HASSASİYETLİ DECIMAL DİZGESİdir ("12.50"); float yoktur. Hesaplanamayan
alan (örn. maliyeti girilmemiş ürünün net kârı) `null`'dır.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.profit.enums import Source, Status, WarningCode
from app.profit.money import fmt


def _money(value: Decimal) -> str:
    text = fmt(value)
    assert text is not None  # fmt yalnız None için None döner
    return text


# JSON'da iki ondalıklı dizge (motorun `schema_v1.to_wire` çıktısıyla aynı biçim); Python tarafında Decimal.
Amount = Annotated[Decimal, PlainSerializer(_money, return_type=str, when_used="json")]


def w(wire_name: str) -> Any:
    """Alanın JSON anahtarı (motorun kablo adı); doğrulama Python adıyla yapılır (özniteliklerden)."""
    return Field(serialization_alias=wire_name)


class WireModel(BaseModel):
    """Motor çıktı nesnelerinden (`from_attributes`) üretilen, kablo adlarıyla serileşen model."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True, frozen=True)


class ApiModel(BaseModel):
    """Zarf modelleri: özniteliklerden ya da sözlükten kurulur, İngilizce adlarla serileşir."""

    model_config = ConfigDict(from_attributes=True, frozen=True)


# --------------------------------------------------------------------------- motor blokları (kablo adları)


class LineItemsOut(WireModel):
    """Satır kalemleri: satış alanları dışında hepsi KDV hariç gider (docs/12 §1)."""

    gross_sales_incl_vat: Amount = w("brut_satis_kdv_dahil")
    seller_discount_incl_vat: Amount = w("satici_indirimi_kdv_dahil")
    ty_discount_incl_vat: Amount = w("trendyol_indirimi_kdv_dahil")
    sales_incl_vat: Amount = w("satis_kdv_dahil")
    sales_excl_vat: Amount = w("satis_kdv_haric")
    refund_incl_vat: Amount = w("iade_kdv_dahil")
    refund_excl_vat: Amount = w("iade_kdv_haric")
    net_sales_excl_vat: Amount = w("net_satis_kdv_haric")
    product_cost: Amount | None = w("urun_maliyeti")
    commission: Amount = w("komisyon")
    shipping_outbound: Amount = w("kargo_gonderi")
    shipping_return: Amount = w("kargo_iade")
    platform_service_fee: Amount = w("platform_hizmet_bedeli")
    penalty: Amount = w("ceza")
    advertising: Amount = w("reklam")
    variable_expenses: Amount = w("degisken_giderler")
    total_expenses: Amount | None = w("toplam_gider")
    contribution_before_cost: Amount = w("maliyet_haric_katki")
    net_profit: Amount | None = w("net_kar")
    net_margin_percent: Amount | None = w("net_kar_marji_yuzde")


class LineVatOut(WireModel):
    """K20: KDV bloğu (kâra girmez, bilgi)."""

    sales_vat: Amount = w("satis_kdv")
    refund_vat: Amount = w("iade_kdv")
    commission_vat: Amount = w("komisyon_kdv")
    shipping_vat: Amount = w("kargo_kdv")
    platform_service_fee_vat: Amount = w("platform_hizmet_bedeli_kdv")
    penalty_vat: Amount = w("ceza_kdv")
    product_cost_vat: Amount | None = w("urun_maliyeti_kdv")
    variable_expenses_vat: Amount = w("degisken_giderler_kdv")
    advertising_vat: Amount = w("reklam_kdv")
    vat_effect: Amount = w("kdv_etkisi")


class LineCashFlowOut(WireModel):
    """K18, K21: nakit akışı bloğu. Stopaj yalnız burada görünür, kâra girmez."""

    seller_payout: Amount = w("trendyol_hakedis")
    invoice_deductions_incl_vat: Amount = w("fatura_kesintileri_kdv_dahil")
    withholding: Amount = w("stopaj")
    expected_net_collection: Amount = w("beklenen_net_tahsilat")


class LineSourcesOut(WireModel):
    """Her kalemin kaynağı (kesin, tahmini, kullanıcı, ...)."""

    sales: Source = w("satis")
    commission: Source = w("komisyon")
    product_cost: Source = w("urun_maliyeti")
    shipping_outbound: Source = w("kargo_gonderi")
    shipping_return: Source = w("kargo_iade")
    platform_service_fee: Source = w("platform_hizmet_bedeli")
    penalty: Source = w("ceza")
    variable_expenses: Source = w("degisken_giderler")
    advertising: Source = w("reklam")


class VariableExpenseDetailOut(WireModel):
    """VariableExpenseDetail(name: 'str', amount_excl_vat: 'Decimal')"""

    name: str = w("ad")
    amount_excl_vat: Amount = w("tutar_kdv_haric")


class AdDetailOut(WireModel):
    """AdDetail(record_id: 'str', kind: 'Source', amount_excl_vat: 'Decimal')"""

    record_id: str = w("kayit")
    kind: Source = w("tur")
    amount_excl_vat: Amount = w("tutar_kdv_haric")


class LineComparisonOut(WireModel):
    """K23: ekstre gelmiş satırda tahmini ve kesin değerlerin karşılaştırması (KDV hariç)."""

    commission_estimated: Amount = w("komisyon_tahmini")
    commission_actual: Amount = w("komisyon_kesin")
    shipping_outbound_estimated: Amount = w("kargo_gonderi_tahmini")
    shipping_outbound_actual: Amount | None = w("kargo_gonderi_kesin")
    platform_service_fee_estimated: Amount = w("platform_hizmet_bedeli_tahmini")
    platform_service_fee_actual: Amount | None = w("platform_hizmet_bedeli_kesin")
    compared_estimated_total: Amount = w("karsilastirilan_tahmini_toplam")
    compared_actual_total: Amount = w("karsilastirilan_kesin_toplam")
    difference: Amount = w("fark")
    threshold: Amount = w("esik")


class LineOut(WireModel):
    """Sipariş satırı (lineId) kâr kırılımı (K25, docs/12 §7.1)."""

    order_number: str = w("orderNumber")
    package_id: int = w("shipmentPackageId")
    line_id: int = w("lineId")
    barcode: str = w("barcode")
    status: Status = w("durum")
    quantity: int = w("adet")
    refunded_quantity: int = w("adet_iade")
    items: LineItemsOut = w("kalemler")
    vat: LineVatOut = w("kdv")
    cash_flow: LineCashFlowOut = w("nakit_akisi")
    sources: LineSourcesOut = w("kaynaklar")
    variable_expense_details: list[VariableExpenseDetailOut] = w("degisken_gider_detayi")
    ad_details: list[AdDetailOut] = w("reklam_detayi")
    comparison: LineComparisonOut | None = w("karsilastirma")
    warnings: list[WarningCode] = w("uyarilar")
    pending_confirmation: list[str] = w("teyit_bekliyor")


class ProductTotalsOut(WireModel):
    """Ürün (barkod) toplamı: satırların yuvarlanmış değerlerinin toplamı, iptaller hariç (K25)."""

    barcode: str = w("barcode")
    line_count: int = w("satir_sayisi")
    quantity: int = w("adet")
    refunded_quantity: int = w("adet_iade")
    net_sales_excl_vat: Amount = w("net_satis_kdv_haric")
    product_cost: Amount | None = w("urun_maliyeti")
    commission: Amount = w("komisyon")
    shipping_outbound: Amount = w("kargo_gonderi")
    shipping_return: Amount = w("kargo_iade")
    platform_service_fee: Amount = w("platform_hizmet_bedeli")
    penalty: Amount = w("ceza")
    advertising_allocated: Amount = w("reklam_satirlara_dagitilan")
    advertising_without_sales: Amount = w("reklam_satissiz")
    variable_expenses: Amount = w("degisken_giderler")
    contribution_before_cost: Amount = w("maliyet_haric_katki")
    net_profit: Amount | None = w("net_kar")
    net_margin_percent: Amount | None = w("net_kar_marji_yuzde")
    cost_missing: bool = w("maliyet_eksik")
    advertising_spend: Amount = w("reklam_harcamasi")
    advertising_revenue: Amount | None = w("reklam_cirosu")
    roas: Amount | None = w("roas")
    breakeven_roas: Amount | None = w("basabas_roas")
    withholding: Amount = w("stopaj")


class PeriodLevelExpensesOut(WireModel):
    """Ürüne dağıtılmayan, dönem düzeyi giderler (K14, K15, K19, K25)."""

    advertising_unsold_products: Amount = w("reklam_satissiz_urunler")
    advertising_undistributed: Amount = w("reklam_dagitilamayan")
    undistributed_penalty: Amount = w("dagitilmamis_ceza")
    early_payment_fee: Amount = w("erken_odeme_bedeli")
    unclassified_deduction: Amount = w("siniflandirilmamis_kesinti")


class PeriodCashFlowOut(WireModel):
    """Dönem nakit akışı kalemleri (K18, K19). Stopaj ve erken ödeme girişi gider değildir."""

    withholding_calculated: Amount = w("stopaj_hesaplanan")
    withholding_statement: Amount = w("stopaj_ekstre")
    early_payment_cash_in: Amount = w("erken_odeme_nakit_girisi")


class PeriodTotalsOut(WireModel):
    """Dönem toplamı (K25, docs/12 §7.3). İptal satırları girmez."""

    order_count: int = w("siparis_sayisi")
    line_count: int = w("satir_sayisi")
    net_sales_excl_vat: Amount = w("net_satis_kdv_haric")
    product_cost: Amount = w("urun_maliyeti")
    commission: Amount = w("komisyon")
    shipping_outbound: Amount = w("kargo_gonderi")
    shipping_return: Amount = w("kargo_iade")
    platform_service_fee: Amount = w("platform_hizmet_bedeli")
    penalty_allocated: Amount = w("ceza_satirlara_dagitilan")
    advertising_allocated: Amount = w("reklam_satirlara_dagitilan")
    variable_expenses: Amount = w("degisken_giderler")
    line_net_profit_total: Amount = w("satir_net_kar_toplami")
    period_level_expenses: PeriodLevelExpensesOut = w("donem_duzeyi_giderler")
    period_net_profit: Amount = w("donem_net_kar")
    net_profit_partial: bool = w("net_kar_kismi")
    missing_cost_line_count: int = w("maliyet_eksik_satir_sayisi")
    net_margin_percent: Amount | None = w("net_kar_marji_yuzde")
    vat_effect: Amount = w("kdv_etkisi")
    cash_flow: PeriodCashFlowOut = w("nakit_akisi")
    warnings: list[WarningCode] = w("uyarilar")
    pending_confirmation: list[str] = w("teyit_bekliyor")


# --------------------------------------------------------------------------- zarflar (İngilizce adlar)

BasisLabel = Literal["estimated", "settled", "mixed", "none"]


class PeriodOut(ApiModel):
    """Raporun kapsadığı İstanbul takvim günleri (uçlar dahil)."""

    start: date
    end: date
    days: int


class StatusCountsOut(ApiModel):
    """Satır sayıları, durum (K22) dağılımı; iptal satırları da sayılır."""

    estimated: int
    settled: int
    adjusted: int
    cancelled: int


class FeedNotesOut(ApiModel):
    """Motora verilmeyen kayıtların sayacı (sessiz veri kaybı olmasın); `total` hepsinin toplamı."""

    lines_missing_rates: int
    lines_bad_items: int
    orders_without_lines: int
    settlements_unmatched: int
    cargo_items_unmatched: int
    claim_items_unmatched: int
    total: int


class SummaryOut(ApiModel):
    """Dönem özeti: motorun dönem toplamı (kablo adlı), durum dağılımı, maliyeti eksik satırlar, besleyici notları."""

    period: PeriodOut
    totals: PeriodTotalsOut
    status_counts: StatusCountsOut
    missing_cost_line_count: int
    settings_configured: bool = Field(
        description="Kiracı kâr ayarları (kargo tarifesi, hizmet bedeli) tanımlı mı. Ayar tablosu gelene dek false: "
        "motor varsayılanları kullanılır ve net kâr kargo ve hizmet bedeli hariç sunulmalıdır."
    )
    tariff_missing_line_count: int = Field(
        description="KARGO_TARIFESI_EKSIK uyarılı aktif satır sayısı (gönderi kargosu 0 ve eksik kaynaklı)."
    )
    estimated_line_count: int = Field(description="Durumu tahmini (ekstresiz) olan satır sayısı.")
    feed_notes: FeedNotesOut


class ProductProfitItemOut(ApiModel):
    """Ürün kârlılık satırı. Paralar KDV hariçtir. `basis`: satırların kaynağı (tahmini mi kesin mi)."""

    barcode: str
    title: str | None
    line_count: int
    quantity: int
    refunded_quantity: int
    net_sales_excl_vat: Amount
    product_cost: Amount | None
    total_expenses: Amount | None
    net_profit: Amount | None
    net_margin_percent: Amount | None
    advertising_spend: Amount
    advertising_revenue: Amount | None
    roas: Amount | None
    breakeven_roas: Amount | None
    cost_missing: bool
    loss_reason: Literal["net_profit", "contribution_before_cost"] | None = Field(
        description="Ürün zararda ise nedeni. net_profit: net kâr hesaplandı ve negatif. contribution_before_cost: "
        "maliyet girilmediği için net kâr hesaplanamıyor ama maliyet hariç katkı negatif (zarar kesin). "
        "Zararda değilse ya da belirsizse null."
    )
    shipping_missing: bool = Field(
        description="Ürünün en az bir aktif satırında KARGO_TARIFESI_EKSIK var (gönderi kargosu 0 ve eksik kaynaklı)."
    )
    basis: BasisLabel = Field(
        description="estimated: hiç ekstreli satır yok; settled: tüm aktif satırlar ekstreli (settled/adjusted); "
        "mixed: karışık; none: aktif satır yok."
    )
    estimated_line_count: int
    settled_line_count: int
    adjusted_line_count: int


class ProductProfitListOut(ApiModel):
    """Ürün kârlılık listesi: sıralı, süzülmüş, imleçle sayfalı. `total_count` süzgeçten sonraki ürün sayısı."""

    period: PeriodOut
    sort: str
    order: str
    filter: str
    total_count: int
    items: list[ProductProfitItemOut]
    next_cursor: str | None


class ComparisonSummaryOut(ApiModel):
    """Tahmini-kesin karşılaştırması (K23) olan satırların toplamı (KDV hariç); fark = kesin - tahmini."""

    compared_line_count: int
    estimated_total: Amount
    actual_total: Amount
    difference: Amount


class ProductProfitDetailOut(ApiModel):
    """Tek ürünün dönem kırılımı: ürün toplamı (satışı yoksa null) ve satırlar (sayfalı)."""

    period: PeriodOut
    barcode: str
    title: str | None
    product: ProductTotalsOut | None
    basis: BasisLabel
    comparison: ComparisonSummaryOut
    total_lines: int
    lines: list[LineOut]
    next_cursor: str | None


class OrderTotalsOut(ApiModel):
    """Siparişin aktif satırlarının toplamı (dönem düzeyi giderler dahil değildir)."""

    line_count: int
    net_sales_excl_vat: Amount
    total_expenses: Amount | None
    net_profit: Amount | None
    cost_missing: bool


class OrderDetailOut(ApiModel):
    """Sipariş kırılımı: satırlar ve kalemleri. Müşteri kişisel verisi yoktur (DB'de de yoktur)."""

    period: PeriodOut
    order_number: str
    ordered_on: date
    totals: OrderTotalsOut
    status_counts: StatusCountsOut
    lines: list[LineOut]


class AlertOut(ApiModel):
    """Motorun ürettiği uyarı. `scope`: period (dönem) ya da line (satır). Önem derecesi motorda yoktur."""

    code: WarningCode
    scope: Literal["period", "line"]
    message: str
    order_number: str | None = None
    package_id: int | None = None
    line_id: int | None = None
    barcode: str | None = None
    net_profit: Amount | None = None
    difference: Amount | None = None
    threshold: Amount | None = None


class AlertCountOut(ApiModel):
    code: WarningCode
    count: int
    message: str


class UnavailableAlertOut(ApiModel):
    """Panelde beklenen ama motorun henüz üretmediği uyarı."""

    code: str
    reason: str


class AlertsOut(ApiModel):
    """Dönem uyarıları: kod başına sayım (tümü), uyarı listesi (imleçle sayfalı), henüz olmayanlar."""

    period: PeriodOut
    counts: list[AlertCountOut]
    total_count: int
    items: list[AlertOut]
    next_cursor: str | None
    not_yet_available: list[UnavailableAlertOut]
