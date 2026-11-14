"""Satır kırılımı: durum makinesi, fark tespiti, eksik kalem, kesinlik, KDV etkisi, nakit akışı
(K18, K20-K23, K25, K37, K38, K40)."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

from app.profit.constants import SELLER_PAYS_CARGO
from app.profit.enums import Certainty, MissingItem, Source, Status, WarningCode
from app.profit.money import percent_of, rnd
from app.profit.results import (
    AdDetail,
    LineCashFlow,
    LineComparison,
    LineItems,
    LineResult,
    LineSources,
    LineVat,
    VariableExpenseDetail,
)
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork

ZERO = Decimal("0.00")

# K40: bu kaynaklar NetKâr tahmini değildir (ekstre/fatura kaydı, kullanıcı beyanı ya da bunların dağıtımı).
CERTAIN_SOURCES = frozenset(
    {Source.ACTUAL, Source.ACTUAL_ALLOCATED, Source.USER, Source.MATCHED, Source.NONE}
)


def line_status(w: LineWork) -> Status:
    """K22: durum her senkronda baştan hesaplanır (idempotent).

    - `cancelled`: Cancelled/UnSupplied.
    - `estimated`: eşleşen Sale/PayByLink yok.
    - `adjusted`: Sale var ve iade/düzeltme, iade kargo kalemi ya da siparişe bağlı ceza var.
    - `settled`: Sale var, düzeltme yok.
    """
    if w.cancelled:
        return Status.CANCELLED
    if not w.has_sale:
        return Status.ESTIMATED
    if w.has_adjustment or w.ship_ret_excl != 0 or w.penalty_excl != 0:
        return Status.ADJUSTED
    return Status.SETTLED


def compare_estimate(w: LineWork, settings: ProfitSettings) -> LineComparison | None:
    """K23, K38: ekstre gelmiş satırda tahmini ve kesin değerleri karşılaştırır (KDV hariç).

    Karşılaştırılan kalemler: komisyon (iade ters kayıtları hariç), gönderi kargo, platform hizmet bedeli.
    Kargo ve hizmet bedeli kalemi YALNIZ tahmini tanımlı VE kesin değeri gelmişse iki toplama girer (K38);
    tanımsız tahmin (tarife ya da hizmet bedeli ayarı yok) karşılaştırmaya girmez. `BEKLENMEYEN_KESINTI`
    yalnız aleyhe farkta: `fark > yuvarlama toleransı` ve `fark > max(mutlak eşik, oransal eşik)`.
    """
    if not w.has_sale or w.cancelled:
        return None
    thresholds = settings.thresholds
    ship_actual = w.ship_out_excl if w.ship_out_actual else None
    fee_actual = w.fee_excl if w.fee_actual else None
    estimated_total = w.commission_estimated_excl
    actual_total = w.commission_actual_sales_excl
    if ship_actual is not None and w.ship_out_estimated_excl is not None:
        estimated_total += w.ship_out_estimated_excl
        actual_total += ship_actual
    if fee_actual is not None and w.fee_estimated_excl is not None:
        estimated_total += w.fee_estimated_excl
        actual_total += fee_actual
    difference = actual_total - estimated_total
    threshold = max(
        thresholds.unexpected_deduction_amount,
        estimated_total * thresholds.unexpected_deduction_percent / 100,
    )
    if difference > thresholds.rounding_tolerance and difference > threshold:
        w.warnings.append(WarningCode.UNEXPECTED_DEDUCTION)
    return LineComparison(
        commission_estimated=w.commission_estimated_excl,
        commission_actual=w.commission_actual_sales_excl,
        shipping_outbound_estimated=w.ship_out_estimated_excl,
        shipping_estimate_default_desi=w.ship_out_default_desi,
        shipping_outbound_actual=ship_actual,
        platform_service_fee_estimated=w.fee_estimated_excl,
        platform_service_fee_actual=fee_actual,
        compared_estimated_total=estimated_total,
        compared_actual_total=actual_total,
        difference=difference,
        threshold=rnd(threshold),
    )


def missing_items_of(w: LineWork) -> tuple[MissingItem, ...]:
    """K37: kaynağı `eksik` olan kalemler, kanonik sırada (maliyet, gönderi kargo, platform hizmet bedeli)."""
    sources = (
        (MissingItem.PRODUCT_COST, w.src_cost),
        (MissingItem.OUTBOUND_SHIPPING, w.src_ship_out),
        (MissingItem.PLATFORM_SERVICE_FEE, w.src_fee),
    )
    return tuple(item for item, source in sources if source is Source.MISSING)


def line_certainty(w: LineWork, missing: tuple[MissingItem, ...]) -> Certainty:
    """K40: iptal; eksik kalem varsa eksik; tüm kaynaklar tahmin değilse ve teyit bekleyen kural yoksa kesin;
    aksi halde tahmini. Durum (`settled`) tek başına kesinlik değildir."""
    if w.cancelled:
        return Certainty.CANCELLED
    if missing:
        return Certainty.MISSING
    sources = (
        w.src_sales,
        w.src_commission,
        w.src_cost,
        w.src_ship_out,
        w.src_ship_ret,
        w.src_fee,
        w.src_penalty,
        w.src_var,
        w.src_ad,
    )
    if all(source in CERTAIN_SOURCES for source in sources) and not w.pending:
        return Certainty.CERTAIN
    return Certainty.ESTIMATED


def build_line_result(w: LineWork, settings: ProfitSettings) -> LineResult:
    """Tek satırın değişmez kâr kırılımını üretir (K25)."""
    expenses_without_cost = (
        w.commission_excl
        + w.ship_out_excl
        + w.ship_ret_excl
        + w.fee_excl
        + w.penalty_excl
        + w.ad_excl
        + w.var_excl
    )
    contribution = w.net_sales - expenses_without_cost
    # K37: bilinen tüm giderlerle kâr; eksik kalem 0 sayılmaz, hariç tutulur.
    known_expenses_profit = contribution - (w.cost_excl or ZERO)
    missing = missing_items_of(w)
    if missing:
        total_expenses = net_profit = None
    else:
        total_expenses = expenses_without_cost + (w.cost_excl or ZERO)
        net_profit = w.net_sales - total_expenses
    # K37: eksik kalemler negatif olamaz; bilinen giderlerle zarar eden satır kesin zarardadır.
    loss = net_profit < 0 if net_profit is not None else known_expenses_profit < 0
    if loss:
        w.warnings.append(WarningCode.LOSS)

    status = line_status(w)
    comparison = compare_estimate(w, settings)

    cost_vat = w.cost_vat or ZERO
    vat_effect = (w.sales_vat - w.refund_vat) - (
        w.commission_vat
        + w.ship_out_vat
        + w.ship_ret_vat
        + w.fee_vat
        + w.penalty_vat
        + cost_vat
        + w.var_vat
        + w.ad_vat
    )
    # K21: Trendyol hakedişi ekstredeki sellerRevenue toplamına denk gelir.
    payout = rnd(w.sales_incl) - rnd(w.refund_incl) - (w.commission_excl + w.commission_vat)
    deductions = (
        w.ship_out_excl
        + w.ship_out_vat
        + w.ship_ret_excl
        + w.ship_ret_vat
        + w.fee_excl
        + w.fee_vat
        + w.penalty_excl
        + w.penalty_vat
    )
    if w.order.who_pays == SELLER_PAYS_CARGO:  # satıcı anlaşmalı kargo hakedişten düşülmez
        deductions -= w.ship_out_excl + w.ship_out_vat
    # K18: stopaj gider değildir; yalnız nakit akışı kalemidir (net satış KDV hariç x oran).
    withholding = rnd(Fraction(w.net_sales) * Fraction(settings.withholding_rate) / 100)

    warnings = tuple(dict.fromkeys(w.warnings))
    return LineResult(
        order_number=w.order.order_number,
        package_id=w.order.package_id,
        line_id=w.line.line_id,
        barcode=w.line.barcode,
        status=status,
        quantity=w.quantity,
        refunded_quantity=w.refunded_in_stock + w.refunded_scrapped,
        pending_refund_quantity=w.pending_refund_quantity,
        suspended_product_cost=w.suspended_cost,
        certainty=line_certainty(w, missing),
        missing_items=missing,
        items=LineItems(
            gross_sales_incl_vat=w.gross,
            seller_discount_incl_vat=w.seller_discount,
            ty_discount_incl_vat=w.ty_discount,
            sales_incl_vat=rnd(w.sales_incl),
            sales_excl_vat=w.sales_excl,
            refund_incl_vat=rnd(w.refund_incl),
            refund_excl_vat=w.refund_excl,
            net_sales_excl_vat=w.net_sales,
            product_cost=w.cost_excl,
            commission=w.commission_excl,
            shipping_outbound=w.ship_out_excl,
            shipping_return=w.ship_ret_excl,
            platform_service_fee=w.fee_excl,
            penalty=w.penalty_excl,
            advertising=w.ad_excl,
            variable_expenses=w.var_excl,
            total_expenses=total_expenses,
            contribution_before_cost=contribution,
            known_expenses_profit=known_expenses_profit,
            net_profit=net_profit,
            net_margin_percent=None if net_profit is None else percent_of(net_profit, w.net_sales),
        ),
        vat=LineVat(
            sales_vat=w.sales_vat,
            refund_vat=w.refund_vat,
            commission_vat=w.commission_vat,
            shipping_vat=w.ship_out_vat + w.ship_ret_vat,
            platform_service_fee_vat=w.fee_vat,
            penalty_vat=w.penalty_vat,
            product_cost_vat=w.cost_vat,
            variable_expenses_vat=w.var_vat,
            advertising_vat=w.ad_vat,
            vat_effect=vat_effect,
        ),
        cash_flow=LineCashFlow(
            seller_payout=payout,
            invoice_deductions_incl_vat=deductions,
            withholding=withholding,
            expected_net_collection=payout - deductions - withholding,
        ),
        sources=LineSources(
            sales=w.src_sales,
            commission=w.src_commission,
            product_cost=w.src_cost,
            shipping_outbound=w.src_ship_out,
            shipping_return=w.src_ship_ret,
            platform_service_fee=w.src_fee,
            penalty=w.src_penalty,
            variable_expenses=w.src_var,
            advertising=w.src_ad,
        ),
        variable_expense_details=tuple(VariableExpenseDetail(n, a) for n, a in w.var_details),
        ad_details=tuple(AdDetail(r, k, a) for r, k, a in w.ad_details),
        comparison=comparison,
        warnings=warnings,
        pending_confirmation=tuple(sorted(w.pending)),
    )
