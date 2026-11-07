"""Reklam dağıtımı, değişken giderler, ürün ve dönem toplulaştırma, ROAS (K15, K17, K25)."""

from __future__ import annotations

from datetime import date

from app.profit import calculate_profit
from app.profit.enums import ExpenseKind, Source
from app.profit.inputs import AdRecord, CostRecord
from app.profit.settings import VariableExpense
from tests.profit_helpers import D, data, line, make_settings, order


def ad(
    record_id: str = "AD1",
    spend: str = "120.00",
    start: date = date(2026, 10, 1),
    end: date = date(2026, 10, 31),
    spend_includes_vat: bool = False,
    barcode: str | None = None,
    ad_revenue: str | None = None,
) -> AdRecord:
    return AdRecord(
        record_id=record_id,
        start=start,
        end=end,
        spend=D(spend),
        spend_includes_vat=spend_includes_vat,
        barcode=barcode,
        ad_revenue=None if ad_revenue is None else D(ad_revenue),
    )


def cost(barcode: str, unit: str = "10.00") -> CostRecord:
    return CostRecord(barcode, date(2026, 1, 1), D(unit), D("20"))


# --------------------------------------------------------------------------- reklam (K15)
def test_matched_ad_goes_to_barcode_lines_by_net_sales() -> None:
    a, b, c = line("A", price="120.00"), line("A", price="240.00"), line("C", price="120.00")
    o = order([a, b, c])
    result = calculate_profit(data([o], ad_records=(ad(barcode="A", spend="90.00", ad_revenue="720.00"),)))
    ra, rb, rc = result.lines
    assert (ra.items.advertising, rb.items.advertising, rc.items.advertising) == (
        D("30.00"),
        D("60.00"),
        D("0.00"),
    )
    assert ra.sources.advertising is Source.MATCHED
    assert rc.sources.advertising is Source.NONE
    assert ra.ad_details[0].kind is Source.MATCHED
    assert ra.vat.advertising_vat + rb.vat.advertising_vat == D("18.00")
    product_a = next(p for p in result.products if p.barcode == "A")
    assert product_a.advertising_spend == D("90.00")
    assert product_a.advertising_revenue == D("720.00")
    assert product_a.roas == D("8.00")


def test_ad_spend_including_vat_is_converted_and_unmatched_ads_are_allocated() -> None:
    a, b = line("A", price="120.00"), line("B", price="360.00")
    o = order([a, b])
    records = (
        ad("S1", "120.00", spend_includes_vat=True),  # mağaza reklamı: KDV hariç 100,00
        ad("S2", "10.00", barcode="UNKNOWN"),  # katalogda yok
    )
    result = calculate_profit(data([o], ad_records=records))
    ra, rb = result.lines
    assert ra.items.advertising + rb.items.advertising == D("110.00")
    assert ra.sources.advertising is Source.ALLOCATED_ESTIMATE
    assert [d.record_id for d in ra.ad_details] == ["S1", "S2"]
    assert ra.items.advertising == D("27.50")
    assert rb.items.advertising == D("82.50")


def test_catalog_barcode_without_sales_stays_period_level() -> None:
    o = order([line("A")])
    sold = calculate_profit(
        data([o], ad_records=(ad(barcode="Z", spend="80.00", ad_revenue="400.00"),), catalog_barcodes=("Z",))
    )
    assert sold.period.period_level_expenses.advertising_unsold_products == D("80.00")
    z = next(p for p in sold.products if p.barcode == "Z")
    assert z.line_count == 0
    assert z.advertising_without_sales == D("80.00")
    assert z.net_profit == D("-80.00")
    assert z.roas == D("5.00")
    assert z.breakeven_roas is None  # reklam öncesi kâr 0 (<= 0)
    assert sold.lines[0].items.advertising == D("0.00")


def test_ad_outside_period_or_without_candidates_is_undistributed() -> None:
    o = order([line("A")], day=date(2026, 10, 5))
    late = ad(start=date(2026, 11, 1), end=date(2026, 11, 30), spend="12.00")
    result = calculate_profit(data([o], ad_records=(late,)))
    assert result.period.period_level_expenses.advertising_undistributed == D("12.00")
    assert result.lines[0].items.advertising == D("0.00")
    edge = calculate_profit(data([o], ad_records=(ad(start=date(2026, 10, 5), end=date(2026, 10, 5)),)))
    assert edge.lines[0].items.advertising == D("120.00")  # uç günler dahil


