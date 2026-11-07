"""Kâr motoru ayarları ve varsayılanları (docs/12 §8)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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
    """K17: kullanıcı tanımlı değişken gider (KDV hariç tutar veya satış yüzdesi)."""

    name: str
    kind: ExpenseKind
    amount_excl_vat: Decimal = N0
    percent: Decimal = N0
    vat_rate: Decimal = N20


@dataclass(frozen=True, slots=True)
class CargoTariff:
    """K08: kargo tarifesi. firma -> (en çok desi, KDV hariç tutar) basamakları, desi artan sırada."""

    steps: Mapping[str, tuple[tuple[Decimal, Decimal], ...]] = field(default_factory=dict)

    def lookup(self, carrier: str, desi: Decimal | None) -> Decimal | None:
        """Desiyi karşılayan ilk basamağın KDV hariç tutarı; firma, desi ya da basamak yoksa None."""
        brackets = self.steps.get(carrier)
        if not brackets or desi is None:
            return None
        for upper, price in brackets:
            if desi <= upper:
                return price
        return None


@dataclass(frozen=True, slots=True)
class ProfitSettings:
    """Kâr hesabı ayarları. Oranlar yüzde olarak (20 = %20)."""

    # K07: commissionAmount KDV dahil mi (varsayılan evet; pilotta teyit edilecek, §9 madde 1).
    commission_includes_vat: bool = True
    commission_vat_rate: Decimal = N20
    shipping_vat_rate: Decimal = N20
    service_fee_vat_rate: Decimal = N20
    ad_vat_rate: Decimal = N20
    # K18: e-ticaret stopajı oranı (nakit akışı kalemi, gider değil).
    withholding_rate: Decimal = N1
    # K13: sipariş başı tahmini platform hizmet bedeli (KDV hariç). Varsayılan 0: tahmin uydurulmaz.
    estimated_service_fee_per_order_excl_vat: Decimal = N0
    # K08: Trendyol anlaşmalı kargo tarifesi ve satıcı anlaşmalı (whoPays=1) tarife. Varsayılan boş.
    cargo_tariff: CargoTariff = field(default_factory=CargoTariff)
    seller_cargo_tariff: CargoTariff = field(default_factory=CargoTariff)
    # K08: fatura KDV tespit toleransı (taban; kalem başına en az 0,01).
    cargo_invoice_vat_tolerance: Decimal = N0_05
    thresholds: WarningThresholds = field(default_factory=WarningThresholds)
    variable_expenses: tuple[VariableExpense, ...] = ()
