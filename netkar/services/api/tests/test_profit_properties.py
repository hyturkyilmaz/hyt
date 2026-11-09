"""Kâr motoru özellik tabanlı testleri (hypothesis): toplamlar korunur, stopaj kâra girmez, determinizm."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.profit import ProfitInput, ProfitResult, ProfitSettings, calculate_profit
from app.profit.enums import Certainty, ExpenseKind, MissingItem, Status, WarningCode
from app.profit.inputs import (
    AdRecord,
    CargoInvoice,
    CargoInvoiceItem,
    CostRecord,
    Order,
    OrderItem,
    OrderLine,
)
from app.profit.money import rnd, split_exclusive
from app.profit.schema_v1 import parse_input, render_result
from app.profit.settings import VariableExpense
from tests.profit_helpers import TARIFF, make_settings, other, ret, sale

D = Decimal
BARCODES = ["A", "B", "C"]

cents = st.integers(min_value=1, max_value=500_000).map(lambda c: D(c).scaleb(-2))


@st.composite
def lines_st(draw: st.DrawFn, index: int) -> OrderLine:
    quantity = draw(st.integers(min_value=1, max_value=4))
    price = draw(cents)
    items = []
    for i in range(quantity):
        seller_discount = D(draw(st.integers(min_value=0, max_value=int(price * 100)))).scaleb(-2)
        items.append(OrderItem(f"i{index}-{i}", seller_discount, D("0.00")))
    return OrderLine(
        line_id=index,
        barcode=draw(st.sampled_from(BARCODES)),
        quantity=quantity,
        unit_gross=price,
        vat_rate=draw(st.sampled_from([D("1"), D("10"), D("20")])),
        commission_rate=draw(st.integers(min_value=0, max_value=30).map(D)),
        items=tuple(items),
    )


@st.composite
def orders_st(draw: st.DrawFn) -> list[Order]:
    result: list[Order] = []
    counter = 0
    for number in range(draw(st.integers(min_value=1, max_value=3))):
        lines = []
        for _ in range(draw(st.integers(min_value=1, max_value=4))):
            counter += 1
            lines.append(draw(lines_st(counter)))
        result.append(
            Order(
                order_number=f"O{number}",
                package_id=100 + number,
                order_day=date(2026, 10, draw(st.integers(min_value=1, max_value=28))),
                status=draw(st.sampled_from(["Delivered", "Delivered", "Delivered", "Cancelled"])),
                carrier="Trendyol Express",
                lines=tuple(lines),
                cargo_deci=D(draw(st.integers(min_value=1, max_value=5))),
            )
        )
    return result


def build_input(orders: list[Order], settled: bool, withholding: str = "1") -> ProfitInput:
    rows = tuple(
        sale(o, ln, credit=str(sum((ln.unit_gross - i.seller_discount for i in ln.items), D(0))))
        for o in orders
        if settled and not o.is_cancelled
        for ln in o.lines
    )
    costs = tuple(CostRecord(code, date(2026, 1, 1), D("7.77"), D("20")) for code in BARCODES[:2])
    expenses = (
        VariableExpense("a", ExpenseKind.PER_ORDER, amount_excl_vat=D("3.33")),
        VariableExpense("b", ExpenseKind.PERCENT_OF_SALES, percent=D("0.7")),
    )
    ads = (
        AdRecord("1", date(2026, 10, 1), date(2026, 10, 31), D("100.01"), False, barcode="A"),
        AdRecord("2", date(2026, 10, 1), date(2026, 10, 31), D("33.33"), True),
    )
    return ProfitInput(
        orders=tuple(orders),
        settings=make_settings(
            variable_expenses=expenses, withholding_rate=D(withholding), cargo_tariff=TARIFF
        ),
        costs=costs,
        settlements=rows,
        ad_records=ads,
    )


@settings(max_examples=60, deadline=None)
@given(orders_st(), st.booleans())
def test_line_breakdown_is_internally_consistent(orders: list[Order], settled: bool) -> None:
    result = calculate_profit(build_input(orders, settled))
    for r in result.lines:
        items = r.items
        assert rnd(items.sales_incl_vat) == items.sales_excl_vat + r.vat.sales_vat
        assert items.net_sales_excl_vat == items.sales_excl_vat - items.refund_excl_vat
        expenses = (
            items.commission
            + items.shipping_outbound
            + items.shipping_return
            + items.platform_service_fee
            + items.penalty
            + items.advertising
            + items.variable_expenses
        )
        assert items.contribution_before_cost == items.net_sales_excl_vat - expenses
        if items.product_cost is None:
            assert items.net_profit is None
            assert items.total_expenses is None
        else:
            assert items.total_expenses == expenses + items.product_cost
            assert items.net_profit == items.net_sales_excl_vat - items.total_expenses
            assert items.net_profit == items.contribution_before_cost - items.product_cost
        if r.status is Status.CANCELLED:
            assert items.net_sales_excl_vat == 0
            assert items.net_profit in (None, D("0.00"))


@settings(max_examples=60, deadline=None)
@given(orders_st(), st.booleans())
def test_allocated_expenses_conserve_package_totals(orders: list[Order], settled: bool) -> None:
    result = calculate_profit(build_input(orders, settled))
    by_order: dict[str, list] = {}
    for r in result.lines:
        by_order.setdefault(r.order_number, []).append(r)
    for number, group in by_order.items():
        order = next(o for o in orders if o.order_number == number)
        if order.is_cancelled:
            assert all(r.items.shipping_outbound == 0 and r.items.platform_service_fee == 0 for r in group)
            continue
        price = TARIFF.lookup(order.carrier, order.cargo_deci, order.order_day)
        assert price is not None
        excl, vat = split_exclusive(price, D("20"))
        assert sum((r.items.shipping_outbound for r in group), D(0)) == excl
        assert sum((r.vat.shipping_vat for r in group), D(0)) == vat
        fee_excl, fee_vat = split_exclusive(D("10.00"), D("20"))
        assert sum((r.items.platform_service_fee for r in group), D(0)) == fee_excl
        assert sum((r.vat.platform_service_fee_vat for r in group), D(0)) == fee_vat
        for expense_total in (D("3.33"),):
            # sipariş başı değişken gider (kdv hariç) yalnız bu satırlarda toplanır: toplam >= tek gider
            assert sum((r.items.variable_expenses for r in group), D(0)) >= expense_total


@settings(max_examples=60, deadline=None)
@given(orders_st(), st.booleans())
def test_product_and_period_totals_are_sums_of_rounded_lines(orders: list[Order], settled: bool) -> None:
    result = calculate_profit(build_input(orders, settled))
    active = [r for r in result.lines if r.status is not Status.CANCELLED]
    assert result.period.line_count == len(active)
    assert result.period.net_sales_excl_vat == sum((r.items.net_sales_excl_vat for r in active), D(0))
    assert result.period.commission == sum((r.items.commission for r in active), D(0))
    assert result.period.vat_effect == sum((r.vat.vat_effect for r in active), D(0))
    expected_line_profit = sum((r.items.net_profit for r in active if r.items.net_profit is not None), D(0))
    assert result.period.line_net_profit_total == expected_line_profit
    expenses = result.period.period_level_expenses
    period_level = (
        expenses.advertising_unsold_products
        + expenses.advertising_undistributed
        + expenses.undistributed_penalty
        + expenses.early_payment_fee
        + expenses.unclassified_deduction
    )
    assert result.period.period_net_profit == expected_line_profit - period_level
    for product in result.products:
        rows = [r for r in active if r.barcode == product.barcode]
        assert product.net_sales_excl_vat == sum((r.items.net_sales_excl_vat for r in rows), D(0))
        assert product.advertising_allocated == sum((r.items.advertising for r in rows), D(0))
        assert product.line_count == len(rows)
    ad_total = (
        sum((r.items.advertising for r in active), D(0))
        + expenses.advertising_unsold_products
        + expenses.advertising_undistributed
    )
    # reklam: harcanan toplam (KDV hariç) satırlara, satışsız ürüne ya da döneme eksiksiz dağılır
    assert ad_total == D("100.01") + split_exclusive(D("33.33") * 100 / D("120"), D("20"))[0]


@settings(max_examples=40, deadline=None)
@given(orders_st(), st.booleans(), st.sampled_from(["0", "1", "5", "15"]))
def test_withholding_is_never_part_of_profit(orders: list[Order], settled: bool, rate: str) -> None:
    base = calculate_profit(build_input(orders, settled, withholding="1"))
    other = calculate_profit(build_input(orders, settled, withholding=rate))
    assert [r.items for r in base.lines] == [r.items for r in other.lines]
    assert base.period.period_net_profit == other.period.period_net_profit
    for r in other.lines:
        assert r.cash_flow.withholding == rnd(r.items.net_sales_excl_vat * D(rate) / 100)


@settings(max_examples=30, deadline=None)
@given(orders_st(), st.booleans())
def test_calculation_is_deterministic(orders: list[Order], settled: bool) -> None:
    data = build_input(orders, settled)
    assert calculate_profit(data) == calculate_profit(data)


@settings(max_examples=40, deadline=None)
@given(orders_st())
def test_full_refund_settles_to_zero_net_sales_and_negative_or_zero_profit(orders: list[Order]) -> None:
    active = [o for o in orders if not o.is_cancelled]
    rows = []
    for o in active:
        for ln in o.lines:
            amount = sum((ln.unit_gross - i.seller_discount for i in ln.items), D(0))
            rows.append(sale(o, ln, credit=str(amount)))
            rows.append(ret(o, ln, str(amount)))
    data = ProfitInput(orders=tuple(orders), settings=make_settings(), settlements=tuple(rows))
    for r in calculate_profit(data).lines:
        assert r.items.net_sales_excl_vat == D("0.00")
        assert r.items.commission == D("0.00")
        assert r.items.net_margin_percent is None


# --------------------------------------------------------------------------- K37-K40 özdeşlikleri (I1-I4)
def assert_period_identities(result: ProfitResult) -> None:
    """docs/12 K39 (I1-I4) ve K37/K40 satır ilişkileri; nesne düzeyinde."""
    p = result.period
    active = [r for r in result.lines if r.status is not Status.CANCELLED]
    full = [r for r in active if not r.missing_items]
    f = p.full_lines
    # I1: tam satırlar bloğunun toplam gideri gider alanlarının toplamıdır.
    assert f.total_expenses == (
        f.product_cost
        + f.commission
        + f.shipping_outbound
        + f.shipping_return
        + f.platform_service_fee
        + f.penalty
        + f.advertising
        + f.variable_expenses
    )
    # I2
    assert f.net_sales_excl_vat - f.total_expenses == f.net_profit == p.line_net_profit_total
    assert f.line_count == len(full)
    # I3
    level = p.period_level_expenses
    level_total = (
        level.advertising_unsold_products
        + level.advertising_undistributed
        + level.undistributed_penalty
        + level.early_payment_fee
        + level.unclassified_deduction
    )
    assert p.period_level_expenses_total == level_total
    assert p.line_net_profit_total - level_total == p.period_net_profit
    # K39: kısmi tanımı ve marj
    assert p.net_profit_partial == (len(full) != len(active))
    if p.net_profit_partial:
        assert p.net_margin_percent is None
    else:
        # I4: tam dönemde üst düzey kalem alanları net kârı verir
        top = (
            p.product_cost
            + p.commission
            + p.shipping_outbound
            + p.shipping_return
            + p.platform_service_fee
            + p.penalty_allocated
            + p.advertising_allocated
            + p.variable_expenses
        )
        assert p.net_sales_excl_vat - top - level_total == p.period_net_profit
    for r in active:
        assert (r.items.net_profit is None) == bool(r.missing_items)  # K37: eksik kalem varken net kâr null
        assert (r.items.total_expenses is None) == bool(r.missing_items)
        assert (r.items.net_margin_percent is None) or r.items.net_profit is not None
        assert (r.certainty is Certainty.MISSING) == bool(r.missing_items)
        if r.items.net_profit is not None:
            assert r.items.known_expenses_profit == r.items.net_profit
        for item in r.missing_items:
            source = {
                MissingItem.PRODUCT_COST: r.sources.product_cost,
                MissingItem.OUTBOUND_SHIPPING: r.sources.shipping_outbound,
                MissingItem.PLATFORM_SERVICE_FEE: r.sources.platform_service_fee,
            }[item]
            assert source.value == "eksik"
        loss = (r.items.net_profit or r.items.known_expenses_profit) < 0
        assert (WarningCode.LOSS in r.warnings) == loss
    assert p.certainty_line_counts.missing == sum(1 for r in active if r.missing_items)


def random_documents(
    draw: st.DrawFn, orders: list[Order]
) -> tuple[tuple[CargoInvoice, ...], tuple[Any, ...]]:
    """Rastgele kargo faturası ve hizmet bedeli faturası (tutarlar tahminden bağımsız, çok büyük olabilir)."""
    items: list[CargoInvoiceItem] = []
    statements: list[Any] = []
    for o in orders:
        if o.is_cancelled:
            continue
        if draw(st.booleans()):
            amount = draw(cents)
            items.append(CargoInvoiceItem("Gönderi Kargo Bedeli", o.order_number, amount, 3))
        if draw(st.booleans()):
            statements.append(
                other(
                    "DeductionInvoices",
                    debt=str(draw(cents)),
                    request_sub_type="PlatformServiceFee",
                    order_number=o.order_number,
                )
            )
    invoice = (CargoInvoice("INV", tuple(items)),) if items else ()
    if invoice:
        total = sum((i.amount for i in items), D(0))
        statements.append(
            other("DeductionInvoices", debt=str(total), row_id="INV", type_text="Kargo Faturası")
        )
    return invoice, tuple(statements)


@st.composite
def documented_input_st(draw: st.DrawFn) -> tuple[list[Order], ProfitInput]:
    orders = draw(orders_st())
    settled = draw(st.booleans())
    base = build_input(orders, settled)
    invoices, statements = random_documents(draw, orders)
    return orders, ProfitInput(
        orders=base.orders,
        settings=base.settings,
        costs=base.costs,
        settlements=base.settlements,
        ad_records=base.ad_records,
        cargo_invoices=invoices,
        other_financials=statements,
    )


@settings(max_examples=60, deadline=None)
@given(documented_input_st(), st.sampled_from(["defaults", "configured"]))
def test_period_identities_hold_for_random_inputs(drawn: tuple[list[Order], ProfitInput], mode: str) -> None:
    _, data = drawn
    if mode == "defaults":
        data = replace(data, settings=ProfitSettings())
    assert_period_identities(calculate_profit(data))


@settings(max_examples=80, deadline=None)
@given(documented_input_st())
def test_unconfigured_account_never_gets_false_unexpected_deduction(
    drawn: tuple[list[Order], ProfitInput],
) -> None:
    """Ayarsız hesapta (ProfitSettings()) tahmini kargo ve hizmet bedeli tanımsızdır: karşılaştırmaya girmez,
    ekstredeki kesin tutarlar ne kadar büyük olursa olsun komisyon tahmini tutan satırda uyarı çıkmaz (K38)."""
    orders, data = drawn
    # Her satıra ayrı barkod: aynı barkodlu satırların ekstre payı (K27) komisyonu tahminden ayırmasın.
    unique = [
        replace(o, lines=tuple(replace(ln, barcode=f"U{ln.line_id}") for ln in o.lines)) for o in orders
    ]
    rows = tuple(
        sale(o, ln, credit=str(sum((ln.unit_gross - i.seller_discount for i in ln.items), D(0))))
        for o in unique
        if not o.is_cancelled and data.settlements
        for ln in o.lines
    )
    unconfigured = ProfitInput(
        orders=tuple(unique),
        settings=ProfitSettings(),
        settlements=rows,  # komisyon tam tahmin kadar: tek olası fark kaynağı kargo ve hizmet bedeli
        cargo_invoices=data.cargo_invoices,
        other_financials=data.other_financials,
    )
    for r in calculate_profit(unconfigured).lines:
        assert WarningCode.UNEXPECTED_DEDUCTION not in r.warnings
        if r.comparison is not None:
            assert r.comparison.shipping_outbound_estimated is None
            assert r.comparison.platform_service_fee_estimated is None
            assert r.comparison.compared_estimated_total == r.comparison.commission_estimated


def test_configured_account_does_alert_on_the_same_large_documents() -> None:
    """Ayrım kanıtı: aynı belgeler ayarlıyken gerçek kesinti farkını yakalar (test ayırt edicidir)."""
    o = Order("O1", 1, date(2026, 10, 5), "Delivered", "Trendyol Express", (_one_line(),), cargo_deci=D("2"))
    ln = o.lines[0]
    invoice = CargoInvoice("INV", (CargoInvoiceItem("Gönderi Kargo Bedeli", "O1", D("500.00"), 2),))
    statements = (other("DeductionInvoices", debt="500.00", row_id="INV", type_text="Kargo Faturası"),)
    rows = (sale(o, ln),)

    def run(account_settings: ProfitSettings) -> ProfitResult:
        return calculate_profit(
            ProfitInput(
                orders=(o,),
                settings=account_settings,
                settlements=rows,
                cargo_invoices=(invoice,),
                other_financials=statements,
            )
        )

    configured, unconfigured = run(make_settings()), run(ProfitSettings())
    assert WarningCode.UNEXPECTED_DEDUCTION in configured.lines[0].warnings
    assert WarningCode.UNEXPECTED_DEDUCTION not in unconfigured.lines[0].warnings


def _one_line() -> OrderLine:
    return OrderLine(1, "A", 1, D("100.00"), D("20"), D("10"), (OrderItem("i1", D("0.00"), D("0.00")),))


# --------------------------------------------------------------------------- altın senaryolar: ayarsız yeniden hesap
GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("G*.json"))
USER_SETTING_KEYS_DEFAULTS: dict[str, Any] = {
    "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": None,
    "kargo_tarifesi": {},
    "satici_kargo_tarifesi": {},
    "varsayilan_desi": None,
    "degisken_giderler": [],
}


def unconfigured_raw(girdi: dict[str, Any]) -> dict[str, Any]:
    """Aynı girdi, kullanıcı ayarları tanımsız (üretim varsayılanı); sistem parametreleri korunur."""
    raw: dict[str, Any] = json.loads(json.dumps(girdi))
    raw["ayarlar"] = {**raw.get("ayarlar", {}), **USER_SETTING_KEYS_DEFAULTS}
    return raw


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_scenarios_recomputed_without_settings(path: Path) -> None:
    """ADR-0006 §6 kabul ölçütü: G01-G48 ayarsız hesaplandığında altın sonuçta olmayan BEKLENMEYEN_KESINTI yok,
    eksik kalemli satırda net kâr sayı değil, kısmi dönemde marj null ve özdeşlikler tutar."""
    scenario = json.loads(path.read_text(encoding="utf-8"))
    golden_lines = scenario["beklenen"]["siparis_satirlari"]
    result = calculate_profit(parse_input(unconfigured_raw(scenario["girdi"])))
    rendered = render_result(result)
    assert len(rendered["siparis_satirlari"]) == len(golden_lines)
    for mine, golden in zip(rendered["siparis_satirlari"], golden_lines, strict=True):
        if "BEKLENMEYEN_KESINTI" in mine["uyarilar"]:
            assert "BEKLENMEYEN_KESINTI" in golden["uyarilar"], "altın sonuçta olmayan BEKLENMEYEN_KESINTI"
        if mine["eksik_kalemler"]:
            assert mine["kalemler"]["net_kar"] is None
    if rendered["donem_toplami"]["net_kar_kismi"]:
        assert rendered["donem_toplami"]["net_kar_marji_yuzde"] is None
    assert_period_identities(result)


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda p: p.stem)
def test_golden_scenarios_hold_identities_with_their_own_settings(path: Path) -> None:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    assert_period_identities(calculate_profit(parse_input(scenario["girdi"])))
