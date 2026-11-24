"""Ürün listesi `missing=true` süzgeci ve `total_missing` sayacı (maliyeti eksik ürünler).

"Bugün geçerli maliyet" kuralı motorla aynıdır: `valid_from <= bugün (İstanbul)`; gelecek tarihli kayıt
bugün geçerli değildir, eski kayıt yeni kayıt gelene kadar geçerlidir (bitiş tarihi yoktur).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from sqlalchemy.dialects import postgresql

from app.core import clock as clock_module
from app.profit.schema_v1 import ISTANBUL
from app.services import product_costs as costs
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import (
    TODAY_ISO,
    Shop,
    add_product,
    fixed_today,  # noqa: F401  (fixture)
    make_shop_factory,
)
from tests.test_rls_idor import app_tx

pytestmark = pytest.mark.usefixtures("fixed_today")

TODAY = date.fromisoformat(TODAY_ISO)


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


def put_cost(shop: Shop, barcode: str, valid_from: str, cost: str = "10.00") -> None:
    r = shop.api.put(
        f"{shop.base}/products/{barcode}/costs",
        {"valid_from": valid_from, "unit_cost_excl_vat": cost, "vat_rate": 20},
    )
    assert r.status_code == 200, r.text


def listing(shop: Shop, **params: Any) -> dict[str, Any]:
    r = shop.api.get(f"{shop.base}/products", params=params)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def barcodes(body: dict[str, Any]) -> list[str]:
    return [i["barcode"] for i in body["items"]]


def walk(shop: Shop, **params: Any) -> list[list[str]]:
    """Tüm sayfaları imleçle gezer; sayfaların barkod listelerini döner."""
    pages: list[list[str]] = []
    after: str | None = None
    for _ in range(100):
        body = listing(shop, **params, **({"after": after} if after else {}))
        pages.append(barcodes(body))
        after = body["next_cursor"]
        if after is None:
            return pages
    raise AssertionError("imleç sonlanmadı")


def seed_catalog(conn: psycopg.Connection[Any], shop: Shop) -> None:
    """Her durumdan bir ürün: C-* maliyeti var, M-* eksik."""
    for code in ("C1-past", "C2-today", "C3-superseded", "C4-past-and-future", "M1-none", "M2-future-only"):
        add_product(conn, shop, code, f"Ürün {code}")
    put_cost(shop, "C1-past", "2026-01-01")
    put_cost(shop, "C2-today", TODAY_ISO)  # sınır: bugün tarihli kayıt geçerlidir
    put_cost(shop, "C3-superseded", "2026-01-01", "10.00")
    put_cost(shop, "C3-superseded", "2026-09-01", "12.00")  # eskisini geçersiz kılar, maliyet var
    put_cost(shop, "C4-past-and-future", "2026-01-01")
    put_cost(shop, "C4-past-and-future", "2026-12-01")  # gelecek kayıt eski geçerli kaydı bozmaz
    put_cost(shop, "M2-future-only", "2026-11-09")  # yarın başlar: bugün geçerli değil
    put_cost(shop, "ORPHAN-no-product", "2026-01-01")  # ürünü olmayan maliyet sayıya girmez


def test_missing_filter_matches_current_cost_rule(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    seed_catalog(admin_conn, shop)
    everything = listing(shop)
    flagged = [i["barcode"] for i in everything["items"] if i["cost_missing"]]
    assert flagged == ["M1-none", "M2-future-only"]

    only_missing = listing(shop, missing="true")
    assert barcodes(only_missing) == ["M1-none", "M2-future-only"]
    assert all(i["cost_missing"] and i["current_cost"] is None for i in only_missing["items"])
    assert only_missing["next_cursor"] is None and only_missing["total_missing"] == 2

    # Varsayılan (parametresiz) ve missing=false eskisi gibi tüm ürünleri döner.
    assert len(everything["items"]) == 6
    assert barcodes(listing(shop, missing="false")) == barcodes(everything)
    by_code = {i["barcode"]: i for i in everything["items"]}
    assert by_code["C2-today"]["current_cost"]["valid_from"] == TODAY_ISO
    assert Decimal(by_code["C3-superseded"]["current_cost"]["unit_cost_excl_vat"]) == Decimal("12.00")
    assert by_code["C4-past-and-future"]["current_cost"]["valid_from"] == "2026-01-01"


def test_total_missing_counts_account_wide_regardless_of_filters(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    seed_catalog(admin_conn, shop)
    for params in (
        {},
        {"missing": "true"},
        {"limit": 1},
        {"limit": 1, "after": "C4-past-and-future"},
        {"q": "C1"},  # arama sonucunda eksik yok, sayaç yine hesap geneli
        {"q": "M1", "missing": "true"},
        {"after": "ZZZ"},  # boş sayfa
    ):
        assert listing(shop, **params)["total_missing"] == 2, params
    # Bütün ürünlerin maliyeti girilince sayaç 0 olur ve süzgeç boş döner.
    put_cost(shop, "M1-none", "2026-11-01")
    put_cost(shop, "M2-future-only", "2026-11-01")
    body = listing(shop, missing="true")
    assert body["items"] == [] and body["next_cursor"] is None and body["total_missing"] == 0


def test_missing_flag_follows_the_istanbul_day(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    add_product(admin_conn, shop, "M2-future-only")
    put_cost(shop, "M2-future-only", "2026-11-09")
    assert listing(shop, missing="true")["total_missing"] == 1
    # İstanbul'da 9 Kasım 00:30 (UTC'de hâlâ 8 Kasım): kayıt o gün geçerli olur.
    moment = datetime(2026, 11, 9, 0, 30, tzinfo=ISTANBUL).timestamp()
    monkeypatch.setattr(clock_module, "unix_time", lambda: moment)
    body = listing(shop, missing="true")
    assert body["items"] == [] and body["total_missing"] == 0


def test_missing_pagination_is_stable_and_complete(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    all_codes = [f"P{i:03d}" for i in range(40)]
    missing_codes = [
        c for i, c in enumerate(all_codes) if i % 3 == 0
    ]  # 14 eksik, araya maliyetliler serpiştirilmiş
    for code in all_codes:
        add_product(admin_conn, shop, code, f"Ürün {code}")
        if code not in missing_codes:
            put_cost(shop, code, "2026-06-01")
    pages = walk(shop, missing="true", limit=4)
    assert [len(p) for p in pages] == [4, 4, 4, 2]  # sayfalar dolu: süzgeç sayfalamadan önce
    flat = [c for p in pages for c in p]
    assert flat == missing_codes and len(set(flat)) == len(flat)
    # Süzgeçsiz gezinti ile eksik bayrağı aynı kümeyi verir.
    unfiltered = walk(shop, limit=7)
    assert [c for p in unfiltered for c in p] == all_codes

    # Tam sınır: sayfa boyutu eksik sayısına eşitken fazladan boş sayfa dönmez.
    exact = walk(shop, missing="true", limit=14)
    assert exact == [missing_codes]
    # `q` ile birlikte: kesişim, aynı sırada.
    with_q = walk(shop, missing="true", limit=3, q="P03")
    assert [c for p in with_q for c in p] == [c for c in missing_codes if c.startswith("P03")]


def test_cursor_survives_cost_entry_between_pages(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    for i in range(6):
        add_product(admin_conn, shop, f"K{i}")
    first = listing(shop, missing="true", limit=2)
    assert barcodes(first) == ["K0", "K1"] and first["next_cursor"] == "K1"
    put_cost(shop, "K2", "2026-06-01")  # sayfalar arasında bir ürünün maliyeti girildi
    put_cost(shop, "K0", "2026-06-01")  # imleçten ÖNCEKİ ürün de değişti
    second = listing(shop, missing="true", limit=2, after=first["next_cursor"])
    assert barcodes(second) == ["K3", "K4"] and second["total_missing"] == 4


def test_tenant_and_account_isolation(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a = make_shop("a@example.com", "Mağaza A")
    b = make_shop("b@example.com", "Mağaza B", seller_id="9999")
    for code in ("S1", "S2", "S3"):
        add_product(admin_conn, a, code)
        add_product(admin_conn, b, code)  # aynı barkodlar iki kiracıda
    add_product(admin_conn, b, "ONLY-B")
    put_cost(a, "S1", "2026-06-01")  # yalnız A'nın S1'i maliyetli
    put_cost(b, "S2", "2026-06-01")
    put_cost(b, "S3", "2026-06-01")
    put_cost(b, "ONLY-B", "2026-06-01")

    la, lb = listing(a, missing="true"), listing(b, missing="true")
    assert barcodes(la) == ["S2", "S3"] and la["total_missing"] == 2
    assert barcodes(lb) == ["S1"] and lb["total_missing"] == 1
    # Başka kiracının hesabı yolda: 404 (varlık sızdırılmaz), sayaç da sızmaz.
    r = a.api.get(f"{b.base}/products", params={"missing": "true"})
    assert r.status_code == 404 and "total_missing" not in r.text


def test_missing_requires_boolean(shop: Shop) -> None:
    r = shop.api.get(f"{shop.base}/products", params={"missing": "belki"})
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:validation-error"


def test_missing_filter_respects_row_level_security(
    shop: Shop, database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    """Yanlış kiracı bağlamı altında aynı sorgu hiçbir şey görmez (FORCE RLS), sayaç 0 olur."""
    seed_catalog(admin_conn, shop)
    stmt = costs.products_page_stmt(
        shop.tenant_id, shop.account_id, TODAY, search=None, after=None, limit=10, missing_only=True
    )
    sql = _literal(stmt)
    with app_tx(database, str(shop.tenant_id)) as conn:
        assert [r[0] for r in conn.execute(sql).fetchall()] == ["M1-none", "M2-future-only"]
    with app_tx(database, "00000000-0000-0000-0000-000000000001") as conn:
        assert conn.execute(sql).fetchall() == []
    with app_tx(database, None) as conn:
        assert conn.execute(sql).fetchall() == []


# --- sorgu planı ve ölçek (duvar saati eşiği YOK: plan düğümleri ve satır sayıları) --------------------


def _literal(stmt: Any) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _nodes(plan: dict[str, Any]) -> list[dict[str, Any]]:
    out = [plan]
    for child in plan.get("Plans", []):
        out.extend(_nodes(child))
    return out


def _explain(conn: psycopg.Connection[Any], sql: str, *, analyze: bool = False) -> list[dict[str, Any]]:
    opts = "ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON"
    row = conn.execute(f"EXPLAIN ({opts}) {sql}").fetchone()
    assert row is not None
    data = row[0] if isinstance(row[0], list) else json.loads(row[0])
    return _nodes(data[0]["Plan"])


@pytest.fixture
def big_shop(shop: Shop, admin_conn: psycopg.Connection[Any]) -> Shop:
    """4000 ürün; ilk 30'unun (barkod sırasıyla) maliyeti eksik, kalanın maliyeti var."""
    with admin_conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title, vat_rate) "
            "VALUES (%s, %s, %s, %s, 20)",
            [(shop.tenant_id, shop.account_id, f"Z{i:05d}", f"Ürün {i}") for i in range(4000)],
        )
        cur.executemany(
            "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, "
            "unit_cost_excl_vat, vat_rate, entered_by) VALUES (%s, %s, %s, '2026-01-01', 10, 20, %s)",
            [(shop.tenant_id, shop.account_id, f"Z{i:05d}", shop.user_id) for i in range(30, 4000)],
        )
    admin_conn.execute("ANALYZE products")
    admin_conn.execute("ANALYZE product_costs")
    return shop


