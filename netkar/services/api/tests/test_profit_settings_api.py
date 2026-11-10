"""Kâr ayarları API'si (ADR-0006 §3.3): okuma, yazma, KDV dönüşümü, sürüm (409), denetim izi, roller, IDOR,
doğrulama kodları, sayı sınırları, hız sınırı ve motora yansıma."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.profit import ProfitSettings, calculate_profit
from app.profit.inputs import Order as EngineOrder
from app.profit.inputs import OrderItem, OrderLine, ProfitInput
from app.services import profit_settings as ps
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import seed_basic

pytestmark = pytest.mark.usefixtures("fixed_today")

TODAY = date(2026, 11, 8)


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop]) -> tuple[Shop, Shop]:
    return make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")


def url(shop: Shop, suffix: str = "") -> str:
    return f"{shop.base}/profit-settings{suffix}"


def tariff_body(**over: Any) -> dict[str, Any]:
    body = {
        "agreement": "trendyol",
        "carrier": "Trendyol Express",
        "valid_from": "2026-10-01",
        "price_includes_vat": True,
        "brackets": [{"max_desi": "2", "price": "54.00"}, {"max_desi": "5", "price": "50.00"}],
        # Başlangıç tarihi geçmiş olduğundan (K43) bu yardımcı geçmiş etkiyi varsayılan olarak onaylar;
        # onay kuralını sınayan testler alanı açıkça `False` yapar.
        "confirm_past_change": True,
    }
    body.update(over)
    return body


def expense_body(**over: Any) -> dict[str, Any]:
    body = {
        "name": "paketleme",
        "kind": "siparis_basi",
        "amount_excl_vat": "6.00",
        "vat_rate": 20,
        "valid_from": "2026-10-01",
        "valid_to": None,
        "confirm_past_change": True,
    }
    body.update(over)
    return body


def put_tariff(shop: Shop, **over: Any) -> Any:
    return shop.api.put(url(shop, "/cargo-tariffs"), tariff_body(**over))


def put_fee(shop: Shop, **over: Any) -> Any:
    body = {
        "valid_from": "2026-10-01",
        "amount": "12.00",
        "amount_includes_vat": True,
        "confirm_past_change": True,
    }
    body.update(over)
    return shop.api.put(url(shop, "/service-fee-estimates"), body)


def read(shop: Shop) -> dict[str, Any]:
    response = shop.api.get(url(shop))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def revision_in_db(conn: psycopg.Connection[Any], shop: Shop) -> int | None:
    row = conn.execute(
        "SELECT revision FROM profit_settings WHERE marketplace_account_id = %s", (shop.account_id,)
    ).fetchone()
    return None if row is None else int(row[0])


def audit_rows(conn: psycopg.Connection[Any], shop: Shop) -> list[tuple[str, str | None, dict[str, Any]]]:
    rows = conn.execute(
        "SELECT action, target, meta FROM audit_log WHERE tenant_id = %s AND action LIKE 'profit_settings.%%' "
        "ORDER BY id",
        (shop.tenant_id,),
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


# --------------------------------------------------------------------------- okuma
def test_empty_account_reads_as_undefined(shop: Shop) -> None:
    body = read(shop)
    assert body["revision"] == 0 and body["default_desi"] is None
    assert body["cargo_tariffs"] == [] and body["service_fee_estimates"] == []
    assert body["variable_expenses"] == []
    assert body["completeness"] == {
        "cargo_tariff_defined": False,
        "seller_cargo_tariff_defined": False,
        "service_fee_estimate_defined": False,
        "variable_expenses_defined": False,
        "default_desi_defined": False,
    }


def test_write_then_read_shows_entered_and_vat_exclusive_prices(shop: Shop) -> None:
    response = put_tariff(shop)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["revision"] == 1 and out["created"] is True
    tariff = out["tariff"]
    assert tariff["brackets"] == [
        {"max_desi": "2.00", "price": "54.00", "price_excl_vat": "45.00"},  # 54,00 dahil -> 45,00
        {"max_desi": "5.00", "price": "50.00", "price_excl_vat": "41.67"},  # 50,00 dahil -> 41,67
    ]
    fee = put_fee(shop).json()["estimate"]
    assert (fee["amount"], fee["amount_includes_vat"], fee["amount_excl_vat"]) == ("12.00", True, "10.00")
    body = read(shop)
    assert body["revision"] == 2 and len(body["cargo_tariffs"]) == 1
    assert (
        body["cargo_tariffs"][0]["id"] == tariff["id"] and body["service_fee_estimates"][0]["id"] == fee["id"]
    )
    assert (
        body["completeness"]["cargo_tariff_defined"] and body["completeness"]["service_fee_estimate_defined"]
    )


def test_vat_exclusive_entry_is_stored_as_entered(shop: Shop) -> None:
    out = put_tariff(shop, price_includes_vat=False).json()["tariff"]
    assert out["price_includes_vat"] is False
    assert [b["price_excl_vat"] for b in out["brackets"]] == ["54.00", "50.00"]
    zero = put_fee(shop, amount="0", amount_includes_vat=False).json()["estimate"]
    assert zero["amount_excl_vat"] == "0.00"  # bilerek 0: tanımlı (K35)


def test_versions_are_kept_and_same_key_is_replaced_not_overwritten(shop: Shop) -> None:
    """ADR-0007: aynı anahtarlı PUT yerinde ezmez; eski satır kapanır, YENİ kimlikle yeni satır eklenir."""
    first = put_tariff(shop, valid_from="2026-01-01").json()
    second = put_tariff(shop, valid_from="2026-10-10").json()
    again = put_tariff(shop, valid_from="2026-10-10", price_includes_vat=False).json()
    assert (first["created"], second["created"], again["created"]) == (True, True, False)
    assert (first["action"], second["action"], again["action"]) == ("created", "created", "replaced")
    assert again["tariff"]["id"] != second["tariff"]["id"] and again["revision"] == 3
    assert again["replaced_id"] == second["tariff"]["id"] and again["changed"] is True
    tariffs = read(shop)["cargo_tariffs"]  # yalnız etkin satırlar
    assert [t["valid_from"] for t in tariffs] == [
        "2026-01-01",
        "2026-10-10",
    ]  # eski sürüm (başka başlangıç) durur
    assert tariffs[1]["price_includes_vat"] is False and tariffs[1]["id"] == again["tariff"]["id"]
    other_carrier = put_tariff(shop, carrier="*", valid_from="2026-10-10").json()
    assert other_carrier["created"] is True and len(read(shop)["cargo_tariffs"]) == 3
    seller = put_tariff(shop, agreement="seller", valid_from="2026-10-10").json()
    assert seller["created"] is True
    completeness = read(shop)["completeness"]
    assert completeness["seller_cargo_tariff_defined"] is True


def test_future_version_is_not_defined_today(shop: Shop) -> None:
    put_tariff(shop, valid_from="2026-12-01")
    put_fee(shop, valid_from="2026-12-01")
    assert read(shop)["completeness"]["cargo_tariff_defined"] is False
    assert read(shop)["completeness"]["service_fee_estimate_defined"] is False


def test_defaults_and_variable_expenses_round_trip(shop: Shop) -> None:
    first_desi = shop.api.put(
        url(shop, "/defaults"), {"default_desi": "3"}
    )  # ilk giriş istisnası: onaysız 200
    assert first_desi.status_code == 200, first_desi.text
    assert first_desi.json() == {
        "revision": 1,
        "default_desi": "3.00",
        "changed": True,
        "action": "created",
        "replaced_id": None,
        "affects_from": None,
        "affects_past": True,
    }
    created = shop.api.post(url(shop, "/variable-expenses"), expense_body())
    assert created.status_code == 201, created.text
    expense = created.json()["expense"]
    assert expense["amount_excl_vat"] == "6.00" and expense["percent"] is None and expense["vat_rate"] == 20
    pct = shop.api.post(
        url(shop, "/variable-expenses"),
        expense_body(
            name="entegratör", kind="satis_yuzdesi", amount_excl_vat=None, percent="0.5", vat_rate=10
        ),
    ).json()["expense"]
    assert pct["percent"] == "0.5" and pct["amount_excl_vat"] is None
    body = read(shop)
    assert body["default_desi"] == "3.00" and len(body["variable_expenses"]) == 2
    assert body["completeness"]["variable_expenses_defined"] and body["completeness"]["default_desi_defined"]
    cleared = shop.api.put(url(shop, "/defaults"), {"default_desi": None, "confirm_past_change": True}).json()
    assert cleared["default_desi"] is None and read(shop)["completeness"]["default_desi_defined"] is False


def test_expired_expense_is_not_defined_today(shop: Shop) -> None:
    shop.api.post(
        url(shop, "/variable-expenses"), expense_body(valid_from="2026-01-01", valid_to="2026-10-09")
    )
    assert read(shop)["completeness"]["variable_expenses_defined"] is False


def test_variable_expense_replace_and_retract(shop: Shop) -> None:
    created = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()["expense"]
    updated = shop.api.put(
        url(shop, f"/variable-expenses/{created['id']}"),
        expense_body(amount_excl_vat="7.50", valid_to="2026-12-31"),
    )
    assert updated.status_code == 200 and updated.json()["expense"]["amount_excl_vat"] == "7.50"
    assert updated.json()["expense"]["valid_to"] == "2026-12-31" and updated.json()["revision"] == 2
    new_id = updated.json()["expense"]["id"]
    assert new_id != created["id"] and updated.json()["replaced_id"] == created["id"]  # yeni kimlik
    # Kapanmış (değiştirilmiş) eski kimliğe yazım 409: gövdede yerini alan etkin satır
    stale = shop.api.put(url(shop, f"/variable-expenses/{created['id']}"), expense_body())
    assert stale.status_code == 409 and stale.json()["type"].endswith("settings-record-ended")
    assert stale.json()["current_id"] == new_id
    stale_delete = shop.api.delete(url(shop, f"/variable-expenses/{created['id']}?confirm_past_change=true"))
    assert stale_delete.status_code == 409 and stale_delete.json()["current_id"] == new_id
    gone = shop.api.delete(url(shop, f"/variable-expenses/{new_id}?confirm_past_change=true"))
    assert gone.status_code == 200 and gone.json()["revision"] == 3 and gone.json()["action"] == "retracted"
    assert read(shop)["variable_expenses"] == []
    again = shop.api.delete(url(shop, f"/variable-expenses/{new_id}?confirm_past_change=true"))
    assert again.status_code == 409 and again.json()["current_id"] is None  # geri çekilmiş: halef yok
    missing_update = shop.api.put(url(shop, f"/variable-expenses/{uuid4()}"), expense_body())
    assert missing_update.status_code == 404


def test_deleting_one_version_keeps_the_rest_and_missing_delete_does_not_bump_revision(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    old = put_tariff(shop, valid_from="2026-01-01").json()["tariff"]
    new = put_tariff(shop, valid_from="2026-10-10").json()["tariff"]
    fee = put_fee(shop).json()["estimate"]
    ok = "?confirm_past_change=true"
    assert shop.api.delete(url(shop, f"/cargo-tariffs/{new['id']}{ok}")).json()["revision"] == 4
    assert [t["id"] for t in read(shop)["cargo_tariffs"]] == [old["id"]]
    assert shop.api.delete(url(shop, f"/service-fee-estimates/{fee['id']}{ok}")).json()["revision"] == 5
    before = revision_in_db(admin_conn, shop)
    assert shop.api.delete(url(shop, f"/cargo-tariffs/{uuid4()}{ok}")).status_code == 404
    assert revision_in_db(admin_conn, shop) == before  # bulunamayan silme sürümü artırmaz


# --------------------------------------------------------------------------- doğrulama
@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        (
            {"brackets": [{"max_desi": "5", "price": "10"}, {"max_desi": "3", "price": "20"}]},
            "brackets",
            "brackets_not_increasing",
        ),
        (
            {"brackets": [{"max_desi": "2", "price": "10"}, {"max_desi": "2", "price": "20"}]},
            "brackets",
            "brackets_not_increasing",
        ),
        ({"brackets": [{"max_desi": "0", "price": "10"}]}, "brackets.0.max_desi", "desi_out_of_range"),
        ({"brackets": [{"max_desi": "1000.01", "price": "10"}]}, "brackets.0.max_desi", "desi_out_of_range"),
        ({"brackets": [{"max_desi": "1.234", "price": "10"}]}, "brackets.0.max_desi", "desi_out_of_range"),
        ({"brackets": [{"max_desi": "-1", "price": "10"}]}, "brackets.0.max_desi", "desi_out_of_range"),
        ({"brackets": [{"max_desi": "1", "price": "-0.01"}]}, "brackets.0.price", "price_out_of_range"),
        ({"brackets": [{"max_desi": "1", "price": "100000.01"}]}, "brackets.0.price", "price_out_of_range"),
        ({"brackets": [{"max_desi": "1", "price": "1.234"}]}, "brackets.0.price", "price_out_of_range"),
        ({"brackets": [{"max_desi": "1", "price": "abc"}]}, "brackets.0.price", "decimal_invalid"),
        (
            {"brackets": [{"max_desi": str(i + 1), "price": "1"} for i in range(51)]},
            "brackets",
            "too_many_brackets",
        ),
        ({"brackets": []}, "brackets", "brackets_empty"),
        ({"carrier": ""}, "carrier", "carrier_invalid"),
        ({"carrier": " Aras"}, "carrier", "carrier_invalid"),
        ({"carrier": "Aras\x00"}, "carrier", "carrier_invalid"),
        ({"carrier": "x" * 101}, "carrier", "carrier_invalid"),
        ({"carrier": "Aras*"}, "carrier", "carrier_invalid"),
        ({"valid_from": "1999-12-31"}, "valid_from", "valid_from_out_of_range"),
        ({"valid_from": "2027-11-10"}, "valid_from", "valid_from_out_of_range"),
        ({"valid_from": 20261001}, "valid_from", "date_type"),
        ({"agreement": "baska"}, "agreement", "literal_error"),
        ({"price_includes_vat": "evet"}, "price_includes_vat", "bool_parsing"),
        ({"fazladan": 1}, "fazladan", "extra_forbidden"),
    ],
)
def test_tariff_validation_codes(shop: Shop, body: dict[str, Any], field: str, code: str) -> None:
    response = put_tariff(shop, **body)
    assert response.status_code == 422, response.text
    errors = response.json()["errors"]
    assert {"field": field, "code": code} in errors, errors
    assert read(shop)["revision"] == 0  # reddedilen yazım sürümü artırmaz


def test_validation_error_does_not_echo_input(shop: Shop) -> None:
    secret = "GIZLI-FIRMA-ADI-12345"
    response = put_tariff(shop, carrier=secret + " ", brackets=[{"max_desi": "9999", "price": "88888888"}])
    assert response.status_code == 422
    assert secret not in response.text and "9999" not in response.text and "88888888" not in response.text


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"amount": "-1"}, "amount", "amount_out_of_range"),
        ({"amount": "10000.01"}, "amount", "amount_out_of_range"),
        ({"amount": "1.234"}, "amount", "amount_out_of_range"),
        ({"valid_from": "1999-01-01"}, "valid_from", "valid_from_out_of_range"),
        ({"amount_includes_vat": None}, "amount_includes_vat", "bool_type"),
    ],
)
def test_service_fee_validation_codes(shop: Shop, body: dict[str, Any], field: str, code: str) -> None:
    response = put_fee(shop, **body)
    assert response.status_code == 422
    assert {"field": field, "code": code} in response.json()["errors"], response.json()


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"vat_rate": 18}, "vat_rate", "vat_rate_invalid"),
        ({"vat_rate": "0.2"}, "vat_rate", "vat_rate_invalid"),
        ({"amount_excl_vat": "-1"}, "amount_excl_vat", "amount_out_of_range"),
        ({"amount_excl_vat": "100000.01"}, "amount_excl_vat", "amount_out_of_range"),
        (
            {"kind": "satis_yuzdesi", "amount_excl_vat": None, "percent": "0"},
            "percent",
            "percent_out_of_range",
        ),
        (
            {"kind": "satis_yuzdesi", "amount_excl_vat": None, "percent": "100.01"},
            "percent",
            "percent_out_of_range",
        ),
        (
            {"kind": "satis_yuzdesi", "amount_excl_vat": None, "percent": "1.23456"},
            "percent",
            "percent_out_of_range",
        ),
        ({"kind": "satis_yuzdesi"}, "", "kind_amount_mismatch"),  # yüzde tipinde tutar var
        ({"kind": "satis_yuzdesi", "amount_excl_vat": None}, "", "kind_amount_mismatch"),  # oran yok
        ({"percent": "5"}, "", "kind_amount_mismatch"),  # tutar tipinde oran var
        ({"amount_excl_vat": None}, "", "kind_amount_mismatch"),  # tutar yok
        ({"valid_to": "2026-09-30"}, "valid_to", "valid_to_before_valid_from"),
        ({"name": ""}, "name", "name_invalid"),
        ({"name": "x" * 81}, "name", "name_invalid"),
        ({"name": "ad\n"}, "name", "name_invalid"),
        ({"kind": "haftalik"}, "kind", "literal_error"),
        ({"valid_from": "2030-01-01"}, "valid_from", "valid_from_out_of_range"),
    ],
)
def test_variable_expense_validation_codes(shop: Shop, body: dict[str, Any], field: str, code: str) -> None:
    response = shop.api.post(url(shop, "/variable-expenses"), expense_body(**body))
    assert response.status_code == 422, response.text
    assert {"field": field, "code": code} in response.json()["errors"], response.json()


@pytest.mark.parametrize("value", ["0", "-1", "1000.01", "1.234", "abc"])
def test_default_desi_validation(shop: Shop, value: str) -> None:
    response = shop.api.put(url(shop, "/defaults"), {"default_desi": value})
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "default_desi"


def test_default_desi_boundaries_are_accepted(shop: Shop) -> None:
    for value in ("0.01", "1000", "1000.00"):
        r = shop.api.put(url(shop, "/defaults"), {"default_desi": value, "confirm_past_change": True})
        assert r.status_code == 200


def test_too_many_expenses_is_rejected(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    for index in range(ps.MAX_EXPENSES):
        admin_conn.execute(
            "INSERT INTO variable_expenses (revision_from, tenant_id, marketplace_account_id, name, kind, amount_excl_vat, "
            "vat_rate, valid_from, entered_by) VALUES (1, %s, %s, %s, 'siparis_basi', 1, 20, '2026-01-01', %s)",
            (shop.tenant_id, shop.account_id, f"g{index}", shop.user_id),
        )
    response = shop.api.post(url(shop, "/variable-expenses"), expense_body())
    assert response.status_code == 422
    assert {"field": "name", "code": "too_many_expenses"} in response.json()["errors"]
    assert revision_in_db(admin_conn, shop) is None  # oluşturulan ayar satırı da geri alındı


def seed_head(conn: psycopg.Connection[Any], shop: Shop, revision: int = 1) -> None:
    """Doğrudan satır tohumlayan testler için hesabın ayar satırı (gerçek veride satırlarla birlikte vardır)."""
    conn.execute(
        "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
        "VALUES (%s, %s, %s, %s)",
        (shop.tenant_id, shop.account_id, shop.user_id, revision),
    )


def test_too_many_tariff_versions_is_rejected(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    seed_head(admin_conn, shop)
    for index in range(ps.MAX_TARIFF_VERSIONS):
        admin_conn.execute(
            "INSERT INTO cargo_tariffs (revision_from, tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
            "price_includes_vat, brackets, entered_by) VALUES (1, %s, %s, 'trendyol', %s, '2026-01-01', false, "
            '\'[{"max_desi": "1", "price": "1"}]\', %s)',
            (shop.tenant_id, shop.account_id, f"F{index}", shop.user_id),
        )
    response = put_tariff(shop, carrier="Yeni Firma")
    assert response.status_code == 422
    assert {"field": "valid_from", "code": "too_many_tariff_versions"} in response.json()["errors"]
    # mevcut bir sürümü değiştirmek sınırdan etkilenmez (K42: sınır etkin satırları sayar, değiştirme sınırı aşmaz)
    assert put_tariff(shop, carrier="F0", valid_from="2026-01-01").status_code == 200
    assert len(read(shop)["cargo_tariffs"]) == ps.MAX_TARIFF_VERSIONS  # eski satır kapandı, sayı aynı


def test_path_and_query_validation(shop: Shop) -> None:
    assert shop.api.delete(url(shop, "/cargo-tariffs/not-a-uuid")).status_code == 422
    assert (
        shop.api.delete(url(shop, f"/cargo-tariffs/{uuid4()}"), params={"expected_revision": -1}).status_code
        == 422
    )


# --------------------------------------------------------------------------- sürüm (409)
def test_revision_conflict_returns_409_and_leaves_no_trace(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    assert put_tariff(shop).json()["revision"] == 1
    stale = put_tariff(shop, carrier="Aras", expected_revision=0)
    assert stale.status_code == 409
    problem = stale.json()
    assert problem["type"] == "urn:netkar:problem:settings-revision-conflict"
    assert problem["current_revision"] == 1
    assert len(read(shop)["cargo_tariffs"]) == 1 and revision_in_db(admin_conn, shop) == 1
    fresh = put_tariff(shop, carrier="Aras", expected_revision=1)
    assert fresh.status_code == 200 and fresh.json()["revision"] == 2


def test_expected_revision_zero_creates_and_other_values_conflict_on_empty_account(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    stale = put_fee(shop, expected_revision=3)
    assert stale.status_code == 409 and stale.json()["current_revision"] == 0
    assert revision_in_db(admin_conn, shop) is None
    assert put_fee(shop, expected_revision=0).json()["revision"] == 1


def test_every_write_endpoint_honours_expected_revision(shop: Shop) -> None:
    tariff = put_tariff(shop).json()["tariff"]
    fee = put_fee(shop).json()["estimate"]
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body()).json()["expense"]
    stale = 99
    assert put_fee(shop, expected_revision=stale).status_code == 409
    assert (
        shop.api.post(url(shop, "/variable-expenses"), expense_body(expected_revision=stale)).status_code
        == 409
    )
    update = shop.api.put(
        url(shop, f"/variable-expenses/{expense['id']}"), expense_body(expected_revision=stale)
    )
    assert update.status_code == 409
    assert (
        shop.api.put(url(shop, "/defaults"), {"default_desi": "2", "expected_revision": stale}).status_code
        == 409
    )
    for kind, item in (
        ("cargo-tariffs", tariff),
        ("service-fee-estimates", fee),
        ("variable-expenses", expense),
    ):
        gone = shop.api.delete(url(shop, f"/{kind}/{item['id']}"), params={"expected_revision": stale})
        assert gone.status_code == 409, kind
    assert read(shop)["revision"] == 3  # hiçbir reddedilen yazım sürümü artırmadı


async def test_concurrent_writers_are_serialised_and_exactly_one_wins_with_same_expectation(
    database: DatabaseInfo, shop: Shop
) -> None:
    """İki yönetici aynı sürümü görüp aynı anda yazar: biri kazanır, diğeri 409 alır (sessiz ezme yok)."""
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def attempt() -> str:
        async with tenant_transaction(sessions, shop.tenant_id) as db:
            try:
                await ps.begin_write(db, shop.tenant_id, shop.account_id, shop.user_id, 0)
            except ps.RevisionConflict:
                return "conflict"
            await asyncio.sleep(0.2)  # kilidi tutarken öbürü beklemeli
            return "won"

    try:
        results = await asyncio.wait_for(asyncio.gather(attempt(), attempt()), timeout=30)
    finally:
        await engine.dispose()
    assert sorted(results) == ["conflict", "won"]


# --------------------------------------------------------------------------- denetim izi
def test_every_write_is_audited_without_amounts(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    tariff = put_tariff(shop, brackets=[{"max_desi": "2", "price": "54.37"}]).json()["tariff"]
    fee = put_fee(shop, amount="12.34").json()["estimate"]
    expense = shop.api.post(url(shop, "/variable-expenses"), expense_body(amount_excl_vat="6.78")).json()[
        "expense"
    ]
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3.21"})
    ok = "?confirm_past_change=true"
    shop.api.delete(url(shop, f"/variable-expenses/{expense['id']}{ok}"))
    shop.api.delete(url(shop, f"/cargo-tariffs/{tariff['id']}{ok}"))
    shop.api.delete(url(shop, f"/service-fee-estimates/{fee['id']}{ok}"))
    rows = audit_rows(admin_conn, shop)
    assert [r[0] for r in rows] == [
        "profit_settings.cargo_tariff.create",
        "profit_settings.service_fee_estimate.create",
        "profit_settings.variable_expense.create",
        "profit_settings.defaults.update",
        "profit_settings.variable_expense.retract",
        "profit_settings.cargo_tariff.retract",
        "profit_settings.service_fee_estimate.retract",
    ]
    assert rows[0][1] == tariff["id"] and rows[1][1] == fee["id"] and rows[2][1] == expense["id"]
    assert [r[2]["revision"] for r in rows] == [1, 2, 3, 4, 5, 6, 7]
    dump = json.dumps([r[2] for r in rows])
    for amount in ("54.37", "12.34", "6.78", "3.21"):
        assert amount not in dump  # tutarlar denetim kaydına yazılmaz


def test_rejected_writes_are_not_audited(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    assert put_tariff(shop, carrier="").status_code == 422
    assert put_fee(shop, expected_revision=5).status_code == 409
    assert shop.api.delete(url(shop, f"/cargo-tariffs/{uuid4()}")).status_code == 404
    assert audit_rows(admin_conn, shop) == []


# --------------------------------------------------------------------------- roller ve kimlik
def test_viewer_can_read_but_not_write(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    tariff = put_tariff(shop).json()["tariff"]
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert shop.api.get(url(shop)).status_code == 200
    assert shop.api.get(url(shop, "/carriers")).status_code == 200
    denied = [
        put_tariff(shop),
        put_fee(shop),
        shop.api.post(url(shop, "/variable-expenses"), expense_body()),
        shop.api.put(url(shop, f"/variable-expenses/{uuid4()}"), expense_body()),
        shop.api.put(url(shop, "/defaults"), {"default_desi": "2"}),
        shop.api.delete(url(shop, f"/cargo-tariffs/{tariff['id']}")),
        shop.api.delete(url(shop, f"/service-fee-estimates/{uuid4()}")),
        shop.api.delete(url(shop, f"/variable-expenses/{uuid4()}")),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)
    assert all(r.json()["type"] == "urn:netkar:problem:forbidden" for r in denied)
    assert revision_in_db(admin_conn, shop) == 1  # viewer hiçbir şey değiştirmedi


def test_admin_role_can_write(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    admin_conn.execute("UPDATE memberships SET role = 'admin'")
    assert put_tariff(shop).status_code == 200


def test_authentication_and_csrf_are_required(shop: Shop, make_api: Callable[..., Api]) -> None:
    anon = make_api()
    assert anon.get(url(shop)).status_code == 401
    assert anon.get(url(shop, "/carriers")).status_code == 401
    assert anon.put(url(shop, "/defaults"), {"default_desi": "2"}).status_code == 401
    r = shop.api.put(url(shop, "/defaults"), {"default_desi": "2"}, csrf=False)
    assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:csrf-failed"
    r = shop.api.delete(url(shop, f"/cargo-tariffs/{uuid4()}"), csrf=False)
    assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:csrf-failed"


# --------------------------------------------------------------------------- IDOR / RLS
def test_other_tenant_gets_404_on_every_endpoint_and_nothing_leaks(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    tariff = put_tariff(a, carrier="GizliFirmaA").json()["tariff"]
    fee = put_fee(a, amount="77.77").json()["estimate"]
    expense = shop_expense = a.api.post(
        url(a, "/variable-expenses"), expense_body(name="GizliGiderA")
    ).json()["expense"]
    assert shop_expense is expense
    target = url(a)  # B oturumu, A'nın hesap kimliğiyle
    attempts = [
        b.api.get(target),
        b.api.get(f"{target}/carriers"),
        b.api.put(f"{target}/cargo-tariffs", tariff_body()),
        b.api.delete(f"{target}/cargo-tariffs/{tariff['id']}"),
        b.api.put(
            f"{target}/service-fee-estimates",
            {"valid_from": "2026-10-01", "amount": "1", "amount_includes_vat": True},
        ),
        b.api.delete(f"{target}/service-fee-estimates/{fee['id']}"),
        b.api.post(f"{target}/variable-expenses", expense_body()),
        b.api.put(f"{target}/variable-expenses/{expense['id']}", expense_body()),
        b.api.delete(f"{target}/variable-expenses/{expense['id']}"),
        b.api.put(f"{target}/defaults", {"default_desi": "9"}),
    ]
    assert [r.status_code for r in attempts] == [404] * len(attempts)
    assert all("GizliFirmaA" not in r.text and "77.77" not in r.text for r in attempts)
    # A'nın verisi bozulmadı
    body = read(a)
    assert body["revision"] == 3 and body["default_desi"] is None and len(body["cargo_tariffs"]) == 1
    # Olmayan hesap da 404
    ghost = f"/v1/marketplace-accounts/{uuid4()}/profit-settings"
    assert (
        b.api.get(ghost).status_code == 404
        and b.api.put(f"{ghost}/defaults", {"default_desi": "1"}).status_code == 404
    )
    # B kendi hesabında A'nın kayıt kimliğini silemez (kayıt hesapla kapsamlıdır)
    assert b.api.delete(url(b, f"/cargo-tariffs/{tariff['id']}")).status_code == 404
    assert b.api.delete(url(b, f"/variable-expenses/{expense['id']}")).status_code == 404
    assert b.api.put(url(b, f"/variable-expenses/{expense['id']}"), expense_body()).status_code == 404
    assert len(read(a)["cargo_tariffs"]) == 1 and len(read(a)["variable_expenses"]) == 1
    assert read(b)["revision"] == 0 and read(b)["cargo_tariffs"] == []  # B'nin hesabına hiçbir şey yazılmadı


# --------------------------------------------------------------------------- hız sınırı
def test_writes_are_rate_limited_per_tenant(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_write_tenant=2)
    assert put_tariff(shop).status_code == 200 and put_fee(shop).status_code == 200
    limited = shop.api.put(url(shop, "/defaults"), {"default_desi": "2"})
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert limited.json()["type"] == "urn:netkar:problem:rate-limited"
    assert shop.api.get(url(shop)).status_code == 200  # okuma sınırlanmaz


# --------------------------------------------------------------------------- firmalar
def seed_order(
    conn: psycopg.Connection[Any],
    shop: Shop,
    number: str,
    package: int,
    carrier: str | None,
    who_pays: int | None,
    status: str = "Delivered",
    lines: int = 1,
    ordered_at: datetime = datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
) -> None:
    order_id = uuid4()
    conn.execute(
        "INSERT INTO orders (id, tenant_id, marketplace_account_id, order_number, shipment_package_id, "
        "ordered_at, status, carrier, who_pays) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (order_id, shop.tenant_id, shop.account_id, number, package, ordered_at, status, carrier, who_pays),
    )
    for index in range(lines):
        conn.execute(
            "INSERT INTO order_lines (tenant_id, marketplace_account_id, order_id, line_id, barcode, quantity, "
            "line_gross_amount) VALUES (%s, %s, %s, %s, 'B1', 1, 100)",
            (shop.tenant_id, shop.account_id, order_id, package * 10 + index),
        )


def test_carriers_lists_recent_pairs_with_coverage(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    seed_order(admin_conn, shop, "1", 1, "Trendyol Express", None, lines=2)
    seed_order(admin_conn, shop, "2", 2, "Trendyol Express", None)
    seed_order(admin_conn, shop, "3", 3, "Aras Kargo", 1)  # satıcı anlaşmalı
    seed_order(admin_conn, shop, "4", 4, "Ornek Kargo", None)
    seed_order(admin_conn, shop, "5", 5, None, None)
    seed_order(admin_conn, shop, "6", 6, "Iptal Kargo", None, status="Cancelled")
    seed_order(admin_conn, shop, "7", 7, "Eski Kargo", None, ordered_at=datetime(2026, 7, 1, tzinfo=UTC))
    put_tariff(shop, carrier="Trendyol Express")
    put_tariff(shop, carrier="*", valid_from="2026-12-01")  # yedek henüz geçerli değil
    body = shop.api.get(url(shop, "/carriers")).json()
    assert body["lookback_days"] == 92
    assert body["items"] == [
        {"carrier": "", "agreement": "trendyol", "line_count": 1, "covered": False},
        {"carrier": "Aras Kargo", "agreement": "seller", "line_count": 1, "covered": False},
        {"carrier": "Ornek Kargo", "agreement": "trendyol", "line_count": 1, "covered": False},
        {"carrier": "Trendyol Express", "agreement": "trendyol", "line_count": 3, "covered": True},
    ]
    put_tariff(shop, carrier="*", valid_from="2026-01-01")
    covered = {
        (i["carrier"], i["agreement"]): i["covered"]
        for i in shop.api.get(url(shop, "/carriers")).json()["items"]
    }
    assert covered[("Ornek Kargo", "trendyol")] is True  # '*' yedeği bugün geçerli
    assert covered[("Aras Kargo", "seller")] is False  # satıcı tarifesi ayrı


# --------------------------------------------------------------------------- motora yansıma
@pytest.fixture
async def app_sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def engine_order(day: date, carrier: str = "Trendyol Express", deci: str | None = "2") -> EngineOrder:
    line = OrderLine(
        1,
        "B1",
        1,
        Decimal("100.00"),
        Decimal("20"),
        Decimal("10"),
        (OrderItem("i1", Decimal(0), Decimal(0)),),
    )
    return EngineOrder(
        "O1", 1, day, "Delivered", carrier, (line,), cargo_deci=None if deci is None else Decimal(deci)
    )


async def test_profit_settings_for_reads_the_database_and_converts_vat(
    shop: Shop, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        empty = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id)
    assert empty == ProfitSettings()  # kayıt yok: tanımsız (0 değil)
    put_tariff(shop, valid_from="2026-01-01")  # 54,00 ve 50,00 KDV dahil
    put_tariff(
        shop, valid_from="2026-10-10", price_includes_vat=False, brackets=[{"max_desi": "2", "price": "60"}]
    )
    put_fee(shop, valid_from="2026-01-01")  # 12,00 dahil
    put_fee(shop, valid_from="2026-10-10", amount="8", amount_includes_vat=False)
    shop.api.put(url(shop, "/defaults"), {"default_desi": "3"})
    shop.api.post(url(shop, "/variable-expenses"), expense_body(valid_to="2026-10-09"))
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        configured = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id)
        completeness = await ps.profit_settings_completeness(db, shop.tenant_id, shop.account_id, TODAY)
        flag = await ps.profit_settings_configured(db, shop.tenant_id, shop.account_id, TODAY)
    assert configured.default_desi == Decimal("3.00")
    assert completeness.cargo_tariff_defined and completeness.service_fee_estimate_defined and flag is True
    assert completeness.variable_expenses_defined is False  # tanımın bitişi geçmişte
    old = date(2026, 10, 5)
    assert configured.cargo_tariff.lookup("Trendyol Express", Decimal("2"), old) == Decimal(
        "45.00"
    )  # 54,00 -> 45,00
    assert configured.cargo_tariff.lookup("Trendyol Express", Decimal("5"), old) == Decimal(
        "41.67"
    )  # 50,00 -> 41,67
    assert configured.cargo_tariff.lookup("Trendyol Express", Decimal("2"), date(2026, 10, 15)) == Decimal(
        "60.00"
    )
    assert configured.service_fee_estimate_on(old) == Decimal("10.00")  # 12,00 -> 10,00
    assert configured.service_fee_estimate_on(date(2026, 10, 15)) == Decimal("8.00")
    assert [e.valid_to for e in configured.variable_expenses] == [date(2026, 10, 9)]


async def test_engine_picks_versions_by_order_day_from_database_settings(
    shop: Shop, app_sessions: async_sessionmaker[AsyncSession]
) -> None:
    put_tariff(
        shop, valid_from="2026-01-01", price_includes_vat=False, brackets=[{"max_desi": "2", "price": "42"}]
    )
    put_tariff(
        shop, valid_from="2026-10-10", price_includes_vat=False, brackets=[{"max_desi": "2", "price": "45"}]
    )
    put_fee(shop, valid_from="2026-01-01", amount="8", amount_includes_vat=False)
    put_fee(shop, valid_from="2026-10-10", amount="10", amount_includes_vat=False)
    async with tenant_transaction(app_sessions, shop.tenant_id) as db:
        settings = await ps.profit_settings_for(db, shop.tenant_id, shop.account_id)
    early = calculate_profit(ProfitInput(orders=(engine_order(date(2026, 10, 5)),), settings=settings)).lines[
        0
    ]
    late = calculate_profit(ProfitInput(orders=(engine_order(date(2026, 10, 15)),), settings=settings)).lines[
        0
    ]
    assert (early.items.shipping_outbound, early.items.platform_service_fee) == (
        Decimal("42.00"),
        Decimal("8.00"),
    )
    assert (late.items.shipping_outbound, late.items.platform_service_fee) == (
        Decimal("45.00"),
        Decimal("10.00"),
    )
    # tarife başlamadan önceki sipariş: eksik (0 değil)
    before = calculate_profit(
        ProfitInput(orders=(engine_order(date(2025, 12, 31)),), settings=settings)
    ).lines[0]
    assert [i.value for i in before.missing_items] == [
        "urun_maliyeti",
        "kargo_gonderi",
        "platform_hizmet_bedeli",
    ]


def test_fifty_brackets_fit_the_body_limit_and_oversized_bodies_are_rejected(shop: Shop) -> None:
    full = [{"max_desi": f"{i + 1}.00", "price": "99999.99"} for i in range(ps.MAX_BRACKETS)]
    ok = put_tariff(shop, brackets=full)
    assert ok.status_code == 200 and len(ok.json()["tariff"]["brackets"]) == ps.MAX_BRACKETS
    big = put_tariff(shop, carrier="x" * 20_000)
    assert big.status_code == 413  # /v1/marketplace-accounts gövde sınırı (8 KiB) bu uçlara da uygulanır


def test_service_fee_with_same_start_is_replaced_not_duplicated(shop: Shop) -> None:
    first = put_fee(shop, amount="12.00").json()
    again = put_fee(shop, amount="18.00", amount_includes_vat=False).json()
    assert (first["created"], again["created"]) == (True, False)
    assert again["estimate"]["id"] != first["estimate"]["id"] and again["revision"] == 2
    assert again["replaced_id"] == first["estimate"]["id"]
    estimates = read(shop)["service_fee_estimates"]
    assert (
        len(estimates) == 1
        and estimates[0]["amount"] == "18.00"
        and estimates[0]["amount_excl_vat"] == "18.00"
    )


def test_json_numbers_are_read_as_exact_decimals_and_bad_numbers_are_rejected(shop: Shop) -> None:
    ok = put_fee(shop, amount=12.5)  # JSON sayısı: en kısa gösterimiyle Decimal("12.5")
    assert ok.status_code == 200 and ok.json()["estimate"]["amount"] == "12.50"
    bracket = put_tariff(shop, brackets=[{"max_desi": 2.5, "price": 54}])
    assert bracket.status_code == 200 and bracket.json()["tariff"]["brackets"][0]["max_desi"] == "2.50"
    for bad in (True, "1e3", "1,5", [1], {"a": 1}):
        r = put_fee(shop, amount=bad)
        assert r.status_code == 422, bad
    non_finite = shop.api.put(
        url(shop, "/service-fee-estimates"),
        None,
        content=b'{"valid_from": "2026-10-01", "amount": Infinity, "amount_includes_vat": true}',
        headers={"content-type": "application/json"},
    )
    assert non_finite.status_code == 422


def test_summary_is_recomputed_with_the_new_settings(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    """ADR-0006 kabul ölçütü: ayar yazımından sonraki özet yeni ayarla hesaplanır (K37: eksik kalem kalkar)."""
    seed_basic(admin_conn, shop)
    period = {"start": "2026-10-01", "end": "2026-10-31"}

    def summary() -> dict[str, Any]:
        response = shop.api.get(f"{shop.base}/profit/summary", params=period)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    before = summary()
    assert before["settings_configured"] is False and before["totals"]["net_kar_kismi"] is True
    assert before["tariff_missing_line_count"] == 3
    assert before["totals"]["eksik_kalem_satir_sayilari"] == {
        "urun_maliyeti": 1,
        "kargo_gonderi": 3,
        "platform_hizmet_bedeli": 3,
    }
    assert (
        put_tariff(shop, valid_from="2026-01-01", brackets=[{"max_desi": "2", "price": "54"}]).status_code
        == 200
    )
    assert put_fee(shop, valid_from="2026-01-01", amount="12").status_code == 200
    after = summary()
    assert after["settings_configured"] is True and after["tariff_missing_line_count"] == 0
    assert (
        after["completeness"]["cargo_tariff_defined"]
        and after["completeness"]["service_fee_estimate_defined"]
    )
    assert after["totals"]["eksik_kalem_satir_sayilari"] == {
        "urun_maliyeti": 1,
        "kargo_gonderi": 0,
        "platform_hizmet_bedeli": 0,
    }
    # 1001: 100,00 net satış - 50,00 maliyet - 10,00 komisyon - 45,00 kargo (54,00 dahil) - 10,00 hizmet (12,00 dahil)
    order = shop.api.get(f"{shop.base}/profit/orders/1001", params=period).json()
    line = order["lines"][0]
    assert line["kalemler"]["net_kar"] == "-15.00" and line["eksik_kalemler"] == []
    assert (
        line["kalemler"]["kargo_gonderi"] == "45.00" and line["kalemler"]["platform_hizmet_bedeli"] == "10.00"
    )
    assert after["totals"]["net_kar_kismi"] is True  # 1002 maliyetsiz: dönem hâlâ kısmi, marj null
    assert after["totals"]["net_kar_marji_yuzde"] is None
    assert after["totals"]["tam_satirlar"]["satir_sayisi"] == 2


def test_viewer_sees_completeness_in_the_summary(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    put_fee(shop, valid_from="2026-01-01")
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    body = shop.api.get(
        f"{shop.base}/profit/summary", params={"start": "2026-10-01", "end": "2026-10-31"}
    ).json()
    assert body["completeness"]["service_fee_estimate_defined"] is True
    assert body["settings_configured"] is False  # kargo tarifesi yok
