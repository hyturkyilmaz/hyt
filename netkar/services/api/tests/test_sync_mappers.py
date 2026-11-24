"""Trendyol modellerinden satırlara saf eşlemeler (veritabanı gerekmez)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.integrations.trendyol.models import (
    ApprovedProduct,
    CargoInvoiceItem,
    Claim,
    FinancialTransaction,
    ShipmentPackage,
)
from app.services.sync import mappers
from tests.sync_helpers import order_line, package, settlement_row

D = Decimal


def test_ms_to_datetime_is_exact_and_none_safe() -> None:
    assert mappers.ms_to_datetime(None) is None
    assert mappers.ms_to_datetime(1_791_199_800_123) == datetime(2026, 10, 5, 11, 30, 0, 123_000, tzinfo=UTC)


def test_dec_str_never_uses_exponent_notation() -> None:
    assert mappers.dec_str(D("1E+1")) == "10"
    assert mappers.dec_str(D("0.00")) == "0.00"
    assert mappers.dec_str(None) == "0"


def test_rate_or_none_bounds() -> None:
    assert mappers.rate_or_none(D("20")) == D("20")
    assert mappers.rate_or_none(D("0")) == D("0")
    assert mappers.rate_or_none(D("100.01")) is None
    assert mappers.rate_or_none(D("-1")) is None
    assert mappers.rate_or_none(None) is None


def test_map_package_keeps_only_province_and_profit_fields() -> None:
    model = ShipmentPackage.model_validate(
        package(
            "5001",
            9001,
            lines=[order_line(90_010, quantity=2, seller_discount="10.00")],
            customerFirstName="SahteAd",
            customerId=888888888,
            invoiceAddress={"fullAddress": "SahteMahalle"},
        )
    )
    mapped = mappers.map_package(model)
    assert mapped is not None
    assert mapped.order["order_number"] == "5001" and mapped.order["province"] == "İstanbul"
    assert mapped.order["province_code"] == 34 and mapped.order["status"] == "Delivered"
    assert mapped.order["ordered_at"] == datetime(2026, 10, 5, 11, 30, tzinfo=UTC)
    assert "customer_key" not in mapped.order  # hukuk onayına kadar yazılmaz (ADR-0005)
    assert not any("customer" in key or "address" in key for key in mapped.order)
    (line,) = mapped.lines
    assert line["quantity"] == 2 and line["line_gross_amount"] == D("299.90")
    assert line["vat_rate"] == D("20") and line["commission_rate"] == D("15")
    assert len(line["items"]) == 2 and line["items"][0]["seller_discount"] == "10.00"
    assert mapped.skipped_lines == 0


def test_map_package_without_order_date_is_rejected() -> None:
    raw = package()
    del raw["orderDate"]
    assert mappers.map_package(ShipmentPackage.model_validate(raw)) is None


def test_map_package_rejects_bad_lines_and_clears_out_of_range_rates() -> None:
    good = order_line(1, vat=20)
    no_barcode = {**order_line(2), "barcode": None}
    no_gross = {**order_line(3), "lineGrossAmount": None}
    no_id = {**order_line(4), "lineId": None}
    weird_rate = order_line(5, vat=250, commission=-5)
    no_item_id = {**order_line(6), "discountDetails": [{"lineItemSellerDiscount": "1.00"}]}
    mapped = mappers.map_package(
        ShipmentPackage.model_validate(
            package(lines=[good, no_barcode, no_gross, no_id, weird_rate, no_item_id])
        )
    )
    assert mapped is not None
    assert [ln["line_id"] for ln in mapped.lines] == [1, 5, 6]
    assert mapped.skipped_lines == 3
    assert mapped.lines[1]["vat_rate"] is None and mapped.lines[1]["commission_rate"] is None
    # kalem kimliği yoksa satır içi sıradan türetilir
    assert mapped.lines[2]["items"] == [{"id": "line-6-0", "seller_discount": "1.00", "ty_discount": "0"}]


def test_map_package_unknown_status_and_missing_province() -> None:
    raw = package()
    raw["status"] = None
    del raw["shipmentAddress"]
    mapped = mappers.map_package(ShipmentPackage.model_validate(raw))
    assert mapped is not None
    assert mapped.order["status"] == "Unknown" and mapped.order["province"] is None


def _claim() -> Claim:
    return Claim.model_validate(
        {
            "claimId": "C-1",
            "orderNumber": "1001",
            "orderShipmentPackageId": 3001,
            "claimDate": 1_791_199_800_000,
            "lastModifiedDate": 1_791_199_900_000,
            "customerFirstName": "SahteAd",
            "items": [
                {
                    "orderLine": {"id": 11, "barcode": "B1"},
                    "claimItems": [
                        {
                            "id": "I-1",
                            "orderLineItemId": 555,
                            "customerClaimItemReason": {"code": "UNFIT"},
                            "claimItemStatus": {"name": "Accepted"},
                            "autoAccepted": True,
                            "acceptedBySeller": False,
                            "note": "SahteNot",
                        },
                        {"id": None},
                        {"id": "I-2", "trendyolClaimItemReason": {"code": "DAMAGED"}},
                    ],
                }
            ],
        }
    )


def test_map_claim_one_row_per_claim_item() -> None:
    rows, skipped = mappers.map_claim(_claim())
    assert skipped == 1 and len(rows) == 2
    first = rows[0]
    assert first["claim_id"] == "C-1" and first["claim_item_id"] == "I-1"
    assert first["order_line_item_id"] == "555" and first["reason_code"] == "UNFIT"
    assert first["status"] == "Accepted" and first["barcode"] == "B1" and first["order_line_id"] == 11
    assert first["claim_date"] == datetime(2026, 10, 5, 11, 30, tzinfo=UTC)
    assert "returned_to_stock" not in first  # kullanıcı işareti, senkron yazmaz
    assert rows[1]["reason_code"] == "DAMAGED" and rows[1]["order_line_item_id"] is None
    assert not any("note" in key for row in rows for key in row)


def test_map_transaction_truncates_description_and_defaults_amounts() -> None:
    tx = FinancialTransaction.model_validate(
        {**settlement_row("S1"), "description": "x" * 2000, "debt": None, "credit": None, "storeAddress": "x"}
    )
    row = mappers.map_transaction(tx, source="settlements", request_type="Sale", request_sub_type="")
    assert len(row["description"]) == mappers.DESCRIPTION_MAX
    assert row["debt"] == D(0) and row["credit"] == D(0)
    assert row["request_type"] == "Sale" and row["source"] == "settlements" and row["transaction_id"] == "S1"
    assert row["commission_amount"] == D("44.985")  # kuruş altı hassasiyet korunur
    assert (
        mappers.map_transaction(
            FinancialTransaction.model_validate({"id": 5}),
            source="other_financials",
            request_type="X",
            request_sub_type="Y",
        )["description"]
        is None
    )


def test_cargo_item_keys_are_stable_unique_and_order_independent() -> None:
    a = CargoInvoiceItem.model_validate(
        {"shipmentPackageType": "Gönderi Kargo Bedeli", "orderNumber": "1", "amount": "34.24", "desi": 1}
    )
    b = CargoInvoiceItem.model_validate(
        {"shipmentPackageType": "İade Kargo Bedeli", "orderNumber": "1", "amount": "34.24", "desi": 1}
    )
    rows, skipped = mappers.map_cargo_items("KRG1", [a, a, b])
    assert skipped == 0 and len(rows) == 3
    keys = [r["item_key"] for r in rows]
    assert len(set(keys)) == 3  # özdeş iki kalem tekilleşip kaybolmaz
    reordered, _ = mappers.map_cargo_items("KRG1", [b, a, a])
    assert {r["item_key"] for r in reordered} == set(keys)
    assert mappers.map_cargo_items("KRG1", [a, a, b])[0] == rows  # deterministik


def test_cargo_item_without_amount_is_rejected() -> None:
    item = CargoInvoiceItem.model_validate({"orderNumber": "1", "desi": 1})
    assert mappers.map_cargo_items("KRG1", [item]) == ([], 1)


def test_map_product_per_variant_and_rejects_barcodeless() -> None:
    product = ApprovedProduct.model_validate(
        {
            "contentId": 77,
            "productMainId": "M1",
            "title": "Açık Gri Tişört",
            "category": {"id": 5, "name": "Tişört"},
            "variants": [
                {"barcode": "B1", "stockCode": "S1", "vatRate": 20, "commission": 7.83},
                {"barcode": "B2", "vatRate": 150},
                {"barcode": None},
            ],
        }
    )
    rows, skipped = mappers.map_product(product)
    assert skipped == 1 and [r["barcode"] for r in rows] == ["B1", "B2"]
    assert rows[0]["commission_rate"] == D("7.83") and rows[0]["category_name"] == "Tişört"
    assert rows[1]["vat_rate"] is None  # 0-100 dışı oran boş bırakılır
    assert "unit_desi" not in rows[0]  # kullanıcı verisi, senkron yazmaz
