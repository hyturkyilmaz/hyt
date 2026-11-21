"""K29-K32: düşük güvenli kurallar için yer tutucu ve "teyit bekliyor" bayrağı.

Bu kurallar altın testlerde yoktur ve docs/12 §9 teyitleri gelmeden tahmini hesap üretilmez. Motor:
- tanınan ama kuralı belirsiz ekstre tiplerini (TyDiscount, TyCoupon, ProvisionPositive/Negative,
  DeliveryFee) gelir ve komisyon hesabına docs/12'deki v1 kuralı kadar katar (K29, K30, K32),
- sistemin bilmediği ekstre tiplerini hesaba katmaz,
- ikisinde de satıra/döneme teyit bekleyen kural kimliğini ekler (`teyit_bekliyor`).

Genişletme: bir kural teyit edilince `LOW_CONFIDENCE_RULES` kaydı kaldırılır, hesap ilgili kural modülüne
taşınır ve altın test senaryosu eklenir (docs/12 "Uygulama notları").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.profit.constants import COMMISSION_SIGN
from app.profit.inputs import CompensationTicket


@dataclass(frozen=True, slots=True)
class LowConfidenceRule:
    """Teyit bekleyen kuralın künyesi (arayüzde "teyit bekliyor" rozeti için)."""

    rule_id: str
    title: str
    confirmation_item: int  # docs/12 §9 madde numarası


LOW_CONFIDENCE_RULES: Mapping[str, LowConfidenceRule] = MappingProxyType(
    {
        "K05": LowConfidenceRule("K05", "Bilinmeyen ekstre işlem tipi (hesaba katılmadı)", 4),
        "K29": LowConfidenceRule("K29", "Teslimat ücreti (DeliveryFee)", 11),
        "K30": LowConfidenceRule("K30", "Kurumsal faturalı sipariş (TyDiscount, TyCoupon)", 3),
        "K31": LowConfidenceRule("K31", "Kargo tazmini (TEX), hesaba katılmadı", 11),
        "K32": LowConfidenceRule("K32", "Gramaj provizyonu ve işçilik bedeli", 12),
    }
)

# Tanınan ekstre tiplerinden teyit bekleyenlerin kural kimliği.
ROW_TYPE_RULES: Mapping[str, str] = MappingProxyType(
    {
        "DeliveryFee": "K29",
        "DeliveryFeeCancel": "K29",
        "TyDiscount": "K30",
        "TyCoupon": "K30",
        "ProvisionPositive": "K32",
        "ProvisionNegative": "K32",
    }
)


def pending_rule_for(request_type: str) -> str | None:
    """Ekstre istek tipi teyit bekliyorsa kural kimliği; tanınmayan tip K05 sayılır; normal tipte None."""
    if request_type in ROW_TYPE_RULES:
        return ROW_TYPE_RULES[request_type]
    if request_type not in COMMISSION_SIGN:
        return "K05"
    return None


def pending_rules_for_tickets(tickets: Iterable[CompensationTicket]) -> set[str]:
    """K31: tazmin kaydı varsa dönem düzeyinde teyit bayrağı (tutar hesaba katılmaz)."""
    return {"K31" for _ in tickets}
