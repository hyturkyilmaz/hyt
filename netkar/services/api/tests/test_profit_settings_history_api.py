"""Ayar tarihçesi (ADR-0007 §5, §8; docs/12 K42-K44): ekle / değiştir / değişmedi / geri çek, geçmiş etki onayı,
ilk giriş istisnası, ayar günlüğü ve `GET /history`, denetim izi (tutar yok), sürüm damgası ve sürümle yeniden hesap.

Gerçek PostgreSQL ve gerçek HTTP katmanı. İstanbul bugünü 2026-11-08'e sabittir (`fixed_today`).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import profit as profit_module
from app.api.v1 import profit_settings as history_module
from app.api.v1.profit_schemas import PeriodTotalsOut
from app.core.config import Settings
from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.models import VariableExpenseRecord
from app.services import profit_settings as ps
from app.services import profit_views as views
from app.services.profit_report import period_profit
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import seed_basic
from tests.test_profit_settings_api import (
    delete_confirmed,
    expense_body,
    put_fee,
    put_tariff,
    read,
    revision_in_db,
    seed_head,
    url,
)

pytestmark = pytest.mark.usefixtures("fixed_today")

TODAY = date(2026, 11, 8)
PERIOD = {"start": "2026-10-01", "end": "2026-10-31"}
UNCONFIRMED = "settings-past-change-unconfirmed"
AMOUNT_KEYS = {"brackets", "price", "amount", "amount_excl_vat", "percent", "default_desi", "price_excl_vat"}


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


@pytest.fixture
async def app_sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def raw_put_tariff(shop: Shop, **over: Any) -> Any:
    """`confirm_past_change` GÖNDERMEDEN tarife yazımı (onay kuralını sınamak için)."""
    body: dict[str, Any] = {
        "agreement": "trendyol",
        "carrier": "Trendyol Express",
        "valid_from": "2026-10-01",
        "price_includes_vat": True,
        "brackets": [{"max_desi": "2", "price": "54.00"}],
    }
    body.update(over)
    return shop.api.put(url(shop, "/cargo-tariffs"), body)


def raw_put_fee(shop: Shop, **over: Any) -> Any:
    body: dict[str, Any] = {"valid_from": "2026-10-01", "amount": "12.00", "amount_includes_vat": True}
    body.update(over)
    return shop.api.put(url(shop, "/service-fee-estimates"), body)


def raw_expense(shop: Shop, **over: Any) -> Any:
    body = expense_body(confirm_past_change=False, **over)  # onay gönderilmez
    return shop.api.post(url(shop, "/variable-expenses"), body)


def journal(conn: psycopg.Connection[Any], shop: Shop) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT revision, item, action, record_id, replaced_record_id, affects_from, affects_past, "
        "past_change_confirmed, changed_by, default_desi_before, default_desi_after "
        "FROM profit_settings_changes WHERE marketplace_account_id = %s ORDER BY revision",
        (shop.account_id,),
    )
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def audits(conn: psycopg.Connection[Any], shop: Shop) -> list[tuple[str, dict[str, Any]]]:
    rows = conn.execute(
        "SELECT action, meta FROM audit_log WHERE tenant_id = %s AND action LIKE 'profit_settings.%%' ORDER BY id",
        (shop.tenant_id,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def history(shop: Shop, **params: Any) -> dict[str, Any]:
    response = shop.api.get(url(shop, "/history"), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def table_rows(conn: psycopg.Connection[Any], table: str, shop: Shop) -> list[tuple[Any, ...]]:
    return conn.execute(
        f"SELECT id, revision_from, revision_to, end_reason, replaces_id FROM {table} "
        "WHERE marketplace_account_id = %s ORDER BY revision_from, id",
        (shop.account_id,),
    ).fetchall()


# --------------------------------------------------------------------------- K42: değiştir, geri çek, değişmedi
def test_same_key_put_replaces_the_row_and_the_old_brackets_stay_readable_in_history(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Denetim PoC A.2'nin tersi: eski kademeler `replaced_record` olarak okunur, eski satır `revision_to` ile durur."""
    first = put_tariff(shop, valid_from="2026-01-01").json()
    again = put_tariff(
        shop,
        valid_from="2026-01-01",
        brackets=[{"max_desi": "2", "price": "60.00"}],
        price_includes_vat=False,
    ).json()
    old_id, new_id = first["tariff"]["id"], again["tariff"]["id"]
    assert again["action"] == "replaced" and again["replaced_id"] == old_id and again["revision"] == 2
    rows = {str(r[0]): r for r in table_rows(admin_conn, "cargo_tariffs", shop)}
    assert rows[old_id][1:4] == (1, 2, "degistirildi")  # revision_from, revision_to, end_reason
    assert rows[new_id][1:3] == (2, None) and str(rows[new_id][4]) == old_id  # replaces_id
    top = history(shop)["items"][0]
    assert top["revision"] == 2 and top["action"] == "degistir" and top["item"] == "cargo_tariff"
    assert top["record"]["id"] == new_id and top["replaced_record"]["id"] == old_id
    assert top["replaced_record"]["brackets"][0]["price"] == "54.00"  # eski değer okunur
    assert top["record"]["brackets"][0]["price"] == "60.00"
    assert [t["id"] for t in read(shop)["cargo_tariffs"]] == [new_id]  # GET yalnız etkin satırları gösterir


