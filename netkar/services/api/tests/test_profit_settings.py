"""Kâr ayarları ve eksik kalem kuralları (docs/12 K33-K41, ADR-0006): sürümlü ayarlar, tanımsız tahmin,
net kâr null, kesin zarar, K23 karşılaştırması, kısmi dönem, kesinlik ve claim'siz iade.

Sentetik senaryolar; beklenen değerler docs/12 §12 formüllerinden elle hesaplanmıştır.
"""

from __future__ import annotations

from datetime import date

from app.profit import ProfitSettings, calculate_profit
from app.profit.enums import Certainty, ExpenseKind, MissingItem, Source, Status, WarningCode
from app.profit.inputs import (
    AdRecord,
    CargoInvoice,
    CargoInvoiceItem,
    Claim,
    ClaimItem,
    CostRecord,
    OtherFinancialRow,
)
from app.profit.money import percent_of
from app.profit.results import ProfitResult
from app.profit.settings import (
    CargoTariff,
    DatedAmount,
    TariffVersion,
    VariableExpense,
    pick_version,
)
from tests.profit_helpers import D, data, line, make_settings, order, other, ret, sale

OUT = "Gönderi Kargo Bedeli"
DAY = date(2026, 10, 5)
NONE = ProfitSettings()  # üretim varsayılanı: hiçbir kullanıcı ayarı yok


def cost(barcode: str = "B1", unit: str = "30.00") -> CostRecord:
    return CostRecord(barcode, date(2026, 1, 1), D(unit), D("20"))


def invoice(serial: str, *items: tuple[str, str, str, int]) -> CargoInvoice:
    return CargoInvoice(serial, tuple(CargoInvoiceItem(t, n, D(a), d) for t, n, a, d in items))


def statement(serial: str, debt: str) -> OtherFinancialRow:
    return other("DeductionInvoices", debt=debt, row_id=serial, type_text="Kargo Faturası")


