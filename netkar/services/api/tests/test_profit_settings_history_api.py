"""Ayar tarihçesi (ADR-0007 §5, §8; docs/12 K42-K44): ekle / değiştir / değişmedi / geri çek, geçmiş etki onayı,
ilk giriş istisnası, ayar günlüğü ve `GET /history`, denetim izi (tutar yok), sürüm damgası ve sürümle yeniden hesap.

Gerçek PostgreSQL ve gerçek HTTP katmanı. İstanbul bugünü 2026-11-08'e sabittir (`fixed_today`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1.profit_schemas import PeriodTotalsOut
from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.services import profit_settings as ps
from app.services.profit_report import period_profit
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import seed_basic
from tests.test_profit_settings_api import (
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
    body = expense_body(**over)
    body.pop("confirm_past_change")
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
    gone = shop.api.delete(
        url(shop, f"/cargo-tariffs/{tariff['id']}"), params={"confirm_past_change": "true"}
    )
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
        confirm_past_change=True,
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
        {**expense_body(amount_excl_vat="9"), "confirm_past_change": False},
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
    ok = shop.api.put(url(shop, "/defaults"), {"default_desi": "4", "confirm_past_change": True})
    assert ok.status_code == 200 and ok.json()["action"] == "replaced" and ok.json()["revision"] == 2
    clear = shop.api.put(url(shop, "/defaults"), {"default_desi": None, "confirm_past_change": True})
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
        {**expense_body(valid_from="2026-11-20"), "confirm_past_change": False},
    )
    assert moved.status_code == 200 and moved.json()["affects_from"] == "2026-11-09"
    back = shop.api.put(
        url(shop, f"/variable-expenses/{moved.json()['expense']['id']}"),
        {**expense_body(valid_from="2026-10-01"), "confirm_past_change": False},
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
    stale = shop.api.delete(url(shop, f"/cargo-tariffs/{old['id']}"), params={"confirm_past_change": "true"})
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
    fee_stale = shop.api.delete(
        url(shop, f"/service-fee-estimates/{fee['id']}"), params={"confirm_past_change": "true"}
    )
    assert fee_stale.status_code == 409 and fee_stale.json()["current_id"] is not None


def test_other_tenants_record_ids_are_404_not_409(two_shops: tuple[Shop, Shop]) -> None:
    a, b = two_shops
    tariff = put_tariff(a, valid_from="2026-01-01").json()["tariff"]
    expense = a.api.post(url(a, "/variable-expenses"), expense_body()).json()["expense"]
    ok = {"confirm_past_change": "true"}
    assert b.api.delete(url(b, f"/cargo-tariffs/{tariff['id']}"), params=ok).status_code == 404
    assert b.api.put(url(b, f"/variable-expenses/{expense['id']}"), expense_body()).status_code == 404
    assert b.api.delete(url(b, f"/variable-expenses/{expense['id']}"), params=ok).status_code == 404
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
    assert (
        shop.api.delete(
            url(shop, f"/cargo-tariffs/{first['id']}"), params={"confirm_past_change": "true"}
        ).status_code
        == 200
    )
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
    assert (
        shop.api.delete(
            url(shop, f"/variable-expenses/{replaced.json()['expense']['id']}"),
            params={"confirm_past_change": "true"},
        ).status_code
        == 200
    )
    assert shop.api.post(url(shop, "/variable-expenses"), expense_body(name="fazla")).status_code == 201


# --------------------------------------------------------------------------- ayar günlüğü ve denetim izi
def test_every_write_adds_exactly_one_journal_row_per_revision(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    tariff = put_tariff(shop, valid_from="2026-01-01").json()
    fee = put_fee(shop, valid_from="2026-01-01").json()
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()
    changed = put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "70"}]).json()
    shop.api.delete(
        url(shop, f"/service-fee-estimates/{fee['estimate']['id']}"), params={"confirm_past_change": "true"}
    )
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
    shop.api.delete(url(shop, f"/cargo-tariffs/{new['id']}"), params={"confirm_past_change": "true"})
    shop.api.delete(url(shop, f"/service-fee-estimates/{fee['id']}"), params={"confirm_past_change": "true"})
    shop.api.delete(url(shop, f"/variable-expenses/{expense['id']}"), params={"confirm_past_change": "true"})
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
    assert [i["revision"] for i in page1["items"]] == [5, 4] and page1["next_cursor"] == "4"
    page2 = history(shop, limit=2, cursor=page1["next_cursor"])
    assert [i["revision"] for i in page2["items"]] == [3, 2] and page2["next_cursor"] == "2"
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
    for params in ({"limit": 0}, {"limit": 101}, {"cursor": 0}, {"cursor": "x"}):
        response = shop.api.get(url(shop, "/history"), params=params)
        assert response.status_code == 422, params
    assert shop.api.get(url(shop, "/history"), params={"limit": 100}).status_code == 200
    assert shop.api.get(url(shop, "/history"), params={"cursor": 1}).status_code == 200


def test_history_shows_desi_before_and_after_and_unauthenticated_is_401(
    shop: Shop, make_api: Callable[..., Api]
) -> None:
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})
    shop.api.put(url(shop, "/defaults"), {"default_desi": "5", "confirm_past_change": True})
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
    shop.api.put(url(shop, "/defaults"), {"default_desi": "5", "confirm_past_change": True})  # 3
    shop.api.put(url(shop, "/defaults"), {"default_desi": None, "confirm_past_change": True})  # 4
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
    ok = {"confirm_past_change": "true"}
    for path in ("cargo-tariffs", "service-fee-estimates", "variable-expenses"):
        assert shop.api.delete(url(shop, f"/{path}/{uuid4()}"), params=ok).status_code == 404
    assert shop.api.put(url(shop, f"/variable-expenses/{UUID(int=1)}"), expense_body()).status_code == 404