def test_retract_keeps_the_row_with_end_reason_and_the_engine_stops_using_it(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    seed_basic(admin_conn, shop)
    tariff = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    put_fee(shop, valid_from="2026-01-01")
    summary = shop.api.get(f"{shop.base}/profit/summary", params=PERIOD).json()
    assert summary["tariff_missing_line_count"] == 0
    gone = delete_confirmed(shop, f"/cargo-tariffs/{tariff['id']}")
    assert gone.status_code == 200 and gone.json()["action"] == "retracted" and gone.json()["changed"] is True
    (row,) = table_rows(admin_conn, "cargo_tariffs", shop)
    assert str(row[0]) == tariff["id"] and row[1:4] == (1, 3, "geri_cekildi")  # satır tabloda kaldı
    after = shop.api.get(f"{shop.base}/profit/summary", params=PERIOD).json()
    assert after["tariff_missing_line_count"] == 3  # motor geri çekilen satırı kullanmaz: kargo eksik
    assert after["totals"]["net_kar_kismi"] is True and after["settings_revision"] == 3
    assert read(shop)["cargo_tariffs"] == []


def test_identical_put_changes_nothing(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()
    fee = put_fee(shop, valid_from="2026-01-01").json()
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()
    desi = shop.api.put(url(shop, "/defaults"), {"default_desi": "3"}).json()
    base_revision, base_journal, base_audit = (
        revision_in_db(admin_conn, shop),
        journal(admin_conn, shop),
        audits(admin_conn, shop),
    )
    assert base_revision == desi["revision"] == 4

    same = [
        put_tariff(shop, valid_from="2026-01-01"),
        put_fee(shop, valid_from="2026-01-01"),
        shop.api.put(url(shop, f"/variable-expenses/{expense['expense']['id']}"), expense_body()),
        shop.api.put(url(shop, "/defaults"), {"default_desi": "3.00"}),
    ]
    for response in same:
        body = response.json()
        assert response.status_code == 200 and body["changed"] is False and body["action"] == "unchanged"
        assert body["revision"] == 4 and body["replaced_id"] is None
    assert same[0].json()["tariff"]["id"] == tariff["tariff"]["id"]
    assert same[1].json()["estimate"]["id"] == fee["estimate"]["id"]
    assert same[2].json()["expense"]["id"] == expense["expense"]["id"]
    assert revision_in_db(admin_conn, shop) == base_revision
    assert journal(admin_conn, shop) == base_journal and audits(admin_conn, shop) == base_audit
    assert len(table_rows(admin_conn, "cargo_tariffs", shop)) == 1  # yeni satır yok


def test_identical_put_on_a_fresh_account_leaves_no_trace(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    response = shop.api.put(url(shop, "/defaults"), {"default_desi": None})
    assert (
        response.status_code == 200
        and response.json()["changed"] is False
        and response.json()["revision"] == 0
    )
    assert revision_in_db(admin_conn, shop) is None  # hesap satırı oluşturma da geri alındı
    assert journal(admin_conn, shop) == [] and audits(admin_conn, shop) == []


def test_unchanged_does_not_need_confirmation_even_for_past_dates(shop: Shop) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    same = put_tariff(shop, valid_from="2026-01-01", confirm_past_change=False)  # geçmiş ama içerik aynı
    assert same.status_code == 200 and same.json()["changed"] is False and same.json()["affects_past"] is True


def test_expense_replace_keeps_definition_order_and_extends_the_end_date(shop: Shop) -> None:
    a = shop.api.post(url(shop, "/variable-expenses"), expense_body(name="A")).json()["expense"]
    shop.api.post(url(shop, "/variable-expenses"), expense_body(name="B"))
    replaced = shop.api.put(
        url(shop, f"/variable-expenses/{a['id']}"), expense_body(name="A", valid_to="2026-12-31")
    )
    assert replaced.status_code == 200 and replaced.json()["expense"]["id"] != a["id"]
    assert [e["name"] for e in read(shop)["variable_expenses"]] == ["A", "B"]  # sıra bozulmadı


# --------------------------------------------------------------------------- K43: onay ve etki tarihi
def test_unconfirmed_past_change_is_409_and_writes_nothing(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    base = (revision_in_db(admin_conn, shop), journal(admin_conn, shop), audits(admin_conn, shop))
    response = raw_put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "99.00"}])
    assert response.status_code == 409 and response.json()["type"] == f"urn:netkar:problem:{UNCONFIRMED}"
    body = response.json()
    assert (
        body["affects_from"] == "2026-01-01"
        and body["affects_past"] is True
        and body["current_revision"] == 1
    )
    assert (revision_in_db(admin_conn, shop), journal(admin_conn, shop), audits(admin_conn, shop)) == base
    assert read(shop)["cargo_tariffs"][0]["brackets"][0]["price"] == "54.00"  # değer değişmedi
    assert len(table_rows(admin_conn, "cargo_tariffs", shop)) == 1
    # onaylı: 200 ve günlükte onay işareti
    ok = raw_put_tariff(
        shop,
        valid_from="2026-01-01",
        brackets=[{"max_desi": "2", "price": "99.00"}],
        confirm_affects_from="2026-01-01",
    )
    assert ok.status_code == 200 and ok.json()["revision"] == 2
    last = journal(admin_conn, shop)[-1]
    assert last["past_change_confirmed"] is True and last["affects_past"] is True
    assert str(last["affects_from"]) == "2026-01-01"
    assert audits(admin_conn, shop)[-1][1]["past_change_confirmed"] is True


def test_unconfirmed_retract_and_expense_replace_are_409_and_leave_rows_active(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()["expense"]
    delete = shop.api.delete(url(shop, f"/cargo-tariffs/{tariff['id']}"))
    assert delete.status_code == 409 and delete.json()["type"].endswith(UNCONFIRMED)
    assert delete.json()["affects_from"] == "2026-01-01"
    replace = shop.api.put(
        url(shop, f"/variable-expenses/{expense['id']}"),
        expense_body(amount_excl_vat="9", confirm_past_change=False),
    )
    assert replace.status_code == 409 and replace.json()["affects_from"] == "2026-10-01"
    assert [r[2] for r in table_rows(admin_conn, "cargo_tariffs", shop)] == [None]
    assert [r[2] for r in table_rows(admin_conn, "variable_expenses", shop)] == [None]
    assert revision_in_db(admin_conn, shop) == 2


def test_first_entry_exception_only_for_filling_missing_items(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    first_tariff = raw_put_tariff(shop, valid_from="2026-01-01")  # ayarsız hesap, ilk Trendyol tarifesi
    first_fee = raw_put_fee(shop, valid_from="2026-01-01")  # ilk hizmet bedeli
    assert first_tariff.status_code == 200 and first_fee.status_code == 200
    rows = journal(admin_conn, shop)
    assert [(r["item"], r["affects_past"], r["past_change_confirmed"]) for r in rows] == [
        ("cargo_tariff", True, False),
        ("service_fee_estimate", True, False),
    ]
    second = raw_put_tariff(shop, carrier="Aras Kargo", valid_from="2026-01-01")  # ikinci Trendyol tarifesi
    assert second.status_code == 409 and second.json()["type"].endswith(UNCONFIRMED)
    seller_first = raw_put_tariff(shop, agreement="seller", carrier="Aras Kargo", valid_from="2026-01-01")
    assert seller_first.status_code == 200  # satıcı anlaşmasında hiç etkin tarife yok: ilk giriş
    second_fee = raw_put_fee(shop, valid_from="2026-02-01")
    assert second_fee.status_code == 409  # ikinci hizmet bedeli sürümü
    expense = raw_expense(shop)  # ilk değişken gider (geçmiş başlangıç): istisna yok
    assert expense.status_code == 409 and expense.json()["affects_from"] == "2026-10-01"
    assert revision_in_db(admin_conn, shop) == 3


def test_first_entry_exception_for_default_desi_only_from_null_to_a_value(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    first = shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})
    assert first.status_code == 200 and first.json()["action"] == "created"
    changed = shop.api.put(url(shop, "/defaults"), {"default_desi": "4"})
    assert changed.status_code == 409 and changed.json()["affects_from"] is None
    assert changed.json()["affects_past"] is True and changed.json()["current_revision"] == 1
    cleared = shop.api.put(url(shop, "/defaults"), {"default_desi": None})
    assert cleared.status_code == 409  # değeri silmek "eksik"i doldurmaz
    ok = shop.api.put(url(shop, "/defaults"), {"default_desi": "4", "confirm_affects_from": "all"})
    assert ok.status_code == 200 and ok.json()["action"] == "replaced" and ok.json()["revision"] == 2
    clear = shop.api.put(url(shop, "/defaults"), {"default_desi": None, "confirm_affects_from": "all"})
    assert clear.json()["action"] == "retracted" and clear.json()["revision"] == 3
    rows = journal(admin_conn, shop)
    assert [(r["item"], r["action"], r["default_desi_before"], r["default_desi_after"]) for r in rows] == [
        ("defaults", "ekle", None, Decimal("3.00")),
        ("defaults", "degistir", Decimal("3.00"), Decimal("4.00")),
        ("defaults", "geri_cek", Decimal("4.00"), None),
    ]
    assert [(r["affects_from"], r["affects_past"], r["past_change_confirmed"]) for r in rows] == [
        (None, True, False),
        (None, True, True),
        (None, True, True),
    ]
    assert all(r["record_id"] is None and r["replaced_record_id"] is None for r in rows)


def test_today_and_future_starts_do_not_affect_the_past(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    today = raw_put_tariff(shop, carrier="Aras Kargo", valid_from="2026-11-08")  # bugün: geçmiş değil
    future = raw_put_tariff(shop, carrier="MNG Kargo", valid_from="2026-12-01")
    assert today.status_code == 200 and today.json()["affects_past"] is False
    assert future.status_code == 200 and future.json()["affects_from"] == "2026-12-01"
    fee = raw_put_fee(shop, valid_from="2026-11-08")  # ilk hizmet bedeli de geçmişi etkilemez
    assert fee.status_code == 200 and fee.json()["affects_past"] is False
    later = raw_put_fee(shop, valid_from="2026-12-15")
    assert later.status_code == 200
    expense = raw_expense(shop, valid_from="2026-11-09")
    assert expense.status_code == 201 and expense.json()["affects_past"] is False
    # değiştirmede etki tarihi eski ve yeni başlangıcın küçüğüdür
    eid = expense.json()["expense"]["id"]
    moved = shop.api.put(
        url(shop, f"/variable-expenses/{eid}"),
        expense_body(valid_from="2026-11-20", confirm_past_change=False),
    )
    assert moved.status_code == 200 and moved.json()["affects_from"] == "2026-11-09"
    back = shop.api.put(
        url(shop, f"/variable-expenses/{moved.json()['expense']['id']}"),
        expense_body(valid_from="2026-10-01", confirm_past_change=False),
    )
    assert back.status_code == 409 and back.json()["affects_from"] == "2026-10-01"
    rows = journal(admin_conn, shop)
    assert all(r["past_change_confirmed"] is False for r in rows[1:])


def test_retracting_a_future_row_needs_no_confirmation(shop: Shop) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    future = raw_put_tariff(shop, carrier="MNG Kargo", valid_from="2026-12-01").json()["tariff"]
    gone = shop.api.delete(url(shop, f"/cargo-tariffs/{future['id']}"))
    assert gone.status_code == 200 and gone.json()["affects_past"] is False


def test_revision_conflict_is_checked_before_the_confirmation(shop: Shop) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    response = raw_put_tariff(
        shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "1"}], expected_revision=0
    )
    assert response.status_code == 409 and response.json()["type"].endswith("settings-revision-conflict")


def test_ended_tariff_and_fee_rows_report_their_successor(shop: Shop) -> None:
    old = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    new = put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "70"}]).json()[
        "tariff"
    ]
    stale = delete_confirmed(shop, f"/cargo-tariffs/{old['id']}")
    assert stale.status_code == 409 and stale.json()["type"].endswith("settings-record-ended")
    assert stale.json()["current_id"] == new["id"]
    # zincir: ikinci değiştirmeden sonra ilk kimlik de son etkin satırı gösterir (gider için PUT zinciri)
    e1 = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()["expense"]
    e2 = shop.api.put(url(shop, f"/variable-expenses/{e1['id']}"), expense_body(amount_excl_vat="7")).json()[
        "expense"
    ]
    e3 = shop.api.put(url(shop, f"/variable-expenses/{e2['id']}"), expense_body(amount_excl_vat="8")).json()[
        "expense"
    ]
    chained = shop.api.put(url(shop, f"/variable-expenses/{e1['id']}"), expense_body(amount_excl_vat="9"))
    assert chained.status_code == 409 and chained.json()["current_id"] == e3["id"]
    fee = put_fee(shop, valid_from="2026-01-01").json()["estimate"]
    put_fee(shop, valid_from="2026-01-01", amount="30")
    fee_stale = delete_confirmed(shop, f"/service-fee-estimates/{fee['id']}")
    assert fee_stale.status_code == 409 and fee_stale.json()["current_id"] is not None


