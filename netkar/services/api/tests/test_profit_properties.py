"""Kâr motoru özellik tabanlı testleri (hypothesis): toplamlar korunur, stopaj kâra girmez, determinizm."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.profit import ProfitInput, calculate_profit
from app.profit.enums import ExpenseKind, Status
from app.profit.inputs import AdRecord, CostRecord, Order, OrderItem, OrderLine
from app.profit.money import rnd, split_exclusive
from app.profit.settings import VariableExpense
from tests.profit_helpers import TARIFF, make_settings, ret, sale

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
        price = TARIFF.lookup(order.carrier, order.cargo_deci)
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
