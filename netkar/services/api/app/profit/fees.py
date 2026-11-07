"""Platform hizmet bedeli, ceza, erken ödeme, stopaj ekstresi ve sınıflandırılamayan kesintiler
(K13, K14, K18, K19).

`otherfinancials` satırları eşleme tablosunun verdiği sınıfa göre işlenir; karşılığı olmayan gider satırı
dönem düzeyinde "sınıflandırılmamış kesinti" olarak ihtiyatla kâra yansır (K14). Stopaj ve erken ödeme
nakit girişi gider değildir; yalnız nakit akışı alanlarında görünür.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.profit.constants import (
    CASH_ADVANCE_TYPE,
    CASH_MOVEMENT_TYPES,
    CATEGORY_EARLY_PAYMENT_FEE,
    CATEGORY_PENALTY,
    DEDUCTION_INVOICES_TYPE,
    PLATFORM_SERVICE_FEE_SUBTYPE,
    STOPPAGE_TYPE,
)
from app.profit.enums import Source, WarningCode
from app.profit.inputs import OtherFinancialRow
from app.profit.money import allocate, rnd, split_exclusive, split_inclusive
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork, active_only, group_by, sales_weights

ZERO = Decimal("0.00")


@dataclass(slots=True)
class PeriodAccumulator:
    """Ürüne dağıtılmayan dönem düzeyi kalemler (docs/12 §7.3)."""

    undistributed_penalty: Decimal = ZERO
    early_payment_fee: Decimal = ZERO
    unclassified_deduction: Decimal = ZERO
    advertising_undistributed: Decimal = ZERO
    withholding_statement: Decimal = ZERO
    early_payment_cash_in: Decimal = ZERO
    warnings: list[WarningCode] = field(default_factory=list)

    def add_unclassified(self, amount: Decimal) -> None:
        self.unclassified_deduction += amount
        if WarningCode.UNCLASSIFIED_DEDUCTION not in self.warnings:
            self.warnings.append(WarningCode.UNCLASSIFIED_DEDUCTION)


def _is_platform_fee(row: OtherFinancialRow) -> bool:
    return (
        row.request_type == DEDUCTION_INVOICES_TYPE and row.request_sub_type == PLATFORM_SERVICE_FEE_SUBTYPE
    )


def apply_service_fees(
    works: Sequence[LineWork],
    rows: Sequence[OtherFinancialRow],
    settings: ProfitSettings,
    acc: PeriodAccumulator,
) -> None:
    """K13: kesin fatura satırı siparişlere (ya da aynı ödeme emrindeki satışlı siparişlere) eşit dağıtılır.

    Sipariş içinde satış oranıyla dağıtılır (K24). Faturası gelmemiş sipariş tahmini kalır.
    Hiçbir siparişe bağlanamayan fatura satırı sınıflandırılmamış kesinti olur.
    """
    by_order = group_by(works, lambda w: w.order.order_number)
    covered: set[str] = set()
    for row in rows:
        if not _is_platform_fee(row):
            continue
        if row.order_number is not None:
            targets = [row.order_number] if active_only(by_order.get(row.order_number, [])) else []
        else:
            targets = [
                number
                for number, group in by_order.items()
                if row.payment_order_id is not None and _paid_in_order(group, row.payment_order_id)
            ]
        if not targets:
            acc.add_unclassified(rnd(row.debt - row.credit))
            continue
        # Fatura tutarı KDV dahil kabul edilir; hariç ve KDV ayrı dağıtılır (K24).
        excl, vat = split_inclusive(row.debt - row.credit, settings.service_fee_vat_rate)
        for number, order_excl, order_vat in zip(
            targets,
            allocate(excl, [1] * len(targets)),
            allocate(vat, [1] * len(targets)),
            strict=True,
        ):
            group = active_only(by_order[number])
            weights = sales_weights(group)
            for w, part_excl, part_vat in zip(
                group, allocate(order_excl, weights), allocate(order_vat, weights), strict=True
            ):
                w.fee_excl += part_excl
                w.fee_vat += part_vat
                w.src_fee = Source.ACTUAL_ALLOCATED
                w.fee_actual = True
            covered.add(number)

    est_excl, est_vat = split_exclusive(
        settings.estimated_service_fee_per_order_excl_vat, settings.service_fee_vat_rate
    )
    for number, order_group in by_order.items():
        group = active_only(order_group)
        if not group:
            continue
        weights = sales_weights(group)
        for w, part_excl, part_vat in zip(
            group, allocate(est_excl, weights), allocate(est_vat, weights), strict=True
        ):
            w.fee_estimated_excl = part_excl
            if number not in covered:
                w.fee_excl, w.fee_vat, w.src_fee = part_excl, part_vat, Source.ESTIMATED


def _paid_in_order(group: Sequence[LineWork], payment_order_id: int) -> bool:
    """Siparişte aynı ödeme emrine düşen bir Sale satırı olan aktif satır var mı (K13)."""
    return any(
        row.request_type == "Sale" and row.payment_order_id == payment_order_id
        for w in active_only(group)
        if w.has_sale
        for row, _ in w.matched
    )


def apply_other_financials(
    works: Sequence[LineWork],
    rows: Sequence[OtherFinancialRow],
    acc: PeriodAccumulator,
) -> None:
    """K14, K18, K19: ceza, erken ödeme bedeli, stopaj ekstresi, nakit girişi, sınıflandırılamayan kesinti."""
    by_order = group_by(works, lambda w: w.order.order_number)
    for row in rows:
        if row.request_type == STOPPAGE_TYPE:
            acc.withholding_statement += row.debt - row.credit
        elif row.request_type == CASH_ADVANCE_TYPE:
            acc.early_payment_cash_in += row.credit - row.debt
        elif _is_platform_fee(row) or row.is_cargo_invoice or row.request_type in CASH_MOVEMENT_TYPES:
            continue  # K13, K08 ya da nakit hareketi: burada gider sayılmaz
        elif row.category == CATEGORY_EARLY_PAYMENT_FEE:
            acc.early_payment_fee += _excl_of(row)[0]
        elif row.category == CATEGORY_PENALTY:
            _apply_penalty(by_order, row, acc)
        else:
            acc.add_unclassified(rnd(row.debt - row.credit))


def _excl_of(row: OtherFinancialRow) -> tuple[Decimal, Decimal]:
    """K14: `vat_rate > 0` ise tutar KDV dahil kabul edilir; değilse KDV'siz."""
    amount = row.debt - row.credit
    rate = row.vat_rate or Decimal(0)
    if rate > 0:
        return split_inclusive(amount, rate)
    return rnd(amount), ZERO


def _apply_penalty(
    by_order: dict[str, list[LineWork]], row: OtherFinancialRow, acc: PeriodAccumulator
) -> None:
    """K14: siparişe bağlı ceza satırlara satış oranıyla; bağsız ceza dönem düzeyinde (ürüne dağıtılmaz)."""
    excl, vat = _excl_of(row)
    group = active_only(by_order.get(row.order_number or "", []))
    if not group:
        acc.undistributed_penalty += excl
        return
    weights = sales_weights(group)
    for w, part_excl, part_vat in zip(group, allocate(excl, weights), allocate(vat, weights), strict=True):
        w.penalty_excl += part_excl
        w.penalty_vat += part_vat
        w.src_penalty = Source.ACTUAL_ALLOCATED
