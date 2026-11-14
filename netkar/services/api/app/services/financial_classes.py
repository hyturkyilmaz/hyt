"""`otherfinancials` satırlarının NetKâr sınıfına eşlenmesi (docs/12 K14).

Trendyol ceza ve erken ödeme hizmet bedeli için ayrı bir `transactionType` vermez; satır
`DeductionInvoices` altında gelir ve yalnız metniyle (`transactionType`/`description`) ayırt edilir.
Aşağıdaki varsayılan kurallar KURGUSAL metin eşlemesidir ve CANLIDA DOĞRULANMAMIŞTIR (docs/12 §9
madde 7): pilot hesapla gerçek metinler çıkarılınca bu tablo güncellenir. Eşleşmeyen satır sınıfsız
kalır; motor onu ihtiyatla `siniflandirilmamis_kesinti` olarak kâra yansıtır ve uyarı verir.
Sınıflandırma okuma anında yapılır (veritabanında saklanmaz): tablo değişince eski satırlara da uygulanır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.profit.constants import CATEGORY_EARLY_PAYMENT_FEE, CATEGORY_PENALTY, DEDUCTION_INVOICES_TYPE


@dataclass(frozen=True, slots=True)
class ClassRule:
    """İstek tipi ve metin parçasına göre sınıf ve KDV oranı (yüzde)."""

    request_type: str
    text_contains: str  # küçük harfe çevrilmiş (casefold) karşılaştırılır
    category: str
    vat_rate: Decimal


DEFAULT_CLASS_RULES: tuple[ClassRule, ...] = (
    ClassRule(DEDUCTION_INVOICES_TYPE, "ceza", CATEGORY_PENALTY, Decimal(20)),
    ClassRule(DEDUCTION_INVOICES_TYPE, "erken ödeme hizmet", CATEGORY_EARLY_PAYMENT_FEE, Decimal(20)),
)


def classify_other_financial(
    request_type: str,
    request_sub_type: str,
    type_text: str | None,
    description: str | None,
    rules: Sequence[ClassRule] = DEFAULT_CLASS_RULES,
) -> tuple[str | None, Decimal | None]:
    """(sınıf, KDV oranı) döndürür; kural yoksa (None, None). Alt tipli satır sınıflanmaz."""
    if request_sub_type:
        return None, None
    haystack = f"{type_text or ''} {description or ''}".casefold()
    for rule in rules:
        if rule.request_type == request_type and rule.text_contains in haystack:
            return rule.category, rule.vat_rate
    return None, None
