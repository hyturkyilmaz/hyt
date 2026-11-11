"""Sipariş kârlılık listesi (`GET /v1/marketplace-accounts/{id}/profit/orders`): gerçek PostgreSQL, RLS.

`tests/test_report_api.py` desenini izler: IDOR, imleç bütünlüğü, süzgeç, arama, sıralama (null'lı zarar dahil),
sayfa sınırı, iptal siparişin null'ı, kişisel veri yokluğu, oran sınırı, ReportGate ve altın senaryolarla
tutarlılık (liste toplamı = özet dönem rakamı, aynı motor sonucu). Takvime bağlı test yoktur (İstanbul bugünü
`fixed_today` ile sabit; tarihler dönem içinde sabit yazılmıştır).
"""

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from app.api.v1 import profit as profit_module
from app.db.session import create_engine
from app.profit import ProfitSettings, calculate_profit
from app.profit.schema_v1 import parse_input, parse_settings, render_result
from app.services import profit_report
from app.services import profit_views as views
from app.services.profit_settings import LoadedSettings
from app.services.profit_settings import load_profit_settings as real_load_settings
from app.services.sync.runner import SyncRunner
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, add_product, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import (
    B1,
    B2,
    B3,
    END,
    START,
    add_cost,
    add_order,
    money_strings,
    seed_basic,
    seller_of,
)
from tests.sync_helpers import client_factory, envelope_for_tests
from tests.test_denetim_s4_kapanis import BlockedEngine
from tests.test_feed_golden_database import (
    NOW,
    add_user_data,
    add_user_settings,
    fake_api_from,
    scenario_param,
)
from tests.test_profit_golden import GOLDEN_FILES
from tests.test_report_api import FORBIDDEN_KEY_PARTS, all_keys
from tests.test_report_units import all_results, golden_result

pytestmark = pytest.mark.usefixtures("fixed_today")  # İstanbul bugünü 2026-11-08
D = Decimal
PERIOD = {"start": START, "end": END}
ORDERS_PATH = "orders"


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]) -> Shop:
    created = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=100_000)
    seed_basic(admin_conn, created)
    return created


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]) -> tuple[Shop, Shop]:
    a, b = make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")
    seed_basic(admin_conn, a)
    return a, b


def call(shop: Shop, path: str = ORDERS_PATH, **params: Any) -> Any:
    return shop.api.get(f"{shop.base}/profit/{path}", params={**PERIOD, **params})


