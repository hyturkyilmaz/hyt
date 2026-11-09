"""Kâr motoru sabit kümeleri: durumlar, kaynaklar, uyarı kodları (docs/12_kar_motoru.md).

Değerler, altın testlerdeki (tests/golden) çıktı biçimiyle birebir aynıdır; adlar İngilizcedir.
"""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    """K22: sipariş satırı durumu."""

    ESTIMATED = "estimated"
    SETTLED = "settled"
    ADJUSTED = "adjusted"
    CANCELLED = "cancelled"


class Source(StrEnum):
    """Bir kalemin değerinin kaynağı (docs/12 §7.1 `kaynaklar`)."""

    ACTUAL = "kesin"
    ACTUAL_ALLOCATED = "kesin_dagitim"
    ESTIMATED = "tahmini"
    USER = "kullanici"
    MATCHED = "eslesen"
    ALLOCATED_ESTIMATE = "dagitim_tahmini"
    MISSING = "eksik"
    NONE = "yok"


class WarningCode(StrEnum):
    """Satır ve dönem uyarı kodları (K05, K08, K14, K16, K23, K28, K34, K35, K37, K41)."""

    MISSING_COST = "MALIYET_EKSIK"
    LOSS = "ZARAR"
    CARGO_DESI_MISMATCH = "KARGO_DESI_FARKI"
    UNEXPECTED_DEDUCTION = "BEKLENMEYEN_KESINTI"
    COMMISSION_RATE_DIFFERENT = "KOMISYON_ORANI_FARKLI"
    STATEMENT_INCONSISTENT = "EKSTRE_IC_TUTARSIZLIK"
    UNMATCHED_PAYOUT_ADJUSTMENT = "ESLESMEMIS_HAKEDIS_DUZELTMESI"
    CARGO_INVOICE_VAT_UNCERTAIN = "KARGO_FATURASI_KDV_BELIRSIZ"
    CARGO_TARIFF_MISSING = "KARGO_TARIFESI_EKSIK"
    UNCLASSIFIED_DEDUCTION = "SINIFLANDIRILMAMIS_KESINTI"
    MISSING_COST_LINES = "MALIYET_EKSIK_SATIRLAR_VAR"
    WITHHOLDING_STATEMENT_DIFF = "STOPAJ_EKSTRE_FARKI"
    # K35, K34, K41 (satır) ve K37, K41 (dönem özeti).
    SERVICE_FEE_ESTIMATE_MISSING = "HIZMET_BEDELI_TAHMINI_EKSIK"
    CARGO_DESI_DEFAULT = "KARGO_DESI_VARSAYILAN"
    REFUND_RECORD_PENDING = "IADE_KAYDI_BEKLENIYOR"
    CARGO_MISSING_LINES = "KARGO_EKSIK_SATIRLAR_VAR"
    SERVICE_FEE_MISSING_LINES = "HIZMET_BEDELI_EKSIK_SATIRLAR_VAR"
    REFUND_RECORD_PENDING_LINES = "IADE_KAYDI_BEKLENEN_SATIRLAR_VAR"


class InvoiceVatStatus(StrEnum):
    """K08: kargo faturası kalem tutarlarının KDV durumu tespiti."""

    INCLUDED = "dahil"
    EXCLUDED = "haric"
    UNKNOWN = "bilinmiyor"


class ExpenseKind(StrEnum):
    """K17: kullanıcı tanımlı değişken gider tipi."""

    PER_ORDER = "siparis_basi"
    PER_UNIT = "adet_basi"
    PERCENT_OF_SALES = "satis_yuzdesi"


class MissingItem(StrEnum):
    """K37: eksik olabilen kalemler (kanonik sıra bu tanım sırasıdır)."""

    PRODUCT_COST = "urun_maliyeti"
    OUTBOUND_SHIPPING = "kargo_gonderi"
    PLATFORM_SERVICE_FEE = "platform_hizmet_bedeli"


class Certainty(StrEnum):
    """K40: satır, ürün ve dönem kesinlik etiketi."""

    CERTAIN = "kesin"
    ESTIMATED = "tahmini"
    MISSING = "eksik"
    CANCELLED = "iptal"
    NONE = "yok"
