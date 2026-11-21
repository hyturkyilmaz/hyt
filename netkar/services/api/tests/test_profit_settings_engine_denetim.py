"""Kâr ayarları denetimi (9 Kasım 2026): motor tarafı bulguları, DB gerektirmez.

AO-01: sürüm seçimi önceden sıralı liste + `bisect` (her siparişte baştan sıralama yok); kural davranışı aynı.
AD-05: varsayılan desiyle fiyatlanan kargo tahmini K23 karşılaştırmasında işaretlenir (uyarı kümesi değişmez).
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.profit import ProfitInput, ProfitSettings, calculate_profit
from app.profit.enums import WarningCode
from app.profit.inputs import CargoInvoice, CargoInvoiceItem
from app.profit.results import LineResult
from app.profit.settings import (
    CargoTariff,
    DatedAmount,
    TariffVersion,
    pick_version,
)
from tests.profit_helpers import D, line, make_settings, order, other, sale

DAY = date(2026, 10, 5)


# --------------------------------------------------------------------------- AO-01: seçim kuralı aynı
def _mixed_versions() -> list[tuple[date | None, str]]:
    """Karışık sıralı, başlangıçsız ve aynı tarihli tekrarları olan sürümler."""
    return [
        (date(2026, 10, 10), "d10"),
        (None, "legacy"),
        (date(2026, 1, 1), "jan"),
        (date(2026, 10, 10), "d10-later-entry"),  # aynı başlangıç: girişte sonra gelen kazanır (eski kural)
        (date(2027, 1, 1), "future"),
        (date(2026, 6, 1), "jun"),
    ]


@pytest.mark.parametrize(
    "day", [date(1999, 1, 1)] + [date(2026, 1, 1) + timedelta(days=i) for i in range(0, 400, 7)]
)
def test_fee_estimate_selection_matches_the_reference_rule(day: date) -> None:
    versions = _mixed_versions()
    settings = ProfitSettings(
        service_fee_estimates=tuple(
            DatedAmount(Decimal(i + 1), start) for i, (start, _) in enumerate(versions)
        )
    )
    expected = pick_version([(start, Decimal(i + 1)) for i, (start, _) in enumerate(versions)], day)
    assert settings.service_fee_estimate_on(day) == expected


def test_fee_estimate_selection_picks_documented_cases() -> None:
    settings = ProfitSettings(
        service_fee_estimates=(
            DatedAmount(D("3"), date(2026, 10, 10)),
            DatedAmount(D("1")),  # başlangıçsız: en eski
            DatedAmount(D("2"), date(2026, 1, 1)),
        )
    )
    assert settings.service_fee_estimate_on(date(2025, 12, 31)) == D("1")
    assert settings.service_fee_estimate_on(date(2026, 10, 9)) == D("2")
    assert settings.service_fee_estimate_on(date(2026, 10, 10)) == D("3")  # başlangıç günü dahil
    assert ProfitSettings().service_fee_estimate_on(DAY) is None
    only_dated = ProfitSettings(service_fee_estimates=(DatedAmount(D("2"), date(2026, 1, 1)),))
    assert only_dated.service_fee_estimate_on(date(2025, 12, 31)) is None


@pytest.mark.parametrize("day", [date(2026, 1, 1) + timedelta(days=i) for i in range(0, 400, 9)])
def test_tariff_lookup_selection_matches_the_reference_rule(day: date) -> None:
    starts = [date(2026, 10, 10), None, date(2026, 1, 1), date(2026, 6, 1), date(2027, 1, 1)]
    versions = tuple(TariffVersion(((D("5"), D(10 + i)),), start) for i, start in enumerate(starts))
    tariff = CargoTariff({"X": versions})
    picked = pick_version([(v.valid_from, v.brackets) for v in versions], day)
    assert picked is not None
    assert tariff.lookup("X", D("1"), day) == picked[0][1]


# --------------------------------------------------------------------------- AO-01: süre doğrusal kalır
VERSIONS = 10_000
CALLS = 5_000


def _timed(call: object, count: int) -> float:
    start = time.perf_counter()
    for _ in range(count):
        call()  # type: ignore[operator]
    return time.perf_counter() - start


def test_fee_estimate_cost_does_not_grow_with_the_number_of_versions() -> None:
    """PoC (fee_bench): 10.175 sürümde 5.000 çağrı 16,9 sn idi (her çağrıda sıralama). Artık log(n)."""
    first = date(2000, 1, 1)
    many = ProfitSettings(
        service_fee_estimates=tuple(DatedAmount(D("10"), first + timedelta(days=i)) for i in range(VERSIONS))
    )
    one = ProfitSettings(service_fee_estimates=(DatedAmount(D("10")),))
    many.service_fee_estimate_on(DAY)  # ısınma (varsa tembel kurulum)
    t_many = _timed(lambda: many.service_fee_estimate_on(DAY), CALLS)
    t_one = _timed(lambda: one.service_fee_estimate_on(DAY), CALLS)
    # Geniş eşik (CI gürültüsü): 10.000 kat sürüm, tek sürümün en çok 30 katı + 0,2 sn. Eski kod ~1000 kat.
    assert t_many < 30 * t_one + 0.2, (t_many, t_one)


def test_tariff_lookup_cost_does_not_grow_with_the_number_of_versions() -> None:
    first = date(2000, 1, 1)
    versions = tuple(
        TariffVersion(((D("2"), D("40.00")), (D("5"), D("60.00"))), first + timedelta(days=i))
        for i in range(VERSIONS)
    )
    many = CargoTariff({"X": versions})
    one = CargoTariff({"X": (versions[0],)})
    many.lookup("X", D("3"), DAY)
    t_many = _timed(lambda: many.lookup("X", D("3"), DAY), CALLS)
    t_one = _timed(lambda: one.lookup("X", D("3"), DAY), CALLS)
    assert t_many < 30 * t_one + 0.2, (t_many, t_one)


def test_engine_run_with_many_fee_versions_stays_close_to_one_version() -> None:
    """Uçtan uca: çok siparişli motor çalıştırması sürüm sayısıyla çarpılmaz."""
    first = date(2000, 1, 1)
    orders = [order([line()], number=f"O{i}", cargo_deci="2") for i in range(1500)]
    many = make_settings(
        service_fee_estimates=tuple(DatedAmount(D("10"), first + timedelta(days=i)) for i in range(VERSIONS))
    )
    one = make_settings()

    def run(settings: ProfitSettings) -> float:
        start = time.perf_counter()
        calculate_profit(ProfitInput(orders=tuple(orders), settings=settings))
        return time.perf_counter() - start

    run(one)
    t_one, t_many = run(one), run(many)
    assert t_many < 3 * t_one + 1.0, (t_many, t_one)


# --------------------------------------------------------------------------- AD-05: varsayılan desi izi
def _default_desi_case(with_invoice: bool, order_desi: str | None, default_desi: str | None) -> LineResult:
    ln = line(price="300.00")
    o = order([ln], carrier="Ornek Kargo", cargo_deci=order_desi)
    tariff = CargoTariff({"*": (TariffVersion(((D("3"), D("50")), (D("30"), D("200"))), None),)})
    settings = make_settings(
        cargo_tariff=tariff,
        default_desi=None if default_desi is None else D(default_desi),
    )
    kwargs: dict[str, object] = {}
    if with_invoice:
        # 150,00 KDV dahil = 125,00 hariç; tahmin 50,00 -> fark 75,00 (BEKLENMEYEN_KESINTI)
        kwargs["cargo_invoices"] = (
            CargoInvoice("INV", (CargoInvoiceItem("Gönderi Kargo Bedeli", "O1", D("150.00"), 12),)),
        )
        kwargs["other_financials"] = (
            other("DeductionInvoices", debt="150.00", row_id="INV", type_text="Kargo Faturası"),
        )
    return calculate_profit(
        ProfitInput(orders=(o,), settings=settings, settlements=(sale(o, ln),), **kwargs)  # type: ignore[arg-type]
    ).lines[0]


def test_default_desi_estimate_is_flagged_in_the_comparison_when_the_invoice_arrives() -> None:
    result = _default_desi_case(with_invoice=True, order_desi=None, default_desi="3")
    comparison = result.comparison
    assert comparison is not None
    assert comparison.shipping_estimate_default_desi is True
    assert comparison.shipping_outbound_estimated == D("50.00")
    assert comparison.difference == D("75.00")
    # Motor davranışı değişmedi: uyarı kümesi önceki gibi (KARGO_DESI_VARSAYILAN fatura gelince çıkmaz).
    warnings = set(result.warnings)
    assert WarningCode.UNEXPECTED_DEDUCTION in warnings
    assert WarningCode.CARGO_DESI_DEFAULT not in warnings


def test_default_desi_estimate_is_flagged_before_the_invoice_too() -> None:
    result = _default_desi_case(with_invoice=False, order_desi=None, default_desi="3")
    assert result.comparison is not None
    assert result.comparison.shipping_estimate_default_desi is True
    assert WarningCode.CARGO_DESI_DEFAULT in result.warnings


def test_order_desi_estimate_is_not_flagged() -> None:
    result = _default_desi_case(with_invoice=True, order_desi="2", default_desi="3")
    assert result.comparison is not None
    assert result.comparison.shipping_estimate_default_desi is False


def test_no_tariff_price_means_no_default_desi_flag() -> None:
    # Varsayılan desi var ama tarife fiyatlayamadı (desi 40 > en yüksek kademe): tahmin yok, işaret yok.
    ln = line(price="300.00")
    o = order([ln], carrier="Ornek Kargo", cargo_deci=None)
    tariff = CargoTariff({"*": (TariffVersion(((D("3"), D("50")),), None),)})
    settings = make_settings(cargo_tariff=tariff, default_desi=D("40"))
    result = calculate_profit(ProfitInput(orders=(o,), settings=settings, settlements=(sale(o, ln),))).lines[
        0
    ]
    assert result.comparison is not None
    assert result.comparison.shipping_outbound_estimated is None
    assert result.comparison.shipping_estimate_default_desi is False
