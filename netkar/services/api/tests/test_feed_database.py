"""Besleyici (profit_feed) ve kâr özeti: dönem sınırları, eksik veri notları, ekstre seçimi, RLS."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.profit import ProfitSettings
from app.profit.settings import DatedAmount
from app.services.financial_classes import ClassRule, classify_other_financial
from app.services.profit_feed import FeedNotes, build_profit_input, epoch_ms, period_bounds
from app.services.profit_report import period_profit, product_profit
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller, make_seller

D = Decimal
B1, B2 = "8681000000011", "8681000000028"


@pytest.fixture
async def sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def seller(admin_conn: psycopg.Connection[Any]) -> Seller:
    return make_seller(admin_conn)


def add_order(
    conn: psycopg.Connection[Any],
    seller: Seller,
    number: str = "1001",
    package_id: int = 3001,
    ordered: datetime = datetime(2026, 10, 5, 11, 30, tzinfo=UTC),
    status: str = "Delivered",
    lines: list[dict[str, Any]] | None = None,
) -> UUID:
    row = conn.execute(
        "INSERT INTO orders (tenant_id, marketplace_account_id, order_number, shipment_package_id, ordered_at, "
        "status, carrier, cargo_deci) VALUES (%s, %s, %s, %s, %s, %s, 'Trendyol Express', 2) RETURNING id",
        (seller.tenant_id, seller.account_id, number, package_id, ordered, status),
    ).fetchone()
    assert row is not None
    order_id: UUID = row[0]
    for line in lines if lines is not None else [{}]:
        add_line(conn, seller, order_id, **line)
    return order_id


def add_line(
    conn: psycopg.Connection[Any],
    seller: Seller,
    order_id: UUID,
    line_id: int = 10,
    barcode: str = B1,
    quantity: int = 1,
    gross: str = "100.00",
    vat: str | None = "20",
    commission: str | None = "10",
    items: list[dict[str, str]] | None = None,
    removed: bool = False,
    seller_discount: str = "0",
) -> None:
    if items is None:
        items = [
            {"id": f"{line_id}-{i}", "seller_discount": seller_discount, "ty_discount": "0"}
            for i in range(quantity)
        ]
    conn.execute(
        "INSERT INTO order_lines (tenant_id, marketplace_account_id, order_id, line_id, barcode, quantity, "
        "line_gross_amount, line_seller_discount, vat_rate, commission_rate, items, removed_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            seller.tenant_id,
            seller.account_id,
            order_id,
            line_id,
            barcode,
            quantity,
            gross,
            seller_discount,
            vat,
            commission,
            json.dumps(items),
            datetime(2026, 10, 6, tzinfo=UTC) if removed else None,
        ),
    )


def add_tx(
    conn: psycopg.Connection[Any],
    seller: Seller,
    source: str,
    request_type: str,
    transaction_id: str,
    *,
    sub_type: str = "",
    order_number: str | None = None,
    barcode: str | None = None,
    debt: str = "0",
    credit: str = "0",
    when: datetime | None = datetime(2026, 10, 10, 9, tzinfo=UTC),
    payment_order_id: int | None = None,
    type_text: str | None = None,
    paid: datetime | None = None,
) -> None:
    conn.execute(
        "INSERT INTO financial_transactions (tenant_id, marketplace_account_id, source, request_type, "
        "request_sub_type, transaction_id, order_number, barcode, debt, credit, transaction_date, "
        "payment_order_id, type_text, payment_date) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            seller.tenant_id,
            seller.account_id,
            source,
            request_type,
            sub_type,
            transaction_id,
            order_number,
            barcode,
            debt,
            credit,
            when,
            payment_order_id,
            type_text,
            paid,
        ),
    )


async def feed(
    sessions: async_sessionmaker[AsyncSession],
    seller: Seller,
    start: str = "2026-10-01",
    end: str = "2026-10-31",
    **kw: Any,
) -> Any:
    async with tenant_transaction(sessions, seller.tenant_id) as session:
        return await build_profit_input(
            session,
            seller.tenant_id,
            seller.account_id,
            date.fromisoformat(start),
            date.fromisoformat(end),
            **kw,
        )


# --- dönem ve çeviri ---------------------------------------------------------------------------------


def test_period_bounds_are_istanbul_days_and_validated() -> None:
    lower, upper = period_bounds(date(2026, 10, 6), date(2026, 10, 6))
    assert lower == datetime(2026, 10, 5, 21, 0, tzinfo=UTC) and upper == datetime(
        2026, 10, 6, 21, 0, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="dönem"):
        period_bounds(date(2026, 10, 7), date(2026, 10, 6))
    assert epoch_ms(datetime(2026, 10, 5, 11, 30, 0, 123_000, tzinfo=UTC)) == 1_791_199_800_123


async def test_orders_are_selected_by_istanbul_calendar_day(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(
        admin_conn, seller, "late", 1, datetime(2026, 10, 5, 20, 59, 59, tzinfo=UTC)
    )  # İstanbul 5 Ekim 23:59
    add_order(
        admin_conn, seller, "next", 2, datetime(2026, 10, 5, 21, 0, tzinfo=UTC)
    )  # İstanbul 6 Ekim 00:00
    on_5th = await feed(sessions, seller, "2026-10-05", "2026-10-05")
    on_6th = await feed(sessions, seller, "2026-10-06", "2026-10-06")
    assert [o.order_number for o in on_5th.profit_input.orders] == ["late"]
    assert [o.order_number for o in on_6th.profit_input.orders] == ["next"]
    assert on_6th.profit_input.orders[0].order_day == date(2026, 10, 6)


async def test_order_and_line_fields_are_translated_for_the_engine(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(
        admin_conn,
        seller,
        lines=[{"line_id": 11, "quantity": 2, "gross": "149.90", "seller_discount": "5.00"}],
    )
    admin_conn.execute("UPDATE orders SET who_pays = 1, deci = 3")
    admin_conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode, unit_desi) VALUES (%s, %s, %s, 2.5)",
        (seller.tenant_id, seller.account_id, B1),
    )
    result = await feed(sessions, seller)
    (order,) = result.profit_input.orders
    assert (order.package_id, order.carrier, order.cargo_deci, order.deci, order.who_pays) == (
        3001,
        "Trendyol Express",
        D("2"),
        D("3"),
        1,
    )
    (line,) = order.lines
    assert line.unit_gross == D("149.90") and line.vat_rate == D("20") and line.commission_rate == D("10")
    assert line.unit_desi == D("2.5") and len(line.items) == 2 and line.items[0].seller_discount == D("5.00")
    assert result.profit_input.catalog_barcodes == (B1,)


# --- eksik ve tutarsız veri: tahmin yok, sayaç var -----------------------------------------------------


async def test_missing_rates_fall_back_to_the_product_then_are_skipped_and_noted(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    admin_conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode, vat_rate, commission_rate) "
        "VALUES (%s, %s, %s, 10, 12)",
        (seller.tenant_id, seller.account_id, B1),
    )
    add_order(admin_conn, seller, "known", 1, lines=[{"line_id": 1, "vat": None, "commission": None}])
    add_order(
        admin_conn,
        seller,
        "unknown",
        2,
        lines=[{"line_id": 2, "barcode": B2, "vat": None, "commission": "10"}],
    )
    result = await feed(sessions, seller)
    (order,) = result.profit_input.orders
    assert order.order_number == "known"
    assert (order.lines[0].vat_rate, order.lines[0].commission_rate) == (D("10"), D("12"))  # ürün kartından
    assert result.notes.lines_missing_rates == 1 and result.notes.orders_without_lines == 1
    assert result.notes.total == 2


async def test_removed_lines_are_excluded_and_bad_item_breakdowns_are_noted(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    order_id = add_order(admin_conn, seller, lines=[{"line_id": 1}])
    add_line(admin_conn, seller, order_id, line_id=2, removed=True)  # paket bölününce kalkan satır
    add_line(
        admin_conn,
        seller,
        order_id,
        line_id=3,
        quantity=2,
        items=[{"id": "x", "seller_discount": "0", "ty_discount": "0"}],
    )
    add_line(admin_conn, seller, order_id, line_id=4, quantity=2, items=[])  # indirimsiz, kalem kırılımı yok
    add_line(
        admin_conn, seller, order_id, line_id=5, quantity=2, items=[], seller_discount="3.00"
    )  # indirimli: kırılım şart
    result = await feed(sessions, seller)
    (order,) = result.profit_input.orders
    assert [ln.line_id for ln in order.lines] == [1, 4]
    assert [i.item_id for i in order.lines[1].items] == [
        "line-4-0",
        "line-4-1",
    ]  # sıfır indirimli kalemler kurulur
    assert result.notes.lines_bad_items == 2


async def test_costs_and_catalog_flow_into_the_engine_input(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller)
    for valid_from, cost in (("2026-01-01", "40.00"), ("2026-10-01", "45.50")):
        admin_conn.execute(
            "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, unit_cost_excl_vat, "
            "vat_rate, entered_by) VALUES (%s, %s, %s, %s, %s, 20, %s)",
            (seller.tenant_id, seller.account_id, B1, valid_from, cost, seller.user_id),
        )
    result = await feed(sessions, seller)
    assert [(c.valid_from, c.unit_cost_excl_vat) for c in result.profit_input.costs] == [
        (date(2026, 1, 1), D("40.00")),
        (date(2026, 10, 1), D("45.50")),
    ]


# --- ekstre, iade ve fatura seçimi -----------------------------------------------------------------------


async def test_settlements_follow_the_period_orders_and_incomplete_rows_are_noted(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller, "1001", 1)
    add_order(admin_conn, seller, "0999", 2, datetime(2026, 9, 1, tzinfo=UTC))  # dönem dışı sipariş
    add_tx(admin_conn, seller, "settlements", "Sale", "S1", order_number="1001", barcode=B1, credit="100")
    add_tx(admin_conn, seller, "settlements", "Sale", "S2", order_number="0999", barcode=B1, credit="100")
    add_tx(admin_conn, seller, "settlements", "Sale", "S3", order_number="1001", barcode=None, credit="5")
    result = await feed(sessions, seller)
    assert [s.row_id for s in result.profit_input.settlements] == ["S1"]
    assert result.notes.settlements_unmatched == 1


async def test_other_financials_selection_rules_dedupe_and_classification(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller, "1001", 1)
    add_tx(
        admin_conn,
        seller,
        "settlements",
        "Sale",
        "S1",
        order_number="1001",
        barcode=B1,
        credit="100",
        payment_order_id=7,
    )
    oth = "other_financials"
    # (a) siparişe bağlı
    add_tx(
        admin_conn,
        seller,
        oth,
        "DeductionInvoices",
        "bound",
        order_number="1001",
        debt="60",
        type_text="Geç Kargolama Cezası",
    )
    # (a) aynı ödeme emrine bağlı hizmet bedeli: alt tipsiz kopya + alt tipli asıl satır -> asıl satır
    add_tx(
        admin_conn,
        seller,
        oth,
        "DeductionInvoices",
        "fee",
        payment_order_id=7,
        debt="40",
        type_text="Platform Hizmet Bedeli",
        when=None,
    )
    add_tx(
        admin_conn,
        seller,
        oth,
        "DeductionInvoices",
        "fee",
        sub_type="PlatformServiceFee",
        payment_order_id=7,
        debt="40",
        type_text="Platform Hizmet Bedeli",
        when=None,
    )
    # (b) bağsız ama dönemde (ödeme tarihine düşer) ve (b) dışı: dönem dışı bağsız satır
    add_tx(
        admin_conn,
        seller,
        oth,
        "Stoppage",
        "stop",
        debt="3",
        when=None,
        paid=datetime(2026, 10, 20, tzinfo=UTC),
    )
    add_tx(admin_conn, seller, oth, "Stoppage", "old", debt="9", when=datetime(2026, 8, 1, tzinfo=UTC))
    add_tx(
        admin_conn,
        seller,
        oth,
        "DeductionInvoices",
        "early",
        debt="120",
        type_text="Erken Ödeme Hizmet Bedeli",
        payment_order_id=99,
    )
    add_tx(admin_conn, seller, oth, "FinancialItem", "unknown", debt="17.35", type_text="Düzeltme")
    result = await feed(sessions, seller)
    rows = {r.row_id: r for r in result.profit_input.other_financials}
    assert set(rows) == {"bound", "fee", "stop", "early", "unknown"}  # "old" dönem dışı
    assert rows["fee"].request_sub_type == "PlatformServiceFee"  # alt tipli satır tercih edilir
    assert (rows["bound"].category, rows["bound"].vat_rate) == ("ceza", D(20))
    assert (rows["early"].category, rows["early"].vat_rate) == ("erken_odeme_bedeli", D(20))
    assert rows["unknown"].category is None and rows["stop"].category is None and rows["fee"].category is None
    assert sum(1 for r in result.profit_input.other_financials if r.row_id == "fee") == 1


async def test_cargo_invoices_include_every_item_of_a_touched_invoice(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller, "1001", 1)
    for serial, key, order, amount in (
        ("K1", "a", "1001", "45.00"),
        (
            "K1",
            "b",
            "99999999",
            "40.00",
        ),  # fatura dönem dışı siparişe de kalem içerir (KDV tespiti için gerekir)
        ("K2", "c", "88888888", "10.00"),  # dönemle ilgisiz fatura
        ("K1", "d", None, "1.00"),
    ):
        admin_conn.execute(
            "INSERT INTO cargo_invoice_items (tenant_id, marketplace_account_id, invoice_serial_number, item_key, "
            "order_number, amount, desi, shipment_package_type) VALUES (%s, %s, %s, %s, %s, %s, 2, 'Gönderi Kargo Bedeli')",
            (seller.tenant_id, seller.account_id, serial, key, order, amount),
        )
    result = await feed(sessions, seller)
    (invoice,) = result.profit_input.cargo_invoices
    assert invoice.serial_number == "K1" and [i.amount for i in invoice.items] == [D("45.00"), D("40.00")]
    assert result.notes.cargo_items_unmatched == 1


async def test_claims_are_grouped_per_order_and_keep_the_user_stock_flag(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller, "1001", 1)
    for item_id, line_item, stock in (("I1", "900", True), ("I2", "901", False), ("I3", None, True)):
        admin_conn.execute(
            "INSERT INTO returns (tenant_id, marketplace_account_id, claim_id, claim_item_id, order_number, "
            "order_line_item_id, status, returned_to_stock) VALUES (%s, %s, 'C1', %s, '1001', %s, 'Accepted', %s)",
            (seller.tenant_id, seller.account_id, item_id, line_item, stock),
        )
    result = await feed(sessions, seller)
    (claim,) = result.profit_input.claims
    assert claim.order_number == "1001"
    assert [(i.order_line_item_id, i.returned_to_stock, i.status) for i in claim.items] == [
        ("900", True, "Accepted"),
        ("901", False, "Accepted"),
    ]
    assert result.notes.claim_items_unmatched == 1


# --- RLS ve kâr özeti --------------------------------------------------------------------------------------


async def test_feed_is_tenant_scoped_even_with_a_foreign_account_id(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    other = make_seller(admin_conn, seller_id="9999")
    add_order(admin_conn, seller, "1001", 1)
    add_tx(admin_conn, seller, "settlements", "Sale", "S1", order_number="1001", barcode=B1, credit="1")
    async with tenant_transaction(sessions, other.tenant_id) as session:
        spy = await build_profit_input(
            session, other.tenant_id, seller.account_id, date(2026, 10, 1), date(2026, 10, 31)
        )
    assert spy.profit_input.orders == () and spy.profit_input.settlements == ()
    async with tenant_transaction(sessions, other.tenant_id) as session:  # kiracı B bağlamı, A'nın kimliği
        spy2 = await build_profit_input(
            session, seller.tenant_id, seller.account_id, date(2026, 10, 1), date(2026, 10, 31)
        )
    assert spy2.profit_input.orders == ()  # RLS satırları gizler


async def test_period_and_product_profit_use_the_engine_with_database_records(
    sessions: async_sessionmaker[AsyncSession], seller: Seller, admin_conn: psycopg.Connection[Any]
) -> None:
    add_order(admin_conn, seller, "1001", 1, lines=[{"line_id": 1, "barcode": B1, "gross": "120.00"}])
    admin_conn.execute(
        "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, unit_cost_excl_vat, "
        "vat_rate, entered_by) VALUES (%s, %s, %s, '2026-01-01', 50, 20, %s)",
        (seller.tenant_id, seller.account_id, B1, seller.user_id),
    )
    settings = ProfitSettings(service_fee_estimates=(DatedAmount(D("0")),))
    async with tenant_transaction(sessions, seller.tenant_id) as session:
        report = await period_profit(
            session, seller.tenant_id, seller.account_id, date(2026, 10, 1), date(2026, 10, 31), settings
        )
        sold = await product_profit(
            session, seller.tenant_id, seller.account_id, B1, date(2026, 10, 1), date(2026, 10, 31), settings
        )
        absent = await product_profit(
            session, seller.tenant_id, seller.account_id, B2, date(2026, 10, 1), date(2026, 10, 31), settings
        )
    assert report.totals.order_count == 1 and report.totals.net_sales_excl_vat == D("100.00")  # 120 / 1,2
    assert report.totals.product_cost == D("50.00") and report.notes.total == 0
    assert sold.product is not None and sold.product.barcode == B1 and len(sold.lines) == 1
    assert sold.period.order_count == 1 and sold.product.net_profit == report.result.products[0].net_profit
    assert absent.product is None and absent.lines == ()  # satışı olmayan ürün: özet yok, hata yok


# --- sınıflandırma kuralları ---------------------------------------------------------------------------------


def test_financial_classification_rules() -> None:
    assert classify_other_financial("DeductionInvoices", "", "Operasyonel CEZA", None) == ("ceza", D(20))
    assert classify_other_financial("DeductionInvoices", "", None, "Erken Ödeme Hizmet Bedeli") == (
        "erken_odeme_bedeli",
        D(20),
    )
    assert classify_other_financial("DeductionInvoices", "PlatformServiceFee", "Ceza", None) == (None, None)
    assert classify_other_financial("Stoppage", "", "ceza", None) == (None, None)  # istek tipi eşleşmez
    assert classify_other_financial("DeductionInvoices", "", None, None) == (None, None)
    custom = (ClassRule("DeductionInvoices", "gecikme", "ceza", D(18)),)
    assert classify_other_financial("DeductionInvoices", "", "Gecikme bedeli", None, custom) == (
        "ceza",
        D(18),
    )
    assert classify_other_financial("DeductionInvoices", "", "Ceza", None, custom) == (None, None)


def test_feed_notes_total_sums_every_counter() -> None:
    notes = FeedNotes(1, 2, 3, 4, 5, 6)
    assert notes.total == 21
    assert uuid4() != uuid4()  # (uuid içe aktarması: kimlikler testlerde rastgele üretilir)