def test_other_tenants_record_ids_are_404_not_409(two_shops: tuple[Shop, Shop]) -> None:
    a, b = two_shops
    tariff = put_tariff(a, valid_from="2026-01-01").json()["tariff"]
    expense = a.api.post(url(a, "/variable-expenses"), expense_body()).json()["expense"]
    assert delete_confirmed(b, f"/cargo-tariffs/{tariff['id']}").status_code == 404
    assert b.api.put(url(b, f"/variable-expenses/{expense['id']}"), expense_body()).status_code == 404
    assert delete_confirmed(b, f"/variable-expenses/{expense['id']}").status_code == 404
    assert b.api.get(url(a, "/history")).status_code == 404  # başka kiracının hesabının geçmişi


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop]) -> tuple[Shop, Shop]:
    return make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")


# --------------------------------------------------------------------------- sürüm sınırı (etkin satırlar)
def test_limit_counts_active_rows_only_replacing_never_hits_it(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    seed_head(admin_conn, shop)
    for index in range(ps.MAX_TARIFF_VERSIONS):
        admin_conn.execute(
            "INSERT INTO cargo_tariffs (revision_from, tenant_id, marketplace_account_id, agreement, carrier, "
            "valid_from, price_includes_vat, brackets, entered_by) VALUES (1, %s, %s, 'trendyol', %s, "
            '\'2026-01-01\', false, \'[{"max_desi": "1", "price": "1"}]\', %s)',
            (shop.tenant_id, shop.account_id, f"F{index}", shop.user_id),
        )
    for price in ("2", "3", "4"):  # her değiştirme eski satırı kapatır: etkin sayı hep 200
        assert (
            put_tariff(
                shop, carrier="F0", valid_from="2026-01-01", brackets=[{"max_desi": "1", "price": price}]
            ).status_code
            == 200
        )
    assert (
        len(table_rows(admin_conn, "cargo_tariffs", shop)) == ps.MAX_TARIFF_VERSIONS + 3
    )  # kapanmışlar tabloda
    assert len(read(shop)["cargo_tariffs"]) == ps.MAX_TARIFF_VERSIONS
    over = put_tariff(shop, carrier="Yeni Firma")
    assert (
        over.status_code == 422
        and {"field": "valid_from", "code": "too_many_tariff_versions"} in over.json()["errors"]
    )
    # geri çekme yer açar
    first = read(shop)["cargo_tariffs"][0]
    assert delete_confirmed(shop, f"/cargo-tariffs/{first['id']}").status_code == 200
    assert put_tariff(shop, carrier="Yeni Firma").status_code == 200


def test_expense_limit_counts_active_rows_only(shop: Shop) -> None:
    ids = [
        shop.api.post(url(shop, "/variable-expenses"), expense_body(name=f"g{i}")).json()["expense"]["id"]
        for i in range(ps.MAX_EXPENSES)
    ]
    over = shop.api.post(url(shop, "/variable-expenses"), expense_body(name="fazla"))
    assert over.status_code == 422 and {"field": "name", "code": "too_many_expenses"} in over.json()["errors"]
    replaced = shop.api.put(
        url(shop, f"/variable-expenses/{ids[0]}"), expense_body(name="g0", amount_excl_vat="7")
    )
    assert replaced.status_code == 200  # değiştirme sınırı aşmaz
    assert delete_confirmed(shop, f"/variable-expenses/{replaced.json()['expense']['id']}").status_code == 200
    assert shop.api.post(url(shop, "/variable-expenses"), expense_body(name="fazla")).status_code == 201


# --------------------------------------------------------------------------- ayar günlüğü ve denetim izi
def test_every_write_adds_exactly_one_journal_row_per_revision(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()
    fee = put_fee(shop, valid_from="2026-01-01").json()
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()
    changed = put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "70"}]).json()
    delete_confirmed(shop, f"/service-fee-estimates/{fee['estimate']['id']}")
    rows = journal(admin_conn, shop)
    assert [r["revision"] for r in rows] == [1, 2, 3, 4, 5]
    assert [(r["item"], r["action"]) for r in rows] == [
        ("cargo_tariff", "ekle"),
        ("service_fee_estimate", "ekle"),
        ("variable_expense", "ekle"),
        ("cargo_tariff", "degistir"),
        ("service_fee_estimate", "geri_cek"),
    ]
    assert str(rows[0]["record_id"]) == tariff["tariff"]["id"]
    assert str(rows[2]["record_id"]) == expense["expense"]["id"]
    assert str(rows[3]["record_id"]) == changed["tariff"]["id"]
    assert str(rows[3]["replaced_record_id"]) == tariff["tariff"]["id"]
    assert str(rows[4]["record_id"]) == fee["estimate"]["id"] and rows[4]["replaced_record_id"] is None
    assert all(r["changed_by"] == shop.user_id for r in rows)
    assert rows[1]["affects_from"] == date(2026, 1, 1) and rows[4]["affects_past"] is True
    assert revision_in_db(admin_conn, shop) == 5


