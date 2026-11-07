"""Ürün ve dönem toplulaştırma, marj, ROAS ve başabaş ROAS (K25, K18).

Ürün ve dönem toplamları satırların yuvarlanmış değerlerinin toplamıdır; yeniden hesaplanmaz.
İptal satırları toplamlara girmez.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.profit.advertising import AdOutcome
from app.profit.enums import Status, WarningCode
from app.profit.fees import PeriodAccumulator
from app.profit.inputs import CompensationTicket
from app.profit.money import percent_of, ratio
from app.profit.pending import pending_rules_for_tickets
from app.profit.results import (
    LineResult,
    PeriodCashFlow,
    PeriodLevelExpenses,
    PeriodTotals,
    ProductTotals,
)
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork

ZERO = Decimal("0.00")


def aggregate_products(
    works: Sequence[LineWork],
    lines: Sequence[LineResult],
    ads: AdOutcome,
) -> tuple[ProductTotals, ...]:
    """K25: barkod bazında toplam. Satışsız reklam harcaması ürünün net kârından düşülür."""
    order: list[str] = []
    by_barcode: dict[str, list[tuple[LineWork, LineResult]]] = {}
    for w, result in zip(works, lines, strict=True):
        if w.line.barcode not in by_barcode:
            order.append(w.line.barcode)
            by_barcode[w.line.barcode] = []
        by_barcode[w.line.barcode].append((w, result))
    order.extend(code for code in ads.unsold_by_barcode if code not in by_barcode)

    products: list[ProductTotals] = []
    for barcode in order:
        pairs = [(w, r) for w, r in by_barcode.get(barcode, []) if w.active]
        results = [r for _, r in pairs]
        unsold = ads.unsold_by_barcode.get(barcode, ZERO)
        cost_missing = any(r.items.product_cost is None for r in results)
        net_sales = sum((r.items.net_sales_excl_vat for r in results), ZERO)
        advertising = sum((r.items.advertising for r in results), ZERO)
        net_profit = (
            None if cost_missing else sum((r.items.net_profit or ZERO for r in results), ZERO) - unsold
        )
        spend = advertising + unsold
        revenue = ads.revenue_by_barcode.get(barcode)
        before_ads = None if net_profit is None else net_profit + spend
        roas = None if revenue is None else ratio(revenue, spend)
        breakeven = (
            ratio(net_sales, before_ads) if before_ads is not None and before_ads > 0 and spend > 0 else None
        )
        products.append(
            ProductTotals(
                barcode=barcode,
                line_count=len(results),
                quantity=sum(r.quantity for r in results),
                refunded_quantity=sum(r.refunded_quantity for r in results),
                net_sales_excl_vat=net_sales,
                product_cost=None
                if cost_missing
                else sum((r.items.product_cost or ZERO for r in results), ZERO),
                commission=sum((r.items.commission for r in results), ZERO),
                shipping_outbound=sum((r.items.shipping_outbound for r in results), ZERO),
                shipping_return=sum((r.items.shipping_return for r in results), ZERO),
                platform_service_fee=sum((r.items.platform_service_fee for r in results), ZERO),
                penalty=sum((r.items.penalty for r in results), ZERO),
                advertising_allocated=advertising,
                advertising_without_sales=unsold,
                variable_expenses=sum((r.items.variable_expenses for r in results), ZERO),
                contribution_before_cost=sum((r.items.contribution_before_cost for r in results), ZERO)
                - unsold,
                net_profit=net_profit,
                net_margin_percent=None if net_profit is None else percent_of(net_profit, net_sales),
                cost_missing=cost_missing,
                advertising_spend=spend,
                advertising_revenue=revenue,
                roas=roas,
                breakeven_roas=breakeven,
                withholding=sum((r.cash_flow.withholding for r in results), ZERO),
            )
        )
    return tuple(products)


def aggregate_period(
    lines: Sequence[LineResult],
    ads: AdOutcome,
    acc: PeriodAccumulator,
    settings: ProfitSettings,
    tickets: Sequence[CompensationTicket],
) -> PeriodTotals:
    """K25: dönem toplamı = satır net kârları (maliyeti olan satırlar) - dönem düzeyi giderler."""
    active = [r for r in lines if r.status is not Status.CANCELLED]
    unsold_total = sum(ads.unsold_by_barcode.values(), ZERO)
    missing = sum(1 for r in active if r.items.product_cost is None)
    line_profit = sum((r.items.net_profit for r in active if r.items.net_profit is not None), ZERO)
    period_expenses = (
        unsold_total
        + acc.advertising_undistributed
        + acc.undistributed_penalty
        + acc.early_payment_fee
        + acc.unclassified_deduction
    )
    withholding = sum((r.cash_flow.withholding for r in active), ZERO)
    warnings = list(acc.warnings)
    if missing:
        warnings.append(WarningCode.MISSING_COST_LINES)
    if acc.withholding_statement != 0 and (
        abs(acc.withholding_statement - withholding) > settings.thresholds.rounding_tolerance
    ):
        warnings.append(WarningCode.WITHHOLDING_STATEMENT_DIFF)
    net_sales = sum((r.items.net_sales_excl_vat for r in active), ZERO)
    pending = {rule for r in active for rule in r.pending_confirmation}
    pending |= pending_rules_for_tickets(tickets)
    return PeriodTotals(
        order_count=len({r.order_number for r in active}),
        line_count=len(active),
        net_sales_excl_vat=net_sales,
        product_cost=sum((r.items.product_cost for r in active if r.items.product_cost is not None), ZERO),
        commission=sum((r.items.commission for r in active), ZERO),
        shipping_outbound=sum((r.items.shipping_outbound for r in active), ZERO),
        shipping_return=sum((r.items.shipping_return for r in active), ZERO),
        platform_service_fee=sum((r.items.platform_service_fee for r in active), ZERO),
        penalty_allocated=sum((r.items.penalty for r in active), ZERO),
        advertising_allocated=sum((r.items.advertising for r in active), ZERO),
        variable_expenses=sum((r.items.variable_expenses for r in active), ZERO),
        line_net_profit_total=line_profit,
        period_level_expenses=PeriodLevelExpenses(
            advertising_unsold_products=unsold_total,
            advertising_undistributed=acc.advertising_undistributed,
            undistributed_penalty=acc.undistributed_penalty,
            early_payment_fee=acc.early_payment_fee,
            unclassified_deduction=acc.unclassified_deduction,
        ),
        period_net_profit=line_profit - period_expenses,
        net_profit_partial=missing > 0,
        missing_cost_line_count=missing,
        net_margin_percent=percent_of(line_profit - period_expenses, net_sales),
        vat_effect=sum((r.vat.vat_effect for r in active), ZERO),
        cash_flow=PeriodCashFlow(
            withholding_calculated=withholding,
            withholding_statement=acc.withholding_statement,
            early_payment_cash_in=acc.early_payment_cash_in,
        ),
        warnings=tuple(warnings),
        pending_confirmation=tuple(sorted(pending)),
    )
