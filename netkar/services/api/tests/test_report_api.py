"""Kâr raporu API'si (`/v1/marketplace-accounts/{id}/profit/*`): gerçek PostgreSQL, RLS, tüm uçlar."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import AsyncIterator, Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.v1 import profit as profit_module
from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.profit import ProfitInputError, ProfitSettings, calculate_profit
from app.profit.schema_v1 import ISTANBUL, to_wire
from app.services import profit_report
from app.services import profit_views as views
from app.services.profit_report import period_profit
from app.services.sync.runner import SyncRunner
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, add_product, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import (
    B1,
    B2,
    B3,
    END,
    MONEY_RE,
    START,
    add_cost,
    add_order,
    money_strings,
    seed_basic,
    seller_of,
)
from tests.sync_helpers import client_factory, envelope_for_tests
from tests.test_sync_pii import pii_api
from tests.trendyol_helpers import PII_SENTINELS

pytestmark = pytest.mark.usefixtures("fixed_today")  # İstanbul bugünü 2026-11-08
D = Decimal
PERIOD = {"start": START, "end": END}


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]) -> Shop:
    created = make_shop("a@example.com", "Mağaza A")
    seed_basic(admin_conn, created)
    return created


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]) -> tuple[Shop, Shop]:
    a, b = make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")
    seed_basic(admin_conn, a)
    return a, b


def call(shop: Shop, path: str, **params: Any) -> Any:
    return shop.api.get(f"{shop.base}/profit/{path}", params={**PERIOD, **params})


ENDPOINTS = ["summary", "products", f"products/{B1}", "orders/1003", "alerts"]


# --- özet ------------------------------------------------------------------------------------------------


def test_summary_returns_engine_totals_status_counts_and_feed_notes(shop: Shop) -> None:
    r = call(shop, "summary")
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    body = r.json()
    assert body["period"] == {"start": START, "end": END, "days": 31}
    totals = body["totals"]
    # 1001 (100.00 KDV hariç) + 1002 (83.33) + 1003 (satış 25.00, tamamı iade: 0.00); 1004 iptal girmez.
    assert totals["siparis_sayisi"] == 3 and totals["satir_sayisi"] == 3
    assert totals["net_satis_kdv_haric"] == "183.33" and totals["komisyon"] == "18.33"
    assert totals["urun_maliyeti"] == "100.00" and totals["donem_net_kar"] == "-10.00"
    assert totals["net_kar_kismi"] is True and totals["maliyet_eksik_satir_sayisi"] == 1
    assert totals["uyarilar"] == ["MALIYET_EKSIK_SATIRLAR_VAR"] and totals["teyit_bekliyor"] == []
    assert body["status_counts"] == {"estimated": 1, "settled": 1, "adjusted": 1, "cancelled": 1}
    assert body["missing_cost_line_count"] == 1
    assert body["feed_notes"] == {
        "lines_missing_rates": 0,
        "lines_bad_items": 0,
        "orders_without_lines": 0,
        "settlements_unmatched": 0,
        "cargo_items_unmatched": 0,
        "claim_items_unmatched": 0,
        "total": 0,
    }


async def test_summary_totals_equal_the_engine_wire_output_exactly(shop: Shop) -> None:
    engine = create_engine(shop.api.client.app.state.settings.database_url)  # type: ignore[attr-defined]
    try:
        async with tenant_transaction(
            async_sessionmaker(engine, expire_on_commit=False), shop.tenant_id
        ) as s:
            report = await period_profit(
                s, shop.tenant_id, shop.account_id, date(2026, 10, 1), date(2026, 10, 31), ProfitSettings()
            )
    finally:
        await engine.dispose()
    assert call(shop, "summary").json()["totals"] == to_wire(report.totals)


def test_summary_reports_feed_notes_for_records_the_engine_did_not_get(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    # Oranı ne satırda ne üründe olan satır motora verilmez (tahmin yok) ve sayaçta görünür.
    add_order(
        admin_conn, seller_of(shop), "1100", 9, datetime(2026, 10, 9, 9, tzinfo=UTC),
        lines=[{"line_id": 9, "barcode": "no-card", "vat": None}],
    )  # fmt: skip
    notes = call(shop, "summary").json()["feed_notes"]
    assert notes["lines_missing_rates"] == 1 and notes["orders_without_lines"] == 1 and notes["total"] == 2


def test_empty_period_returns_zeros_and_empty_lists(shop: Shop) -> None:
    quiet = {"start": "2026-03-01", "end": "2026-03-31"}
    summary = call(shop, "summary", **quiet).json()
    assert summary["totals"]["siparis_sayisi"] == 0 and summary["totals"]["net_satis_kdv_haric"] == "0.00"
    assert summary["totals"]["net_kar_marji_yuzde"] is None  # net satış 0: marj hesaplanamaz
    assert summary["status_counts"] == {"estimated": 0, "settled": 0, "adjusted": 0, "cancelled": 0}
    products = call(shop, "products", **quiet).json()
    assert products["items"] == [] and products["total_count"] == 0 and products["next_cursor"] is None
    alerts = call(shop, "alerts", **quiet).json()
    assert alerts["items"] == [] and alerts["counts"] == [] and alerts["total_count"] == 0


def test_every_money_field_is_a_two_decimal_string_never_a_float(shop: Shop) -> None:
    seen = 0
    for path in ENDPOINTS:
        for where, value in money_strings(call(shop, path).json()):
            assert not isinstance(value, float), where
            if isinstance(value, str) and re.fullmatch(r"-?[0-9]+\.[0-9]+", value):
                assert MONEY_RE.fullmatch(value), (where, value)  # tam iki ondalık
                seen += 1
    assert seen > 150


def test_money_keeps_cent_precision_for_half_cent_inputs(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Yarım kuruşlu girdi (74,985 gibi) motorda tek yuvarlamayla iner; API ek yuvarlama yapmaz."""
    add_order(
        admin_conn, seller_of(shop), "1200", 20, datetime(2026, 10, 12, 9, tzinfo=UTC),
        lines=[{"line_id": 20, "barcode": B1, "gross": "99.99", "commission": "12.5"}],
    )  # fmt: skip
    line = call(shop, "orders/1200").json()["lines"][0]["kalemler"]
    assert line["brut_satis_kdv_dahil"] == "99.99" and line["satis_kdv_haric"] == "83.33"
    assert line["komisyon"] == "10.42" and line["net_kar"] == "22.91"  # 83.325 -> 83.33; 10.4163 -> 10.42


