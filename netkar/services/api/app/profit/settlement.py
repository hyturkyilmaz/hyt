"""Ekstre eşleştirme ve satış, iade, komisyon hesabı (K04, K05, K06, K07, K27, K28).

Kesin değerler ekstreden, ekstre gelmemiş satırlarda tahmini değerler sipariş satırından alınır.
Ara adımlar tam hassasiyetli kalır; kuruşa yuvarlama satır sonunda bir kez yapılır (K01).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction

from app.profit.constants import (
    ADJUSTMENT_TYPES,
    COMMISSION_SIGN,
    CONSISTENCY_TYPES,
    REFUND_TYPES,
    REVENUE_TYPES,
    SALE_TRIGGER_TYPES,
)
from app.profit.enums import Source, WarningCode
from app.profit.inputs import SettlementRow
from app.profit.money import split_exclusive, split_inclusive
from app.profit.pending import pending_rule_for
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork, group_by

CONSISTENCY_TOLERANCE = Decimal("0.01")


def match_rows(works: Sequence[LineWork], rows: Sequence[SettlementRow]) -> None:
    """K27: ekstre satırı -> sipariş satırı. `orderNumber` ve `barcode` eşit, paket eşit ya da ekstrede null.

    Aynı barkod aynı siparişte birden çok satırdaysa satırın tutarı satırlara adet oranında paylaştırılır.
    """
    index = group_by(works, lambda w: (w.order.order_number, w.line.barcode))
    for row in rows:
        targets = [
            w
            for w in index.get((row.order_number, row.barcode), [])
            if row.package_id is None or row.package_id == w.order.package_id
        ]
        total_quantity = sum(w.quantity for w in targets)
        for w in targets:
            w.matched.append((row, Fraction(w.quantity, total_quantity)))


def _signed_commission(row: SettlementRow) -> Fraction:
    """K05: işaretli komisyon maliyeti; tutar `abs()` ile okunur, işaret tablodan gelir."""
    return COMMISSION_SIGN[row.request_type] * abs(Fraction(row.commission_amount or 0))


def _statement_inconsistent(row: SettlementRow) -> bool:
    """K28: `|sellerRevenue| = |(credit - debt) - işaret x |commissionAmount||` (0,01 tolerans)."""
    if row.request_type not in CONSISTENCY_TYPES or row.seller_revenue is None:
        return False
    expected = Fraction(row.credit - row.debt) - _signed_commission(row)
    return abs(abs(Fraction(row.seller_revenue)) - abs(expected)) > Fraction(CONSISTENCY_TOLERANCE)


def apply_settlement(w: LineWork, settings: ProfitSettings) -> None:
    """K04-K07, K22 giriş koşulları, K23 komisyon oranı farkı, K28: satış, iade ve komisyonu doldurur."""
    line = w.line
    rate = Fraction(line.commission_rate)
    estimated_sales = Fraction(w.gross - w.seller_discount)
    estimated_commission = estimated_sales * rate / 100

    # K29-K32: tanınan-teyit bekleyen ya da tanınmayan tipler bayrak taşır; yalnız bilinenler hesaba girer.
    known = [(row, share) for row, share in w.matched if row.request_type in COMMISSION_SIGN]
    for row, _ in w.matched:
        flag = pending_rule_for(row.request_type)
        if flag is not None:
            w.pending.add(flag)
    request_types = {row.request_type for row, _ in known}
    w.has_sale = bool(request_types & SALE_TRIGGER_TYPES)
    w.has_adjustment = bool(request_types & (REFUND_TYPES | ADJUSTMENT_TYPES))

    commission_sales = estimated_commission
    if w.cancelled:
        sales = refunds = commission = commission_sales = Fraction(0)
    elif w.has_sale:
        sales = sum(
            (
                share * Fraction(row.credit - row.debt)
                for row, share in known
                if row.request_type in REVENUE_TYPES
            ),
            Fraction(0),
        )
        refunds = sum(
            (
                share * Fraction(row.debt - row.credit)
                for row, share in known
                if row.request_type in REFUND_TYPES
            ),
            Fraction(0),
        )
        # K41: yalnız `Return` satırlarından gelen iade (claim'siz iade tespiti için).
        w.refund_return_incl = sum(
            (share * Fraction(row.debt - row.credit) for row, share in known if row.request_type == "Return"),
            Fraction(0),
        )
        commission = sum((share * _signed_commission(row) for row, share in known), Fraction(0))
        # K23: karşılaştırmaya giren kesin komisyon, iade ters kayıtları hariç, düzeltmeler dahil.
        commission_sales = sum(
            (share * _signed_commission(row) for row, share in known if row.request_type not in REFUND_TYPES),
            Fraction(0),
        )
        # K05: hakediş düzeltmeleri eşi olan komisyon düzeltmesiyle birlikte okunur; eşleşmeyen kalan
        # tutar gelir düzeltmesidir ve uyarı verir.
        commission_adjustment = sum(
            (
                share * _signed_commission(row)
                for row, share in known
                if row.request_type.startswith("Commission")
            ),
            Fraction(0),
        )
        payout_adjustment = sum(
            (
                share * Fraction(row.credit - row.debt)
                for row, share in known
                if row.request_type.startswith("SellerRevenue")
            ),
            Fraction(0),
        )
        residual = payout_adjustment + commission_adjustment
        if residual != 0:
            sales += residual
            w.warnings.append(WarningCode.UNMATCHED_PAYOUT_ADJUSTMENT)
        if any(_statement_inconsistent(row) for row, _ in known):
            w.warnings.append(WarningCode.STATEMENT_INCONSISTENT)
        tolerance = settings.thresholds.commission_rate_tolerance_points
        for row, _ in known:
            if (
                row.request_type == "Sale"
                and row.commission_rate is not None
                and abs(row.commission_rate - line.commission_rate) > tolerance
            ):
                w.warnings.append(WarningCode.COMMISSION_RATE_DIFFERENT)
    else:
        sales, refunds, commission = estimated_sales, Fraction(0), estimated_commission

    source = Source.ACTUAL if w.has_sale else Source.ESTIMATED
    w.src_sales = w.src_commission = source
    w.sales_incl, w.refund_incl, w.commission_exact = sales, refunds, commission
    w.sales_excl, w.sales_vat = split_inclusive(sales, line.vat_rate)
    w.refund_excl, w.refund_vat = split_inclusive(refunds, line.vat_rate)
    w.net_sales = w.sales_excl - w.refund_excl
    w.commission_excl, w.commission_vat = _split_commission(commission, settings)
    w.commission_estimated_excl = _split_commission(estimated_commission, settings)[0]
    w.commission_actual_sales_excl = _split_commission(commission_sales, settings)[0]


def _split_commission(exact: Fraction, settings: ProfitSettings) -> tuple[Decimal, Decimal]:
    """K07: commissionAmount KDV dahil ise içinden, değilse üstüne KDV ayrılır."""
    if settings.commission_includes_vat:
        return split_inclusive(exact, settings.commission_vat_rate)
    return split_exclusive(exact, settings.commission_vat_rate)
