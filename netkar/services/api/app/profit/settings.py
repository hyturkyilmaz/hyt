"""Kâr motoru ayarları ve varsayılanları (docs/12 §8, §12 K33-K36).

Kullanıcı ayarlarının varsayılanı "tanımsız"dır (None ya da boş), 0 değildir: tanımsız kalem eksik sayılır,
bilerek girilmiş 0 sayılmaz (K35). Sürümlü ayarlar (kargo tarifesi, hizmet bedeli tahmini, değişken gider)
sipariş gününe göre çözülür: `başlangıç <= gün` olan en son sürüm; başlangıçsız sürüm en eskidir (K33).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.profit.enums import ExpenseKind

# Varsayılan değerler için sabitler (dataclass varsayılanında işlev çağrısı yapılmaz).
N0 = Decimal("0")
N1 = Decimal("1")
N5 = Decimal("5")
N20 = Decimal("20")
N5_00 = Decimal("5.00")
N0_05 = Decimal("0.05")
N0_01 = Decimal("0.01")

# K34: tarifede "diğer firmalar" yedeğinin firma adı.
FALLBACK_CARRIER = "*"


def _version_key(start: date | None) -> tuple[bool, date]:
    """Sıralama anahtarı: başlangıçsız sürüm (None) tarihlilerden önce gelir (K33)."""
    return (start is not None, start or date.min)


class SortedVersions[T]:
    """K33 sürüm seçimi için önceden sıralı liste: kurulumda bir kez sıralanır, seçim `bisect` ile O(log n).

    Her siparişte baştan süzüp sıralamak sipariş x sürüm x log(sürüm) maliyetliydi (denetim AO-01). Kural
    değişmedi: `başlangıç <= gün` olan en son sürüm; başlangıçsız sürüm en eskidir; aynı başlangıçta girişte
    sonra gelen kazanır (kararlı sıralama + `bisect_right`).
    """

    __slots__ = ("_keys", "_values")

    def __init__(self, versions: Sequence[tuple[date | None, T]]) -> None:
        ordered = sorted(versions, key=lambda item: _version_key(item[0]))
        self._keys = [_version_key(start) for start, _ in ordered]
        self._values = [value for _, value in ordered]

    def pick(self, day: date) -> T | None:
        """`başlangıç <= gün` olan en son sürüm; uygun sürüm yoksa None."""
        index = bisect_right(self._keys, (True, day))
        return self._values[index - 1] if index else None


def pick_version[T](versions: Sequence[tuple[date | None, T]], day: date) -> T | None:
    """K33: `başlangıç <= gün` olan en son sürüm; başlangıçsız sürüm en eskidir. Uygun sürüm yoksa None.

    Tek seferlik seçim içindir; çok sayıda seçimde (sipariş başına) `SortedVersions` kullanılır.
    """
    return SortedVersions(versions).pick(day)


@dataclass(frozen=True, slots=True)
class WarningThresholds:
    """K23: beklenmeyen kesinti ve fark eşikleri (docs/12 §6 önerisi; pilot verisiyle ayarlanır)."""

    # Mutlak eşik (TL): fark bunu ve oransal eşiği aşarsa BEKLENMEYEN_KESINTI.
    unexpected_deduction_amount: Decimal = N5_00
    # Oransal eşik (tahmini toplamın yüzdesi).
    unexpected_deduction_percent: Decimal = N5
    # Bu tutara kadar fark yuvarlama sayılır (K23); stopaj ekstre farkı (K18) için de kullanılır.
    rounding_tolerance: Decimal = N0_05
    # KOMISYON_ORANI_FARKLI için yüzde puanı toleransı.
    commission_rate_tolerance_points: Decimal = N0_01


@dataclass(frozen=True, slots=True)
class VariableExpense:
    """K17, K36: kullanıcı tanımlı değişken gider (KDV hariç tutar ya da yüzde), geçerlilik aralıklı."""

    name: str
    kind: ExpenseKind
    amount_excl_vat: Decimal = N0
    percent: Decimal = N0
    vat_rate: Decimal = N20
    # Uçlar dahil; boş uç sınırsız (K36).
    valid_from: date | None = None
    valid_to: date | None = None

    def applies_on(self, day: date) -> bool:
        """K36: sipariş günü `[başlangıç, bitiş]` aralığında mı."""
        return (self.valid_from is None or self.valid_from <= day) and (
            self.valid_to is None or day <= self.valid_to
        )


@dataclass(frozen=True, slots=True)
class TariffVersion:
    """K34: bir firmanın tarife sürümü. Basamaklar (en çok desi, KDV hariç fiyat), desi artan sırada."""

    brackets: tuple[tuple[Decimal, Decimal], ...]
    valid_from: date | None = None


@dataclass(frozen=True, slots=True)
class DatedAmount:
    """K35: başlangıç tarihli KDV hariç tutar (hizmet bedeli tahmini sürümü)."""

    amount_excl_vat: Decimal
    valid_from: date | None = None


@dataclass(frozen=True, slots=True)
class CargoTariff:
    """K08, K34: kargo tarifesi. firma -> sürümler. `*` firması diğer firmalar yedeğidir. Varsayılan boş."""

    steps: Mapping[str, tuple[TariffVersion, ...]] = field(default_factory=dict)
    # Firma başına önceden sıralı sürüm listesi (AO-01); `steps`'ten türetilir, karşılaştırmaya girmez.
    _index: dict[str, SortedVersions[tuple[tuple[Decimal, Decimal], ...]]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        index = {
            carrier: SortedVersions([(v.valid_from, v.brackets) for v in versions])
            for carrier, versions in self.steps.items()
        }
        object.__setattr__(self, "_index", index)

    @classmethod
    def unversioned(cls, raw: Mapping[str, Sequence[tuple[Decimal, Decimal]]]) -> CargoTariff:
        """Başlangıçsız tek sürümlü tarife (altın testlerin eski biçimi)."""
        return cls({carrier: (TariffVersion(tuple(brackets)),) for carrier, brackets in raw.items()})

    def lookup(self, carrier: str, desi: Decimal | None, day: date) -> Decimal | None:
        """K34: firmanın o gün geçerli sürümü varsa YALNIZ o kullanılır; desi bilinmiyorsa ya da en yüksek
        kademeyi aşıyorsa None (yedeğe düşülmez). Firmanın o gün geçerli sürümü yoksa `*` yedeği; o da
        yoksa None.
        """
        for key in (carrier, FALLBACK_CARRIER):
            versions = self._index.get(key)
            brackets = None if versions is None else versions.pick(day)
            if brackets is None:
                continue
            if desi is None:
                return None
            for upper, price in brackets:
                if desi <= upper:
                    return price
            return None
        return None


@dataclass(frozen=True, slots=True)
class ProfitSettings:
    """Kâr hesabı ayarları. Oranlar yüzde (20 = %20). `ProfitSettings()` = hiçbir kullanıcı ayarı yok."""

    # K07: commissionAmount KDV dahil mi (varsayılan evet; pilotta teyit edilecek, §9 madde 1).
    commission_includes_vat: bool = True
    commission_vat_rate: Decimal = N20
    shipping_vat_rate: Decimal = N20
    service_fee_vat_rate: Decimal = N20
    ad_vat_rate: Decimal = N20
    # K18: e-ticaret stopajı oranı (nakit akışı kalemi, gider değil).
    withholding_rate: Decimal = N1
    # K35: sipariş başı tahmini platform hizmet bedeli sürümleri (KDV hariç). Boş = tanımsız (eksik); tahmin
    # uydurulmaz. Açıkça girilmiş 0 tanımlıdır.
    service_fee_estimates: tuple[DatedAmount, ...] = ()
    # K08, K34: Trendyol anlaşmalı kargo tarifesi ve satıcı anlaşmalı (whoPays=1) tarife. Varsayılan boş.
    cargo_tariff: CargoTariff = field(default_factory=CargoTariff)
    seller_cargo_tariff: CargoTariff = field(default_factory=CargoTariff)
    # K34: siparişte desi yoksa kullanılan hesap varsayılanı (tanımsız: None).
    default_desi: Decimal | None = None
    # K08: fatura KDV tespit toleransı (taban; kalem başına en az 0,01).
    cargo_invoice_vat_tolerance: Decimal = N0_05
    thresholds: WarningThresholds = field(default_factory=WarningThresholds)
    variable_expenses: tuple[VariableExpense, ...] = ()
    # K35 sürümleri önceden sıralı (AO-01); `service_fee_estimates`'ten türetilir, karşılaştırmaya girmez.
    _fee_index: SortedVersions[Decimal] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        index = SortedVersions([(e.valid_from, e.amount_excl_vat) for e in self.service_fee_estimates])
        object.__setattr__(self, "_fee_index", index)

    def service_fee_estimate_on(self, day: date) -> Decimal | None:
        """K35: sipariş gününde geçerli hizmet bedeli tahmini (KDV hariç); tanımsızsa None."""
        return self._fee_index.pick(day)
