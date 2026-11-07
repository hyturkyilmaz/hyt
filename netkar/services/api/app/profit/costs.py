"""Ürün maliyeti, iade kalemleri ve değişken giderler (K10, K16, K17)."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

from app.profit.enums import ExpenseKind, Source, WarningCode
from app.profit.inputs import Claim, CostRecord
from app.profit.money import allocate, split_exclusive
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork, active_only, group_by, sales_weights

ACCEPTED_CLAIM_STATUS = "Accepted"


def apply_refund_items(w: LineWork, claims: Sequence[Claim]) -> None:
    """K10: kabul edilmiş iade kalemlerini sayar (kalem kimliği satırın `discountDetails` kümesinde).

    Stoğa dönmeyen (`returned_to_stock=False`) kalemin maliyeti gider kalır.
    """
    item_ids = {item.item_id for item in w.line.items}
    for claim in claims:
        if claim.order_number != w.order.order_number:
            continue
        for item in claim.items:
            if item.order_line_item_id in item_ids and item.status == ACCEPTED_CLAIM_STATUS:
                if item.returned_to_stock:
                    w.refunded_in_stock += 1
                else:
                    w.refunded_scrapped += 1


def apply_product_cost(w: LineWork, costs: Sequence[CostRecord]) -> None:
    """K16: sipariş gününde geçerli en son maliyet kaydı; yoksa maliyet None (sıfır varsayılmaz)."""
    if w.cancelled:
        w.cost_excl = w.cost_vat = Decimal("0.00")
        w.src_cost = Source.NONE
        return
    candidates = sorted(
        (c for c in costs if c.barcode == w.line.barcode and c.valid_from <= w.order.order_day),
        key=lambda c: c.valid_from,
    )
    if not candidates:
        w.cost_excl = w.cost_vat = None
        w.warnings.append(WarningCode.MISSING_COST)
        w.src_cost = Source.MISSING
        return
    record = candidates[-1]
    billable = w.quantity - w.refunded_in_stock
    w.cost_excl, w.cost_vat = split_exclusive(record.unit_cost_excl_vat * billable, record.vat_rate)
    w.src_cost = Source.USER


def apply_variable_expenses(works: Sequence[LineWork], settings: ProfitSettings) -> None:
    """K17: sipariş başı (satırlara satış oranıyla), adet başı ve satış yüzdesi giderler."""
    by_order = group_by(works, lambda w: w.order.order_number)
    for expense in settings.variable_expenses:
        if expense.kind is ExpenseKind.PER_ORDER:
            for group in by_order.values():
                active = active_only(group)
                if not active:
                    continue
                excl, vat = split_exclusive(expense.amount_excl_vat, expense.vat_rate)
                weights = sales_weights(active)
                for w, part_excl, part_vat in zip(
                    active, allocate(excl, weights), allocate(vat, weights), strict=True
                ):
                    _add_variable(w, expense.name, part_excl, part_vat)
        else:
            for w in active_only(works):
                if expense.kind is ExpenseKind.PER_UNIT:
                    base = Fraction(expense.amount_excl_vat * w.quantity)
                else:
                    base = Fraction(w.net_sales) * Fraction(expense.percent) / 100
                excl, vat = split_exclusive(base, expense.vat_rate)
                _add_variable(w, expense.name, excl, vat)
    for w in works:
        w.src_var = Source.USER if w.var_details else Source.NONE


def _add_variable(w: LineWork, name: str, excl: Decimal, vat: Decimal) -> None:
    w.var_excl += excl
    w.var_vat += vat
    w.var_details.append((name, excl))
