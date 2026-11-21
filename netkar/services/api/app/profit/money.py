"""Para yardımcıları: tek yuvarlama fonksiyonu, KDV ayrımı, en büyük kalan dağıtımı (K01, K02, K24).

Kural: float yok. Bölme gerektiren her işlem tam hassasiyetli `Fraction` ile yapılır ve kuruşa tek bir
yerde (`rnd`) ROUND_HALF_UP ile yuvarlanır; böylece Decimal bağlam hassasiyetinden kaynaklanan sınır
hataları (örneğin 10,025 değerinin 10,02 çıkması) oluşmaz.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

# Yuvarlanabilir her sayı türü (Decimal, tam hassasiyetli Fraction, int).
Number = Decimal | Fraction | int

ZERO = Decimal("0.00")
HUNDRED = Fraction(100)


def to_decimal(value: object) -> Decimal:
    """K01: girdiyi Decimal'e çevirir. float ve bool reddedilir; JSON number önce string yapılmalıdır."""
    if isinstance(value, bool | float):
        raise TypeError(f"float/bool para değeri olarak kullanılamaz: {value!r}")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | str):
        return Decimal(str(value))
    raise TypeError(f"Decimal'e çevrilemeyen tür: {type(value).__name__}")


def rnd(value: Number) -> Decimal:
    """K01: kuruşa ROUND_HALF_UP (yarım kuruş sıfırdan uzağa: -0,005 -> -0,01).

    Sonuç her zaman iki ondalıklı Decimal'dir ve negatif sıfır üretmez.
    """
    exact = Fraction(value)
    cents = math.floor(abs(exact) * 100 + Fraction(1, 2))
    if exact < 0:
        cents = -cents
    return Decimal(cents).scaleb(-2)


def split_inclusive(gross: Number, vat_rate: Number) -> tuple[Decimal, Decimal]:
    """K02 (KDV dahilden): `haric = rnd(dahil / (1 + r/100))`, `kdv = rnd(dahil) - haric`.

    Böylece `rnd(dahil) == haric + kdv` her zaman tutar. `vat_rate` yüzde olarak verilir (20 = %20).
    """
    haric = rnd(Fraction(gross) * 100 / (100 + Fraction(vat_rate)))
    return haric, rnd(gross) - haric


def split_exclusive(net: Number, vat_rate: Number) -> tuple[Decimal, Decimal]:
    """K02 (KDV hariçten): `haric = rnd(haric_exact)`, `kdv = rnd(haric_exact x r/100)`."""
    return rnd(net), rnd(Fraction(net) * Fraction(vat_rate) / 100)


def allocate(total: Number, weights: Sequence[Number]) -> list[Decimal]:
    """K24: kuruşa yuvarlanmış `total` tutarını en büyük kalan (Hamilton) yöntemiyle dağıtır.

    - Kalan kuruşlar, kesirli payı en büyük olandan başlayarak birer kuruş verilir; eşitlikte listedeki
      ilk öğe önce alır.
    - Negatif ağırlık 0 sayılır; tüm ağırlıklar 0 ise eşit ağırlık kullanılır.
    - Negatif toplam, mutlak değeri dağıtılıp işareti geri verilerek işlenir.
    - Parçaların toplamı her zaman `rnd(total)` değerine eşittir.
    """
    count = len(weights)
    if count == 0:
        return []
    cleaned = [max(Fraction(w), Fraction(0)) for w in weights]
    weight_sum = sum(cleaned, Fraction(0))
    if weight_sum == 0:
        cleaned = [Fraction(1)] * count
        weight_sum = Fraction(count)
    rounded = rnd(total)
    sign = -1 if rounded < 0 else 1
    cents = int(abs(rounded) * 100)
    raw = [Fraction(cents) * w / weight_sum for w in cleaned]
    floors = [math.floor(r) for r in raw]
    leftover = cents - sum(floors)
    order = sorted(range(count), key=lambda i: (-(raw[i] - floors[i]), i))
    for i in order[:leftover]:
        floors[i] += 1
    return [Decimal(sign * f).scaleb(-2) for f in floors]


def percent_of(part: Number, whole: Number) -> Decimal | None:
    """`part / whole x 100` iki ondalık (marj yüzdesi gibi). Payda 0 ise None."""
    if Fraction(whole) == 0:
        return None
    return rnd(Fraction(part) * 100 / Fraction(whole))


def ratio(part: Number, whole: Number) -> Decimal | None:
    """`part / whole` iki ondalık (ROAS gibi oran). Payda 0 ise None."""
    if Fraction(whole) == 0:
        return None
    return rnd(Fraction(part) / Fraction(whole))


def fmt(value: Decimal | None) -> str | None:
    """Çıktı biçimi: kuruş hassasiyetinde string (örn. "4.17"); None korunur."""
    if value is None:
        return None
    return format(rnd(value), "f")
