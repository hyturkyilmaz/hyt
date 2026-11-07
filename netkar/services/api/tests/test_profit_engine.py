"""Kâr motoru birim testleri: ekstre eşleştirme, maliyet, iade kalemleri, durum, düşük güvenli kurallar.

Sentetik senaryolar; beklenen değerler docs/12 formüllerinden elle hesaplanmıştır.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.profit import ProfitInputError, calculate_profit
from app.profit.enums import Source, Status, WarningCode
from app.profit.inputs import (
    Claim,
    ClaimItem,
    CompensationTicket,
    CostRecord,
    OrderLine,
)
from app.profit.pending import LOW_CONFIDENCE_RULES, pending_rule_for
from tests.profit_helpers import D, data, line, make_settings, order, ret, sale


def cost(
    barcode: str = "B1", unit: str = "30.00", valid_from: date = date(2026, 1, 1), vat: str = "20"
) -> CostRecord:
    return CostRecord(barcode, valid_from, D(unit), D(vat))


# --------------------------------------------------------------------------- girdi doğrulama
def test_zero_or_negative_quantity_is_rejected() -> None:
    ln = line()
    for quantity in (0, -1):
        with pytest.raises(ProfitInputError, match="adet"):
            OrderLine(1, "B", quantity, D("1"), D("20"), D("10"), ())
    assert ln.quantity == 1


def test_item_count_must_match_quantity() -> None:
    ln = line(qty=2)
    with pytest.raises(ProfitInputError, match="kalem sayısı"):
        OrderLine(1, "B", 3, D("1"), D("20"), D("10"), ln.items)


def test_empty_input_yields_empty_result() -> None:
    result = calculate_profit(data([]))
    assert result.lines == ()
    assert result.products == ()
    assert result.period.period_net_profit == D("0.00")
    assert result.period.net_margin_percent is None
    assert result.period.order_count == 0


def test_order_cancelled_statuses() -> None:
    assert order(status="Cancelled").is_cancelled
    assert order(status="UnSupplied").is_cancelled
    assert not order(status="Delivered").is_cancelled


# --------------------------------------------------------------------------- tahmini satır
def test_estimated_line_breakdown() -> None:
    o = order([line(price="100.00")])
    r = calculate_profit(data([o], costs=(cost(unit="30.00"),))).lines[0]
    assert r.status is Status.ESTIMATED
    assert r.items.sales_excl_vat == D("83.33")
    assert r.vat.sales_vat == D("16.67")
    assert r.items.commission == D("8.33")  # 10,00 KDV dahil komisyon
    assert r.vat.commission_vat == D("1.67")
    assert r.items.shipping_outbound == D("45.00")
    assert r.items.platform_service_fee == D("10.00")
    assert r.items.product_cost == D("30.00")
    assert r.items.total_expenses == D("93.33")
    assert r.items.net_profit == D("-10.00")
    assert r.items.contribution_before_cost == D("20.00")
    assert WarningCode.LOSS in r.warnings
    assert r.sources.sales is Source.ESTIMATED
    assert r.sources.shipping_outbound is Source.ESTIMATED
    assert r.sources.platform_service_fee is Source.ESTIMATED
    assert r.comparison is None


def test_stopaj_is_cash_flow_only_and_never_a_cost() -> None:
    o = order([line(price="100.00")])
    base = calculate_profit(data([o], costs=(cost(),))).lines[0]
    high = calculate_profit(
        data([o], costs=(cost(),), settings=make_settings(withholding_rate=D("5")))
    ).lines[0]
    assert base.items == high.items
    assert base.cash_flow.withholding == D("0.83")
    assert high.cash_flow.withholding == D("4.17")
    assert high.cash_flow.expected_net_collection < base.cash_flow.expected_net_collection


# --------------------------------------------------------------------------- ekstre eşleştirme (K27)
def test_same_barcode_lines_share_row_by_quantity() -> None:
    first, second = line(qty=1), line(qty=2)
    o = order([first, second])
    row = sale(o, first, credit="300.00", commission_amount=D("30"), seller_revenue=D("270"))
    result = calculate_profit(data([o], settlements=(row,), costs=(cost(),)))
    a, b = result.lines
    assert a.items.sales_incl_vat == D("100.00")
    assert b.items.sales_incl_vat == D("200.00")
    assert a.items.commission == D("8.33")
    assert b.items.commission == D("16.67")


def test_package_mismatch_is_not_matched_but_null_package_matches() -> None:
    ln = line()
    o = order([ln])
    other_package = sale(o, ln, package_id=o.package_id + 999)
    assert calculate_profit(data([o], settlements=(other_package,))).lines[0].status is Status.ESTIMATED
    no_package = sale(o, ln, package_id=None)
    assert calculate_profit(data([o], settlements=(no_package,))).lines[0].status is Status.SETTLED


def test_settled_uses_statement_and_flags_commission_rate_and_inconsistency() -> None:
    ln = line(commission="10")
    o = order([ln])
    row = sale(o, ln, commission_rate=D("12"), commission_amount=D("12"), seller_revenue=D("50"))
    r = calculate_profit(data([o], settlements=(row,))).lines[0]
    assert r.status is Status.SETTLED
    assert r.sources.sales is Source.ACTUAL
    assert r.items.commission == D("10.00")  # 12,00 KDV dahil
    assert WarningCode.COMMISSION_RATE_DIFFERENT in r.warnings
    assert WarningCode.STATEMENT_INCONSISTENT in r.warnings
    assert r.comparison is not None


def test_commission_amount_excluding_vat_setting() -> None:
    ln = line(commission="10")
    o = order([ln])
    r = calculate_profit(
        data([o], settings=make_settings(commission_includes_vat=False), settlements=(sale(o, ln),))
    ).lines[0]
    assert r.items.commission == D("10.00")
    assert r.vat.commission_vat == D("2.00")


def test_cancelled_order_is_zero_and_excluded_from_totals() -> None:
    ln = line()
    o = order([ln], status="Cancelled")
    result = calculate_profit(data([o], settlements=(sale(o, ln),), costs=(cost(),)))
    r = result.lines[0]
    assert r.status is Status.CANCELLED
    assert r.items.net_profit == D("0.00")
    assert r.items.net_margin_percent is None
    assert r.items.sales_incl_vat == D("0.00")
    assert r.vat.product_cost_vat == D("0.00")
    assert r.sources.product_cost is Source.NONE
    assert r.items.shipping_outbound == D("0.00")
    assert result.period.line_count == 0
    assert result.products[0].line_count == 0


# --------------------------------------------------------------------------- düşük güvenli kurallar (K29-K32)
def test_pending_rule_lookup() -> None:
    assert pending_rule_for("Sale") is None
    assert pending_rule_for("DeliveryFee") == "K29"
    assert pending_rule_for("TyCoupon") == "K30"
    assert pending_rule_for("ProvisionNegative") == "K32"
    assert pending_rule_for("SomethingNew") == "K05"
    assert set(LOW_CONFIDENCE_RULES) == {"K05", "K29", "K30", "K31", "K32"}


def test_delivery_fee_is_treated_as_sale_and_flagged_k29() -> None:
    ln = line()
    o = order([ln])
    fee = sale(o, ln, credit="10.00", request_type="DeliveryFee", commission_amount=D("1"))
    r = calculate_profit(data([o], settlements=(sale(o, ln), fee))).lines[0]
    assert r.items.sales_incl_vat == D("110.00")
    assert r.pending_confirmation == ("K29",)
    assert WarningCode.STATEMENT_INCONSISTENT not in r.warnings


def test_delivery_fee_alone_does_not_settle_the_line() -> None:
    ln = line()
    o = order([ln])
    fee = sale(o, ln, credit="10.00", request_type="DeliveryFee")
    r = calculate_profit(data([o], settlements=(fee,))).lines[0]
    assert r.status is Status.ESTIMATED
    assert r.pending_confirmation == ("K29",)


def test_ty_discount_rows_do_not_change_revenue_and_are_flagged_k30() -> None:
    ln = line()
    o = order([ln])
    base = calculate_profit(data([o], settlements=(sale(o, ln),))).lines[0]
    ty = sale(o, ln, credit="0", request_type="TyDiscount", debt=D("20"), commission_amount=D("0"))
    r = calculate_profit(data([o], settlements=(sale(o, ln), ty))).lines[0]
    assert r.items == base.items
    assert r.pending_confirmation == ("K30",)


def test_provision_rows_are_sales_and_flagged_k32() -> None:
    ln = line()
    o = order([ln])
    prov = sale(o, ln, credit="5.00", request_type="ProvisionPositive")
    r = calculate_profit(data([o], settlements=(sale(o, ln), prov))).lines[0]
    assert r.items.sales_incl_vat == D("105.00")
    assert r.pending_confirmation == ("K32",)


def test_unknown_row_type_is_ignored_and_flagged_k05() -> None:
    ln = line()
    o = order([ln])
    mystery = sale(o, ln, credit="999.00", request_type="MysteryType")
    alone = calculate_profit(data([o], settlements=(mystery,))).lines[0]
    assert alone.status is Status.ESTIMATED
    assert alone.items.sales_incl_vat == D("100.00")
    assert alone.pending_confirmation == ("K05",)
    both = calculate_profit(data([o], settlements=(sale(o, ln), mystery)))
    assert both.lines[0].items.sales_incl_vat == D("100.00")
    assert both.period.pending_confirmation == ("K05",)


def test_compensation_ticket_sets_period_flag_only() -> None:
    o = order([line()])
    ticket = CompensationTicket("O1", "CompensationApproved", D("50.00"))
    plain = calculate_profit(data([o]))
    flagged = calculate_profit(data([o], compensation_tickets=(ticket,)))
    assert flagged.period.pending_confirmation == ("K31",)
    assert plain.period.pending_confirmation == ()
    assert flagged.period.period_net_profit == plain.period.period_net_profit


# --------------------------------------------------------------------------- iade kalemleri ve maliyet (K10, K16)
def test_refund_items_stock_scrap_and_ignored_claims() -> None:
    ln = line(qty=2)
    o = order([ln])
    claims = (
        Claim(
            "O1",
            (
                ClaimItem(ln.items[0].item_id, "Accepted", True),
                ClaimItem(ln.items[1].item_id, "Accepted", False),
                ClaimItem(ln.items[0].item_id, "Rejected", True),
                ClaimItem("no-such-item", "Accepted", True),
            ),
        ),
        Claim("OTHER", (ClaimItem(ln.items[0].item_id, "Accepted", True),)),
    )
    r = calculate_profit(data([o], claims=claims, costs=(cost(unit="30.00"),))).lines[0]
    assert r.refunded_quantity == 2
    assert r.items.product_cost == D("30.00")  # biri stoğa döndü, biri satılamaz
    assert r.vat.product_cost_vat == D("6.00")


def test_cost_effective_date_and_missing_cost() -> None:
    o = order([line()], day=date(2026, 10, 5))
    costs = (
        cost(unit="40.00", valid_from=date(2026, 10, 1)),
        cost(unit="30.00", valid_from=date(2026, 1, 1)),
        cost(unit="99.00", valid_from=date(2026, 10, 6)),  # henüz geçerli değil
        cost(barcode="OTHER", unit="1.00"),
    )
    r = calculate_profit(data([o], costs=costs)).lines[0]
    assert r.items.product_cost == D("40.00")
    assert r.sources.product_cost is Source.USER

    missing = calculate_profit(data([o], costs=(cost(unit="1.00", valid_from=date(2026, 11, 1)),)))
    mr = missing.lines[0]
    assert mr.items.product_cost is None
    assert mr.items.net_profit is None
    assert mr.items.total_expenses is None
    assert mr.items.net_margin_percent is None
    assert mr.vat.product_cost_vat is None
    assert mr.sources.product_cost is Source.MISSING
    assert WarningCode.MISSING_COST in mr.warnings
    assert WarningCode.LOSS not in mr.warnings
    assert mr.items.contribution_before_cost == D("20.00")
    assert missing.products[0].cost_missing
    assert missing.products[0].net_profit is None
    assert missing.period.net_profit_partial
    assert missing.period.missing_cost_line_count == 1
    assert WarningCode.MISSING_COST_LINES in missing.period.warnings
    assert missing.period.line_net_profit_total == D("0.00")


def test_same_date_cost_records_use_the_last_one() -> None:
    o = order([line()])
    r = calculate_profit(data([o], costs=(cost(unit="10.00"), cost(unit="20.00")))).lines[0]
    assert r.items.product_cost == D("20.00")


# --------------------------------------------------------------------------- durum makinesi (K22)
def test_status_adjusted_by_return_row() -> None:
    ln = line(qty=1)
    o = order([ln])
    r = calculate_profit(data([o], settlements=(sale(o, ln), ret(o, ln, "100.00")))).lines[0]
    assert r.status is Status.ADJUSTED
    assert r.items.refund_incl_vat == D("100.00")
    assert r.items.net_sales_excl_vat == D("0.00")
    assert r.items.net_margin_percent is None
    assert r.items.commission == D("0.00")


def test_status_adjusted_by_order_penalty() -> None:
    from tests.profit_helpers import other

    ln = line()
    o = order([ln])
    penalty = other("DeductionInvoices", debt="12.00", order_number="O1", category="ceza", vat_rate=D("20"))
    r = calculate_profit(data([o], settlements=(sale(o, ln),), other_financials=(penalty,))).lines[0]
    assert r.status is Status.ADJUSTED
    assert r.items.penalty == D("10.00")
    assert r.vat.penalty_vat == D("2.00")


def test_unmatched_payout_adjustment_adds_to_sales() -> None:
    ln = line()
    o = order([ln])
    adj = sale(o, ln, credit="20.00", request_type="SellerRevenuePositive", commission_amount=D("0"))
    r = calculate_profit(data([o], settlements=(sale(o, ln), adj))).lines[0]
    assert r.status is Status.ADJUSTED
    assert r.items.sales_incl_vat == D("120.00")
    assert WarningCode.UNMATCHED_PAYOUT_ADJUSTMENT in r.warnings


def test_unexpected_deduction_only_above_both_thresholds() -> None:
    ln = line(commission="10")
    o = order([ln])
    # komisyon oranı 10 -> 19: fark (19-10)/1,2 = 7,50 > max(5, %5)
    high = sale(o, ln, commission_rate=D("19"), commission_amount=D("19"), seller_revenue=D("81"))
    r = calculate_profit(data([o], settlements=(high,))).lines[0]
    assert WarningCode.UNEXPECTED_DEDUCTION in r.warnings
    assert r.comparison is not None
    assert r.comparison.difference == D("7.50")
    # lehe fark uyarı vermez
    low = sale(o, ln, commission_rate=D("1"), commission_amount=D("1"), seller_revenue=D("99"))
    r2 = calculate_profit(data([o], settlements=(low,))).lines[0]
    assert WarningCode.UNEXPECTED_DEDUCTION not in r2.warnings
    assert r2.comparison is not None
    assert r2.comparison.difference < 0
