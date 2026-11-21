"""Uyarı kuralı eşikleri: tek, değişmez ayar nesnesi (ADR-0009 §3, §13 H9).

Varsayılanlar H9 ÖNERİSİdir ("öneri, Hasan onayı bekliyor"); ilk 4 hafta pilot verisiyle gözden geçirilir.
Kiracı (hesap) ayarı tablosu bu dilimde YOKTUR: çağıran, kiracı değerlerini `with_overrides` ile verir.
Motorun sabit eşikleri (`app.profit.settings.WarningThresholds`) buradan etkilenmez.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from decimal import Decimal
from typing import Any

N0 = Decimal("0")
N5 = Decimal("5")
N50 = Decimal("50")
N100 = Decimal("100")
N5_00 = Decimal("5.00")
N10_00 = Decimal("10.00")
# numeric(14,2) üst sınırı (dışlayıcı).
MAX_AMOUNT = Decimal("1e12")
_DECIMAL_FIELDS = (
    "loss_min_amount",
    "ad_share_percent",
    "ad_min_spend",
    "deduction_notify_min",
    "return_min_diff_points",
)
N50_00 = Decimal("50.00")


@dataclass(frozen=True, slots=True)
class AlertThresholds:
    """Hesap başına ezilebilir bildirim eşikleri. Tutarlar KDV hariç TL, yüzdeler 100 üzerinden."""

    # Öneri, Hasan onayı bekliyor (H9): toplam zarar bu tutarın altındaysa olay açılmaz. 0 izinli.
    loss_min_amount: Decimal = N5_00
    # Öneri, Hasan onayı bekliyor (H9): reklam payı eşiği (reklam öncesi kârın yüzdesi); izinli aralık 50-100.
    ad_share_percent: Decimal = N100
    # Öneri, Hasan onayı bekliyor (H9): bu tutarın altındaki reklam harcaması kurala girmez.
    ad_min_spend: Decimal = N50_00
    # Öneri, Hasan onayı bekliyor (H9): kesinti farkı bunun altındaysa anlık değil yalnız özet.
    deduction_notify_min: Decimal = N10_00
    # Öneri, Hasan onayı bekliyor (H9): iade oranı farkı en az bu yüzde puanı olmalı.
    return_min_diff_points: Decimal = N5
    # Öneri, Hasan onayı bekliyor (H10): varsayılan desiyle tahmin edilen kargodan doğan kesinti bildirime
    # girmesin (False); olay yine açılır ve panelde görünür.
    notify_default_desi_deductions: bool = False

    def __post_init__(self) -> None:
        # Tür denetimi: tutar ve oran alanları yalnız Decimal (bool, int, float değil), sonlu ve en çok 2
        # ondalıklı (numeric(14,2) ile uyumlu); bool alan yalnız bool.
        for name in _DECIMAL_FIELDS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Decimal):
                raise TypeError(f"{name} Decimal olmalı")
            if not value.is_finite():
                raise ValueError(f"{name} sonlu olmalı")
            if value.as_tuple().exponent < -2:  # type: ignore[operator]
                raise ValueError(f"{name} en çok 2 ondalıklı olmalı")
            if abs(value) >= MAX_AMOUNT:
                raise ValueError(f"{name} numeric(14,2) sınırını aşıyor")
        if not isinstance(self.notify_default_desi_deductions, bool):
            raise TypeError("notify_default_desi_deductions bool olmalı")
        for name in ("loss_min_amount", "ad_min_spend", "deduction_notify_min"):
            if getattr(self, name) < N0:
                raise ValueError(f"{name} negatif olamaz")
        if not N50 <= self.ad_share_percent <= N100:
            raise ValueError("ad_share_percent 50 ile 100 arasında olmalı")
        if not N0 <= self.return_min_diff_points <= N100:
            raise ValueError("return_min_diff_points 0 ile 100 arasında olmalı")

    def with_overrides(self, overrides: Mapping[str, Decimal | bool | None] | None) -> AlertThresholds:
        """Kiracı ayarıyla ezer. None değer ve boş eşleme varsayılanı korur; bilinmeyen anahtar hatadır."""
        if not overrides:
            return self
        known = {f.name for f in fields(self)}
        unknown = set(overrides) - known
        if unknown:
            raise ValueError(f"bilinmeyen eşik: {sorted(unknown)}")
        changes: dict[str, Any] = {k: v for k, v in overrides.items() if v is not None}
        return replace(self, **changes)