def test_audit_trail_carries_identities_only_never_amounts(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "54.37"}]).json()[
        "tariff"
    ]
    new = put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "61.11"}]).json()[
        "tariff"
    ]
    fee = put_fee(shop, valid_from="2026-01-01", amount="12.34").json()["estimate"]
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body(amount_excl_vat="6.78")).json()[
        "expense"
    ]
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3.21"})
    delete_confirmed(shop, f"/cargo-tariffs/{new['id']}")
    delete_confirmed(shop, f"/service-fee-estimates/{fee['id']}")
    delete_confirmed(shop, f"/variable-expenses/{expense['id']}")
    rows = audits(admin_conn, shop)
    assert [r[0] for r in rows] == [
        "profit_settings.cargo_tariff.create",
        "profit_settings.cargo_tariff.replace",
        "profit_settings.service_fee_estimate.create",
        "profit_settings.variable_expense.create",
        "profit_settings.defaults.update",
        "profit_settings.cargo_tariff.retract",
        "profit_settings.service_fee_estimate.retract",
        "profit_settings.variable_expense.retract",
    ]
    for _, meta in rows:
        assert not (set(meta) & AMOUNT_KEYS), meta  # hiçbir yazımda tutar anahtarı yok
        assert {"account_id", "revision", "affects_from", "affects_past", "past_change_confirmed"} <= set(
            meta
        )
    dump = " ".join(str(m) for _, m in rows)
    for amount in ("54.37", "61.11", "12.34", "6.78", "3.21"):
        assert amount not in dump
    replace_meta = rows[1][1]
    assert replace_meta["record_id"] == new["id"] and replace_meta["replaced_id"] == tariff["id"]
    assert replace_meta["agreement"] == "trendyol" and replace_meta["carrier"] == "Trendyol Express"
    assert replace_meta["valid_from"] == "2026-01-01"
    retract = rows[5][1]  # silmede agreement, carrier, valid_from ve record_id var
    assert retract["record_id"] == new["id"] and retract["agreement"] == "trendyol"
    assert retract["carrier"] == "Trendyol Express" and retract["valid_from"] == "2026-01-01"
    assert rows[7][1]["name"] == "paketleme" and rows[7][1]["kind"] == "siparis_basi"
    assert rows[3][1]["valid_to"] is None and rows[2][1]["valid_from"] == "2026-01-01"


def test_rejected_unconfirmed_and_unchanged_writes_are_not_audited(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    base = len(audits(admin_conn, shop))
    assert (
        raw_put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "9"}]).status_code
        == 409
    )
    assert put_tariff(shop, valid_from="2026-01-01").json()["changed"] is False
    assert len(audits(admin_conn, shop)) == base == 1


# --------------------------------------------------------------------------- GET /history
def test_history_is_newest_first_paged_with_cursor_and_readable_by_every_role(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    for day in range(1, 6):
        put_fee(shop, valid_from=f"2026-01-0{day}", amount=str(day))
    page1 = history(shop, limit=2)
    assert [i["revision"] for i in page1["items"]] == [5, 4]
    assert page1["next_cursor"] not in ("4", None)  # mühürlü, opak imleç (YT-06): düz sürüm numarası değil
    page2 = history(shop, limit=2, cursor=page1["next_cursor"])
    assert [i["revision"] for i in page2["items"]] == [3, 2] and page2["next_cursor"] not in ("2", None)
    page3 = history(shop, limit=2, cursor=page2["next_cursor"])
    assert [i["revision"] for i in page3["items"]] == [1] and page3["next_cursor"] is None
    assert [i["revision"] for i in history(shop)["items"]] == [
        5,
        4,
        3,
        2,
        1,
    ]  # varsayılan sayfa hepsini içerir
    item = page1["items"][0]
    assert item["changed_by"] == {"user_id": str(shop.user_id), "role": "owner"}
    assert item["item"] == "service_fee_estimate" and item["action"] == "ekle"
    assert item["affects_from"] == "2026-01-05" and item["affects_past"] is True
    assert item["past_change_confirmed"] is True  # 5. sürüm geçmişi etkiledi ve onaylandı
    assert item["record"]["amount"] == "5.00" and item["replaced_record"] is None
    assert item["default_desi_before"] is None and item["default_desi_after"] is None
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert [i["revision"] for i in history(shop, limit=1)["items"]] == [5]
    admin_conn.execute("UPDATE memberships SET role = 'admin'")
    assert history(shop, limit=1)["items"][0]["changed_by"]["role"] == "admin"


def test_history_validation_and_empty_account(shop: Shop) -> None:
    assert history(shop) == {"items": [], "next_cursor": None}
    for params in (
        {"limit": 0},
        {"limit": 101},
        {"cursor": ""},
        {"cursor": "x"},
        {"cursor": "1"},
        {"cursor": 0},
    ):
        response = shop.api.get(url(shop, "/history"), params=params)
        assert response.status_code == 422, params
    assert shop.api.get(url(shop, "/history"), params={"limit": 100}).status_code == 200


def test_history_shows_desi_before_and_after_and_unauthenticated_is_401(
    shop: Shop, make_api: Callable[..., Api]
) -> None:
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})
    shop.api.put(url(shop, "/defaults"), {"default_desi": "5", "confirm_affects_from": "all"})
    top = history(shop)["items"][0]
    assert top["item"] == "defaults" and top["action"] == "degistir"
    assert (top["default_desi_before"], top["default_desi_after"]) == ("3.00", "5.00")
    assert top["affects_from"] is None and top["past_change_confirmed"] is True
    assert make_api().get(url(shop, "/history")).status_code == 401


