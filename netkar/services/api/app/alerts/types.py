"""Uyarı kurallarının ortak değer tipleri (ADR-0009 §3, §4.1).

Hepsi saf ve değişmezdir: veritabanı, saat ve I/O yoktur. Kural sonucu `AlertCandidate` değeridir; kalıcı
olay (alert_events) yazımı sonraki dilimlerin işidir.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from app.profit.enums import Certainty

# Kanıt alanı değer tipleri: yalnız sayı, metin, mantıksal. Kişisel veri (ad, adres, e-posta) YOK.
EvidenceValue = int | str | bool | Decimal


class AlertRule(StrEnum):
    """ADR-0009 §2: dört bildirim kuralı."""

    LOSS_MAKING_SALE = "ZARARINA_SATIS"
    AD_EATS_PROFIT = "REKLAM_KARI_YIYOR"
    UNEXPECTED_DEDUCTION = "BEKLENMEYEN_KESINTI"
    RETURN_RATE_INCREASE = "IADE_ORANI_ARTISI"


class AlertScope(StrEnum):
    """alert_events.scope (ADR-0009 §4.1)."""

    PRODUCT = "product"
    ORDER_LINE = "order_line"
    ACCOUNT = "account"


class Severity(StrEnum):
    """alert_events.severity: zarar ve kesinti yüksek, reklam ve iade orta."""

    HIGH = "high"
    MEDIUM = "medium"


class NotifyMode(StrEnum):
    """Olayın bildirim üretip üretmeyeceği (olay her durumda açılır; panelde görünür).

    NORMAL: kullanıcı tercih matrisine göre anlık ya da özet. DIGEST_ONLY: yalnız günlük özet.
    NONE: bildirim yok, yalnız panel.
    """

    NORMAL = "normal"
    DIGEST_ONLY = "digest_only"
    NONE = "none"


class RuleStatus(StrEnum):
    """Kuralın çalışıp çalışmadığı: veri yoksa uyarı üretilmez ve durum açıkça ayrılır."""

    EVALUATED = "evaluated"
    NO_DATA = "no_data"


# Hesap kapsamının konusu (kapsam önekli, ürün barkoduyla çakışmaz).
ACCOUNT_SUBJECT = "hesap:*"


def normalize_account_id(account_id: str | UUID) -> str:
    """Hesap kimliğini kanonik küçük harfli tireli UUID metnine çevirir; UUID değilse ValueError."""
    return str(UUID(str(account_id)))


def product_subject(barcode: str) -> str:
    """Ürün konusu `urun:<barkod>`; barkodun baş ve son boşluğu atılır, boş barkod reddedilir."""
    clean = barcode.strip()
    if not clean:
        raise ValueError("barkod boş olamaz")
    return f"urun:{clean}"


def order_line_subject(order_number: str, package_id: int, line_id: int) -> str:
    """Sipariş satırı konusu `satir:<sipariş no>|<paket>|<satır>`."""
    return f"satir:{order_number.strip()}|{package_id}|{line_id}"


def dedupe_key(rule: AlertRule, account_id: str | UUID, subject: str) -> str:
    """ADR-0009 §4.1: `sha256(kural|hesap|konu)` onaltılık. Hesap kimliği kanonik UUID'ye çevrilir
    (büyük/küçük harf ve tire farkı aynı anahtarı verir). Pencere anahtara girmez."""
    raw = f"{rule.value}|{normalize_account_id(account_id)}|{subject}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def freeze_evidence(items: Mapping[str, EvidenceValue]) -> Mapping[str, EvidenceValue]:
    """Kanıt sözlüğünü salt okunur yapar (olay değerinin değişmezliği)."""
    return MappingProxyType(dict(items))


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    """Bir kuralın ürettiği aday olay (henüz kalıcı değil)."""

    rule: AlertRule
    scope: AlertScope
    # `urun:<barkod>`, `satir:<sipariş no>|<paket>|<satır>` ya da `hesap:*` (kapsam önekli).
    subject: str
    dedupe_key: str
    severity: Severity
    # K40: kesin ya da tahmini (bildirim metni "tahmini" sözcüğünü gösterir).
    certainty: Certainty
    notify: NotifyMode
    # Sayılarla kanıt alanları; tutarlar Decimal (kuruş), oranlar yüzde 2 ondalık.
    evidence: Mapping[str, EvidenceValue]


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Bir kural değerlendirmesinin sonucu. `NO_DATA` iken `candidates` boştur."""

    rule: AlertRule
    status: RuleStatus
    candidates: tuple[AlertCandidate, ...] = ()
    # Yalnız iade kuralı: Bonferroni için test edilen ürün sayısı `k` (diğerlerinde 0).
    tested_count: int = 0