# --- dönem parametreleri ---------------------------------------------------------------------------------


def test_range_presets_use_the_istanbul_day_with_today_included(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = make_shop("a@example.com", "Mağaza A")
    add_product(admin_conn, shop, B1)
    add_cost(admin_conn, shop, B1, "10.00")
    # Bugün İstanbul 2026-11-08: UTC 21:30 (10-07 akşamı) İstanbul'da 11-08 00:30'dur.
    cases = (
        datetime(2026, 11, 7, 21, 30, tzinfo=UTC),  # İstanbul 11-08 00:30: bugün
        datetime(2026, 11, 3, 9, tzinfo=UTC),  # 7 gün içinde
        datetime(2026, 11, 1, 20, 59, tzinfo=UTC),  # İstanbul 11-01 23:59: 7 günün dışı
        datetime(2026, 10, 10, 0, 0, tzinfo=UTC),  # 30 günün ilk günü (10-10)
        datetime(2026, 10, 9, 20, 59, tzinfo=UTC),  # İstanbul 10-09 23:59: 30 günün dışı
    )
    for index, when in enumerate(cases, start=1):
        add_order(
            admin_conn, seller_of(shop), f"r{index}", index, when,
            lines=[{"line_id": index, "barcode": B1}],
        )  # fmt: skip

    def orders(**params: Any) -> tuple[int, dict[str, Any]]:
        body = shop.api.get(f"{shop.base}/profit/summary", params=params).json()
        return body["totals"]["siparis_sayisi"], body["period"]

    assert orders(range="today") == (1, {"start": "2026-11-08", "end": "2026-11-08", "days": 1})
    assert orders(range="7d") == (2, {"start": "2026-11-02", "end": "2026-11-08", "days": 7})
    assert orders(range="30d") == (4, {"start": "2026-10-10", "end": "2026-11-08", "days": 30})
    assert orders() == orders(range="30d")  # varsayılan 30 gün


@pytest.mark.parametrize(
    ("params", "field", "code"),
    [
        ({"start": "2026-10-01"}, "end", "period_incomplete"),
        ({"end": "2026-10-01"}, "start", "period_incomplete"),
        ({"range": "7d", "start": "2026-10-01", "end": "2026-10-02"}, "range", "period_conflict"),
        ({"start": "2026-10-05", "end": "2026-10-04"}, "end", "period_reversed"),
        ({"start": "2026-08-01", "end": "2026-11-01"}, "end", "period_too_long"),
        ({"start": "2026-02-30", "end": "2026-03-04"}, "start", "date_invalid"),
        ({"start": "1999-12-31", "end": "2000-01-02"}, "start", "date_out_of_range"),
        ({"start": "2026-10-1", "end": "2026-10-04"}, "start", "string_pattern_mismatch"),
        ({"start": "2026-10-01T00:00:00", "end": "2026-10-04"}, "start", "string_too_long"),
        ({"start": "٢٠٢٦-١٠-٠١", "end": "2026-10-04"}, "start", "string_pattern_mismatch"),
        ({"range": "90d"}, "range", "literal_error"),
        ({"range": "TODAY"}, "range", "literal_error"),
    ],
)
@pytest.mark.parametrize("path", ["summary", "products", f"products/{B1}", "alerts"])
def test_invalid_period_is_a_422_problem_with_the_offending_field(
    shop: Shop, path: str, params: dict[str, str], field: str, code: str
) -> None:
    r = shop.api.get(f"{shop.base}/profit/{path}", params=params)
    assert r.status_code == 422 and r.headers["content-type"] == "application/problem+json"
    body = r.json()
    assert body["type"] == "urn:netkar:problem:validation-error" and body["status"] == 422
    assert {"field": field, "code": code} in body["errors"]
    assert params.get("start", "-") not in json.dumps(body["errors"])  # girdi değeri yansıtılmaz


def test_a_92_day_period_is_accepted_and_93_is_not(shop: Shop) -> None:
    ok = shop.api.get(f"{shop.base}/profit/summary", params={"start": "2026-08-01", "end": "2026-10-31"})
    assert ok.status_code == 200 and ok.json()["period"]["days"] == 92


def test_order_endpoint_validates_its_optional_period_too(shop: Shop) -> None:
    r = shop.api.get(f"{shop.base}/profit/orders/1003", params={"start": "2026-10-01"})
    assert r.status_code == 422 and {"field": "end", "code": "period_incomplete"} in r.json()["errors"]


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("products", {"limit": 0}),
        ("products", {"limit": 201}),
        ("products", {"sort": "margin"}),
        ("products", {"order": "up"}),
        ("products", {"filter": "profit"}),
        ("products", {"cursor": ""}),
        ("alerts", {"limit": 0}),
        ("alerts", {"code": "NOPE"}),
        (f"products/{B1}", {"limit": 500}),
    ],
)
def test_bad_list_parameters_are_422(shop: Shop, path: str, params: dict[str, Any]) -> None:
    assert call(shop, path, **params).status_code == 422