def test_history_shares_the_read_rate_limit_counter(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_read_tenant=2)
    assert shop.api.get(url(shop)).status_code == 200
    assert shop.api.get(url(shop, "/history")).status_code == 200
    limited = shop.api.get(url(shop, "/history"))
    assert limited.status_code == 429 and "Retry-After" in limited.headers


# --------------------------------------------------------------------------- K44: rapor damgası ve sürümle yeniden hesap
def summary(shop: Shop) -> dict[str, Any]:
    response = shop.api.get(f"{shop.base}/profit/summary", params=PERIOD)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_every_report_response_carries_the_settings_revision(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    seed_basic(admin_conn, shop)
    base = f"{shop.base}/profit"
    paths = ["summary", "products", "products/8681000000011", "orders/1001", "alerts"]
    for path in paths:
        body = shop.api.get(f"{base}/{path}", params=PERIOD).json()
        assert body["settings_revision"] == 0, path  # ayarsız hesap: 0
    put_tariff(shop, valid_from="2026-01-01")
    put_fee(shop, valid_from="2026-01-01")
    assert summary(shop)["settings_revision"] == revision_in_db(admin_conn, shop) == 2
    for path in paths:
        assert shop.api.get(f"{base}/{path}", params=PERIOD).json()["settings_revision"] == 2, path
    unchanged = put_tariff(shop, valid_from="2026-01-01")  # değişmeyen yazım damgayı artırmaz
    assert unchanged.json()["changed"] is False and summary(shop)["settings_revision"] == 2
    put_fee(shop, valid_from="2026-01-01", amount="13")
    assert summary(shop)["settings_revision"] == 3  # her gerçek yazımda artar


async def test_loader_at_a_revision_reproduces_the_report_of_that_moment(
    shop: Shop, admin_conn: psycopg.Connection[Any], app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """K44 kabul ölçütü: R sürümüyle yeniden hesap, R anındaki rapora kuruşu kuruşuna eşittir (aynı veriyle)."""
    seed_basic(admin_conn, shop)
    snapshots: dict[int, dict[str, Any]] = {0: summary(shop)}
    put_tariff(
        shop, valid_from="2026-01-01", price_includes_vat=False, brackets=[{"max_desi": "2", "price": "40"}]
    )
    snapshots[1] = summary(shop)
    put_fee(shop, valid_from="2026-01-01", amount="8", amount_includes_vat=False)
    snapshots[2] = summary(shop)
    put_tariff(
        shop, valid_from="2026-01-01", price_includes_vat=False, brackets=[{"max_desi": "2", "price": "65"}]
    )
    snapshots[3] = summary(shop)
    shop.api.post(
        url(shop, "/variable-expenses"), expense_body(amount_excl_vat="5", confirm_past_change=True)
    )
    snapshots[4] = summary(shop)
    put_fee(shop, valid_from="2026-02-01", amount="9", amount_includes_vat=False)
    snapshots[5] = summary(shop)
    assert len({str(s["totals"]) for s in snapshots.values()}) > 3  # sürümler gerçekten farklı sonuç verir
    for revision, expected in snapshots.items():
        assert expected["settings_revision"] == revision
        async with tenant_transaction(app_sessions, shop.tenant_id) as db:
            loaded = await ps.load_profit_settings(db, shop.tenant_id, shop.account_id, at_revision=revision)
            assert loaded.revision == revision
            report = await period_profit(
                db, shop.tenant_id, shop.account_id, date(2026, 10, 1), date(2026, 10, 31), loaded.settings
            )
        totals = PeriodTotalsOut.model_validate(report.totals).model_dump(mode="json", by_alias=True)
        assert totals == expected["totals"], revision
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        # güncel sürüm (None) ile belirli güncel sürüm aynı ayarı verir
        latest = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id)
        same = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=5)
    assert latest == same


async def test_loader_reads_the_default_desi_of_that_revision_from_the_journal(
    shop: Shop, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})  # 1
    put_fee(shop, valid_from="2026-01-01")  # 2
    shop.api.put(url(shop, "/defaults"), {"default_desi": "5", "confirm_affects_from": "all"})  # 3
    shop.api.put(url(shop, "/defaults"), {"default_desi": None, "confirm_affects_from": "all"})  # 4
    expected = {0: None, 1: Decimal("3"), 2: Decimal("3"), 3: Decimal("5"), 4: None}
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        for revision, desi in expected.items():
            settings = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=revision)
            assert settings.default_desi == desi, revision


async def test_loader_rejects_future_revisions_and_revisions_before_the_move(
    shop: Shop, admin_conn: psycopg.Connection[Any], app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    put_fee(shop, valid_from="2026-01-01")  # 1
    put_fee(shop, valid_from="2026-02-01", amount="9")  # 2 (ilk hizmet bedeli sonrası geçmiş onaylı)
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        with pytest.raises(ps.RevisionUnavailable) as future:
            await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=3)
        assert (future.value.requested, future.value.current) == (3, 2)
        with pytest.raises(ps.RevisionUnavailable):
            await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=-1)
    # 0008 öncesi sürüm: günlükteki ilk kayıt `tasima` ise ondan eski sürüm yeniden kurulamaz
    admin_conn.execute(
        "UPDATE profit_settings_changes SET item = 'tasima', action = 'tasima', changed_by = NULL, "
        "record_id = NULL, affects_from = NULL, affects_past = false WHERE marketplace_account_id = %s AND revision = 1",
        (shop.account_id,),
    )
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        with pytest.raises(ps.RevisionUnavailable):
            await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=0)
        ok = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id, at_revision=1)
        assert ok.service_fee_estimates  # taşıma sürümü ve sonrası kurulabilir


# --------------------------------------------------------------------------- eşzamanlılık ve yardımcılar
def test_two_unrelated_accounts_have_independent_histories(two_shops: tuple[Shop, Shop]) -> None:
    a, b = two_shops
    put_fee(a, valid_from="2026-01-01")
    put_fee(b, valid_from="2026-01-01")
    put_fee(b, valid_from="2026-02-01")
    assert [i["revision"] for i in history(a)["items"]] == [1]
    assert [i["revision"] for i in history(b)["items"]] == [2, 1]


def test_is_past_rule() -> None:
    assert ps.is_past(None, TODAY) is True
    assert ps.is_past(date(2026, 11, 7), TODAY) is True
    assert ps.is_past(TODAY, TODAY) is False and ps.is_past(date(2027, 1, 1), TODAY) is False


def test_random_record_id_is_404(shop: Shop) -> None:
    for path in ("cargo-tariffs", "service-fee-estimates", "variable-expenses"):
        assert delete_confirmed(shop, f"/{path}/{uuid4()}").status_code == 404
    assert shop.api.put(url(shop, f"/variable-expenses/{UUID(int=1)}"), expense_body()).status_code == 404


# --------------------------------------------------------------------------- YT-06: mühürlü geçmiş imleci
def cursor_error(shop: Shop, cursor: str) -> Any:
    response = shop.api.get(url(shop, "/history"), params={"cursor": cursor})
    assert response.status_code == 422, cursor
    body = response.json()
    assert body["errors"] == [{"field": "cursor", "code": "cursor_invalid"}]
    return body