def service_fee(debt: str, **kw: object) -> OtherFinancialRow:
    return other("DeductionInvoices", debt=debt, request_sub_type="PlatformServiceFee", **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- K33: sürüm seçimi
def test_pick_version_uses_latest_started_version_and_undated_is_oldest() -> None:
    versions = [(date(2026, 10, 10), "new"), (None, "legacy"), (date(2026, 1, 1), "old")]
    assert pick_version(versions, date(2026, 10, 9)) == "old"
    assert pick_version(versions, date(2026, 10, 10)) == "new"  # başlangıç günü dahil
    assert pick_version(versions, date(2025, 12, 31)) == "legacy"  # başlangıçsız sürüm en eski
    assert pick_version([(date(2026, 1, 1), "x")], date(2025, 12, 31)) is None
    assert pick_version([], DAY) is None


def test_default_settings_are_all_undefined() -> None:
    s = ProfitSettings()
    assert s.service_fee_estimates == ()
    assert s.service_fee_estimate_on(DAY) is None
    assert s.default_desi is None
    assert s.cargo_tariff.steps == {} and s.seller_cargo_tariff.steps == {}
    assert s.variable_expenses == ()


# --------------------------------------------------------------------------- K34: tarife çözümleme
def versioned_tariff() -> CargoTariff:
    return CargoTariff(
        {
            "TE": (
                TariffVersion(((D("2"), D("42.00")), (D("5"), D("55.00"))), date(2026, 1, 1)),
                TariffVersion(((D("2"), D("45.00")), (D("5"), D("60.00"))), date(2026, 10, 10)),
            ),
            "FUTURE": (TariffVersion(((D("5"), D("99.00")),), date(2027, 1, 1)),),
            "*": (TariffVersion(((D("3"), D("50.00")), (D("10"), D("80.00"))), date(2026, 1, 1)),),
        }
    )


def test_tariff_picks_version_by_order_day() -> None:
    t = versioned_tariff()
    assert t.lookup("TE", D("2"), date(2026, 10, 9)) == D("42.00")
    assert t.lookup("TE", D("2"), date(2026, 10, 10)) == D("45.00")


def test_carrier_version_overrides_fallback_and_never_falls_through() -> None:
    t = versioned_tariff()
    # firmanın geçerli sürümü var ama desi en yüksek kademeyi aşıyor: '*' yedeğine düşülmez
    assert t.lookup("TE", D("7"), date(2026, 10, 15)) is None
    assert t.lookup("TE", None, date(2026, 10, 15)) is None  # desi bilinmiyor


def test_fallback_is_used_when_carrier_has_no_version_valid_that_day() -> None:
    t = versioned_tariff()
    assert t.lookup("UNKNOWN", D("3"), DAY) == D("50.00")  # firma tarifede yok
    assert t.lookup("FUTURE", D("3"), DAY) == D("50.00")  # firma sürümü gelecekte: yedek kullanılır
    assert t.lookup("FUTURE", D("3"), date(2027, 2, 1)) == D("99.00")  # firma sürümü geçerli: yalnız o
    assert t.lookup("UNKNOWN", None, DAY) is None  # yedekte de desi şart
    assert t.lookup("UNKNOWN", D("11"), DAY) is None
    assert CargoTariff().lookup("UNKNOWN", D("1"), DAY) is None


def test_fallback_carrier_future_version_is_not_valid_yet() -> None:
    t = CargoTariff({"*": (TariffVersion(((D("5"), D("70.00")),), date(2026, 11, 1)),)})
    assert t.lookup("X", D("2"), DAY) is None


def test_default_desi_is_used_with_info_warning_when_order_has_no_desi() -> None:
    settings = make_settings(cargo_tariff=versioned_tariff(), default_desi=D("3"))
    o = order(carrier="Ornek", cargo_deci=None)
    r = calculate_profit(data([o], settings=settings)).lines[0]
    assert r.items.shipping_outbound == D("50.00")  # '*' yedeği, varsayılan desi 3 (tarife KDV hariç)
    assert r.sources.shipping_outbound is Source.ESTIMATED
    assert WarningCode.CARGO_DESI_DEFAULT in r.warnings
    assert WarningCode.CARGO_TARIFF_MISSING not in r.warnings


def test_default_desi_not_used_when_order_has_desi_and_no_default_means_missing() -> None:
    settings = make_settings(cargo_tariff=versioned_tariff(), default_desi=D("3"))
    with_desi = calculate_profit(data([order(carrier="Ornek", cargo_deci="2")], settings=settings)).lines[0]
    assert WarningCode.CARGO_DESI_DEFAULT not in with_desi.warnings
    no_default = make_settings(cargo_tariff=versioned_tariff())
    missing = calculate_profit(data([order(carrier="Ornek", cargo_deci=None)], settings=no_default)).lines[0]
    assert missing.sources.shipping_outbound is Source.MISSING
    assert MissingItem.OUTBOUND_SHIPPING in missing.missing_items


def test_cargo_desi_mismatch_compares_only_order_desi_not_default() -> None:
    settings = make_settings(cargo_tariff=versioned_tariff(), default_desi=D("3"))
    o = order(carrier="Ornek", cargo_deci=None)
    ln = o.lines[0]
    inv = invoice("S1", (OUT, "O1", "60.00", 5))
    r = calculate_profit(
        data(
            [o],
            settings=settings,
            settlements=(sale(o, ln),),
            cargo_invoices=(inv,),
            other_financials=(statement("S1", "60.00"),),
        )
    ).lines[0]
    assert WarningCode.CARGO_DESI_MISMATCH not in r.warnings  # sipariş desisi yok: karşılaştırma yok
    assert r.sources.shipping_outbound is Source.ACTUAL


def test_actual_invoice_needs_no_tariff_and_clears_missing() -> None:
    o = order(cargo_deci=None)
    ln = o.lines[0]
    inv = invoice("S1", (OUT, "O1", "54.00", 2))
    r = calculate_profit(
        data(
            [o],
            settings=NONE,
            settlements=(sale(o, ln),),
            cargo_invoices=(inv,),
            other_financials=(statement("S1", "54.00"),),
        )
    ).lines[0]
    assert r.sources.shipping_outbound is Source.ACTUAL
    assert r.items.shipping_outbound == D("45.00")
    assert MissingItem.OUTBOUND_SHIPPING not in r.missing_items


# --------------------------------------------------------------------------- K35: hizmet bedeli
def test_undefined_service_fee_is_missing_not_zero() -> None:
    o = order()
    r = calculate_profit(data([o], settings=make_settings(service_fee_estimates=()), costs=(cost(),))).lines[
        0
    ]
    assert r.sources.platform_service_fee is Source.MISSING
    assert WarningCode.SERVICE_FEE_ESTIMATE_MISSING in r.warnings
    assert r.missing_items == (MissingItem.PLATFORM_SERVICE_FEE,)
    assert r.items.platform_service_fee == D("0.00")
    assert (
        r.items.net_profit is None and r.items.total_expenses is None and r.items.net_margin_percent is None
    )
    # 83,33 - 30,00 - 8,33 (komisyon %10 / 1,2) - 40/45 kargo = bilinen giderlerle kâr
    assert r.items.known_expenses_profit == D("83.33") - D("30.00") - D("8.33") - D("45.00")
    assert r.certainty is Certainty.MISSING


def test_explicit_zero_service_fee_is_defined_and_not_missing() -> None:
    settings = make_settings(service_fee_estimates=(DatedAmount(D("0")),))
    r = calculate_profit(data([order()], settings=settings, costs=(cost(),))).lines[0]
    assert r.sources.platform_service_fee is Source.ESTIMATED
    assert WarningCode.SERVICE_FEE_ESTIMATE_MISSING not in r.warnings
    assert r.items.net_profit is not None
    assert r.certainty is Certainty.ESTIMATED


def test_service_fee_estimate_version_by_order_day() -> None:
    settings = make_settings(
        service_fee_estimates=(
            DatedAmount(D("8.00"), date(2026, 1, 1)),
            DatedAmount(D("10.00"), date(2026, 10, 10)),
        )
    )
    old = calculate_profit(data([order(day=date(2026, 10, 9))], settings=settings)).lines[0]
    new = calculate_profit(data([order(day=date(2026, 10, 10))], settings=settings)).lines[0]
    assert old.items.platform_service_fee == D("8.00")
    assert new.items.platform_service_fee == D("10.00")
    before_any = calculate_profit(data([order(day=date(2025, 12, 31))], settings=settings)).lines[0]
    assert before_any.sources.platform_service_fee is Source.MISSING  # hiçbir sürüm henüz başlamadı


def test_statement_allocated_fee_needs_no_estimate() -> None:
    o = order()
    ln = o.lines[0]
    r = calculate_profit(
        data(
            [o],
            settings=NONE,
            costs=(cost(),),
            settlements=(sale(o, ln),),
            other_financials=(service_fee("12.00", order_number="O1"),),
        )
    ).lines[0]
    assert r.sources.platform_service_fee is Source.ACTUAL_ALLOCATED
    assert r.items.platform_service_fee == D("10.00")
    assert WarningCode.SERVICE_FEE_ESTIMATE_MISSING not in r.warnings
    assert MissingItem.PLATFORM_SERVICE_FEE not in r.missing_items


# --------------------------------------------------------------------------- K36: değişken gider geçerliliği
def test_variable_expense_validity_window_is_inclusive_and_open_ended() -> None:
    expenses = (
        VariableExpense(
            "old", ExpenseKind.PER_ORDER, D("6.00"), valid_from=date(2026, 1, 1), valid_to=date(2026, 10, 9)
        ),
        VariableExpense("new", ExpenseKind.PER_ORDER, D("7.50"), valid_from=date(2026, 10, 10)),
        VariableExpense("unit", ExpenseKind.PER_UNIT, D("1.00"), valid_from=date(2026, 10, 10)),
        VariableExpense("pct", ExpenseKind.PERCENT_OF_SALES, percent=D("10"), valid_to=date(2026, 10, 9)),
    )
    settings = make_settings(variable_expenses=expenses)
    early = calculate_profit(data([order(day=date(2026, 10, 9))], settings=settings)).lines[0]
    late = calculate_profit(data([order(day=date(2026, 10, 10))], settings=settings)).lines[0]
    assert [d.name for d in early.variable_expense_details] == ["old", "pct"]
    assert [d.name for d in late.variable_expense_details] == ["new", "unit"]
    assert early.items.variable_expenses == D("6.00") + D("8.33")
    assert late.items.variable_expenses == D("7.50") + D("1.00")
    assert VariableExpense("x", ExpenseKind.PER_ORDER).applies_on(DAY)


def test_undefined_variable_expense_is_not_missing() -> None:
    r = calculate_profit(data([order()], settings=make_settings(), costs=(cost(),))).lines[0]
    assert r.sources.variable_expenses is Source.NONE
    assert r.missing_items == ()


# --------------------------------------------------------------------------- K37: eksik kalem, kesin zarar
def test_missing_items_follow_canonical_order() -> None:
    o = order(cargo_deci=None)
    r = calculate_profit(data([o], settings=NONE)).lines[0]  # maliyet yok, tarife yok, hizmet bedeli yok
    assert r.missing_items == (
        MissingItem.PRODUCT_COST,
        MissingItem.OUTBOUND_SHIPPING,
        MissingItem.PLATFORM_SERVICE_FEE,
    )
    assert r.items.product_cost is None
    assert r.certainty is Certainty.MISSING


def test_known_expense_loss_is_certain_loss_even_when_net_profit_is_null() -> None:
    # 41,67 satış - 6,25 komisyon - 40,00 kargo = -4,58 < 0 (maliyet ve hizmet bedeli eksik, negatif olamaz)
    o = order([line(price="50.00", commission="15")], cargo_deci="1")
    r = calculate_profit(data([o], settings=make_settings(service_fee_estimates=()))).lines[0]
    assert r.items.net_profit is None
    assert r.items.known_expenses_profit == D("-4.58")
    assert WarningCode.LOSS in r.warnings


def test_known_expense_profit_positive_with_null_net_profit_is_not_loss() -> None:
    r = calculate_profit(data([order()], settings=make_settings(service_fee_estimates=()))).lines[0]
    assert r.items.net_profit is None
    assert r.items.known_expenses_profit > 0
    assert WarningCode.LOSS not in r.warnings


def test_complete_line_known_expense_profit_equals_net_profit() -> None:
    r = calculate_profit(data([order()], costs=(cost(),))).lines[0]
    assert r.items.net_profit is not None
    assert r.items.known_expenses_profit == r.items.net_profit
    assert r.missing_items == ()


def test_product_net_profit_is_null_when_any_line_misses_shipping_or_fee() -> None:
    complete = order([line(barcode="P")], number="O1")
    no_tariff = order([line(barcode="P")], number="O2", cargo_deci="9")  # kademe aşımı: kargo eksik
    result = calculate_profit(data([complete, no_tariff], costs=(cost("P"),)))
    product = result.products[0]
    assert product.net_profit is None and product.net_margin_percent is None
    assert product.cost_missing is False  # maliyet alanı yalnız maliyeti anlatır
    assert product.missing_line_counts.outbound_shipping == 1
    assert product.missing_line_counts.product_cost == 0
    assert product.known_expenses_profit == sum((r.items.known_expenses_profit for r in result.lines), D(0))
    assert product.certainty is Certainty.MISSING


def test_ad_only_product_has_no_lines_and_none_certainty() -> None:
    o = order([line(barcode="P")])
    ads = (AdRecord("1", date(2026, 10, 1), date(2026, 10, 31), D("10.00"), False, barcode="Q"),)
    result = calculate_profit(data([o], costs=(cost("P"), cost("Q")), ad_records=ads))
    unsold = next(p for p in result.products if p.barcode == "Q")
    assert unsold.certainty is Certainty.NONE
    assert unsold.net_profit == D("-10.00")
    assert unsold.known_expenses_profit == D("-10.00")


# --------------------------------------------------------------------------- K38: karşılaştırma
def settled_two_orders(settings: ProfitSettings) -> ProfitResult:
    o1 = order([line(barcode="P")], number="O1")
    o2 = order([line(barcode="P")], number="O2")
    l1, l2 = o1.lines[0], o2.lines[0]
    inv = invoice("S1", (OUT, "O1", "54.00", 2), (OUT, "O2", "54.00", 2))
    return calculate_profit(
        data(
            [o1, o2],
            settings=settings,
            costs=(cost("P"),),
            settlements=(sale(o1, l1), sale(o2, l2)),
            cargo_invoices=(inv,),
            other_financials=(statement("S1", "108.00"), service_fee("12.00", order_number="O1")),
        )
    )


def test_undefined_estimates_do_not_enter_comparison_and_never_alert() -> None:
    result = settled_two_orders(NONE)
    for r in result.lines:
        c = r.comparison
        assert c is not None
        assert c.shipping_outbound_estimated is None and c.platform_service_fee_estimated is None
        assert c.shipping_outbound_actual == D("45.00")  # kesin değer yine de gösterilir
        assert c.compared_estimated_total == c.commission_estimated
        assert c.compared_actual_total == c.commission_actual
        assert c.difference == D("0.00")
        assert WarningCode.UNEXPECTED_DEDUCTION not in r.warnings


def test_explicit_zero_fee_estimate_enters_comparison_and_can_alert() -> None:
    settings = ProfitSettings(
        cargo_tariff=CargoTariff.unversioned({"Trendyol Express": ((D("2"), D("45.00")),)}),
        service_fee_estimates=(DatedAmount(D("0")),),
    )
    o = order()
    ln = o.lines[0]
    r = calculate_profit(
        data(
            [o],
            settings=settings,
            costs=(cost(),),
            settlements=(sale(o, ln),),
            other_financials=(service_fee("60.00", order_number="O1"),),  # 50,00 KDV hariç gerçek kesinti
        )
    ).lines[0]
    assert r.comparison is not None
    assert r.comparison.platform_service_fee_estimated == D("0.00")
    assert r.comparison.platform_service_fee_actual == D("50.00")
    assert r.comparison.difference == D("50.00")
    assert WarningCode.UNEXPECTED_DEDUCTION in r.warnings


# --------------------------------------------------------------------------- K39/K40: dönem ve kesinlik
def test_partial_period_has_null_margin_and_consistent_full_lines_block() -> None:
    full = order([line(barcode="A", price="499.90")], number="O1")
    nocost = order([line(barcode="B", price="350.00", commission="18")], number="O2")
    fi = other("FinancialItem", debt="17.35", type_text="Düzeltme")
    result = calculate_profit(data([full, nocost], costs=(cost("A", "180.00"),), other_financials=(fi,)))
    p = result.period
    assert p.net_profit_partial is True
    assert p.net_margin_percent is None
    # K39 Revizyon 1: kısmi dönemde satır toplamı ve dönem net kârı null; bilinen kısım ayrı alanda.
    assert p.line_net_profit_total is None
    assert p.period_net_profit is None
    assert p.period_level_expenses_total == D("17.35")
    known = sum((r.items.known_expenses_profit for r in result.lines), D("0.00"))
    assert p.period_known_expenses_profit == known - D("17.35")
    f = p.full_lines
    assert f.line_count == 1
    assert f.net_sales_excl_vat - f.total_expenses == f.net_profit == result.lines[0].items.net_profit
    assert f.net_margin_percent == percent_of(f.net_profit, f.net_sales_excl_vat)  # pay ve payda aynı küme
    assert p.missing_line_counts.product_cost == 1
    assert p.missing_cost_line_count == 1
    assert WarningCode.UNCLASSIFIED_DEDUCTION in p.warnings


def test_partial_period_by_shipping_or_fee_alone() -> None:
    result = calculate_profit(data([order(cargo_deci=None)], settings=make_settings(), costs=(cost(),)))
    assert result.period.net_profit_partial is True
    assert result.period.net_margin_percent is None
    assert result.period.line_net_profit_total is None
    assert result.period.period_net_profit is None
    assert result.period.period_known_expenses_profit == result.lines[0].items.known_expenses_profit
    assert result.period.full_lines.line_count == 0
    assert result.period.full_lines.net_margin_percent is None  # net satış 0: marj tanımsız
    assert WarningCode.CARGO_MISSING_LINES in result.period.warnings
    assert WarningCode.MISSING_COST_LINES not in result.period.warnings


def test_period_warnings_for_missing_fee_and_pending_refund() -> None:
    o = order()
    ln = o.lines[0]
    result = calculate_profit(
        data(
            [o],
            settings=NONE,
            costs=(cost(),),
            settlements=(sale(o, ln), ret(o, ln, "100.00")),
        )
    )
    warnings = set(result.period.warnings)
    assert {
        WarningCode.SERVICE_FEE_MISSING_LINES,
        WarningCode.CARGO_MISSING_LINES,
        WarningCode.REFUND_RECORD_PENDING_LINES,
    } <= warnings
    assert result.period.certainty_line_counts.missing == 1
    assert result.period.certainty is Certainty.MISSING


def test_complete_period_margin_uses_period_net_profit_over_all_net_sales() -> None:
    result = calculate_profit(data([order()], costs=(cost(),)))
    p = result.period
    assert p.net_profit_partial is False
    assert p.net_margin_percent is not None
    assert p.certainty is Certainty.ESTIMATED
    assert (p.certainty_line_counts.certain, p.certainty_line_counts.estimated) == (0, 1)


def test_no_active_lines_certainty_is_none() -> None:
    result = calculate_profit(data([order(status="Cancelled")]))
    assert result.period.certainty is Certainty.NONE
    assert result.lines[0].certainty is Certainty.CANCELLED
    assert result.lines[0].missing_items == ()
    assert result.lines[0].items.known_expenses_profit == D("0.00")
    assert result.lines[0].status is Status.CANCELLED


def certain_scenario(settings: ProfitSettings) -> ProfitResult:
    """Ekstre, kargo faturası ve siparişe bağlı hizmet bedeli faturası gelmiş tek sipariş (sipariş desisi yok)."""
    o = order(cargo_deci=None)
    ln = o.lines[0]
    return calculate_profit(
        data(
            [o],
            settings=settings,
            costs=(cost(),),
            settlements=(sale(o, ln),),
            cargo_invoices=(invoice("S1", (OUT, "O1", "54.00", 2)),),
            other_financials=(statement("S1", "54.00"), service_fee("12.00", order_number="O1")),
        )
    )


def test_line_is_certain_only_when_no_source_is_an_estimate() -> None:
    result = certain_scenario(NONE)
    certain = result.lines[0]
    assert certain.certainty is Certainty.CERTAIN
    assert certain.items.net_profit is not None
    assert result.products[0].certainty is Certainty.CERTAIN
    assert result.period.certainty is Certainty.CERTAIN
    assert result.period.certainty_line_counts.certain == 1


def test_settled_line_with_estimated_fee_is_not_certain() -> None:
    # ekstre geldi, kargo faturası geldi ama hizmet bedeli faturası yok ve ayar tanımlı: tahmini
    o = order(cargo_deci=None)
    ln = o.lines[0]
    estimated = calculate_profit(
        data(
            [o],
            settings=make_settings(service_fee_estimates=(DatedAmount(D("10.00")),)),
            costs=(cost(),),
            settlements=(sale(o, ln),),
            cargo_invoices=(invoice("S1", (OUT, "O1", "54.00", 2)),),
            other_financials=(statement("S1", "54.00"),),
        )
    ).lines[0]
    assert estimated.status is Status.SETTLED
    assert estimated.certainty is Certainty.ESTIMATED


def test_pending_confirmation_rule_makes_certain_line_estimated() -> None:
    o = order(cargo_deci=None)
    ln = o.lines[0]
    delivery = sale(o, ln, credit="5.00", request_type="DeliveryFee")  # K29: teyit bekliyor
    r = calculate_profit(
        data(
            [o],
            settings=NONE,
            costs=(cost(),),
            settlements=(sale(o, ln), delivery),
            cargo_invoices=(invoice("S1", (OUT, "O1", "54.00", 2)),),
            other_financials=(statement("S1", "54.00"), service_fee("12.00", order_number="O1")),
        )
    ).lines[0]
    assert r.pending_confirmation == ("K29",)
    assert r.certainty is Certainty.ESTIMATED


# --------------------------------------------------------------------------- K41: claim'siz iade
def test_return_without_claim_keeps_cost_marks_estimated_and_reports_suspended_cost() -> None:
    o = order()
    ln = o.lines[0]
    r = calculate_profit(
        data([o], costs=(cost(unit="30.00"),), settlements=(sale(o, ln), ret(o, ln, "100.00")))
    ).lines[0]
    assert r.pending_refund_quantity == 1
    assert r.suspended_product_cost == D("30.00")
    assert r.items.product_cost == D("30.00")  # ihtiyat: maliyet tam gider
    assert r.sources.product_cost is Source.ESTIMATED
    assert WarningCode.REFUND_RECORD_PENDING in r.warnings
    assert r.certainty is Certainty.ESTIMATED


def test_pending_quantity_is_proportional_and_clamped() -> None:
    ln = line(qty=4)
    o = order([ln])
    r = calculate_profit(
        data([o], costs=(cost(unit="10.00"),), settlements=(sale(o, ln), ret(o, ln, "100.00")))
    ).lines[0]
    # 4 x 100 / 400 = 1; bekleyen adet 1, askıdaki maliyet 10,00
    assert (r.pending_refund_quantity, r.suspended_product_cost) == (1, D("10.00"))
    tiny = calculate_profit(
        data([o], costs=(cost(unit="10.00"),), settlements=(sale(o, ln), ret(o, ln, "1.00")))
    ).lines[0]
    assert tiny.pending_refund_quantity == 1  # en az 1
    over = calculate_profit(
        data([o], costs=(cost(unit="10.00"),), settlements=(sale(o, ln), ret(o, ln, "800.00")))
    ).lines[0]
    assert over.pending_refund_quantity == 4  # en çok adet (iade satıştan büyük olsa bile)


def test_pending_quantity_is_line_quantity_when_sales_are_zero() -> None:
    ln = line(qty=2)
    o = order([ln])
    zero_sale = sale(o, ln, credit="0.00")
    r = calculate_profit(
        data([o], costs=(cost(unit="10.00"),), settlements=(zero_sale, ret(o, ln, "50.00")))
    ).lines[0]
    assert r.pending_refund_quantity == 2


def test_claim_or_manual_refund_or_cancelled_cancel_pending() -> None:
    ln = line()
    o = order([ln])
    claim = Claim("O1", (ClaimItem(ln.items[0].item_id, "Accepted", True),))
    with_claim = calculate_profit(
        data([o], costs=(cost(),), claims=(claim,), settlements=(sale(o, ln), ret(o, ln, "100.00")))
    ).lines[0]
    assert with_claim.pending_refund_quantity == 0 and with_claim.suspended_product_cost is None
    assert WarningCode.REFUND_RECORD_PENDING not in with_claim.warnings
    manual = calculate_profit(
        data(
            [o], costs=(cost(),), settlements=(sale(o, ln), ret(o, ln, "30.00", request_type="ManualRefund"))
        )
    ).lines[0]
    assert manual.pending_refund_quantity == 0
    assert manual.sources.product_cost is Source.USER
    plain = calculate_profit(data([o], costs=(cost(),), settlements=(sale(o, ln),))).lines[0]
    assert (plain.pending_refund_quantity, plain.suspended_product_cost) == (0, None)
    cancelled = order([line()], status="Cancelled", number="O9")
    cl = cancelled.lines[0]
    gone = calculate_profit(
        data([cancelled], costs=(cost(),), settlements=(sale(cancelled, cl), ret(cancelled, cl, "100.00")))
    ).lines[0]
    assert gone.pending_refund_quantity == 0


def test_pending_refund_with_missing_cost_keeps_missing_source() -> None:
    o = order()
    ln = o.lines[0]
    r = calculate_profit(data([o], settlements=(sale(o, ln), ret(o, ln, "100.00")))).lines[0]
    assert r.pending_refund_quantity == 1
    assert r.suspended_product_cost is None  # maliyet bilinmiyor
    assert r.sources.product_cost is Source.MISSING
    assert WarningCode.REFUND_RECORD_PENDING in r.warnings
