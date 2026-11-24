"""Kâr raporu API testleri için ortak yardımcılar (veri kurucular, para biçimi denetimi)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg

from tests.product_cost_helpers import B1, B2, B3, Shop, add_product
from tests.sync_helpers import Seller
from tests.test_feed_database import add_order, add_tx

__all__ = ["B1", "B2", "B3", "add_cost", "add_order", "add_sale", "money_strings", "seed_basic", "seller_of"]

MONEY_RE = re.compile(r"-?[0-9]+\.[0-9]{2}")
START, END = "2026-10-01", "2026-10-31"


def seller_of(shop: Shop) -> Seller:
    return Seller(shop.tenant_id, shop.user_id, shop.account_id, "2738")


def add_cost(
    conn: psycopg.Connection[Any],
    shop: Shop,
    barcode: str,
    unit_cost: str,
    vat: int = 20,
    valid_from: str = "2026-01-01",
) -> None:
    conn.execute(
        "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, unit_cost_excl_vat, "
        "vat_rate, entered_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (shop.tenant_id, shop.account_id, barcode, valid_from, unit_cost, vat, shop.user_id),
    )


def add_sale(
    conn: psycopg.Connection[Any],
    seller: Seller,
    order_number: str,
    barcode: str,
    credit: str,
    commission_amount: str,
    rate: str = "10",
    tx: str | None = None,
    returned: bool = False,
) -> None:
    """Ekstre satışı (ve istenirse aynı tutarda iade): satırı settled (iade varsa adjusted) yapar."""
    ids = [(tx or f"S-{order_number}", "Sale", "credit")]
    if returned:
        ids.append((f"R-{order_number}", "Return", "debt"))
    for tx_id, kind, column in ids:
        amounts: dict[str, Any] = {column: credit}
        add_tx(
            conn,
            seller,
            "settlements",
            kind,
            tx_id,
            order_number=order_number,
            barcode=barcode,
            **amounts,
        )
        conn.execute(
            "UPDATE financial_transactions SET commission_amount = %s, commission_rate = %s, "
            "seller_revenue = %s WHERE transaction_id = %s AND marketplace_account_id = %s",
            (
                commission_amount,
                rate,
                str(float(credit) - float(commission_amount)),
                tx_id,
                seller.account_id,
            ),
        )


def seed_basic(conn: psycopg.Connection[Any], shop: Shop) -> None:
    """Ekim 2026'da küçük, elle hesaplanabilir veri.

    - 1001 (B1, 120 TL KDV dahil, maliyet var), tahmini
    - 1002 (B2, 100 TL, maliyet YOK), ekstreli (settled)
    - 1003 (B1, 30 TL: maliyet 50 olduğundan ZARAR), ekstreli ve iadeli (adjusted)
    - 1004 (B1, iptal)
    B3 katalogda başlıksız, satışı yok.
    """
    seller = seller_of(shop)
    add_product(conn, shop, B1, "Ürün Bir")
    add_product(conn, shop, B2, "Ürün İki")
    add_product(conn, shop, B3, None)
    add_cost(conn, shop, B1, "50.00")
    add_order(
        conn,
        seller,
        "1001",
        1,
        datetime(2026, 10, 5, 11, 30, tzinfo=UTC),
        lines=[{"line_id": 1, "barcode": B1, "gross": "120.00"}],
    )
    add_order(
        conn,
        seller,
        "1002",
        2,
        datetime(2026, 10, 6, 11, 30, tzinfo=UTC),
        lines=[{"line_id": 2, "barcode": B2, "gross": "100.00"}],
    )
    add_order(
        conn,
        seller,
        "1003",
        3,
        datetime(2026, 10, 7, 11, 30, tzinfo=UTC),
        lines=[{"line_id": 3, "barcode": B1, "gross": "30.00"}],
    )
    add_order(conn, seller, "1004", 4, datetime(2026, 10, 8, 11, 30, tzinfo=UTC), status="Cancelled", lines=[{"line_id": 4, "barcode": B1, "gross": "60.00"}])  # fmt: skip
    add_sale(conn, seller, "1002", B2, "100.00", "10.00")
    add_sale(conn, seller, "1003", B1, "30.00", "3.00", returned=True)


def money_strings(node: Any, key: str = "") -> Iterator[tuple[str, Any]]:
    """JSON ağacındaki TÜM yaprakları (yol, değer) olarak gezer: testler float olmadığını denetler."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from money_strings(v, f"{key}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from money_strings(v, f"{key}[{i}]")
    else:
        yield key, node
