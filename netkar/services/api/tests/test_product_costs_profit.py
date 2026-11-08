"""API ile girilen maliyetin kâr motoruna SİPARİŞ GÜNÜNDE geçerli değerle girdiği (uçtan uca, gerçek veritabanı)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.profit import ProfitSettings
from app.profit.enums import WarningCode
from app.services.profit_report import period_profit, product_profit
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import B1, Shop, csv_bytes, fixed_today, make_shop_factory, upload  # noqa: F401
from tests.sync_helpers import Seller
from tests.test_feed_database import add_order

D = Decimal
pytestmark = pytest.mark.usefixtures("fixed_today")
SETTINGS = ProfitSettings(estimated_service_fee_per_order_excl_vat=D("0"))


@pytest.fixture
async def sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def cost_on(sessions: async_sessionmaker[AsyncSession], shop: Shop, day: date) -> Decimal:
    async with tenant_transaction(sessions, shop.tenant_id) as session:
        report = await period_profit(session, shop.tenant_id, shop.account_id, day, day, SETTINGS)
    return report.totals.product_cost


async def test_cost_entered_via_api_applies_with_the_order_day_validity(
    make_api: Callable[..., Api],
    admin_conn: psycopg.Connection[Any],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seller = Seller(shop.tenant_id, shop.user_id, shop.account_id, "2738")
    # Üç sipariş: maliyetten önce, birinci maliyet döneminde, ikinci maliyet döneminde (hepsi 120 TL KDV dahil).
    for number, package, day in (("1001", 1, 30), ("1002", 2, 5), ("1003", 3, 12)):
        month = 9 if day == 30 else 10
        add_order(
            admin_conn,
            seller,
            number,
            package,
            ordered=datetime(2026, month, day, 11, 30, tzinfo=UTC),
            lines=[{"line_id": package, "barcode": B1, "gross": "120.00"}],
        )
    put = f"{shop.base}/products/{B1}/costs"
    assert (
        shop.api.put(
            put, {"valid_from": "2026-10-01", "unit_cost_excl_vat": "50.00", "vat_rate": 20}
        ).status_code
        == 200
    )
    assert (
        shop.api.put(
            put, {"valid_from": "2026-10-10", "unit_cost_excl_vat": "80.00", "vat_rate": 20}
        ).status_code
        == 200
    )

    # Sipariş günündeki geçerli kayıt kullanılır (valid_from <= sipariş günü, en yenisi).
    assert await cost_on(sessions, shop, date(2026, 10, 5)) == D("50.00")
    assert await cost_on(sessions, shop, date(2026, 10, 12)) == D("80.00")
    # Geçerlilik günü dahildir (>=): 10-10 tarihli sipariş yeni maliyeti kullanır.
    add_order(
        admin_conn, seller, "1004", 4, ordered=datetime(2026, 10, 10, 8, 0, tzinfo=UTC),
        lines=[{"line_id": 4, "barcode": B1, "gross": "120.00"}],
    )  # fmt: skip
    assert await cost_on(sessions, shop, date(2026, 10, 10)) == D("80.00")

    # Maliyetten ÖNCEKİ sipariş: maliyet tahmin edilmez (eksik maliyet uyarısı), eski kayıt geriye uygulanmaz.
    async with tenant_transaction(sessions, shop.tenant_id) as session:
        early = await product_profit(
            session, shop.tenant_id, shop.account_id, B1, date(2026, 9, 30), date(2026, 9, 30), SETTINGS
        )
    assert WarningCode.MISSING_COST in early.lines[0].warnings

    # Aynı geçerlilik tarihine PUT (upsert) motorun gördüğü değeri değiştirir; yeni satır eklenmez.
    assert (
        shop.api.put(
            put, {"valid_from": "2026-10-01", "unit_cost_excl_vat": "55.50", "vat_rate": 20}
        ).status_code
        == 200
    )
    assert await cost_on(sessions, shop, date(2026, 10, 5)) == D("55.50")
    # Geçmiş kaydı tamamlayınca (9-30'a geçerli yeni kayıt) eksik uyarısı kalkar.
    assert (
        shop.api.put(
            put, {"valid_from": "2026-09-01", "unit_cost_excl_vat": "30.00", "vat_rate": 10}
        ).status_code
        == 200
    )
    assert await cost_on(sessions, shop, date(2026, 9, 30)) == D("30.00")


async def test_imported_costs_feed_the_engine_and_vat_rate_is_a_percentage(
    make_api: Callable[..., Api],
    admin_conn: psycopg.Connection[Any],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seller = Seller(shop.tenant_id, shop.user_id, shop.account_id, "2738")
    add_order(
        admin_conn, seller, "2001", 7, ordered=datetime(2026, 10, 5, 11, 30, tzinfo=UTC),
        lines=[{"line_id": 7, "barcode": B1, "gross": "120.00", "quantity": 2}],
    )  # fmt: skip
    r = upload(shop, csv_bytes(f"{B1};1.234,50;20;01.10.2026"), dry_run=False)
    assert r.status_code == 200, r.text
    async with tenant_transaction(sessions, shop.tenant_id) as session:
        report = await period_profit(
            session, shop.tenant_id, shop.account_id, date(2026, 10, 5), date(2026, 10, 5), SETTINGS
        )
    # 2 adet x 1234,50 = 2469,00 KDV hariç maliyet (KDV oranı yüzde 20 olarak okunur).
    assert report.totals.product_cost == D("2469.00") and report.notes.total == 0