def test_missing_queries_use_indexes_without_seq_scans(big_shop: Shop, database: DatabaseInfo) -> None:
    page = costs.products_page_stmt(
        big_shop.tenant_id,
        big_shop.account_id,
        TODAY,
        search=None,
        after="Z00009",
        limit=20,
        missing_only=True,
    )
    count = costs.missing_count_stmt(big_shop.tenant_id, big_shop.account_id, TODAY)
    with app_tx(database, str(big_shop.tenant_id)) as conn:
        # Seq Scan kapatılır: indeks yolu varsa planda hiç Seq Scan düğümü kalmaz (yoksa kalırdı).
        conn.execute("SET LOCAL enable_seqscan = off")
        for stmt in (page, count):
            nodes = _explain(conn, _literal(stmt))
            kinds = {n["Node Type"] for n in nodes}
            assert "Seq Scan" not in kinds, kinds
            scanned = {n["Index Name"] for n in nodes if "Index Name" in n}
            # Her iki tablo da bir indeksten okunur (sayaçta bitmap, sayfada sıralı indeks taraması olabilir).
            assert any("product_costs" in name for name in scanned), scanned
            assert any("products" in name for name in scanned), scanned
        page_scanned = {n["Index Name"] for n in _explain(conn, _literal(page)) if "Index Name" in n}
        assert {"uq_products_account_barcode", "uq_product_costs_account_barcode_from"} <= page_scanned
        page_nodes = _explain(conn, _literal(page))
        products_scan = next(n for n in page_nodes if n.get("Relation Name") == "products")
        # Keyset: `after` koşulu indeks koşulunda (baştan taranmaz), sıralama indeksten gelir (Sort yok).
        assert "barcode" in products_scan.get("Index Cond", ""), products_scan
        assert "Sort" not in {n["Node Type"] for n in page_nodes}


def test_missing_page_stops_early_and_count_is_exact(big_shop: Shop, database: DatabaseInfo) -> None:
    page = costs.products_page_stmt(
        big_shop.tenant_id, big_shop.account_id, TODAY, search=None, after=None, limit=10, missing_only=True
    )
    with app_tx(database, str(big_shop.tenant_id)) as conn:
        nodes = _explain(conn, _literal(page), analyze=True)
        products_scan = next(n for n in nodes if n.get("Relation Name") == "products")
        # LIMIT 11 eksik satırı bulunca durur: 4000 ürünün tamamı taranmaz (satır sayısı belirleyici, saat değil).
        assert products_scan["Actual Rows"] <= 40, products_scan["Actual Rows"]
    body = listing(big_shop, missing="true", limit=10)
    assert len(body["items"]) == 10 and body["next_cursor"] == "Z00009" and body["total_missing"] == 30
    last = listing(big_shop, missing="true", limit=10, after="Z00019")
    assert barcodes(last)[0] == "Z00020" and len(last["items"]) == 10 and last["next_cursor"] is None
    tail = listing(big_shop, missing="true", limit=10, after="Z00029")
    assert tail["items"] == [] and tail["next_cursor"] is None
