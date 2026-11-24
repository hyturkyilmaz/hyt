"""Trendyol modellerinden veritabanı satırlarına saf eşlemeler (I/O yok).

Girdi zaten PII'siz modellerdir (`app.integrations.trendyol.models`, `extra="ignore"`); bu katman
yalnız kâr hesabı için gereken sütunları seçer ve veritabanı kısıtlarına uymayan değeri (ör. oran
0-100 dışı, eksik zorunlu alan) satırı REDDEDEREK ya da alanı boş bırakarak ele alır: tek bir bozuk
kayıt tüm pencerenin yazımını düşürmesin. Reddedilen kayıt sayısı `skipped` olarak sayılır.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.integrations.trendyol.models import (
    ApprovedProduct,
    CargoInvoiceItem,
    Claim,
    FinancialTransaction,
    ShipmentPackage,
)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ZERO = Decimal(0)
DESCRIPTION_MAX = 1000


def ms_to_datetime(value: int | None) -> datetime | None:
    """Epoch milisaniyeyi UTC datetime'a çevirir (tamsayı aritmetiği, float yok)."""
    return None if value is None else _EPOCH + timedelta(milliseconds=value)


def dec_str(value: Decimal | None) -> str:
    """Decimal'i üstel gösterimsiz metne çevirir (JSONB içindeki tutarlar için)."""
    return format(value if value is not None else _ZERO, "f")


def rate_or_none(value: Decimal | None) -> Decimal | None:
    """Oran 0-100 aralığında değilse (veritabanı CHECK'ini düşürmesin) boş bırakılır."""
    if value is None or not (Decimal(0) <= value <= Decimal(100)):
        return None
    return value


@dataclass(frozen=True, slots=True)
class PackageRows:
    """Bir paketin sipariş satırı ve sipariş kalemi satırları (`order_id` yazım sırasında eklenir)."""

    order: dict[str, Any]
    lines: list[dict[str, Any]]
    skipped_lines: int


def map_package(package: ShipmentPackage) -> PackageRows | None:
    """ShipmentPackage -> sipariş + satırlar. Sipariş tarihi yoksa paket reddedilir (None)."""
    ordered_at = ms_to_datetime(package.order_date)
    if ordered_at is None:
        return None
    province = package.shipment_province
    order: dict[str, Any] = {
        "order_number": package.order_number,
        "shipment_package_id": package.shipment_package_id,
        "ordered_at": ordered_at,
        "last_modified_at": ms_to_datetime(package.last_modified_date),
        "status": package.status or "Unknown",
        "carrier": package.cargo_provider_name,
        "cargo_tracking_number": package.cargo_tracking_number,
        "cargo_deci": package.cargo_deci,
        "deci": package.deci,
        "who_pays": package.who_pays,
        "commercial": package.commercial,
        # Teslimat adresinden YALNIZ il adı ve kodu (ProvinceOnly); başka adres alanı modelde yoktur.
        "province": province.city if province else None,
        "province_code": province.city_code if province else None,
        "package_gross_amount": package.package_gross_amount,
        "package_seller_discount": package.package_seller_discount,
        "package_ty_discount": package.package_ty_discount,
        "package_total_price": package.package_total_price,
    }
    lines: list[dict[str, Any]] = []
    skipped = 0
    for line in package.lines:
        if line.line_id is None or not line.barcode or line.line_gross_amount is None or line.quantity < 1:
            skipped += 1
            continue
        items = [
            {
                # Kalem kimliği yoksa satır içi sıradan türetilir (iade eşlemesi için kimlik gerekir).
                "id": detail.line_item_id or f"line-{line.line_id}-{index}",
                "seller_discount": dec_str(detail.line_item_seller_discount),
                "ty_discount": dec_str(detail.line_item_ty_discount),
            }
            for index, detail in enumerate(line.discount_details)
        ]
        lines.append(
            {
                "line_id": line.line_id,
                "barcode": line.barcode,
                "stock_code": line.stock_code,
                "quantity": line.quantity,
                "line_gross_amount": line.line_gross_amount,
                "line_seller_discount": line.line_seller_discount or _ZERO,
                "line_ty_discount": line.line_ty_discount or _ZERO,
                "vat_rate": rate_or_none(line.vat_rate),
                "commission_rate": rate_or_none(line.commission),
                "status": line.order_line_item_status_name,
                "items": items,
                "removed_at": None,
            }
        )
    return PackageRows(order=order, lines=lines, skipped_lines=skipped)


