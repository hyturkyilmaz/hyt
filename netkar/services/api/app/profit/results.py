"""Kâr motoru çıktı alan modeli (docs/12 §7).

Alanların `wire` üst verisi, altın test şemasındaki (tests/golden/README.md) anahtar adıdır;
`schema_v1.render_result` bu üst veriden JSON uyumlu sözlük üretir. Para alanları kuruşa yuvarlanmış
Decimal'dir; hesaplanamayan alanlar None'dır (örn. maliyet girilmemişse net kâr).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.profit.enums import Certainty, InvoiceVatStatus, MissingItem, Source, Status, WarningCode


def wire(name: str) -> Any:
    """Alanın dış şemadaki anahtar adını işaretler."""
    return field(metadata={"wire": name})


@dataclass(frozen=True, slots=True)
class LineItems:
    """Satır kalemleri: satış alanları dışında hepsi KDV hariç gider (docs/12 §1)."""

    gross_sales_incl_vat: Decimal = wire("brut_satis_kdv_dahil")
    seller_discount_incl_vat: Decimal = wire("satici_indirimi_kdv_dahil")
    ty_discount_incl_vat: Decimal = wire("trendyol_indirimi_kdv_dahil")
    sales_incl_vat: Decimal = wire("satis_kdv_dahil")
    sales_excl_vat: Decimal = wire("satis_kdv_haric")
    refund_incl_vat: Decimal = wire("iade_kdv_dahil")
    refund_excl_vat: Decimal = wire("iade_kdv_haric")
    net_sales_excl_vat: Decimal = wire("net_satis_kdv_haric")
    product_cost: Decimal | None = wire("urun_maliyeti")
    commission: Decimal = wire("komisyon")
    shipping_outbound: Decimal = wire("kargo_gonderi")
    shipping_return: Decimal = wire("kargo_iade")
    platform_service_fee: Decimal = wire("platform_hizmet_bedeli")
    penalty: Decimal = wire("ceza")
    advertising: Decimal = wire("reklam")
    variable_expenses: Decimal = wire("degisken_giderler")
    total_expenses: Decimal | None = wire("toplam_gider")
    contribution_before_cost: Decimal = wire("maliyet_haric_katki")
    # K37: bilinen tüm giderlerle kâr (eksik kalem 0 sayılmaz, hariç tutulur). Tam satırda net kâra eşittir.
    known_expenses_profit: Decimal = wire("eksik_giderler_haric_kar")
    net_profit: Decimal | None = wire("net_kar")
    net_margin_percent: Decimal | None = wire("net_kar_marji_yuzde")


@dataclass(frozen=True, slots=True)
class LineVat:
    """K20: KDV bloğu (kâra girmez, bilgi)."""

    sales_vat: Decimal = wire("satis_kdv")
    refund_vat: Decimal = wire("iade_kdv")
    commission_vat: Decimal = wire("komisyon_kdv")
    shipping_vat: Decimal = wire("kargo_kdv")
    platform_service_fee_vat: Decimal = wire("platform_hizmet_bedeli_kdv")
    penalty_vat: Decimal = wire("ceza_kdv")
    product_cost_vat: Decimal | None = wire("urun_maliyeti_kdv")
    variable_expenses_vat: Decimal = wire("degisken_giderler_kdv")
    advertising_vat: Decimal = wire("reklam_kdv")
    vat_effect: Decimal = wire("kdv_etkisi")


@dataclass(frozen=True, slots=True)
class LineCashFlow:
    """K18, K21: nakit akışı bloğu. Stopaj yalnız burada görünür, kâra girmez."""

    seller_payout: Decimal = wire("trendyol_hakedis")
    invoice_deductions_incl_vat: Decimal = wire("fatura_kesintileri_kdv_dahil")
    withholding: Decimal = wire("stopaj")
    expected_net_collection: Decimal = wire("beklenen_net_tahsilat")


@dataclass(frozen=True, slots=True)
class LineSources:
    """Her kalemin kaynağı (kesin, tahmini, kullanıcı, ...)."""

    sales: Source = wire("satis")
    commission: Source = wire("komisyon")
    product_cost: Source = wire("urun_maliyeti")
    shipping_outbound: Source = wire("kargo_gonderi")
    shipping_return: Source = wire("kargo_iade")
    platform_service_fee: Source = wire("platform_hizmet_bedeli")
    penalty: Source = wire("ceza")
    variable_expenses: Source = wire("degisken_giderler")
    advertising: Source = wire("reklam")


@dataclass(frozen=True, slots=True)
class VariableExpenseDetail:
    name: str = wire("ad")
    amount_excl_vat: Decimal = wire("tutar_kdv_haric")


@dataclass(frozen=True, slots=True)
class AdDetail:
    record_id: str = wire("kayit")
    kind: Source = wire("tur")
    amount_excl_vat: Decimal = wire("tutar_kdv_haric")


@dataclass(frozen=True, slots=True)
class LineComparison:
    """K23, K38: ekstre gelmiş satırda tahmini ve kesin değerlerin karşılaştırması (KDV hariç)."""

    commission_estimated: Decimal = wire("komisyon_tahmini")
    commission_actual: Decimal = wire("komisyon_kesin")
    # K38: tahmini tanımsızsa (tarife ya da hizmet bedeli ayarı yok) None; toplamlara girmez.
    shipping_outbound_estimated: Decimal | None = wire("kargo_gonderi_tahmini")
    shipping_outbound_actual: Decimal | None = wire("kargo_gonderi_kesin")
    platform_service_fee_estimated: Decimal | None = wire("platform_hizmet_bedeli_tahmini")
    platform_service_fee_actual: Decimal | None = wire("platform_hizmet_bedeli_kesin")
    # AD-05: kargo tahmini siparişte desi olmadığı için hesabın varsayılan desisiyle yapıldı (yer tutucu,
    # beklenti değil): fark varsayımdan doğuyor olabilir. Yalnız bilgi alanı; uyarıları ve toplamları
    # DEĞİŞTİRMEZ.
    shipping_estimate_default_desi: bool = wire("kargo_tahmini_varsayilan_desi")
    compared_estimated_total: Decimal = wire("karsilastirilan_tahmini_toplam")
    compared_actual_total: Decimal = wire("karsilastirilan_kesin_toplam")
    difference: Decimal = wire("fark")
    threshold: Decimal = wire("esik")


@dataclass(frozen=True, slots=True)
class LineResult:
    """Sipariş satırı (lineId) kâr kırılımı (K25, docs/12 §7.1)."""

    order_number: str = wire("orderNumber")
    package_id: int = wire("shipmentPackageId")
    line_id: int = wire("lineId")
    barcode: str = wire("barcode")
    status: Status = wire("durum")
    quantity: int = wire("adet")
    refunded_quantity: int = wire("adet_iade")
    # K41: claim'siz `Return`'de bekleyen adet ve stoğa dönerse geri gelecek maliyet (yoksa 0 ve None).
    pending_refund_quantity: int = wire("iade_kaydi_bekleyen_adet")
    suspended_product_cost: Decimal | None = wire("askidaki_urun_maliyeti")
    # K40: kesin, tahmini, eksik, iptal. K37: kaynağı `eksik` olan kalemler (kanonik sıra).
    certainty: Certainty = wire("kesinlik")
    missing_items: tuple[MissingItem, ...] = wire("eksik_kalemler")
    items: LineItems = wire("kalemler")
    vat: LineVat = wire("kdv")
    cash_flow: LineCashFlow = wire("nakit_akisi")
    sources: LineSources = wire("kaynaklar")
    variable_expense_details: tuple[VariableExpenseDetail, ...] = wire("degisken_gider_detayi")
    ad_details: tuple[AdDetail, ...] = wire("reklam_detayi")
    comparison: LineComparison | None = wire("karsilastirma")
    warnings: tuple[WarningCode, ...] = wire("uyarilar")
    # K29-K32 (düşük güven): bu satırda teyit bekleyen kural kimlikleri; hesaba tahmini katılmaz.
    pending_confirmation: tuple[str, ...] = wire("teyit_bekliyor")


@dataclass(frozen=True, slots=True)
class MissingCounts:
    """K37: kalem başına eksik satır sayısı (ürün ve dönem)."""

    product_cost: int = wire("urun_maliyeti")
    outbound_shipping: int = wire("kargo_gonderi")
    platform_service_fee: int = wire("platform_hizmet_bedeli")


@dataclass(frozen=True, slots=True)
class CertaintyCounts:
    """K40: dönemin aktif satırlarının kesinlik dağılımı."""

    certain: int = wire("kesin")
    estimated: int = wire("tahmini")
    missing: int = wire("eksik")


@dataclass(frozen=True, slots=True)
class ProductTotals:
    """Ürün (barkod) toplamı: satırların yuvarlanmış değerlerinin toplamı, iptaller hariç (K25)."""

    barcode: str = wire("barcode")
    line_count: int = wire("satir_sayisi")
    quantity: int = wire("adet")
    refunded_quantity: int = wire("adet_iade")
    net_sales_excl_vat: Decimal = wire("net_satis_kdv_haric")
    product_cost: Decimal | None = wire("urun_maliyeti")
    commission: Decimal = wire("komisyon")
    shipping_outbound: Decimal = wire("kargo_gonderi")
    shipping_return: Decimal = wire("kargo_iade")
    platform_service_fee: Decimal = wire("platform_hizmet_bedeli")
    penalty: Decimal = wire("ceza")
    advertising_allocated: Decimal = wire("reklam_satirlara_dagitilan")
    advertising_without_sales: Decimal = wire("reklam_satissiz")
    variable_expenses: Decimal = wire("degisken_giderler")
    contribution_before_cost: Decimal = wire("maliyet_haric_katki")
    known_expenses_profit: Decimal = wire("eksik_giderler_haric_kar")
    net_profit: Decimal | None = wire("net_kar")
    net_margin_percent: Decimal | None = wire("net_kar_marji_yuzde")
    cost_missing: bool = wire("maliyet_eksik")
    missing_line_counts: MissingCounts = wire("eksik_kalem_satir_sayilari")
    certainty: Certainty = wire("kesinlik")
    advertising_spend: Decimal = wire("reklam_harcamasi")
    advertising_revenue: Decimal | None = wire("reklam_cirosu")
    roas: Decimal | None = wire("roas")
    breakeven_roas: Decimal | None = wire("basabas_roas")
    withholding: Decimal = wire("stopaj")


@dataclass(frozen=True, slots=True)
class PeriodLevelExpenses:
    """Ürüne dağıtılmayan, dönem düzeyi giderler (K14, K15, K19, K25)."""

    advertising_unsold_products: Decimal = wire("reklam_satissiz_urunler")
    advertising_undistributed: Decimal = wire("reklam_dagitilamayan")
    undistributed_penalty: Decimal = wire("dagitilmamis_ceza")
    early_payment_fee: Decimal = wire("erken_odeme_bedeli")
    unclassified_deduction: Decimal = wire("siniflandirilmamis_kesinti")


@dataclass(frozen=True, slots=True)
class PeriodCashFlow:
    """Dönem nakit akışı kalemleri (K18, K19). Stopaj ve erken ödeme girişi gider değildir."""

    withholding_calculated: Decimal = wire("stopaj_hesaplanan")
    withholding_statement: Decimal = wire("stopaj_ekstre")
    early_payment_cash_in: Decimal = wire("erken_odeme_nakit_girisi")


@dataclass(frozen=True, slots=True)
class FullLinesTotals:
    """K39: yalnız tam satırların (eksik kalemsiz) kalem kalem toplamı; pay ve payda aynı satır kümesi."""

    line_count: int = wire("satir_sayisi")
    net_sales_excl_vat: Decimal = wire("net_satis_kdv_haric")
    product_cost: Decimal = wire("urun_maliyeti")
    commission: Decimal = wire("komisyon")
    shipping_outbound: Decimal = wire("kargo_gonderi")
    shipping_return: Decimal = wire("kargo_iade")
    platform_service_fee: Decimal = wire("platform_hizmet_bedeli")
    penalty: Decimal = wire("ceza")
    advertising: Decimal = wire("reklam")
    variable_expenses: Decimal = wire("degisken_giderler")
    total_expenses: Decimal = wire("toplam_gider")
    net_profit: Decimal = wire("net_kar")
    net_margin_percent: Decimal | None = wire("net_kar_marji_yuzde")


@dataclass(frozen=True, slots=True)
class PeriodTotals:
    """Dönem toplamı (K25, docs/12 §7.3). İptal satırları girmez."""

    order_count: int = wire("siparis_sayisi")
    line_count: int = wire("satir_sayisi")
    net_sales_excl_vat: Decimal = wire("net_satis_kdv_haric")
    product_cost: Decimal = wire("urun_maliyeti")
    commission: Decimal = wire("komisyon")
    shipping_outbound: Decimal = wire("kargo_gonderi")
    shipping_return: Decimal = wire("kargo_iade")
    platform_service_fee: Decimal = wire("platform_hizmet_bedeli")
    penalty_allocated: Decimal = wire("ceza_satirlara_dagitilan")
    advertising_allocated: Decimal = wire("reklam_satirlara_dagitilan")
    variable_expenses: Decimal = wire("degisken_giderler")
    # K39 Revizyon 1: tam dönemde tüm aktif satırların net kârı; kısmi dönemde None (bilinmeyen terim).
    line_net_profit_total: Decimal | None = wire("satir_net_kar_toplami")
    period_level_expenses: PeriodLevelExpenses = wire("donem_duzeyi_giderler")
    period_level_expenses_total: Decimal = wire("donem_duzeyi_giderler_toplami")
    # K39 Revizyon 1: kısmi dönemde None; bilinen kısım `period_known_expenses_profit`'tedir.
    period_net_profit: Decimal | None = wire("donem_net_kar")
    # K39 Revizyon 1: her dönemde sayı; aktif satırların bilinen giderlerle kârı eksi dönem düzeyi giderler.
    period_known_expenses_profit: Decimal = wire("donem_eksik_giderler_haric_kar")
    net_profit_partial: bool = wire("net_kar_kismi")
    missing_cost_line_count: int = wire("maliyet_eksik_satir_sayisi")
    missing_line_counts: MissingCounts = wire("eksik_kalem_satir_sayilari")
    # Kısmi dönemde None (K39); gösterilebilecek tek marj `full_lines.net_margin_percent`.
    net_margin_percent: Decimal | None = wire("net_kar_marji_yuzde")
    full_lines: FullLinesTotals = wire("tam_satirlar")
    certainty: Certainty = wire("kesinlik")
    certainty_line_counts: CertaintyCounts = wire("kesinlik_satir_sayilari")
    vat_effect: Decimal = wire("kdv_etkisi")
    cash_flow: PeriodCashFlow = wire("nakit_akisi")
    warnings: tuple[WarningCode, ...] = wire("uyarilar")
    pending_confirmation: tuple[str, ...] = wire("teyit_bekliyor")


@dataclass(frozen=True, slots=True)
class ProfitResult:
    """Motorun tek çıktısı: satır, ürün, dönem ve kargo faturası KDV durumları."""

    lines: tuple[LineResult, ...] = wire("siparis_satirlari")
    products: tuple[ProductTotals, ...] = wire("urun_toplamlari")
    period: PeriodTotals = wire("donem_toplami")
    cargo_invoice_vat_status: Mapping[str, InvoiceVatStatus] = wire("kargo_faturasi_kdv_durumu")
