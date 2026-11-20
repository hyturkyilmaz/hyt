"""Uyarı kuralı testleri için küçük kurucular (sentetik değerler; gerçek veri değildir)."""

from __future__ import annotations

from decimal import Decimal

from app.profit.enums import Certainty, MissingItem, Source, Status, WarningCode
from app.profit.money import ZERO
from app.profit.results import (
    AdDetail,
    CertaintyCounts,
    FullLinesTotals,
    LineCashFlow,
    LineComparison,
    LineItems,
    LineResult,
    LineSources,
    LineVat,
    MissingCounts,
    PeriodCashFlow,
    PeriodLevelExpenses,
    PeriodTotals,
    ProductTotals,
    ProfitResult,
)

D = Decimal
_Z = ZERO


def make_items(net_profit: str | None, known: str | None = None) -> LineItems:
    """Yalnız `net_kar` ve `eksik_giderler_haric_kar` anlamlı; diğer kalemler sıfır."""
    known_value = known if known is not None else net_profit
    assert known_value is not None
    return LineItems(
        gross_sales_incl_vat=_Z,
        seller_discount_incl_vat=_Z,
        ty_discount_incl_vat=_Z,
        sales_incl_vat=_Z,
        sales_excl_vat=_Z,
        refund_incl_vat=_Z,
        refund_excl_vat=_Z,
        net_sales_excl_vat=_Z,
        product_cost=_Z,
        commission=_Z,
        shipping_outbound=_Z,
        shipping_return=_Z,
        platform_service_fee=_Z,
        penalty=_Z,
        advertising=_Z,
        variable_expenses=_Z,
        total_expenses=_Z,
        contribution_before_cost=_Z,
        known_expenses_profit=D(known_value),
        net_profit=None if net_profit is None else D(net_profit),
        net_margin_percent=None,
    )


def make_comparison(
    difference: str,
    threshold: str = "5.00",
    default_desi: bool = False,
    ship_estimated: str | None = None,
    ship_actual: str | None = None,
) -> LineComparison:
    return LineComparison(
        commission_estimated=_Z,
        commission_actual=_Z,
        shipping_outbound_estimated=None if ship_estimated is None else D(ship_estimated),
        shipping_outbound_actual=None if ship_actual is None else D(ship_actual),
        platform_service_fee_estimated=None,
        platform_service_fee_actual=None,
        shipping_estimate_default_desi=default_desi,
        compared_estimated_total=_Z,
        compared_actual_total=_Z,
        difference=D(difference),
        threshold=D(threshold),
    )


_VAT = LineVat(
    sales_vat=_Z,
    refund_vat=_Z,
    commission_vat=_Z,
    shipping_vat=_Z,
    platform_service_fee_vat=_Z,
    penalty_vat=_Z,
    product_cost_vat=_Z,
    variable_expenses_vat=_Z,
    advertising_vat=_Z,
    vat_effect=_Z,
)
_CASH = LineCashFlow(_Z, _Z, _Z, _Z)
_SOURCES = LineSources(*([Source.NONE] * 9))


def make_line(
    barcode: str = "A",
    net_profit: str | None = "-10.00",
    *,
    known: str | None = None,
    warnings: tuple[WarningCode, ...] = (WarningCode.LOSS,),
    status: Status = Status.ESTIMATED,
    refunded: int = 0,
    pending: int = 0,
    certainty: Certainty = Certainty.CERTAIN,
    missing: tuple[MissingItem, ...] = (),
    comparison: LineComparison | None = None,
    ad_details: tuple[AdDetail, ...] = (),
    order_number: str = "O1",
    package_id: int = 11,
    line_id: int = 101,
) -> LineResult:
    return LineResult(
        order_number=order_number,
        package_id=package_id,
        line_id=line_id,
        barcode=barcode,
        status=status,
        quantity=1,
        refunded_quantity=refunded,
        pending_refund_quantity=pending,
        suspended_product_cost=None,
        certainty=certainty,
        missing_items=missing,
        items=make_items(net_profit, known),
        vat=_VAT,
        cash_flow=_CASH,
        sources=_SOURCES,
        variable_expense_details=(),
        ad_details=ad_details,
        comparison=comparison,
        warnings=warnings,
        pending_confirmation=(),
    )


def make_product(
    barcode: str = "A",
    net_profit: str | None = "40.00",
    spend: str = "60.00",
    unsold: str = "0.00",
) -> ProductTotals:
    return ProductTotals(
        barcode=barcode,
        line_count=1,
        quantity=1,
        refunded_quantity=0,
        net_sales_excl_vat=_Z,
        product_cost=_Z,
        commission=_Z,
        shipping_outbound=_Z,
        shipping_return=_Z,
        platform_service_fee=_Z,
        penalty=_Z,
        advertising_allocated=_Z,
        advertising_without_sales=D(unsold),
        variable_expenses=_Z,
        contribution_before_cost=_Z,
        known_expenses_profit=_Z,
        net_profit=None if net_profit is None else D(net_profit),
        net_margin_percent=None,
        cost_missing=False,
        missing_line_counts=MissingCounts(0, 0, 0),
        certainty=Certainty.ESTIMATED,
        advertising_spend=D(spend),
        advertising_revenue=None,
        roas=None,
        breakeven_roas=None,
        withholding=_Z,
    )


def make_period() -> PeriodTotals:
    return PeriodTotals(
        order_count=0,
        line_count=0,
        net_sales_excl_vat=_Z,
        product_cost=_Z,
        commission=_Z,
        shipping_outbound=_Z,
        shipping_return=_Z,
        platform_service_fee=_Z,
        penalty_allocated=_Z,
        advertising_allocated=_Z,
        variable_expenses=_Z,
        line_net_profit_total=_Z,
        period_level_expenses=PeriodLevelExpenses(_Z, _Z, _Z, _Z, _Z),
        period_level_expenses_total=_Z,
        period_net_profit=_Z,
        period_known_expenses_profit=_Z,
        net_profit_partial=False,
        missing_cost_line_count=0,
        missing_line_counts=MissingCounts(0, 0, 0),
        net_margin_percent=None,
        full_lines=FullLinesTotals(0, _Z, _Z, _Z, _Z, _Z, _Z, _Z, _Z, _Z, _Z, _Z, None),
        certainty=Certainty.NONE,
        certainty_line_counts=CertaintyCounts(0, 0, 0),
        vat_effect=_Z,
        cash_flow=PeriodCashFlow(_Z, _Z, _Z),
        warnings=(),
        pending_confirmation=(),
    )


def make_result(lines: tuple[LineResult, ...] = (), products: tuple[ProductTotals, ...] = ()) -> ProfitResult:
    return ProfitResult(lines=lines, products=products, period=make_period(), cargo_invoice_vat_status={})