@pytest.mark.parametrize("barcode", ["a b", "=cmd", "-x", "x" * 201])
def test_barcode_path_is_validated(shop: Shop, barcode: str) -> None:
    assert call(shop, f"products/{barcode}").status_code == 422


@pytest.mark.parametrize("number", ["a b", ".x", "x" * 65, "1;2"])
def test_order_number_path_is_validated(shop: Shop, number: str) -> None:
    assert call(shop, f"orders/{number}").status_code == 422


# --- ürün listesi ------------------------------------------------------------------------------------------


def test_products_list_shape_titles_basis_and_unknown_values_last(shop: Shop) -> None:
    body = call(shop, "products").json()
    assert (body["sort"], body["order"], body["filter"], body["total_count"]) == (
        "net_profit",
        "desc",
        "all",
        2,
    )
    b1, b2 = body["items"]
    assert (b1["barcode"], b1["title"]) == (B1, "Ürün Bir")
    assert (b1["net_sales_excl_vat"], b1["product_cost"], b1["total_expenses"], b1["net_profit"]) == (
        "100.00", "100.00", "110.00", "-10.00",
    )  # fmt: skip
    assert (b1["net_margin_percent"], b1["quantity"], b1["line_count"], b1["cost_missing"]) == (
        "-10.00", 2, 2, False,
    )  # fmt: skip
    assert (b1["basis"], b1["estimated_line_count"], b1["adjusted_line_count"]) == ("mixed", 1, 1)
    assert (b2["barcode"], b2["title"], b2["cost_missing"]) == (B2, "Ürün İki", True)
    assert b2["net_profit"] is None and b2["total_expenses"] is None and b2["net_margin_percent"] is None
    assert b2["basis"] == "settled" and b2["net_sales_excl_vat"] == "83.33"
    # Maliyeti eksik ürün her yönde sonda: asc'de de.
    asc = call(shop, "products", order="asc").json()["items"]
    assert [i["barcode"] for i in asc] == [B1, B2]