def test_ad_revenue_accumulates_and_zero_spend_has_no_roas() -> None:
    o = order([line("A")])
    records = (
        ad("1", "50.00", barcode="A", ad_revenue="100.00"),
        ad("2", "50.00", barcode="A", ad_revenue="300.00"),
        ad("3", "10.00", barcode="A"),
    )
    product = calculate_profit(data([o], ad_records=records, costs=(cost("A"),))).products[0]
    assert product.advertising_revenue == D("400.00")
    assert product.roas == D("3.64")  # 400 / 110
    nothing = calculate_profit(data([o], ad_records=(ad("0", "0.00", barcode="A", ad_revenue="9.00"),)))
    assert nothing.products[0].roas is None


def test_break_even_roas_and_missing_cost() -> None:
    o = order([line("A", price="120.00")])
    with_cost = calculate_profit(
        data(
            [o],
            ad_records=(ad(barcode="A", spend="20.00", ad_revenue="240.00"),),
            costs=(cost("A", "10.00"),),
        )
    ).products[0]
    # net satış 100,00; gider 10 komisyon + 45 kargo + 10 hizmet + 20 reklam + 10 maliyet = 95; net kâr 5,00
    assert with_cost.net_profit == D("5.00")
    assert with_cost.breakeven_roas == D("4.00")  # 100,00 / (5,00 + 20,00)
    no_cost = calculate_profit(
        data([o], ad_records=(ad(barcode="A", spend="20.00", ad_revenue="240.00"),))
    ).products[0]
    assert no_cost.net_profit is None
    assert no_cost.breakeven_roas is None
    assert no_cost.roas == D("12.00")
    assert no_cost.product_cost is None


# --------------------------------------------------------------------------- değişken giderler (K17)
def test_variable_expenses_all_kinds() -> None:
    a, b = line("A", price="120.00"), line("B", price="360.00", qty=2)
    cancelled = order([line("C")], number="O2", status="Cancelled")
    o = order([a, b], number="O1")
    expenses = (
        VariableExpense("paket", ExpenseKind.PER_ORDER, amount_excl_vat=D("6.00")),
        VariableExpense("etiket", ExpenseKind.PER_UNIT, amount_excl_vat=D("0.50"), vat_rate=D("10")),
        VariableExpense("entegrator", ExpenseKind.PERCENT_OF_SALES, percent=D("0.5")),
    )
    result = calculate_profit(data([o, cancelled], settings=make_settings(variable_expenses=expenses)))
    ra, rb, rc = result.lines
    # sipariş başı 6,00: satış 100,00 : 600,00 oranı (1:6)
    assert [d.name for d in ra.variable_expense_details] == ["paket", "etiket", "entegrator"]
    assert ra.items.variable_expenses == D("0.86") + D("0.50") + D("0.50")
    assert rb.items.variable_expenses == D("5.14") + D("1.00") + D("3.00")
    assert ra.sources.variable_expenses is Source.USER
    assert rc.items.variable_expenses == D("0.00")
    assert rc.sources.variable_expenses is Source.NONE
    assert ra.vat.variable_expenses_vat + rb.vat.variable_expenses_vat == D(
        "2.05"
    )  # 1,20 + 0,15 (%10) + 0,70


# --------------------------------------------------------------------------- toplulaştırma (K25)
def test_period_totals_are_sums_of_rounded_line_values() -> None:
    lines = [line("A", price="12.03", qty=3), line("B", price="33.33")]
    o = order(lines)
    result = calculate_profit(data([o], costs=(cost("A", "3.335"), cost("B"))))
    assert result.period.line_net_profit_total == sum(
        (r.items.net_profit or D(0) for r in result.lines), D(0)
    )
    assert result.period.period_net_profit == result.period.line_net_profit_total
    assert result.period.order_count == 1
    assert result.period.line_count == 2
    assert result.period.vat_effect == sum((r.vat.vat_effect for r in result.lines), D(0))
    for product in result.products:
        line_result = next(r for r in result.lines if r.barcode == product.barcode)
        assert product.net_profit == line_result.items.net_profit
        assert product.net_margin_percent == line_result.items.net_margin_percent


def test_period_net_profit_subtracts_period_level_expenses() -> None:
    o = order([line("A")])
    result = calculate_profit(
        data(
            [o],
            costs=(cost("A"),),
            ad_records=(ad(spend="12.00", start=date(2027, 1, 1), end=date(2027, 1, 2)),),
        )
    )
    assert result.period.period_net_profit == result.period.line_net_profit_total - D("12.00")
    assert result.period.net_margin_percent is not None
