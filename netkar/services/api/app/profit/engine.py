"""Kâr motoru giriş noktası: saf, deterministik, I/O yok (docs/12_kar_motoru.md).

`calculate_profit` aynı girdiyle her zaman aynı çıktıyı üretir; veritabanı, ağ ve saat kullanmaz.
Adımlar docs/12 kural numaralarıyla eşlenmiştir:

1. Satır kurulumu (K03), iptal (K26)
2. Ekstre eşleştirme, satış, iade, komisyon (K04-K07, K27, K28)
3. İade kalemleri ve ürün maliyeti (K10, K16)
4. Kargo (K08, K09, K12)
5. Platform hizmet bedeli (K13)
6. Ceza, erken ödeme, stopaj ekstresi, sınıflandırılamayan kesinti (K14, K18, K19)
7. Değişken giderler (K17), reklam (K15)
8. Satır kırılımı: durum, fark, KDV, nakit akışı (K18, K20-K23)
9. Toplulaştırma (K25)
"""

from __future__ import annotations

from decimal import Decimal

from app.profit.advertising import apply_advertising
from app.profit.aggregate import aggregate_period, aggregate_products
from app.profit.costs import apply_product_cost, apply_refund_items, apply_variable_expenses
from app.profit.fees import PeriodAccumulator, apply_other_financials, apply_service_fees
from app.profit.inputs import ProfitInput
from app.profit.lines import build_line_result
from app.profit.results import ProfitResult
from app.profit.settlement import apply_settlement, match_rows
from app.profit.shipping import apply_shipping
from app.profit.work import LineWork

ZERO = Decimal("0.00")


def _build_works(data: ProfitInput) -> list[LineWork]:
    """K03: satır başına brüt ve indirimleri `discountDetails` kalemlerinden toplar."""
    works: list[LineWork] = []
    for order in data.orders:
        for line in order.lines:
            works.append(
                LineWork(
                    order=order,
                    line=line,
                    cancelled=order.is_cancelled,
                    gross=line.unit_gross * line.quantity,
                    seller_discount=sum((i.seller_discount for i in line.items), ZERO),
                    ty_discount=sum((i.ty_discount for i in line.items), ZERO),
                )
            )
    return works


def calculate_profit(data: ProfitInput) -> ProfitResult:
    """Girdiden satır, ürün ve dönem kâr çıktısını üretir."""
    settings = data.settings
    works = _build_works(data)
    acc = PeriodAccumulator()

    match_rows(works, data.settlements)
    for w in works:
        apply_settlement(w, settings)
        apply_refund_items(w, data.claims)
        apply_product_cost(w, data.costs)
    invoice_status = apply_shipping(works, data)
    apply_service_fees(works, data.other_financials, settings, acc)
    apply_other_financials(works, data.other_financials, acc)
    apply_variable_expenses(works, settings)
    catalog = {w.line.barcode for w in works} | {c.barcode for c in data.costs} | set(data.catalog_barcodes)
    ads = apply_advertising(works, data.ad_records, catalog, settings, acc)

    lines = tuple(build_line_result(w, settings) for w in works)
    return ProfitResult(
        lines=lines,
        products=aggregate_products(works, lines, ads),
        period=aggregate_period(lines, ads, acc, settings, data.compensation_tickets),
        cargo_invoice_vat_status=invoice_status,
    )
