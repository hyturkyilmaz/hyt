"""Reklam gideri dağıtımı (K15).

Reklam Excel'i kullanıcıdan gelir ve barkodla eşlenir. Eşlenen reklam o barkodun satırlarına, eşlenmeyen
(mağaza reklamı, barkodsuz, katalog dışı) dönemdeki tüm satırlara net satış oranıyla dağıtılır ve
"tahmini" etiketlenir. Aday satır yoksa harcama başka ürüne kaydırılmaz; dönem düzeyinde kalır.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.profit.enums import Source
from app.profit.fees import PeriodAccumulator
from app.profit.inputs import AdRecord
from app.profit.money import allocate, rnd, split_exclusive, split_inclusive
from app.profit.settings import ProfitSettings
from app.profit.work import LineWork, active_only, ad_in_period


@dataclass(slots=True)
class AdOutcome:
    """Reklam dağıtım sonucu: satışsız ürün harcaması ve Excel cirosu barkod bazında."""

    unsold_by_barcode: dict[str, Decimal] = field(default_factory=dict)
    revenue_by_barcode: dict[str, Decimal] = field(default_factory=dict)


def apply_advertising(
    works: Sequence[LineWork],
    records: Sequence[AdRecord],
    catalog: set[str],
    settings: ProfitSettings,
    acc: PeriodAccumulator,
) -> AdOutcome:
    """K15: her reklam kaydını KDV hariçleştirir ve satırlara net satış oranıyla dağıtır."""
    outcome = AdOutcome()
    for record in records:
        if record.spend_includes_vat:
            spend, _ = split_inclusive(record.spend, settings.ad_vat_rate)
        else:
            spend = rnd(record.spend)
        _, vat = split_exclusive(spend, settings.ad_vat_rate)
        in_period = [w for w in active_only(works) if ad_in_period(w, record)]
        barcode = record.barcode
        if barcode is not None and barcode in catalog:
            if record.ad_revenue is not None:
                outcome.revenue_by_barcode[barcode] = (
                    outcome.revenue_by_barcode.get(barcode, Decimal(0)) + record.ad_revenue
                )
            targets = [w for w in in_period if w.line.barcode == barcode and w.net_sales > 0]
            if not targets:
                outcome.unsold_by_barcode[barcode] = (
                    outcome.unsold_by_barcode.get(barcode, Decimal(0)) + spend
                )
                continue
            kind = Source.MATCHED
        else:
            targets = [w for w in in_period if w.net_sales > 0]
            if not targets:
                acc.advertising_undistributed += spend
                continue
            kind = Source.ALLOCATED_ESTIMATE
        weights = [w.net_sales for w in targets]
        for w, part_excl, part_vat in zip(
            targets, allocate(spend, weights), allocate(vat, weights), strict=True
        ):
            w.ad_excl += part_excl
            w.ad_vat += part_vat
            w.ad_details.append((record.record_id, kind, part_excl))
    for w in works:
        kinds = {kind for _, kind, _ in w.ad_details}
        if Source.ALLOCATED_ESTIMATE in kinds:
            w.src_ad = Source.ALLOCATED_ESTIMATE
        elif kinds:
            w.src_ad = Source.MATCHED
        else:
            w.src_ad = Source.NONE
    return outcome
