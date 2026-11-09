"""Kargo: tahmini tarife (K34), kesin fatura, KDV durumu tespiti, dağıtım, iade kargosu (K08, K09, K12)."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from fractions import Fraction

from app.profit.constants import (
    OUTBOUND_CARGO_ITEM,
    RETURN_CARGO_ITEM,
    SELLER_PAYS_CARGO,
)
from app.profit.enums import InvoiceVatStatus, Source, WarningCode
from app.profit.inputs import CargoInvoice, CargoInvoiceItem, Order, OtherFinancialRow, ProfitInput
from app.profit.money import allocate, split_exclusive, split_inclusive
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork, active_only, distribution_weights, group_by


def detect_invoice_vat_status(
    invoice: CargoInvoice, other_rows: Sequence[OtherFinancialRow], settings: ProfitSettings
) -> InvoiceVatStatus:
    """K08: kalem toplamı ekstre borcuna eşitse KDV dahil, borç/1,20'ye eşitse hariç, aksi halde bilinmiyor.

    `tol = max(toleranstaban, 0,01 x kalem sayısı)`.
    """
    statement = next((r for r in other_rows if r.row_id == invoice.serial_number), None)
    if statement is None:
        return InvoiceVatStatus.UNKNOWN
    total = sum((item.amount for item in invoice.items), Decimal(0))
    tolerance = max(settings.cargo_invoice_vat_tolerance, Decimal("0.01") * len(invoice.items))
    if abs(total - statement.debt) <= tolerance:
        return InvoiceVatStatus.INCLUDED
    vat_multiplier = 1 + settings.shipping_vat_rate / 100
    if abs(total * vat_multiplier - statement.debt) <= tolerance:
        return InvoiceVatStatus.EXCLUDED
    return InvoiceVatStatus.UNKNOWN


def _invoice_items(
    invoices: Sequence[CargoInvoice],
    statuses: Mapping[str, InvoiceVatStatus],
    order_number: str,
    package_type: str,
) -> list[tuple[CargoInvoiceItem, InvoiceVatStatus]]:
    """Siparişe ait belirli tipteki fatura kalemleri ve ait oldukları faturanın KDV durumu."""
    return [
        (item, statuses[invoice.serial_number])
        for invoice in invoices
        for item in invoice.items
        if item.order_number == order_number and item.package_type == package_type
    ]


def _items_total(
    items: Sequence[tuple[CargoInvoiceItem, InvoiceVatStatus]], vat_rate: Decimal
) -> tuple[Decimal, Decimal, bool]:
    """Kalemleri KDV durumuna göre ayırıp (hariç, KDV, belirsiz mi) döndürür."""
    inclusive = sum((i.amount for i, s in items if s is InvoiceVatStatus.INCLUDED), Decimal(0))
    exclusive = sum((i.amount for i, s in items if s is not InvoiceVatStatus.INCLUDED), Decimal(0))
    uncertain = any(s is InvoiceVatStatus.UNKNOWN for _, s in items)
    excl_a, vat_a = split_inclusive(inclusive, vat_rate)
    excl_b, vat_b = split_exclusive(exclusive, vat_rate)
    return excl_a + excl_b, vat_a + vat_b, uncertain


def _order_desi(order: Order) -> Decimal | None:
    """K08, K34: siparişten gelen desi: `cargoDeci`, yoksa `ceil(deci)`. `KARGO_DESI_FARKI` yalnız bununla."""
    if order.cargo_deci is not None:
        return order.cargo_deci
    if order.deci is not None:
        return Decimal(math.ceil(order.deci))
    return None


def apply_shipping(works: Sequence[LineWork], data: ProfitInput) -> dict[str, InvoiceVatStatus]:
    """Gönderi ve iade kargosunu satırlara yazar; faturaların KDV durumlarını döndürür."""
    settings = data.settings
    statuses = {
        inv.serial_number: detect_invoice_vat_status(inv, data.other_financials, settings)
        for inv in data.cargo_invoices
    }
    by_order = group_by(works, lambda w: w.order.order_number)
    packages = group_by(works, lambda w: (w.order.order_number, w.order.package_id))

    # Kesin fatura kalemleri sipariş numarasıyla eşleşir (paket ayrımı yok, §9 madde 14): bu yüzden
    # kesin tutar siparişin tüm aktif (satıcı anlaşmasız) paketlerinin satırlarına bir kez dağıtılır.
    actual_items = {
        number: _invoice_items(data.cargo_invoices, statuses, number, OUTBOUND_CARGO_ITEM)
        for number in by_order
    }

    for (number, _package_id), group in packages.items():
        active = active_only(group)
        if not active:
            continue
        order = active[0].order
        seller_pays = order.who_pays == SELLER_PAYS_CARGO
        tariff = settings.seller_cargo_tariff if seller_pays else settings.cargo_tariff
        # K34 desi sırası: siparişten gelen desi, yoksa hesabın varsayılan desisi (uyarılı), yoksa bilinmiyor.
        order_desi = _order_desi(order)
        default_used = order_desi is None and settings.default_desi is not None
        desi = settings.default_desi if default_used else order_desi
        price = tariff.lookup(order.carrier, desi, order.order_day)
        weights = distribution_weights(active)
        estimate = None if price is None else split_exclusive(price, settings.shipping_vat_rate)
        if estimate is not None:
            # K23 karşılaştırması için tahmini tutar hesaplanır; tarife fiyatlayamadıysa None kalır (K38).
            for w, part in zip(active, allocate(estimate[0], weights), strict=True):
                w.ship_out_estimated_excl = part
        if actual_items[number] and not seller_pays:
            continue  # kesin tutar aşağıda sipariş düzeyinde yazılır
        if estimate is None:
            # K37: eksik kalem 0 yazılır ama kaynağı `eksik`tir (net kâra karışmaz).
            for w in active:
                w.src_ship_out = Source.MISSING
                w.warnings.append(WarningCode.CARGO_TARIFF_MISSING)
            continue
        source = Source.USER if seller_pays else Source.ESTIMATED
        for w, part_excl, part_vat in zip(
            active, allocate(estimate[0], weights), allocate(estimate[1], weights), strict=True
        ):
            w.ship_out_excl, w.ship_out_vat, w.src_ship_out = part_excl, part_vat, source
            if default_used:
                w.warnings.append(WarningCode.CARGO_DESI_DEFAULT)

    for number, items in actual_items.items():
        targets = active_only(w for w in by_order[number] if w.order.who_pays != SELLER_PAYS_CARGO)
        if not items or not targets:
            continue
        excl, vat, uncertain = _items_total(items, settings.shipping_vat_rate)
        weights = distribution_weights(targets)
        for w, part_excl, part_vat in zip(
            targets, allocate(excl, weights), allocate(vat, weights), strict=True
        ):
            w.ship_out_excl, w.ship_out_vat = part_excl, part_vat
            w.src_ship_out = Source.ACTUAL
            w.ship_out_actual = True
        _warn_actual_cargo(targets, items, uncertain)

    _apply_return_shipping(by_order, data, statuses)
    return statuses


def _warn_actual_cargo(
    targets: Sequence[LineWork],
    items: Sequence[tuple[CargoInvoiceItem, InvoiceVatStatus]],
    uncertain: bool,
) -> None:
    """K23: faturadaki desi siparişteki tahmini desiden farklıysa; K08: KDV durumu bilinmiyorsa."""
    package_orders = {w.order.package_id: w.order for w in targets}
    estimates = [_order_desi(order) for order in package_orders.values()]
    actual_desi = sum(item.desi for item, _ in items)
    if all(e is not None for e in estimates) and Fraction(actual_desi) != sum(
        (Fraction(e) for e in estimates if e is not None), Fraction(0)
    ):
        for w in targets:
            w.warnings.append(WarningCode.CARGO_DESI_MISMATCH)
    if uncertain:
        for w in targets:
            w.warnings.append(WarningCode.CARGO_INVOICE_VAT_UNCERTAIN)


def _apply_return_shipping(
    by_order: Mapping[str, list[LineWork]],
    data: ProfitInput,
    statuses: Mapping[str, InvoiceVatStatus],
) -> None:
    """K12: iade kargo kalemleri, iade kalemi olan satırlara iade tutarı oranında (yoksa satışa oranla)."""
    for number, group in by_order.items():
        items = _invoice_items(data.cargo_invoices, statuses, number, RETURN_CARGO_ITEM)
        active = active_only(group)
        if not items or not active:
            continue
        excl, vat, _ = _items_total(items, data.settings.shipping_vat_rate)
        targets = [w for w in active if w.refunded_in_stock + w.refunded_scrapped > 0 or w.refund_excl > 0]
        targets = targets or active
        weights = [w.refund_excl if w.refund_excl > 0 else w.sales_excl for w in targets]
        for w, part_excl, part_vat in zip(
            targets, allocate(excl, weights), allocate(vat, weights), strict=True
        ):
            w.ship_ret_excl, w.ship_ret_vat, w.src_ship_ret = part_excl, part_vat, Source.ACTUAL