def test_history_cursor_is_sealed_and_bound_to_tenant_account_and_query(
    two_shops: tuple[Shop, Shop], settings: Settings
) -> None:
    a, b = two_shops
    for shop in (a, b):
        for day in range(1, 4):
            put_fee(shop, valid_from=f"2026-01-0{day}", amount=str(day))
    cursor = history(a, limit=1)["next_cursor"]
    assert cursor is not None and not cursor.isdigit() and len(cursor) > 20
    assert [i["revision"] for i in history(a, limit=1, cursor=cursor)["items"]] == [2]
    # bozulmuş, kısaltılmış, düz sayı ve rastgele imleçler reddedilir (içerik ayrıştırılmadan)
    tampered = cursor[:-2] + ("AA" if cursor[-2:] != "AA" else "BB")
    for bad in (tampered, cursor[:10], "2", "not-a-cursor", "A" * 60):
        cursor_error(a, bad)
    # başka kiracının hesabının imleci ve başka sorgunun imleci çözülemez
    cursor_error(a, history(b, limit=1)["next_cursor"])
    codec = views.CursorCodec(settings.master_key, a.tenant_id, a.account_id)
    foreign_query = codec.encode("products|net_profit|desc|all|2026-10-01|2026-10-31", ["2"])
    cursor_error(a, foreign_query)
    # içerik doğru mühürlenmiş ama geçersiz sürüm numarası
    for parts in (["0"], ["-1"], ["x"], ["1", "2"], ["99999999999999999999"], [""]):
        cursor_error(a, codec.encode(history_module.HISTORY_FINGERPRINT, parts))
    assert [
        i["revision"]
        for i in history(a, cursor=codec.encode(history_module.HISTORY_FINGERPRINT, ["3"]))["items"]
    ] == [2, 1]


# --------------------------------------------------------------------------- YT-07: onay etki tarihine bağlı
def test_bare_confirm_past_change_is_no_longer_enough_and_writes_nothing(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    base = (revision_in_db(admin_conn, shop), journal(admin_conn, shop), audits(admin_conn, shop))
    response = raw_put_tariff(
        shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "70"}], confirm_past_change=True
    )
    assert response.status_code == 409 and response.json()["type"].endswith(UNCONFIRMED)
    assert response.json()["affects_from"] == "2026-01-01"
    tariff_id = read(shop)["cargo_tariffs"][0]["id"]
    delete = shop.api.delete(url(shop, f"/cargo-tariffs/{tariff_id}"), params={"confirm_past_change": "true"})
    assert delete.status_code == 409 and delete.json()["type"].endswith(UNCONFIRMED)
    desi = shop.api.put(url(shop, "/defaults"), {"default_desi": "3", "confirm_past_change": True})
    assert desi.status_code == 200  # ilk giriş istisnası: onay zaten gerekmez
    changed = shop.api.put(url(shop, "/defaults"), {"default_desi": "4", "confirm_past_change": True})
    assert changed.status_code == 409 and changed.json()["affects_from"] is None  # çıplak bool yetmez
    assert [r[2] for r in table_rows(admin_conn, "cargo_tariffs", shop)] == [None]  # tarife satırı kapanmadı
    assert revision_in_db(admin_conn, shop) == 2  # yalnız ilk desi girişi yazıldı (1 -> 2)
    assert (base[0], len(base[1]), len(base[2])) == (1, 1, 1)
    assert journal(admin_conn, shop)[-1]["item"] == "defaults" and audits(admin_conn, shop)[-1][0].endswith(
        "defaults.update"
    )


def test_confirmation_must_match_the_affects_from_the_server_computed(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Denetim YT-07 PoC A.6'nın tersi: bir tarih için alınan onay başka tarihli gövdede kullanılamaz."""
    put_tariff(shop, valid_from="2026-01-01")
    put_tariff(shop, valid_from="2026-03-01")
    changed = [{"max_desi": "2", "price": "70"}]
    revision = revision_in_db(admin_conn, shop)
    assert revision is not None
    # "1 Ekim" için verilen onayla Ocak başlangıçlı gövde: eşleşmez
    for wrong in ("2026-10-01", "2000-01-01", "all"):
        response = raw_put_tariff(shop, valid_from="2026-01-01", brackets=changed, confirm_affects_from=wrong)
        assert response.status_code == 409 and response.json()["affects_from"] == "2026-01-01", wrong
    assert revision_in_db(admin_conn, shop) == revision  # hiçbiri yazmadı
    ok = raw_put_tariff(shop, valid_from="2026-01-01", brackets=changed, confirm_affects_from="2026-01-01")
    assert ok.status_code == 200 and ok.json()["revision"] == revision + 1
    last = journal(admin_conn, shop)[-1]
    assert last["past_change_confirmed"] is True and str(last["affects_from"]) == "2026-01-01"
    # geçersiz biçim doğrulama hatasıdır
    for junk in ("garbage", "2026-13-45", "", 5, True):
        bad = raw_put_tariff(shop, valid_from="2026-01-01", brackets=changed, confirm_affects_from=junk)
        assert bad.status_code == 422, junk


def test_expense_replace_confirmation_is_the_earlier_of_old_and_new_start(shop: Shop) -> None:
    created = shop.api.post(url(shop, "/variable-expenses"), expense_body(valid_from="2026-10-01")).json()
    eid = created["expense"]["id"]
    earlier = expense_body(valid_from="2026-09-01", amount_excl_vat="9", confirm_past_change=False)
    new_start_only = shop.api.put(
        url(shop, f"/variable-expenses/{eid}"), {**earlier, "confirm_affects_from": "2026-09-01"}
    )
    assert new_start_only.status_code == 200  # yeni başlangıç eskiden önce: etki tarihi yeni başlangıç
    nid = new_start_only.json()["expense"]["id"]
    later = expense_body(valid_from="2026-10-15", amount_excl_vat="8", confirm_past_change=False)
    stale = shop.api.put(
        url(shop, f"/variable-expenses/{nid}"), {**later, "confirm_affects_from": "2026-10-15"}
    )
    assert stale.status_code == 409 and stale.json()["affects_from"] == "2026-09-01"  # min(eski, yeni)
    good = shop.api.put(
        url(shop, f"/variable-expenses/{nid}"), {**later, "confirm_affects_from": "2026-09-01"}
    )
    assert good.status_code == 200


def test_confirmation_for_untimed_defaults_is_all_and_dates_do_not_match(shop: Shop) -> None:
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})  # ilk giriş istisnası
    for wrong in ("2026-10-01", None):
        response = shop.api.put(url(shop, "/defaults"), {"default_desi": "4", "confirm_affects_from": wrong})
        assert response.status_code == 409 and response.json()["affects_from"] is None, wrong
    ok = shop.api.put(url(shop, "/defaults"), {"default_desi": "4", "confirm_affects_from": "all"})
    assert ok.status_code == 200 and ok.json()["action"] == "replaced"
    # tarihli bir yazım için "all" onayı da eşleşmez
    wrong_all = raw_put_tariff(shop, valid_from="2026-01-01", confirm_affects_from="all")
    assert wrong_all.status_code == 409  # ilk giriş istisnası olsa bile eşleşmeyen onay reddedilir
    assert raw_put_tariff(shop, valid_from="2026-01-01").status_code == 200  # onaysız ilk giriş: istisna
    assert raw_put_fee(shop, valid_from="2026-01-01").status_code == 200  # ilk hizmet bedeli
    second = raw_put_fee(shop, valid_from="2026-02-01", confirm_affects_from="all")
    assert second.status_code == 409 and second.json()["affects_from"] == "2026-02-01"