def numbers(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [i["order_number"] for i in response.json()["items"]]


def add_more_orders(conn: psycopg.Connection[Any], shop: Shop) -> None:
    """seed_basic'e ek: 2001 (3 ürünlü, 12 Ekim), 2002 (maliyetsiz kesin zarar değil), 2003 (derin zarar, 13 Ekim)."""
    seller = seller_of(shop)
    add_order(
        conn, seller, "2001", 21, datetime(2026, 10, 12, 9, tzinfo=UTC),
        lines=[
            {"line_id": 21, "barcode": B1, "gross": "120.00"},
            {"line_id": 22, "barcode": B2, "gross": "60.00"},
            {"line_id": 23, "barcode": B3, "gross": "60.00"},
        ],
    )  # fmt: skip
    add_cost(conn, shop, B3, "500.00")  # B3 maliyeti satış fiyatından çok büyük: derin zarar
    add_order(
        conn, seller, "2003", 23, datetime(2026, 10, 13, 9, tzinfo=UTC),
        lines=[{"line_id": 24, "barcode": B3, "gross": "60.00"}],
    )  # fmt: skip


# --- biçim, iptal, kişisel veri ----------------------------------------------------------------------------


def test_list_shape_defaults_and_cancelled_order_has_null_amounts_not_zero(shop: Shop) -> None:
    r = call(shop)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    body = r.json()
    assert body["period"] == {"start": START, "end": END, "days": 31}
    assert (body["sort"], body["order"], body["filter"], body["q"], body["total_count"]) == (
        "date", "desc", "all", None, 4,
    )  # fmt: skip
    assert body["settings_revision"] == 0 and body["next_cursor"] is None
    assert numbers(r) == ["1004", "1003", "1002", "1001"]  # yeni önce
    by = {i["order_number"]: i for i in body["items"]}
    cancelled = by["1004"]
    assert cancelled["cancelled"] is True and cancelled["certainty"] == "iptal"
    # B-02: iptal siparişte "0.00" yok; tutarlar null.
    assert cancelled["net_profit"] is None and cancelled["net_sales_excl_vat"] is None
    assert cancelled["known_expenses_profit"] is None and cancelled["loss_reason"] is None
    assert (cancelled["line_count"], cancelled["cancelled_line_count"]) == (0, 1)
    assert cancelled["status_counts"] == {"estimated": 0, "settled": 0, "adjusted": 0, "cancelled": 1}
    assert not cancelled["awaiting_payout"] and not cancelled["unexpected_deduction"]
    assert cancelled["ordered_on"] == "2026-10-08"
    # Ayarsız hesapta kargo ve hizmet bedeli eksik: net kâr null ("hesaplanamadı"), iptal DEĞİL.
    waiting = by["1001"]
    assert waiting["cancelled"] is False and waiting["net_profit"] is None and waiting["certainty"] == "eksik"
    assert waiting["net_sales_excl_vat"] == "100.00" and waiting["known_expenses_profit"] == "40.00"
    assert waiting["missing_items"] == ["kargo_gonderi", "platform_hizmet_bedeli"]
    assert waiting["awaiting_payout"] is True and by["1002"]["awaiting_payout"] is False
    assert (
        waiting["products"] == [{"barcode": B1, "title": "Ürün Bir"}] and waiting["more_product_count"] == 0
    )
    assert by["1002"]["cost_missing"] is True and waiting["cost_missing"] is False
    assert by["1003"]["loss_reason"] == "known_expenses" and by["1001"]["loss_reason"] is None


def test_every_money_field_is_a_two_decimal_string_never_a_float(shop: Shop) -> None:
    import re

    money = re.compile(r"-?[0-9]+\.[0-9]{2}")
    for path, value in money_strings(call(shop).json()):
        if (
            path.split(".")[-1] in {"net_profit", "net_sales_excl_vat", "known_expenses_profit"}
            and value is not None
        ):
            assert isinstance(value, str) and money.fullmatch(value), (path, value)


def test_a_three_product_order_shows_the_first_two_names_and_a_remainder_count(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_more_orders(admin_conn, shop)
    item = next(i for i in call(shop, q="2001").json()["items"])
    assert [p["barcode"] for p in item["products"]] == [B1, B2]  # satır sırası, en fazla 2
    assert [p["title"] for p in item["products"]] == ["Ürün Bir", "Ürün İki"]
    assert item["more_product_count"] == 1 and item["line_count"] == 3
    # Katalogda başlığı olmayan ürün: title null (adı uydurulmaz).
    other = call(shop, q="2003").json()["items"][0]
    assert other["products"] == [{"barcode": B3, "title": None}]


async def test_response_never_carries_customer_data_even_with_a_pii_laden_sync(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    from app.profit.schema_v1 import ISTANBUL
    from tests.test_sync_pii import pii_api
    from tests.trendyol_helpers import PII_SENTINELS

    shop = make_shop("a@example.com", "Mağaza A")
    engine = create_engine(database.worker_url.render_as_string(hide_password=False))
    try:
        outcome = await SyncRunner(
            engine,
            client_factory(pii_api()),
            envelope_for_tests(),
            now=lambda: datetime(2026, 11, 1, 12, tzinfo=UTC),
        ).run(shop.account_id, "backfill")
    finally:
        await engine.dispose()
    assert outcome.status == "completed", outcome.summary()
    rows = admin_conn.execute(
        "SELECT ordered_at FROM orders WHERE marketplace_account_id = %s ORDER BY ordered_at",
        (shop.account_id,),
    ).fetchall()
    day = rows[0][0].astimezone(ISTANBUL).date()
    wide = {"start": str(day.replace(day=1)), "end": str(day.replace(day=28))}
    r = shop.api.get(f"{shop.base}/profit/orders", params=wide)
    assert r.status_code == 200 and r.json()["total_count"] >= 1
    assert not {k for k in all_keys(r.json()) if any(p in k.lower() for p in FORBIDDEN_KEY_PARTS)}
    assert [s for s in PII_SENTINELS if s in r.text] == []
    assert "İstanbul" not in r.text  # il adı bile yok


def test_item_keys_are_exactly_the_documented_contract(shop: Shop) -> None:
    keys = set(call(shop).json()["items"][0])
    assert keys == {
        "order_number", "ordered_on", "cancelled", "line_count", "cancelled_line_count", "products",
        "more_product_count", "net_sales_excl_vat", "net_profit", "known_expenses_profit", "certainty",
        "missing_items", "cost_missing", "loss_reason", "awaiting_payout", "unexpected_deduction",
        "status_counts",
    }  # fmt: skip


# --- süzgeçler ve arama ------------------------------------------------------------------------------------


def test_filters_loss_awaiting_payout_unexpected_deduction_and_all(shop: Shop) -> None:
    assert numbers(call(shop, filter="all")) == ["1004", "1003", "1002", "1001"]
    loss = call(shop, filter="loss")
    assert numbers(loss) == ["1003"] and loss.json()["total_count"] == 1
    assert loss.json()["filter"] == "loss"
    assert numbers(call(shop, filter="awaiting_payout")) == ["1001"]  # iptal ve ekstreliler girmez
    assert numbers(call(shop, filter="unexpected_deduction")) == []  # tohum veride kesinti farkı yok
    assert call(shop, filter="nonsense").status_code == 422


def test_search_is_an_exact_order_number_match_and_composes_with_filters(shop: Shop) -> None:
    r = call(shop, q="1002")
    assert numbers(r) == ["1002"] and r.json()["q"] == "1002" and r.json()["total_count"] == 1
    assert numbers(call(shop, q="100")) == []  # kısmi eşleşme yok
    assert numbers(call(shop, q="10022")) == []
    assert (
        call(shop, q="100").json()["total_count"] == 0 and call(shop, q="100").json()["next_cursor"] is None
    )
    assert numbers(call(shop, q="1001", filter="loss")) == []  # arama süzgeçle birlikte daralır
    assert numbers(call(shop, q="1003", filter="loss")) == ["1003"]
    assert numbers(call(shop, q="1004")) == ["1004"]  # iptal sipariş de aranabilir


@pytest.mark.parametrize("q", ["a b", ".x", "x" * 65, "1;2", "", "%"])
def test_search_value_is_validated(shop: Shop, q: str) -> None:
    assert call(shop, q=q).status_code == 422


# --- sıralama ---------------------------------------------------------------------------------------------------


def test_date_sort_both_directions_with_order_number_as_stable_tiebreak(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = seller_of(shop)
    for number, package in (("3003", 33), ("3001", 31), ("3002", 32)):  # aynı an: sipariş no artan ayırır
        add_order(admin_conn, seller, number, package, datetime(2026, 10, 20, 9, tzinfo=UTC),
                  lines=[{"line_id": package, "barcode": B1}])  # fmt: skip
    assert numbers(call(shop, sort="date", order="desc")) == [
        "3001", "3002", "3003", "1004", "1003", "1002", "1001",
    ]  # fmt: skip
    assert numbers(call(shop, sort="date", order="asc")) == [
        "1001", "1002", "1003", "1004", "3001", "3002", "3003",
    ]  # fmt: skip


def test_net_profit_sort_puts_known_losses_first_and_unknown_last_in_both_directions(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_more_orders(admin_conn, shop)
    # Ayarsız hesap: net kâr her yerde null. Maliyeti satış fiyatından büyük B3'lü siparişler (2001, 2003) ve 1003
    # kesin zarardır (AD-04): bilinen değerle sıralanır; kârı pozitif belirsizler (1001, 1002) ve iptal (1004)
    # sonda, sipariş no artan.
    asc = numbers(call(shop, sort="net_profit", order="asc"))
    desc = numbers(call(shop, sort="net_profit", order="desc"))
    known = call(shop, filter="loss").json()["items"]
    losses = {i["order_number"]: D(i["known_expenses_profit"]) for i in known}
    assert set(losses) == {"1003", "2001", "2003"} and all(v < 0 for v in losses.values())
    assert all(i["net_profit"] is None and i["loss_reason"] is not None for i in known)
    worst_first = sorted(losses, key=lambda n: (losses[n], n))
    assert asc[:3] == worst_first  # en büyük zarar önce (net_profit asc)
    assert desc[:3] == sorted(losses, key=lambda n: (-losses[n], n))
    unknown = ["1001", "1002", "1004"]
    assert asc[3:] == unknown and desc[3:] == unknown  # belirsizler her yönde sonda, kararlı
    assert numbers(call(shop, filter="loss", sort="net_profit", order="asc")) == worst_first


def test_net_profit_sort_with_computed_values_and_loss_filter(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Ayar tanımlıyken net kâr sayıdır: sıralama sayıya göre; zarar süzgecinde en büyük zarar önce."""
    add_more_orders(admin_conn, shop)
    settings = {
        "kargo_tarifesi": {"*": [["10", "10.00"]]},
        "platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric": "2.00",
        "varsayilan_desi": "2",
    }
    add_user_settings(admin_conn, shop.tenant_id, shop.account_id, shop.user_id, settings)
    add_cost(admin_conn, shop, B2, "10.00")  # 1002 de hesaplanabilir olsun
    body = call(shop, sort="net_profit", order="desc").json()
    values = [(i["order_number"], i["net_profit"]) for i in body["items"]]
    computed = [(n, D(v)) for n, v in values if v is not None]
    assert len(computed) >= 3 and [v for _, v in computed] == sorted((v for _, v in computed), reverse=True)
    # null net kârlılar (iptal) sonda
    assert values[-1] == ("1004", None)
    losses = call(shop, filter="loss", sort="net_profit", order="asc").json()["items"]
    assert [i["net_profit"] for i in losses] == sorted((i["net_profit"] for i in losses), key=D)
    assert all(D(i["net_profit"]) < 0 and i["loss_reason"] == "net_profit" for i in losses)
    assert "2003" in [i["order_number"] for i in losses]
    # İptal "0.00" olarak sayıya karışmaz
    assert next(i for i in body["items"] if i["order_number"] == "1004")["net_profit"] is None


# --- sayfalama ve imleç -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sort", "order", "extra"),
    [
        ("date", "desc", {}),
        ("date", "asc", {}),
        ("net_profit", "asc", {}),
        ("net_profit", "desc", {"filter": "all"}),
        ("net_profit", "asc", {"filter": "loss"}),
    ],
)
def test_cursor_paging_walks_the_full_list_once_in_the_same_order(
    shop: Shop, admin_conn: psycopg.Connection[Any], sort: str, order: str, extra: dict[str, str]
) -> None:
    add_more_orders(admin_conn, shop)
    for i in range(6):  # aynı değerler ve aynı anlar tekrar eder
        add_order(admin_conn, seller_of(shop), f"pg{i}", 800 + i, datetime(2026, 10, 16, 9, tzinfo=UTC),
                  lines=[{"line_id": 800 + i, "barcode": B1, "gross": str(60 + 10 * (i % 2))}])  # fmt: skip
    whole = call(shop, sort=sort, order=order, limit=200, **extra).json()
    assert whole["next_cursor"] is None
    expected = [i["order_number"] for i in whole["items"]]
    assert len(expected) == whole["total_count"] >= 2
    walked: list[str] = []
    cursor = None
    for _ in range(20):
        page = call(
            shop, sort=sort, order=order, limit=3, **extra, **({"cursor": cursor} if cursor else {})
        ).json()
        assert len(page["items"]) <= 3 and page["total_count"] == whole["total_count"]
        walked += [i["order_number"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == expected and len(set(walked)) == len(expected)


def test_page_size_bounds_and_next_cursor_presence(shop: Shop) -> None:
    assert call(shop, limit=0).status_code == 422 and call(shop, limit=201).status_code == 422
    assert call(shop, limit="x").status_code == 422
    one = call(shop, limit=1).json()
    assert len(one["items"]) == 1 and one["next_cursor"] and one["total_count"] == 4
    exact = call(shop, limit=4).json()  # tam sığıyor: devam yok
    assert len(exact["items"]) == 4 and exact["next_cursor"] is None
    assert len(call(shop, limit=200).json()["items"]) == 4
    assert len(call(shop).json()["items"]) == 4  # varsayılan 50


def test_cursor_from_another_query_garbage_or_the_products_list_is_a_422(shop: Shop) -> None:
    cursor = call(shop, limit=1).json()["next_cursor"]
    assert cursor
    for params in (
        {"sort": "net_profit"}, {"order": "asc"}, {"filter": "loss"}, {"q": "1001"}, {"end": "2026-10-30"},
        {"start": "2026-10-02"},
    ):  # fmt: skip
        r = call(shop, limit=1, cursor=cursor, **params)
        assert r.status_code == 422, params
        assert {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]
    assert call(shop, cursor="bozuk-imlec").status_code == 422
    assert call(shop, cursor="A" * 401).status_code == 422
    # Ürün listesinin imleci sipariş listesinde, siparişinki ürün listesinde geçmez (parmak izi ayrı).
    product_cursor = call(shop, "products", limit=1).json()["next_cursor"]
    assert product_cursor and call(shop, cursor=product_cursor).status_code == 422
    assert call(shop, "products", limit=1, cursor=cursor).status_code == 422
    assert call(shop, limit=1, cursor=cursor).status_code == 200  # aynı sorguda geçerli


def test_tampered_cursor_is_a_422_and_does_not_run_the_engine(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    cursor = call(shop, limit=1).json()["next_cursor"]
    flipped = cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]
    for bad in (flipped, cursor[:-4], cursor + "AAAA"):
        r = call(shop, cursor=bad)
        assert r.status_code == 422 and {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]
    calls: list[int] = []
    real = calculate_profit

    def counting(profit_input: Any) -> Any:
        calls.append(1)
        return real(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", counting)
    assert call(shop, cursor=flipped).status_code == 422
    assert calls == []  # imleç motordan ÖNCE doğrulanır


def test_cursor_of_another_tenant_or_account_is_a_422(
    two_shops: tuple[Shop, Shop], make_shop: Callable[..., Shop]
) -> None:
    a, b = two_shops
    cursor = call(a, limit=1).json()["next_cursor"]
    assert cursor
    seed = {"order_number": "1001"}  # b'nin kendi verisi yok; yine de imleç b'de çözülemez
    del seed
    r = call(b, limit=1, cursor=cursor)
    assert r.status_code == 422 and {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]


def test_cursor_with_the_right_fingerprint_but_forged_contents_is_still_a_422(shop: Shop) -> None:
    codec = views.CursorCodec(shop.api.client.app.state.settings.master_key, shop.tenant_id, shop.account_id)  # type: ignore[attr-defined]
    fingerprint = f"orders|date|desc|all||{START}|{END}"
    for parts in (
        ["0", "NaN", "1001"],
        ["0", "abc", "1001"],
        ["2", "", "1001"],
        ["0", "1"],
        ["1", "", "x", "y"],
    ):
        r = call(shop, cursor=codec.encode(fingerprint, parts))
        assert r.status_code == 422, parts
        assert {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]


# --- dönem ---------------------------------------------------------------------------------------------------------


def test_period_rules_match_the_other_report_endpoints(shop: Shop) -> None:
    r = shop.api.get(f"{shop.base}/profit/orders", params={"range": "30d"})
    assert r.status_code == 200 and r.json()["period"]["days"] == 30
    assert shop.api.get(f"{shop.base}/profit/orders").json()["period"]["days"] == 30  # varsayılan 30 gün
    assert (
        shop.api.get(
            f"{shop.base}/profit/orders", params={"start": "2026-01-01", "end": "2026-04-02"}
        ).status_code
        == 200
    )
    long = shop.api.get(f"{shop.base}/profit/orders", params={"start": "2026-01-01", "end": "2026-04-03"})
    assert long.status_code == 422 and {"field": "end", "code": "period_too_long"} in long.json()["errors"]
    assert shop.api.get(f"{shop.base}/profit/orders", params={"start": "2026-01-01"}).status_code == 422
    assert (
        shop.api.get(f"{shop.base}/profit/orders", params={"range": "7d", "start": START}).status_code == 422
    )
    assert numbers(call(shop, start="2026-10-06", end="2026-10-06")) == ["1002"]  # dönem dışı sipariş yok


# --- yetki, IDOR, roller, sınır ---------------------------------------------------------------------------------


def test_unauthenticated_request_is_401(shop: Shop, make_api: Callable[..., Api]) -> None:
    r = make_api().get(f"{shop.base}/profit/orders", params=PERIOD)
    assert r.status_code == 401 and r.headers["content-type"] == "application/problem+json"


def test_other_tenants_account_is_404_and_leaks_nothing(two_shops: tuple[Shop, Shop]) -> None:
    a, b = two_shops
    r = b.api.get(f"{a.base}/profit/orders", params=PERIOD)
    assert r.status_code == 404 and r.json()["type"] == "urn:netkar:problem:not-found"
    assert "1001" not in r.text and "Ürün" not in r.text
    assert numbers(a.api.get(f"{a.base}/profit/orders", params=PERIOD)) == ["1004", "1003", "1002", "1001"]
    missing = b.api.get(f"/v1/marketplace-accounts/{uuid4()}/profit/orders", params=PERIOD)
    assert missing.status_code == 404
    assert (missing.json()["type"], missing.json()["title"]) == (r.json()["type"], r.json()["title"])
    # Arama ve imleç yabancı hesapta da 404 (önce hesap sahipliği)
    assert b.api.get(f"{a.base}/profit/orders", params={**PERIOD, "q": "1001"}).status_code == 404


def test_each_tenant_sees_only_its_own_orders(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    add_product(admin_conn, b, B1, "B'nin ürünü")
    add_order(admin_conn, seller_of(b), "9001", 90, datetime(2026, 10, 5, 9, tzinfo=UTC),
              lines=[{"line_id": 90, "barcode": B1}])  # fmt: skip
    assert (
        numbers(call(b)) == ["9001"] and call(b).json()["items"][0]["products"][0]["title"] == "B'nin ürünü"
    )
    assert "9001" not in numbers(call(a))
    assert numbers(call(b, q="1001")) == [] and numbers(call(a, q="9001")) == []  # arama kiracıyı aşmaz


def test_viewer_can_read_the_list(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert call(shop).status_code == 200


def test_rate_limit_is_per_tenant_per_minute_and_shared_with_the_other_report_endpoints(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    a = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=3)
    b = make_shop("b@example.com", "Mağaza B", seller_id="9999", rate_limit_profit_report_tenant=3)
    assert call(a, "summary").status_code == 200  # tek kova: özet + sipariş listesi
    assert call(a).status_code == 200 and call(a).status_code == 200
    r = call(a)
    assert r.status_code == 429 and r.headers["content-type"] == "application/problem+json"
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert call(a, "summary").status_code == 429
    assert call(b).status_code == 200  # başka kiracının kovası ayrı
    # Doğrulama hatası (422) ve yabancı hesap (404) kovayı tüketmez.
    assert b.api.get(f"{b.base}/profit/orders", params={"q": "a b"}).status_code == 422
    assert a.api.get(f"/v1/marketplace-accounts/{uuid4()}/profit/orders", params=PERIOD).status_code == 404


def test_one_request_runs_the_engine_exactly_once_and_a_second_page_is_a_new_run(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    real = calculate_profit

    def counting(profit_input: Any) -> Any:
        calls.append(len(profit_input.orders))
        return real(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", counting)
    cursor = call(shop, limit=1).json()["next_cursor"]
    assert len(calls) == 1
    call(shop, limit=1, cursor=cursor)
    assert len(calls) == 2


def test_inconsistent_records_are_a_500_problem_without_internal_detail(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.profit import ProfitInputError

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise ProfitInputError("sipariş 1003 tutarsız: 12345.67")

    monkeypatch.setattr(profit_module, "period_profit", boom)
    r = call(shop)
    assert r.status_code == 500 and r.json()["type"] == "urn:netkar:problem:profit-calculation-failed"
    assert "1003" not in r.text and "12345" not in r.text


def test_report_gate_tenant_slot_full_is_429_and_process_full_is_503(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    frozen_ratelimit_clock: float,
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", rate_limit_profit_report_tenant=10_000,
        profit_report_tenant_concurrency=1, profit_report_process_concurrency=5,
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    first: list[Any] = []
    t = threading.Thread(target=lambda: first.append(call(shop)))
    t.start()
    try:
        assert engine.started.wait(15)
        second = call(shop)  # motor hâlâ bekliyor: kapı beklemez, hemen reddeder
        assert second.status_code == 429 and second.json()["type"].endswith("report-in-progress")
        assert int(second.headers["retry-after"]) >= 1
        assert second.headers["content-type"].startswith("application/problem+json")
    finally:
        engine.release.set()
        t.join()
    assert first[0].status_code == 200 and engine.calls == 1
    assert call(shop).status_code == 200  # yuva geri verildi


def test_report_gate_process_slots_full_is_503(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", rate_limit_profit_report_tenant=10_000,
        profit_report_tenant_concurrency=5, profit_report_process_concurrency=1,
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    first: list[Any] = []
    t = threading.Thread(target=lambda: first.append(call(shop)))
    t.start()
    try:
        assert engine.started.wait(15)
        second = call(shop)
        assert second.status_code == 503 and second.json()["type"].endswith("report-busy")
        assert int(second.headers["retry-after"]) >= 1
    finally:
        engine.release.set()
        t.join()
    assert first[0].status_code == 200 and engine.calls == 1


def test_openapi_documents_the_endpoint_and_its_schemas(shop: Shop) -> None:
    spec = shop.api.get("/v1/openapi.json").json()
    operation = spec["paths"]["/v1/marketplace-accounts/{account_id}/profit/orders"]["get"]
    assert operation["tags"] == ["profit"] and "200" in operation["responses"]
    params = {p["name"] for p in operation["parameters"]}
    assert {"start", "end", "range", "sort", "order", "filter", "q", "limit", "cursor"} <= params
    schemas = spec["components"]["schemas"]
    for name in ("OrderListOut", "OrderListItemOut", "OrderProductOut"):
        assert name in schemas, name
    assert (
        schemas["OrderListItemOut"]["properties"]["net_profit"]["anyOf"][0]["type"] == "string"
    )  # para dizge
    # Mevcut sipariş detay ucu yolu bozulmadı
    assert "/v1/marketplace-accounts/{account_id}/profit/orders/{order_number}" in spec["paths"]


# --- altın senaryolarla tutarlılık -----------------------------------------------------------------------------------


@pytest.fixture
async def worker_engine(database: DatabaseInfo) -> AsyncIterator[Any]:
    engine = create_engine(database.worker_url.render_as_string(hide_password=False))
    yield engine
    await engine.dispose()


@pytest.fixture
def scenario(path: Path) -> dict[str, Any]:
    """Parametreli senaryo dosyasını okur (senkron: async testte blokajlı dosya okuması olmasın)."""
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


GOLDEN_IDS = ("G11", "G27", "G29", "G31", "G32", "G38", "G44", "G46")


@pytest.mark.parametrize("path", [scenario_param(p) for p in GOLDEN_FILES if p.stem[:3] in GOLDEN_IDS])
async def test_golden_order_list_agrees_with_the_summary_and_the_engine_output(
    scenario: dict[str, Any],
    make_api: Callable[..., Api],
    admin_conn: psycopg.Connection[Any],
    worker_engine: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    girdi = scenario["girdi"]
    shop: Shop = make_shop_factory(make_api, admin_conn)(
        "a@example.com", "Mağaza A", rate_limit_profit_report_tenant=100_000
    )
    outcome = await SyncRunner(
        worker_engine, client_factory(fake_api_from(girdi)), envelope_for_tests(), now=lambda: NOW
    ).run(shop.account_id, "backfill")
    assert outcome.status == "completed", outcome.summary()
    add_user_data(admin_conn, shop.tenant_id, shop.account_id, shop.user_id, girdi)
    add_user_settings(admin_conn, shop.tenant_id, shop.account_id, shop.user_id, girdi.get("ayarlar", {}))
    golden = parse_settings(girdi.get("ayarlar", {}))

    async def settings_from_database(db: Any, tenant_id: UUID, account_id: UUID) -> LoadedSettings:
        loaded = await real_load_settings(db, tenant_id, account_id)
        stored: ProfitSettings = loaded.settings
        merged = dataclasses.replace(
            stored,
            commission_includes_vat=golden.commission_includes_vat,
            commission_vat_rate=golden.commission_vat_rate,
            shipping_vat_rate=golden.shipping_vat_rate,
            service_fee_vat_rate=golden.service_fee_vat_rate,
            ad_vat_rate=golden.ad_vat_rate,
            withholding_rate=golden.withholding_rate,
            cargo_invoice_vat_tolerance=golden.cargo_invoice_vat_tolerance,
            thresholds=golden.thresholds,
        )
        return LoadedSettings(merged, loaded.revision, loaded.bundle)

    monkeypatch.setattr(profit_module, "load_profit_settings", settings_from_database)
    direct = render_result(calculate_profit(parse_input(girdi)))
    period = {"start": "2026-10-01", "end": "2026-10-31"}

    def get(suffix: str, **params: Any) -> Any:
        r = shop.api.get(f"{shop.base}/profit/{suffix}", params={**period, **params})
        assert r.status_code == 200, (suffix, r.text)
        return r.json()

    summary = get("summary")
    listing = get("orders", limit=200)
    items = listing["items"]
    assert listing["next_cursor"] is None and listing["total_count"] == len(items)
    assert listing["settings_revision"] == summary["settings_revision"]

    wire_lines = direct["siparis_satirlari"]
    all_numbers = {ln["orderNumber"] for ln in wire_lines}
    assert {i["order_number"] for i in items} == all_numbers  # iptal siparişler dahil, eksiksiz
    active = [ln for ln in wire_lines if ln["durum"] != "cancelled"]
    active_numbers = {ln["orderNumber"] for ln in active}
    live = [i for i in items if not i["cancelled"]]
    assert {i["order_number"] for i in live} == active_numbers
    assert {i["order_number"] for i in items if i["cancelled"]} == all_numbers - active_numbers

    # Liste toplamı = özet dönem rakamı (aynı dönem, aynı motor sonucu).
    totals = summary["totals"]
    assert len(live) == totals["siparis_sayisi"]
    assert sum(i["line_count"] for i in live) == totals["satir_sayisi"]
    assert sum((D(i["net_sales_excl_vat"]) for i in live), D(0)) == D(totals["net_satis_kdv_haric"])
    # Dönem düzeyi giderler siparişlere dağıtılmaz: bilinen kâr = sipariş toplamı - dönem düzeyi giderler.
    known = sum((D(i["known_expenses_profit"]) for i in live), D(0))
    assert known - D(totals["donem_duzeyi_giderler_toplami"]) == D(totals["donem_eksik_giderler_haric_kar"])
    if totals["satir_net_kar_toplami"] is not None:  # tam dönem: her siparişin net kârı sayıdır
        assert all(i["net_profit"] is not None for i in live)
        assert sum((D(i["net_profit"]) for i in live), D(0)) == D(totals["satir_net_kar_toplami"])
    else:  # kısmi dönem: en az bir sipariş "hesaplanamadı"
        assert any(i["net_profit"] is None for i in live)
    assert totals["kesinlik"] in {i["certainty"] for i in live} or not live

    # Satır düzeyi doğrulama (motorun kablo çıktısından bağımsız türetilmiş beklentiler).
    for item in live:
        mine = [ln for ln in active if ln["orderNumber"] == item["order_number"]]
        assert item["line_count"] == len(mine)
        assert item["awaiting_payout"] == any(ln["durum"] == "estimated" for ln in mine)
        assert item["unexpected_deduction"] == any("BEKLENMEYEN_KESINTI" in ln["uyarilar"] for ln in mine)
        incomplete = any(ln["eksik_kalemler"] for ln in mine)
        assert (item["net_profit"] is None) == incomplete
        if not incomplete:
            assert D(item["net_profit"]) == sum((D(ln["kalemler"]["net_kar"]) for ln in mine), D(0))
        assert item["certainty"] in {"kesin", "tahmini", "eksik"}
        assert (item["loss_reason"] is not None) == (
            D(item["net_profit"]) < 0
            if item["net_profit"] is not None
            else D(item["known_expenses_profit"]) < 0
        )
    for item in items:
        if item["cancelled"]:
            assert item["net_profit"] is None and item["net_sales_excl_vat"] is None
            assert item["certainty"] == "iptal"

    # Süzgeçler aynı küme.
    for name, flag in (
        ("loss", None),
        ("awaiting_payout", "awaiting_payout"),
        ("unexpected_deduction", "unexpected_deduction"),
    ):
        filtered = get("orders", limit=200, filter=name)
        expected = [
            i["order_number"] for i in items if (i["loss_reason"] is not None if flag is None else i[flag])
        ]
        assert [i["order_number"] for i in filtered["items"]] == expected and filtered["total_count"] == len(
            expected
        )
    for number in sorted(all_numbers):  # tam eşleşme araması
        assert [i["order_number"] for i in get("orders", q=number)["items"]] == [number]

    # Sipariş detay ucuyla uyum: aynı dönem, aynı motor sonucu.
    for item in live:
        detail = get(f"orders/{item['order_number']}")
        assert detail["totals"]["net_profit"] == item["net_profit"]
        assert detail["totals"]["known_expenses_profit"] == item["known_expenses_profit"]
        assert detail["totals"]["net_sales_excl_vat"] == item["net_sales_excl_vat"]
        assert detail["status_counts"] == item["status_counts"]


# --- DB'siz birim: motor sonuçlarından sipariş satırları -----------------------------------------------------------


def test_unit_totals_of_orders_equal_period_totals_for_every_golden_scenario() -> None:
    for prefix, result in all_results():
        rows = views.build_order_rows(result)
        live = [r for r in rows if not r.cancelled]
        period = result.period
        assert len(live) == period.order_count, prefix
        assert sum((r.totals.net_sales_excl_vat for r in live if r.totals), D(0)) == period.net_sales_excl_vat
        known = sum((r.totals.known_expenses_profit for r in live if r.totals), D(0))
        assert known - period.period_level_expenses_total == period.period_known_expenses_profit, prefix
        if period.line_net_profit_total is not None:
            assert sum((r.net_profit or D(0) for r in live), D(0)) == period.line_net_profit_total, prefix
        for r in rows:
            if r.cancelled:  # B-02: iptal siparişte tutar yok
                assert r.totals is None and r.net_profit is None and r.loss_reason is None, prefix


def test_unit_cancelled_order_is_flagged_with_null_net_profit() -> None:
    rows = views.build_order_rows(golden_result("G38"))
    cancelled = [r for r in rows if r.cancelled]
    assert cancelled and all(r.net_profit is None and r.certainty.value == "iptal" for r in cancelled)


def test_unit_null_net_profit_loss_sorts_by_its_known_value_and_unknowns_last() -> None:
    base = views.build_order_rows(golden_result("G11"))[0]
    totals = base.totals
    assert totals is not None

    def make(number: str, net: str | None, known: str, missing: bool = True) -> views.OrderRow:
        t = dataclasses.replace(
            totals,
            net_profit=None if net is None else D(net),
            known_expenses_profit=D(known),
            missing_items=list(totals.missing_items) if missing else [],
        )
        reason = views.order_loss_reason(t)
        return dataclasses.replace(base, order_number=number, totals=t, loss_reason=reason)

    rows = [
        make("A", "5.00", "5.00", False),
        make("B", None, "75.00"),  # belirsiz
        make("C", None, "-10.00"),  # kesin zarar (net null)
        make("D", "-50.00", "-50.00", False),  # hesaplanmış net zarar
        make("E", None, "-30.00"),
        make("F", None, "0.00"),  # sıfır zarar değildir
    ]
    dates: dict[str, datetime] = {}
    codec = views.CursorCodec(b"0123456789abcdef0123456789abcdef", UUID(int=1), UUID(int=2))

    def ids(order: str) -> list[str]:
        page, _ = views.order_page(rows, dates, "net_profit", order, 50, None, "fp", codec)  # type: ignore[arg-type]
        return [r.order_number for r in page]

    assert ids("asc") == ["D", "E", "C", "A", "B", "F"]  # en büyük zarar önce, belirsizler sonda
    assert ids("desc") == ["A", "C", "E", "D", "B", "F"]  # belirsizler yine sonda


def test_unit_date_sort_without_a_known_date_goes_last_and_cursor_round_trips() -> None:
    rows = views.build_order_rows(golden_result("G11"))
    dates = {r.order_number: datetime(2026, 10, 1 + i, 9, tzinfo=UTC) for i, r in enumerate(rows[:-1])}
    codec = views.CursorCodec(b"0123456789abcdef0123456789abcdef", UUID(int=1), UUID(int=2))
    walked: list[str] = []
    cursor = None
    for _ in range(len(rows) + 1):
        page, cursor = views.order_page(rows, dates, "date", "desc", 1, cursor, "fp", codec)
        walked += [r.order_number for r in page]
        if cursor is None:
            break
    expected = [r.order_number for r in reversed(rows[:-1])] + [rows[-1].order_number]
    assert walked == expected  # tarihi bilinmeyen en sonda


def test_unit_filter_orders_exact_match_only() -> None:
    rows = views.build_order_rows(golden_result("G11"))
    first = rows[0].order_number
    assert [r.order_number for r in views.filter_orders(rows, "all", first)] == [first]
    assert views.filter_orders(rows, "all", first[:-1]) == [] or first[:-1] in {r.order_number for r in rows}
    assert views.filter_orders(rows, "all", None) == rows