def map_claim(claim: Claim) -> tuple[list[dict[str, Any]], int]:
    """Claim -> iade kalemi satırları ve reddedilen kalem sayısı (kimliksiz kalem)."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in claim.items:
        order_line = line.order_line
        for item in line.claim_items:
            if not item.id:
                skipped += 1
                continue
            reason = item.customer_claim_item_reason or item.trendyol_claim_item_reason
            rows.append(
                {
                    "claim_id": claim.claim_id,
                    "claim_item_id": item.id,
                    "order_number": claim.order_number,
                    "shipment_package_id": claim.order_shipment_package_id,
                    "order_line_id": order_line.id if order_line else None,
                    "order_line_item_id": None
                    if item.order_line_item_id is None
                    else str(item.order_line_item_id),
                    "barcode": order_line.barcode if order_line else None,
                    "reason_code": reason.code if reason else None,
                    "status": item.claim_item_status.name if item.claim_item_status else None,
                    "claim_date": ms_to_datetime(claim.claim_date),
                    "last_modified_at": ms_to_datetime(claim.last_modified_date),
                    "auto_accepted": item.auto_accepted,
                    "accepted_by_seller": item.accepted_by_seller,
                }
            )
    return rows, skipped


def map_transaction(
    tx: FinancialTransaction, *, source: str, request_type: str, request_sub_type: str
) -> dict[str, Any]:
    """Ekstre satırı -> financial_transactions satırı. `request_type`: motorun çektiği istek tipi (K05)."""
    description = tx.description
    return {
        "source": source,
        "request_type": request_type,
        "request_sub_type": request_sub_type,
        "transaction_id": tx.id,
        "type_text": tx.transaction_type,
        "description": description[:DESCRIPTION_MAX] if description else description,
        "transaction_date": ms_to_datetime(tx.transaction_date),
        "order_date": ms_to_datetime(tx.order_date),
        "payment_date": ms_to_datetime(tx.payment_date),
        "barcode": tx.barcode,
        "order_number": tx.order_number,
        "shipment_package_id": tx.shipment_package_id,
        "payment_order_id": tx.payment_order_id,
        "receipt_id": tx.receipt_id,
        "debt": tx.debt if tx.debt is not None else _ZERO,
        "credit": tx.credit if tx.credit is not None else _ZERO,
        "commission_rate": tx.commission_rate,
        "commission_amount": tx.commission_amount,
        "seller_revenue": tx.seller_revenue,
        "commission_invoice_serial_number": tx.commission_invoice_serial_number,
    }


def cargo_item_key(item: CargoInvoiceItem, ordinal: int) -> str:
    """Kalem kimliği: alanların özeti + aynı özetin fatura içindeki sıra numarası.

    Aynı tuple'dan birden çok kalem varsa hiçbiri tekilleşip kaybolmaz (sıra numarası ayırır);
    kalem sırası değişse de aynı kalem aynı anahtarı alır.
    """
    canonical = "|".join(
        (
            item.shipment_package_type or "",
            "" if item.parcel_unique_id is None else str(item.parcel_unique_id),
            item.order_number or "",
            dec_str(item.amount),
            "" if item.desi is None else str(item.desi),
            str(ordinal),
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def map_cargo_items(serial: str, items: list[CargoInvoiceItem]) -> tuple[list[dict[str, Any]], int]:
    """Bir faturanın kalemleri -> satırlar; tutarı olmayan kalem reddedilir."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    seen: dict[tuple[str, ...], int] = {}
    for item in items:
        if item.amount is None:
            skipped += 1
            continue
        signature = (
            item.shipment_package_type or "",
            str(item.parcel_unique_id),
            item.order_number or "",
            dec_str(item.amount),
            str(item.desi),
        )
        ordinal = seen.get(signature, 0)
        seen[signature] = ordinal + 1
        rows.append(
            {
                "invoice_serial_number": serial,
                "item_key": cargo_item_key(item, ordinal),
                "shipment_package_type": item.shipment_package_type,
                "parcel_unique_id": item.parcel_unique_id,
                "order_number": item.order_number,
                "amount": item.amount,
                "desi": item.desi,
            }
        )
    return rows, skipped


def map_product(product: ApprovedProduct) -> tuple[list[dict[str, Any]], int]:
    """Onaylı ürün -> varyant başına ürün satırı; barkodsuz varyant reddedilir."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for variant in product.variants:
        if not variant.barcode:
            skipped += 1
            continue
        rows.append(
            {
                "barcode": variant.barcode,
                "stock_code": variant.stock_code,
                "content_id": product.content_id,
                "product_main_id": product.product_main_id,
                "title": product.title,
                "category_id": product.category.id if product.category else None,
                "category_name": product.category.name if product.category else None,
                "vat_rate": rate_or_none(variant.vat_rate),
                "commission_rate": rate_or_none(variant.commission),
            }
        )
    return rows, skipped