def test_first_entry_exception_still_rejects_a_mismatched_confirmation(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    mismatched = raw_put_tariff(shop, valid_from="2026-01-01", confirm_affects_from="2026-02-02")
    assert mismatched.status_code == 409 and mismatched.json()["affects_from"] == "2026-01-01"
    assert revision_in_db(admin_conn, shop) is None and journal(admin_conn, shop) == []
    matching = raw_put_tariff(shop, valid_from="2026-01-01", confirm_affects_from="2026-01-01")
    assert matching.status_code == 200
    assert journal(admin_conn, shop)[-1]["past_change_confirmed"] is True


def test_delete_confirmation_query_is_bound_to_the_date_and_validated(shop: Shop) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    path = f"/cargo-tariffs/{tariff['id']}"
    for params in (
        {"confirm_past_change": "true"},
        {"confirm_affects_from": "all"},
        {"confirm_affects_from": "2026-02-02"},
    ):
        response = shop.api.delete(url(shop, path), params=params)
        assert response.status_code == 409 and response.json()["affects_from"] == "2026-01-01", params
    for junk in ("2026-13-45", "garbage", "2026-1-1"):
        assert shop.api.delete(url(shop, path), params={"confirm_affects_from": junk}).status_code == 422, (
            junk
        )
    ok = shop.api.delete(url(shop, path), params={"confirm_affects_from": "2026-01-01"})
    assert ok.status_code == 200 and ok.json()["action"] == "retracted"


def test_future_start_needs_no_confirmation_and_ignores_a_stray_one(shop: Shop) -> None:
    put_tariff(shop, valid_from="2026-01-01")
    future = raw_put_tariff(
        shop, carrier="MNG Kargo", valid_from="2026-12-01", confirm_affects_from="2000-01-01"
    )
    assert future.status_code == 200 and future.json()["affects_past"] is False


# --------------------------------------------------------------------------- YT-03: başlıksız hesap taşıması
def test_moved_headless_account_has_a_stamp_and_the_first_replace_is_200_not_500(
    shop: Shop, admin_conn: psycopg.Connection[Any], alembic_cfg: Config
) -> None:
    """Denetim YT-03 PoC A.7'nin tersi: 0007 şemasında başlıksız satır; upgrade sonrası damga 1, değiştirme 200."""
    try:
        command.downgrade(alembic_cfg, "0007")
        admin_conn.execute(
            "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
            "amount_includes_vat) VALUES (%s, %s, %s, '2026-01-01', 12, true)",
            (shop.tenant_id, shop.account_id, shop.user_id),
        )
        assert revision_in_db(admin_conn, shop) is None  # başlık yok (0007 durumu)
        command.upgrade(alembic_cfg, "head")
    finally:
        command.upgrade(alembic_cfg, "head")
    assert revision_in_db(admin_conn, shop) == 1  # taşıma başlığı oluşturdu
    body = read(shop)
    assert body["revision"] == 1 and len(body["service_fee_estimates"]) == 1  # etkin satır, damga 0 DEĞİL
    assert summary(shop)["settings_revision"] == 1
    assert [(r["item"], r["action"], r["revision"]) for r in journal(admin_conn, shop)] == [
        ("tasima", "tasima", 1)
    ]
    replaced = put_fee(shop, valid_from="2026-01-01", amount="13")
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["action"] == "replaced" and replaced.json()["revision"] == 2
    gone = delete_confirmed(shop, f"/service-fee-estimates/{replaced.json()['estimate']['id']}")
    assert gone.status_code == 200 and gone.json()["revision"] == 3
    assert table_rows(admin_conn, "service_fee_estimates", shop)[0][1:4] == (1, 2, "degistirildi")


# --------------------------------------------------------------------------- YT-01: damga ve satırlar aynı sürümden
async def race_fee_replace(shop: Shop) -> None:
    assert put_fee(shop, valid_from="2026-01-01", amount="99").status_code == 200  # sürüm 2: 99,00


async def race_fee_add(shop: Shop) -> None:
    assert put_fee(shop, valid_from="2026-02-01", amount="99").status_code == 200  # sürüm 2: yeni satır


async def race_tariff_add(shop: Shop) -> None:
    assert put_tariff(shop, valid_from="2026-01-01").status_code == 200  # sürüm 2: yeni tarife


@pytest.mark.parametrize("race", [race_fee_replace, race_fee_add, race_tariff_add])
async def test_bundle_rows_and_stamp_come_from_one_revision_despite_a_concurrent_commit(
    shop: Shop,
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    race: Callable[[Shop], Any],
) -> None:
    """Denetim YT-01 PoC A.1'in tersi: başlık okunduktan sonra commit edilen yazım demete sızmaz."""
    put_fee(shop, valid_from="2026-01-01", amount="12")  # sürüm 1
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        real_execute = db.execute
        seen = {"statements": 0}

        async def racing(*args: Any, **kwargs: Any) -> Any:
            result = await real_execute(*args, **kwargs)
            seen["statements"] += 1
            if seen["statements"] == 1:  # başlık okundu; araya eşzamanlı yönetici yazımı girer ve commit eder
                await race(shop)
            return result

        monkeypatch.setattr(db, "execute", racing)
        bundle = await ps.load_bundle(db, shop.tenant_id, shop.account_id)
    assert seen["statements"] >= 4  # yarış gerçekten başlıktan sonra yaşandı
    assert bundle.revision == 1
    # (eşzamanlı değiştirme eski satırın `revision_to`'sunu 2 yapmış olabilir; satır 1. sürümde etkindir)
    assert [(f.amount, f.revision_from) for f in bundle.fees] == [(Decimal("12.000000"), 1)]
    assert bundle.tariffs == () and bundle.expenses == ()
    # aynı veri, yarış bittikten sonra güncel sürümde (2) yeni durumu gösterir
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        after = await ps.load_bundle(db, shop.tenant_id, shop.account_id)
    assert after.revision == 2


def test_summary_completeness_and_figures_come_from_the_same_settings_read(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Denetim YT-01 / AB-02: `summary` tamlığı üçüncü bir okumadan değil, motorun okuduğu demetten gelir."""
    seed_basic(admin_conn, shop)
    put_tariff(shop, valid_from="2026-01-01")
    put_fee(shop, valid_from="2026-01-01")  # sürüm 2
    real_load = ps.load_profit_settings

    async def racing(db: Any, tenant_id: UUID, account_id: UUID) -> Any:
        loaded = await real_load(db, tenant_id, account_id)
        admin_conn.execute(  # eşzamanlı yönetici hizmet bedelini geri çeker ve commit eder (sürüm 3)
            "UPDATE service_fee_estimates SET revision_to = 3, ended_at = now(), ended_by = %s, "
            "end_reason = 'geri_cekildi' WHERE marketplace_account_id = %s AND revision_to IS NULL",
            (shop.user_id, shop.account_id),
        )
        admin_conn.execute(
            "UPDATE profit_settings SET revision = 3 WHERE marketplace_account_id = %s", (shop.account_id,)
        )
        return loaded

    monkeypatch.setattr(profit_module, "load_profit_settings", racing)
    body = summary(shop)
    assert body["settings_revision"] == 2
    assert (
        body["completeness"]["service_fee_estimate_defined"] is True and body["settings_configured"] is True
    )
    assert body["tariff_missing_line_count"] == 0
    monkeypatch.undo()
    assert summary(shop)["completeness"]["service_fee_estimate_defined"] is False  # yarıştan sonra sürüm 3


# --------------------------------------------------------------------------- YT-10: aynı anahtara eşzamanlı yazım
async def test_concurrent_writes_to_the_same_key_serialise_per_account(
    shop: Shop, admin_conn: psycopg.Connection[Any], app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Denetim YT-10 / PoC A.2: ayarsız hesapta aynı anahtara iki eşzamanlı yazım sürüm 1 ve 2 alır, tek etkin satır."""
    valid_from = date(2026, 1, 1)

    async def write(amount: str) -> ps.WriteOutcome:
        async with tenant_transaction(app_sessions, shop.tenant_id) as db:
            ticket = await ps.begin_write(db, shop.tenant_id, shop.account_id, shop.user_id, None)
            return await ps.write_service_fee(
                db,
                shop.tenant_id,
                shop.account_id,
                shop.user_id,
                ticket,
                valid_from,
                Decimal(amount),
                False,
                TODAY,
                valid_from,
            )

    outcomes = await asyncio.gather(write("10"), write("20"))
    assert sorted((o.revision, o.action) for o in outcomes) == [(1, "created"), (2, "replaced")]
    rows = admin_conn.execute(
        "SELECT amount, revision_from, revision_to, revision_to IS NULL FROM service_fee_estimates "
        "WHERE marketplace_account_id = %s ORDER BY revision_from",
        (shop.account_id,),
    ).fetchall()
    assert [(r[1], r[2], r[3]) for r in rows] == [(1, 2, False), (2, None, True)]
    assert [(r["revision"], r["action"]) for r in journal(admin_conn, shop)] == [(1, "ekle"), (2, "degistir")]
    assert revision_in_db(admin_conn, shop) == 2


# --------------------------------------------------------------------------- YT-02: halef zinciri
def seed_chain(conn: psycopg.Connection[Any], shop: Shop, length: int) -> list[UUID]:
    """`length` halkalı değişken gider zinciri: ilk satır en eski, son satır etkin (sürüm `length`)."""
    seed_head(conn, shop, revision=length)
    ids = [uuid4() for _ in range(length)]
    rows = [
        (
            ids[i],
            shop.tenant_id,
            shop.account_id,
            shop.user_id,
            i + 1,
            None if i == length - 1 else i + 2,
            None if i == length - 1 else shop.user_id,
            None if i == length - 1 else "degistirildi",
            None if i == 0 else ids[i - 1],
        )
        for i in range(length)
    ]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO variable_expenses (id, tenant_id, marketplace_account_id, entered_by, name, kind, "
            "amount_excl_vat, vat_rate, valid_from, revision_from, revision_to, ended_at, ended_by, end_reason, "
            "replaces_id) VALUES (%s, %s, %s, %s, 'zincir', 'siparis_basi', 1, 20, '2026-01-01', %s, %s, "
            "CASE WHEN %s::uuid IS NULL THEN NULL ELSE now() END, %s, %s, %s)",
            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[6], r[7], r[8]) for r in rows],
        )
    return ids