def test_products_filters_loss_and_missing_cost(shop: Shop) -> None:
    loss = call(shop, "products", filter="loss").json()
    assert [i["barcode"] for i in loss["items"]] == [B1] and loss["total_count"] == 1
    missing = call(shop, "products", filter="missing_cost").json()
    assert [i["barcode"] for i in missing["items"]] == [B2] and missing["total_count"] == 1
    assert call(shop, "products", filter="all").json()["total_count"] == 2


def test_sort_fields_order_and_tiebreak_on_barcode(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    seller = seller_of(shop)
    for i, barcode in enumerate(("8681000000099", "8681000000050", "8681000000070"), start=1):
        add_product(admin_conn, shop, barcode, f"T{i}")
        add_cost(admin_conn, shop, barcode, "10.00")
        add_order(admin_conn, seller, f"tie{i}", 500 + i, datetime(2026, 10, 15, 9, tzinfo=UTC),
                  lines=[{"line_id": 500 + i, "barcode": barcode, "gross": "60.00"}])  # fmt: skip
    # Üç ürün birebir aynı kârda: eşitlikte barkod artan, hem desc hem asc.
    for order in ("desc", "asc"):
        items = call(shop, "products", sort="net_profit", order=order, filter="all").json()["items"]
        tied = [i["barcode"] for i in items if i["barcode"].startswith("86810000000") and i["barcode"] != B1]
        tied = [b for b in tied if b in {"8681000000099", "8681000000050", "8681000000070"}]
        assert tied == ["8681000000050", "8681000000070", "8681000000099"], order
    by_units = call(shop, "products", sort="units", order="desc").json()["items"]
    assert by_units[0]["barcode"] == B1  # 2 adet
    by_sales = call(shop, "products", sort="sales", order="asc").json()["items"]
    sales = [D(i["net_sales_excl_vat"]) for i in by_sales]
    assert sales == sorted(sales)
    margins = call(shop, "products", sort="net_margin", order="desc").json()["items"]
    known = [D(i["net_margin_percent"]) for i in margins if i["net_margin_percent"] is not None]
    assert known == sorted(known, reverse=True) and margins[-1]["net_margin_percent"] is None


@pytest.mark.parametrize(("sort", "order"), [("net_profit", "desc"), ("sales", "asc"), ("units", "desc")])
def test_cursor_paging_walks_the_full_list_once_in_the_same_order(
    shop: Shop, admin_conn: psycopg.Connection[Any], sort: str, order: str
) -> None:
    for i in range(7):  # 9 ürün toplam; aynı değerler tekrarlanır
        barcode = f"86810000001{i:02d}"
        add_product(admin_conn, shop, barcode, f"P{i}")
        add_cost(admin_conn, shop, barcode, "10.00")
        add_order(admin_conn, seller_of(shop), f"pg{i}", 600 + i, datetime(2026, 10, 16, 9, tzinfo=UTC),
                  lines=[{"line_id": 600 + i, "barcode": barcode, "gross": str(60 + 10 * (i % 3))}])  # fmt: skip
    whole = call(shop, "products", sort=sort, order=order, limit=200).json()
    assert whole["total_count"] == 9 and whole["next_cursor"] is None
    expected = [i["barcode"] for i in whole["items"]]
    walked: list[str] = []
    cursor = None
    for _ in range(10):
        page = call(
            shop, "products", sort=sort, order=order, limit=2, **({"cursor": cursor} if cursor else {})
        ).json()
        assert len(page["items"]) <= 2 and page["total_count"] == 9
        walked += [i["barcode"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert walked == expected and len(set(walked)) == 9


def test_cursor_from_another_query_or_garbage_is_a_422(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, "86810000009")
    add_order(admin_conn, seller_of(shop), "cu1", 700, datetime(2026, 10, 17, 9, tzinfo=UTC),
              lines=[{"line_id": 700, "barcode": "86810000009"}])  # fmt: skip
    cursor = call(shop, "products", limit=1).json()["next_cursor"]
    assert cursor
    for params in ({"sort": "sales"}, {"order": "asc"}, {"filter": "loss"}, {"end": "2026-10-30"}):
        r = call(shop, "products", limit=1, cursor=cursor, **params)
        assert r.status_code == 422 and {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]
    assert call(shop, "products", cursor="bozuk-imlec").status_code == 422
    # Aynı sorguda geçerli
    assert call(shop, "products", limit=1, cursor=cursor).status_code == 200


# --- ürün kırılımı ---------------------------------------------------------------------------------------------


def test_product_detail_has_lines_totals_and_estimate_vs_actual_comparison(shop: Shop) -> None:
    body = call(shop, f"products/{B1}").json()
    assert (body["barcode"], body["title"], body["basis"], body["total_lines"]) == (
        B1,
        "Ürün Bir",
        "mixed",
        3,
    )
    assert body["product"]["net_kar"] == "-10.00" and body["product"]["adet"] == 2
    lines = body["lines"]
    assert [(ln["orderNumber"], ln["durum"]) for ln in lines] == [
        ("1001", "estimated"), ("1003", "adjusted"), ("1004", "cancelled"),
    ]  # fmt: skip
    estimated, adjusted, cancelled = lines
    assert estimated["karsilastirma"] is None  # ekstre yok: karşılaştırma yok
    assert estimated["kaynaklar"]["satis"] == "tahmini" and adjusted["kaynaklar"]["satis"] == "kesin"
    assert adjusted["karsilastirma"]["fark"] == "0.00" and adjusted["karsilastirma"]["esik"] == "5.00"
    assert adjusted["uyarilar"] == ["KARGO_TARIFESI_EKSIK", "ZARAR"]
    assert cancelled["kalemler"]["net_kar"] == "0.00" and cancelled["kalemler"]["urun_maliyeti"] == "0.00"
    assert body["comparison"] == {
        "compared_line_count": 1, "estimated_total": "2.50", "actual_total": "2.50", "difference": "0.00",
    }  # fmt: skip


def test_product_detail_for_a_known_product_without_sales_is_empty_not_404(shop: Shop) -> None:
    body = call(shop, f"products/{B3}").json()
    assert body["product"] is None and body["lines"] == [] and body["total_lines"] == 0
    assert (
        body["basis"] == "none" and body["title"] is None and body["comparison"]["compared_line_count"] == 0
    )


def test_unknown_barcode_is_404_and_does_not_run_the_engine(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = count_engine_calls(monkeypatch)
    r = call(shop, "products/0000000000000")
    assert r.status_code == 404 and r.headers["content-type"] == "application/problem+json"
    assert calls == []


def test_product_lines_are_paged_with_a_cursor(shop: Shop) -> None:
    first = call(shop, f"products/{B1}", limit=2).json()
    assert [ln["orderNumber"] for ln in first["lines"]] == ["1001", "1003"] and first["next_cursor"]
    second = call(shop, f"products/{B1}", limit=2, cursor=first["next_cursor"]).json()
    assert [ln["orderNumber"] for ln in second["lines"]] == ["1004"] and second["next_cursor"] is None
    assert second["total_lines"] == 3 and second["product"] == first["product"]  # toplam sayfadan bağımsız
    assert call(shop, f"products/{B2}", limit=2, cursor=first["next_cursor"]).status_code == 422


# --- sipariş kırılımı ---------------------------------------------------------------------------------------------


def test_order_detail_has_lines_items_and_totals(shop: Shop) -> None:
    body = call(shop, "orders/1003").json()
    assert (body["order_number"], body["ordered_on"]) == ("1003", "2026-10-07")
    assert body["totals"] == {
        "line_count": 1, "net_sales_excl_vat": "0.00", "total_expenses": "50.00",
        "net_profit": "-50.00", "cost_missing": False,
    }  # fmt: skip
    assert body["status_counts"] == {"estimated": 0, "settled": 0, "adjusted": 1, "cancelled": 0}
    (line,) = body["lines"]
    assert line["kalemler"]["iade_kdv_haric"] == "25.00" and line["kdv"]["kdv_etkisi"] == "-10.00"
    assert line["nakit_akisi"]["stopaj"] == "0.00" and line["durum"] == "adjusted"
    cancelled = call(shop, "orders/1004").json()
    assert cancelled["totals"]["line_count"] == 0 and cancelled["status_counts"]["cancelled"] == 1
    missing = call(shop, "orders/1002").json()  # maliyeti olmayan ürün: kâr uydurulmaz
    assert missing["totals"]["net_profit"] is None and missing["totals"]["cost_missing"] is True


def test_order_without_a_period_uses_its_own_days_and_an_explicit_period_must_contain_it(shop: Shop) -> None:
    # Ekim siparişi "bugün"den 30 günden eski: dönem verilmezse siparişin kendi günü kullanılır.
    r = shop.api.get(f"{shop.base}/profit/orders/1001")
    assert r.status_code == 200 and r.json()["period"] == {
        "start": "2026-10-05",
        "end": "2026-10-05",
        "days": 1,
    }
    assert r.json()["lines"][0]["kalemler"]["net_kar"] == "40.00"
    outside = shop.api.get(f"{shop.base}/profit/orders/1001", params={"range": "7d"})
    assert outside.status_code == 404  # sipariş var ama seçilen dönemde değil
    assert shop.api.get(f"{shop.base}/profit/orders/9999").status_code == 404
    assert call(shop, "orders/9999").status_code == 404


def test_multi_package_order_returns_all_its_lines(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    seller = seller_of(shop)
    when = datetime(2026, 10, 20, 9, tzinfo=UTC)
    add_order(admin_conn, seller, "2000", 31, when, lines=[{"line_id": 31, "barcode": B1}])
    add_order(admin_conn, seller, "2000", 32, when, lines=[{"line_id": 32, "barcode": B1}])
    body = call(shop, "orders/2000").json()
    assert [(ln["shipmentPackageId"], ln["lineId"]) for ln in body["lines"]] == [(31, 31), (32, 32)]
    assert body["totals"]["line_count"] == 2


# --- kişisel veri ---------------------------------------------------------------------------------------------------

FORBIDDEN_KEY_PARTS = (
    "customer", "address", "adres", "phone", "telefon", "email", "tckn", "surname", "soyad",
    "firstname", "lastname", "musteri", "identity", "buyer",
)  # fmt: skip


def all_keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in all_keys(v)}
    if isinstance(node, list):
        return {k for v in node for k in all_keys(v)}
    return set()


async def test_order_and_other_responses_never_carry_customer_data_even_after_a_pii_laden_sync(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
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
        "SELECT order_number, ordered_at FROM orders WHERE marketplace_account_id = %s ORDER BY order_number",
        (shop.account_id,),
    ).fetchall()
    assert len(rows) >= 2
    bodies = []
    found = 0
    for number, _ordered_at in rows:
        r = shop.api.get(f"{shop.base}/profit/orders/{number}")  # dönemsiz: siparişin kendi günleri
        bodies.append(r.text)
        if r.status_code == 200:
            found += 1
            assert not {k for k in all_keys(r.json()) if any(p in k.lower() for p in FORBIDDEN_KEY_PARTS)}
    assert found >= 1
    day = rows[0][1].astimezone(ISTANBUL).date()
    wide = {"start": str(day.replace(day=1)), "end": str(day.replace(day=28))}
    for path in ("summary", "products", "alerts"):
        r = shop.api.get(f"{shop.base}/profit/{path}", params=wide)
        assert r.status_code == 200
        bodies.append(r.text)
    text = "\n".join(bodies)
    assert [s for s in PII_SENTINELS if s in text] == []
    assert "İstanbul" not in text  # il adı bile yanıtta yok (panel ihtiyacı değil)


# --- uyarılar ---------------------------------------------------------------------------------------------------------


def test_alerts_list_engine_warnings_with_counts_messages_and_unavailable_codes(shop: Shop) -> None:
    body = call(shop, "alerts").json()
    counts = {c["code"]: c["count"] for c in body["counts"]}
    assert counts == {
        "KARGO_TARIFESI_EKSIK": 3, "MALIYET_EKSIK": 1, "MALIYET_EKSIK_SATIRLAR_VAR": 1, "ZARAR": 1,
    }  # fmt: skip
    assert body["total_count"] == 6 and len(body["items"]) == 6 and body["next_cursor"] is None
    first = body["items"][0]
    assert (first["code"], first["scope"], first["order_number"]) == (
        "MALIYET_EKSIK_SATIRLAR_VAR",
        "period",
        None,
    )
    loss = next(i for i in body["items"] if i["code"] == "ZARAR")
    assert (loss["scope"], loss["order_number"], loss["line_id"], loss["barcode"], loss["net_profit"]) == (
        "line", "1003", 3, B1, "-50.00",
    )  # fmt: skip
    assert all(i["message"] for i in body["items"]) and all(c["message"] for c in body["counts"])
    assert {u["code"] for u in body["not_yet_available"]} == {"REKLAM_KARI_YIYOR", "IADE_ORANI_ARTISI"}
    # İptal satırı (1004) uyarı üretmez.
    assert not [i for i in body["items"] if i["order_number"] == "1004"]


def test_alerts_filter_by_code_and_page_with_a_cursor(shop: Shop) -> None:
    only = call(shop, "alerts", code="KARGO_TARIFESI_EKSIK").json()
    assert only["total_count"] == 3 and {i["code"] for i in only["items"]} == {"KARGO_TARIFESI_EKSIK"}
    assert len(only["counts"]) == 4  # sayımlar süzgeçten bağımsız
    seen, cursor = [], None
    for _ in range(10):
        page = call(shop, "alerts", limit=2, **({"cursor": cursor} if cursor else {})).json()
        seen += [(i["code"], i["order_number"]) for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 6 and len(set(seen)) == 6 and seen[0][0] == "MALIYET_EKSIK_SATIRLAR_VAR"
    assert call(shop, "alerts", code="ZARAR", cursor=page["next_cursor"] or "x").status_code == 422
    r = call(shop, "alerts", limit=2).json()
    assert (
        call(shop, "alerts", limit=2, code="ZARAR", cursor=r["next_cursor"]).status_code == 422
    )  # başka sorgu


def test_alerts_accept_the_range_shortcut(shop: Shop) -> None:
    r = shop.api.get(f"{shop.base}/profit/alerts", params={"range": "7d"})
    assert r.status_code == 200 and r.json()["period"]["days"] == 7 and r.json()["total_count"] == 0


# --- yetki, IDOR, roller -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ENDPOINTS)
def test_unauthenticated_requests_are_401(shop: Shop, make_api: Callable[..., Api], path: str) -> None:
    anonymous = make_api()
    r = anonymous.get(f"{shop.base}/profit/{path}", params=PERIOD)
    assert r.status_code == 401 and r.headers["content-type"] == "application/problem+json"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_other_tenants_account_is_404_and_leaks_nothing(two_shops: tuple[Shop, Shop], path: str) -> None:
    a, b = two_shops
    r = b.api.get(f"{a.base}/profit/{path}", params=PERIOD)
    assert r.status_code == 404 and r.json()["type"] == "urn:netkar:problem:not-found"
    assert a.api.get(f"{a.base}/profit/{path}", params=PERIOD).status_code == 200  # sahibi görür
    missing = b.api.get(f"/v1/marketplace-accounts/{uuid4()}/profit/{path}", params=PERIOD)
    # Var olmayan hesap ile yabancı hesap ayırt edilemez.
    assert missing.status_code == 404
    assert (missing.json()["type"], missing.json()["title"]) == (r.json()["type"], r.json()["title"])


def test_each_tenant_sees_only_its_own_data_through_its_own_account(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    seller_b = seller_of(b)
    add_product(admin_conn, b, B1, "B'nin ürünü")
    add_order(
        admin_conn,
        seller_b,
        "9001",
        90,
        datetime(2026, 10, 5, 9, tzinfo=UTC),
        lines=[{"line_id": 90, "barcode": B1}],
    )
    a_body, b_body = call(a, "summary").json(), call(b, "summary").json()
    assert a_body["totals"]["siparis_sayisi"] == 3 and b_body["totals"]["siparis_sayisi"] == 1
    assert call(b, "orders/1001").status_code == 404  # A'nın siparişi B'nin hesabında yok
    assert call(a, "orders/9001").status_code == 404
    assert call(b, "products").json()["items"][0]["title"] == "B'nin ürünü"


@pytest.mark.parametrize("path", ENDPOINTS)
def test_viewer_can_read_every_report_endpoint(
    shop: Shop, admin_conn: psycopg.Connection[Any], path: str
) -> None:
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert call(shop, path).status_code == 200


# --- hız sınırı ----------------------------------------------------------------------------------------------------------


def test_rate_limit_is_per_tenant_per_minute_and_shared_across_report_endpoints(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    frozen_ratelimit_clock: float,
) -> None:
    a = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=3)
    b = make_shop("b@example.com", "Mağaza B", seller_id="9999", rate_limit_profit_report_tenant=3)
    for path in ("summary", "products", "alerts"):  # üç farklı uç, tek kova
        assert call(a, path).status_code == 200
    r = call(a, "summary")
    assert r.status_code == 429 and r.headers["content-type"] == "application/problem+json"
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    assert call(a, f"orders/{1}").status_code == 429  # sipariş ucu da aynı kovada (404 yerine 429)
    assert call(b, "summary").status_code == 200  # başka kiracının kovası ayrı
    # Doğrulama hatası (422) ve yabancı hesap (404) kovayı tüketmez.
    assert b.api.get(f"{b.base}/profit/summary", params={"start": "x"}).status_code == 422
    assert a.api.get(f"/v1/marketplace-accounts/{uuid4()}/profit/summary", params=PERIOD).status_code == 404
    assert [call(b, "summary").status_code for _ in range(3)] == [200, 200, 429]  # 1 + 2 = 3. isteğe kadar


def test_default_rate_limit_is_sixty_a_minute() -> None:
    from app.core.config import Settings

    assert Settings.model_fields["rate_limit_profit_report_tenant"].default == 60


# --- motor bir kez, hata yolu, OpenAPI -----------------------------------------------------------------------------------


def count_engine_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    real = calculate_profit
    calls: list[int] = []

    def counting(profit_input: Any) -> Any:
        calls.append(len(profit_input.orders))
        return real(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", counting)
    return calls


@pytest.mark.parametrize("path", ENDPOINTS)
def test_one_request_runs_the_engine_exactly_once(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    calls = count_engine_calls(monkeypatch)
    assert call(shop, path).status_code == 200
    assert len(calls) == 1


def test_a_second_page_of_the_list_is_a_new_request_with_its_own_single_run(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = count_engine_calls(monkeypatch)
    cursor = call(shop, "products", limit=1).json()["next_cursor"]
    call(shop, "products", limit=1, cursor=cursor)
    assert len(calls) == 2


def test_inconsistent_records_are_a_500_problem_without_internal_detail(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise ProfitInputError("sipariş 1003 tutarsız: 12345.67")

    monkeypatch.setattr(profit_module, "period_profit", boom)
    r = call(shop, "summary")
    assert r.status_code == 500 and r.json()["type"] == "urn:netkar:problem:profit-calculation-failed"
    assert "1003" not in r.text and "12345" not in r.text
    assert "1003" not in caplog.text and "12345" not in caplog.text  # ayrıntı log'a da girmez
    assert "ProfitInputError" in caplog.text and str(shop.account_id) in caplog.text


def test_openapi_lists_every_endpoint_and_schema_with_string_money(shop: Shop) -> None:
    spec = shop.api.get("/v1/openapi.json").json()
    base = "/v1/marketplace-accounts/{account_id}/profit"
    for suffix in ("/summary", "/products", "/products/{barcode}", "/orders/{order_number}", "/alerts"):
        operation = spec["paths"][base + suffix]["get"]
        assert operation["tags"] == ["profit"] and "200" in operation["responses"]
    schemas = spec["components"]["schemas"]
    for name in ("SummaryOut", "ProductProfitListOut", "ProductProfitDetailOut", "OrderDetailOut", "AlertsOut", "LineOut",
                 "PeriodTotalsOut", "ProductTotalsOut", "ProductProfitItemOut", "AlertOut"):  # fmt: skip
        assert name in schemas, name
    sales = schemas["PeriodTotalsOut"]["properties"]["net_satis_kdv_haric"]
    assert sales["type"] == "string"  # para OpenAPI'de de dizge
    assert "number" not in json.dumps(schemas["LineItemsOut"]["properties"]["net_kar"])
    assert "orderNumber" in schemas["LineOut"]["properties"]  # kablo adları şemada
    params = {p["name"] for p in spec["paths"][base + "/products"]["get"]["parameters"]}
    assert {"start", "end", "range", "sort", "order", "filter", "limit", "cursor"} <= params


@pytest.fixture
async def sessions(database: DatabaseInfo) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_engine_runs_off_the_event_loop_thread(
    sessions: async_sessionmaker[AsyncSession], shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def spy(profit_input: Any) -> Any:
        seen.append(threading.current_thread().name)
        return calculate_profit(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", spy)
    async with tenant_transaction(sessions, shop.tenant_id) as session:
        await period_profit(session, shop.tenant_id, shop.account_id, date(2026, 10, 1), date(2026, 10, 31))
    assert seen and seen[0] != threading.current_thread().name


def test_cursor_with_the_right_fingerprint_but_forged_contents_is_still_a_422(shop: Shop) -> None:
    """Doğru mühürlü (anahtar sahibi üretmiş) ama içeriği bozuk imleç: parmak izi geçse de 422."""
    codec = views.CursorCodec(shop.api.client.app.state.settings.master_key, shop.tenant_id, shop.account_id)  # type: ignore[attr-defined]
    base = f"{START}|{END}"
    forged: dict[str, tuple[str, list[str]]] = {
        "products": ("products|net_profit|desc|all|" + base, ["0", "NaN", B1]),
        f"products/{B1}": (f"lines|{B1}|" + base, ["1001", "x", "1"]),
        "alerts": ("alerts||" + base, ["1", "ZARAR", "1001", "x", "1"]),
    }
    for path, (fingerprint, parts) in forged.items():
        cursor = codec.encode(fingerprint, parts)
        r = call(shop, path, cursor=cursor)
        assert r.status_code == 422, path
        assert {"field": "cursor", "code": "cursor_invalid"} in r.json()["errors"]
