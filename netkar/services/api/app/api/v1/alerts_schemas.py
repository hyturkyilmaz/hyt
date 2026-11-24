"""Uyarı API'sinin istek ve yanıt şemaları (ADR-0009 §8.2, D6).

Kurallar:

- Tüm şemalar `extra="forbid"`: bilinmeyen alan 422 (toplu atama, API3:2023). Geçiş gövdesinde `resolved` yoktur
  (yalnız sistem yazar); şema `to` alanını `read | open | muted` ile sınırlar.
- Para ve oran alanları JSON'da DECIMAL DİZGESİ olarak döner ("5.00"). Girdide dizge ya da JSON sayısı kabul
  edilir; float aritmetiği yapılmaz (en kısa gösterim Decimal'e çevrilir). Alan aralıkları migrasyon 0025 CHECK
  kısıtlarıyla birebir aynıdır (aralık dışı 422).
- Doğrulama hataları RFC 9457 `errors: [{field, code}]` biçimindedir ve girdi değerini yansıtmaz (genel işleyici).
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.alerts.types import AlertRule

# Dört kural adı (migrasyon 0025 CHECK listesiyle aynı sıra).
RuleName = Literal["ZARARINA_SATIS", "REKLAM_KARI_YIYOR", "BEKLENMEYEN_KESINTI", "IADE_ORANI_ARTISI"]
RULE_NAMES: tuple[RuleName, ...] = (
    AlertRule.LOSS_MAKING_SALE.value,
    AlertRule.AD_EATS_PROFIT.value,
    AlertRule.UNEXPECTED_DEDUCTION.value,
    AlertRule.RETURN_RATE_INCREASE.value,
)
EventStatus = Literal["open", "read", "muted", "resolved"]
Severity = Literal["high", "medium"]
Scope = Literal["product", "order_line", "account"]
Channel = Literal["email", "push"]
DeliveryMode = Literal["off", "instant", "digest"]
Actor = Literal["user", "system"]

# İşaretli, yalnız ASCII rakam; çok uzun dizge doğrulamadan önce reddedilir.
_PLAIN_DECIMAL = re.compile(r"-?[0-9]{1,15}(?:\.[0-9]{1,10})?")
_CLOCK = re.compile(r"([01][0-9]|2[0-3]):[0-5][0-9]")


def _coerce_decimal(value: Any) -> Any:
    """float ve bool para değeri olamaz; JSON sayısı en kısa gösterimiyle, dizge sade biçimle Decimal olur."""
    if isinstance(value, bool):
        raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır.")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır.")
        return Decimal(repr(value))
    if isinstance(value, str):
        if not _PLAIN_DECIMAL.fullmatch(value):
            raise PydanticCustomError("decimal_invalid", "Sayı olmalıdır (örn. 12.50).")
        return Decimal(value)
    return value


def _clock(value: Any) -> Any:
    """Saat yalnız `HH:MM` dizgesi (saat dilimi, saniye ve esnek biçimler yok; Europe/Istanbul duvar saati)."""
    if not isinstance(value, str) or not _CLOCK.fullmatch(value):
        raise PydanticCustomError("clock_invalid", "Saat SS:DD biçiminde olmalıdır (örn. 22:00).")
    return value


def _unique_rules(value: list[RuleName]) -> list[RuleName]:
    if len(set(value)) != len(value):
        raise PydanticCustomError("rules_duplicate", "Kural adları tekrarlanamaz.")
    # Kanonik sıra: ETag ve karşılaştırma içerik sırasından bağımsız olsun.
    return [r for r in RULE_NAMES if r in value]


# Hesap eşikleri: numeric(14,2) ve CHECK aralıkları (migrasyon 0025 `alert_rule_settings`).
Amount = Annotated[
    Decimal, BeforeValidator(_coerce_decimal), Field(ge=0, le=1_000_000, max_digits=15, decimal_places=2)
]
SharePercent = Annotated[
    Decimal, BeforeValidator(_coerce_decimal), Field(ge=50, le=100, max_digits=5, decimal_places=2)
]
Points = Annotated[
    Decimal, BeforeValidator(_coerce_decimal), Field(ge=0, le=100, max_digits=5, decimal_places=2)
]
Clock = Annotated[str, BeforeValidator(_clock)]
RuleList = Annotated[list[RuleName], Field(max_length=4), AfterValidator(_unique_rules)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- olaylar
class AlertEventOut(_Strict):
    """Tek uyarı olayı. `payload` tutarları metin taşır (rules.py kanıt alanları; son müşteri verisi yoktur)."""

    id: str
    rule: RuleName
    scope: Scope
    # Kapsam önekli konu: `urun:<barkod>`, `satir:<sipariş no>|<paket>|<satır>`, `hesap:*` (ADR §4.1).
    subject: str
    severity: Severity
    status: EventStatus
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: int
    muted_until: datetime | None
    resolved_at: datetime | None
    payload: dict[str, Any]
    payload_version: int
    data_revision: int
    settings_revision: int


class AlertEventListOut(_Strict):
    items: list[AlertEventOut]
    next_cursor: str | None
    # Süzgeçten bağımsız: hesabın `open` olay sayısı ("Yeni (3)" sekmesi).
    open_count: int
    # Hesabın son BAŞARILI değerlendirmesi (yoksa null); `settings_revision` birleşik damgadır
    # (K44 kâr ayarı sürümü + eşik özeti; app/services/alert_evaluation.py).
    last_evaluated_at: datetime | None
    data_revision: int | None
    settings_revision: int | None


class TransitionOut(_Strict):
    id: str
    from_status: EventStatus
    to_status: EventStatus
    actor: Actor
    # Sistem geçişinde null.
    actor_user_id: str | None
    muted_until: datetime | None
    created_at: datetime


class AlertEventDetailOut(_Strict):
    event: AlertEventOut
    # Son `TRANSITIONS_LIMIT` kayıt eskiden yeniye döner; daha eskileri kesildiyse true.
    transitions: list[TransitionOut]
    truncated: bool


class TransitionIn(_Strict):
    """Kullanıcı geçişi. `resolved` kabul edilmez (yalnız sistem); `muted` için `muted_days` zorunlu (1-90)."""

    to: Literal["read", "open", "muted"]
    muted_days: Annotated[StrictInt, Field(ge=1, le=90)] | None = None

    @model_validator(mode="after")
    def _muted_days_rule(self) -> TransitionIn:
        if (self.to == "muted") != (self.muted_days is not None):
            raise PydanticCustomError(
                "muted_days_invalid", "muted_days yalnız muted geçişinde ve zorunlu olarak verilir."
            )
        return self


class TransitionResultOut(_Strict):
    event: AlertEventOut
    transition_id: str


class ReadAllOut(_Strict):
    """Toplu okundu sonucu: en çok `READ_ALL_LIMIT` olay işlenir; kalan varsa istemci yeniden çağırır."""

    updated: int
    remaining_open: int


# --------------------------------------------------------------------------- hesap eşikleri
class AlertSettingsIn(_Strict):
    """Hesap eşikleri (PUT tam değiştirme). `If-Match` başlığı zorunludur (GET'teki ETag)."""

    loss_min_amount: Amount
    ad_share_percent: SharePercent
    ad_min_spend: Amount
    deduction_notify_min: Amount
    return_min_diff_points: Points
    rules_enabled: RuleList


class AlertSettingsOut(_Strict):
    loss_min_amount: Decimal
    ad_share_percent: Decimal
    ad_min_spend: Decimal
    deduction_notify_min: Decimal
    return_min_diff_points: Decimal
    rules_enabled: list[RuleName]
    # Hiç kaydedilmediyse varsayılanlar döner (ADR §13 H9 önerisi): `is_default` true, `updated_at` null.
    is_default: bool
    updated_at: datetime | None


# --------------------------------------------------------------------------- kullanıcı tercihleri
class ChannelModes(_Strict):
    email: DeliveryMode
    push: DeliveryMode


class PreferenceMatrix(_Strict):
    """Kural x kanal matrisi: dört kural da zorunludur (kısmi matris belirsizlik doğurur)."""

    ZARARINA_SATIS: ChannelModes
    REKLAM_KARI_YIYOR: ChannelModes
    BEKLENMEYEN_KESINTI: ChannelModes
    IADE_ORANI_ARTISI: ChannelModes


class NotificationPreferencesIn(_Strict):
    matrix: PreferenceMatrix
    # Europe/Istanbul duvar saati, `SS:DD`.
    quiet_start: Clock
    quiet_end: Clock
    digest_hour: Annotated[StrictInt, Field(ge=0, le=23)]
    show_amounts_email: StrictBool
    show_amounts_push: StrictBool


class NotificationPreferencesOut(_Strict):
    matrix: PreferenceMatrix
    quiet_start: str
    quiet_end: str
    digest_hour: int
    show_amounts_email: bool
    show_amounts_push: bool