def test_record_ended_on_a_long_chain_stays_fast_and_correct(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Denetim YT-02 PoC A.4: 2000 halkalı zincir 2,29 sn sürüyordu; tek özyinelemeli sorgu ile gevşek eşik altında."""
    ids = seed_chain(admin_conn, shop, 2000)
    started = time.perf_counter()
    response = shop.api.put(url(shop, f"/variable-expenses/{ids[0]}"), expense_body())
    elapsed = time.perf_counter() - started
    assert response.status_code == 409 and response.json()["type"].endswith("settings-record-ended")
    assert response.json()["current_id"] == str(ids[-1])
    assert elapsed < 1.5, f"2000 halkalı zincirde settings-record-ended {elapsed:.2f} sn sürdü"
    middle = shop.api.put(url(shop, f"/variable-expenses/{ids[1000]}"), expense_body())
    assert middle.json()["current_id"] == str(ids[-1])
    active = shop.api.put(
        url(shop, f"/variable-expenses/{ids[-1]}"), expense_body(amount_excl_vat="2", valid_from="2026-01-01")
    )
    assert active.status_code == 200  # zincirin etkin ucu normal değiştirilir


async def test_successor_walk_uses_a_constant_number_of_queries_and_is_capped(
    shop: Shop,
    admin_conn: psycopg.Connection[Any],
    app_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = seed_chain(admin_conn, shop, 300)
    statements: list[str] = []
    engine = app_sessions.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, *rest: statements.append(stmt))

    async def walk(start: UUID) -> UUID | None:
        async with tenant_transaction(app_sessions, shop.tenant_id) as db:
            record = await ps.get_record(db, VariableExpenseRecord, shop.tenant_id, shop.account_id, start)
            before = len(statements)
            found = await ps._current_id(db, VariableExpenseRecord, shop.tenant_id, shop.account_id, record)
            assert len(statements) - before == 1, "zincir tek sorguyla yürünmeli"
            return found

    assert await walk(ids[0]) == ids[-1]  # 299 halka
    assert await walk(ids[290]) == ids[-1]
    assert await walk(ids[-2]) == ids[-1]  # tek halka
    # üst sınır: aşılırsa `current_id` null döner (yanıt yine 409 settings-record-ended)
    monkeypatch.setattr(ps, "MAX_SUCCESSOR_CHAIN", 5)
    assert await walk(ids[-1 - 5]) == ids[-1]  # tam sınırda (5 halef)
    assert await walk(ids[-1 - 6]) is None
    assert await walk(ids[0]) is None


def test_retracted_row_has_no_successor_and_dangling_chain_is_none(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    assert delete_confirmed(shop, f"/cargo-tariffs/{tariff['id']}").status_code == 200
    again = delete_confirmed(shop, f"/cargo-tariffs/{tariff['id']}")
    assert again.status_code == 409 and again.json()["current_id"] is None
    # halefi olmayan ama `degistirildi` ile kapanmış satır (olmaması gereken durum): savunma, null
    fee = put_fee(shop, valid_from="2026-01-01").json()["estimate"]
    admin_conn.execute(
        "UPDATE service_fee_estimates SET revision_to = 9, ended_at = now(), ended_by = %s, "
        "end_reason = 'degistirildi' WHERE id = %s",
        (shop.user_id, fee["id"]),
    )
    dangling = delete_confirmed(shop, f"/service-fee-estimates/{fee['id']}")
    assert dangling.status_code == 409 and dangling.json()["current_id"] is None
