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
    """Satır ve dönem uyarı kodları (K05, K08, K14, K16, K23, K28)."""

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
