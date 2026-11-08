"""Ürün maliyeti API'si: listeleme, geçmiş, upsert, roller, IDOR, doğrulama, hız sınırı, şablon."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.api.v1 import product_costs as product_costs_module
from tests.conftest import Api
from tests.product_cost_helpers import (
    B1,
    B2,
    B3,
    TODAY_ISO,
    Shop,
    add_product,
    audit_actions,
    count_costs,
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


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop]) -> tuple[Shop, Shop]:
    return make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")


def put_cost(shop: Shop, barcode: str = B1, **body: Any) -> Any:
    payload = {"valid_from": "2026-10-01", "unit_cost_excl_vat": "50.00", "vat_rate": 20, **body}
    return shop.api.put(f"{shop.base}/products/{barcode}/costs", payload)


# --- GET products ----------------------------------------------------------------------------------


def test_list_products_shows_current_cost_and_missing_flag(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1, "Kırmızı Tişört", "STK-1")
    add_product(admin_conn, shop, B2, "Mavi Pantolon")
    assert put_cost(shop, B1, valid_from="2026-01-01", unit_cost_excl_vat="40.00").status_code == 200
    assert put_cost(shop, B1, valid_from="2026-10-01", unit_cost_excl_vat="50.5").status_code == 200
    # Gelecek tarihli kayıt bugün geçerli değildir.
    assert put_cost(shop, B1, valid_from="2026-12-01", unit_cost_excl_vat="99.00").status_code == 200

    r = shop.api.get(f"{shop.base}/products")
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["barcode"] for i in items] == [B1, B2] and r.json()["next_cursor"] is None
    assert items[0]["current_cost"] == {
        "valid_from": "2026-10-01",
        "unit_cost_excl_vat": "50.50",
        "vat_rate": 20,
    }
    assert items[0]["cost_missing"] is False and items[0]["stock_code"] == "STK-1"
    assert (
        items[1]["current_cost"] is None
        and items[1]["cost_missing"] is True
        and items[1]["title"] == "Mavi Pantolon"
    )


def test_list_products_only_future_cost_counts_as_missing(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1)
    assert put_cost(shop, B1, valid_from="2026-12-01").status_code == 200
    item = shop.api.get(f"{shop.base}/products").json()["items"][0]
    assert item["cost_missing"] is True and item["current_cost"] is None


def test_list_products_pagination_and_search(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    for i in range(5):
        add_product(admin_conn, shop, f"B{i}", f"Ürün {i}")
    add_product(admin_conn, shop, "X%_9", "Yüzde 100%_indirim")
    first = shop.api.get(f"{shop.base}/products", params={"limit": 2}).json()
    assert [i["barcode"] for i in first["items"]] == ["B0", "B1"] and first["next_cursor"] == "B1"
    second = shop.api.get(f"{shop.base}/products", params={"limit": 2, "after": first["next_cursor"]}).json()
    assert [i["barcode"] for i in second["items"]] == ["B2", "B3"]
    last = shop.api.get(f"{shop.base}/products", params={"limit": 2, "after": second["next_cursor"]}).json()
    assert [i["barcode"] for i in last["items"]] == ["B4", "X%_9"] and last["next_cursor"] is None

    by_title = shop.api.get(f"{shop.base}/products", params={"q": "rün 3"}).json()
    assert [i["barcode"] for i in by_title["items"]] == ["B3"]
    by_barcode = shop.api.get(f"{shop.base}/products", params={"q": "b4"}).json()
    assert [i["barcode"] for i in by_barcode["items"]] == ["B4"]
    # LIKE jokerleri düz metindir: "%" ve "_" her şeyle eşleşmez.
    literal = shop.api.get(f"{shop.base}/products", params={"q": "%_"}).json()
    assert [i["barcode"] for i in literal["items"]] == ["X%_9"]
    # SQL enjeksiyonu denemesi parametre olarak bağlanır, sonuç yok.
    assert shop.api.get(f"{shop.base}/products", params={"q": "' OR 1=1 --"}).json()["items"] == []


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"limit": "x"}, {"q": ""}, {"q": "a" * 101}]
)
def test_list_products_validates_query(shop: Shop, params: dict[str, Any]) -> None:
    r = shop.api.get(f"{shop.base}/products", params=params)
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == "urn:netkar:problem:validation-error"


def test_limit_200_is_accepted(shop: Shop) -> None:
    assert shop.api.get(f"{shop.base}/products", params={"limit": 200}).status_code == 200


# --- GET history, PUT upsert --------------------------------------------------------------------------


def test_put_upserts_by_valid_from_and_history_is_descending(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1)
    r = put_cost(shop, valid_from="2026-10-01", unit_cost_excl_vat="50.00")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "barcode": B1,
        "product_known": True,
        "created": True,
        "cost": {"valid_from": "2026-10-01", "unit_cost_excl_vat": "50.00", "vat_rate": 20},
    }
    # Aynı geçerlilik tarihi: günceller, ikinci satır eklemez.
    r2 = put_cost(shop, valid_from="2026-10-01", unit_cost_excl_vat=55.25, vat_rate=10)
    assert r2.status_code == 200 and r2.json()["created"] is False
    assert r2.json()["cost"] == {"valid_from": "2026-10-01", "unit_cost_excl_vat": "55.25", "vat_rate": 10}
    assert put_cost(shop, valid_from="2026-11-01", unit_cost_excl_vat="60").status_code == 200
    assert count_costs(admin_conn, shop) == 2

    history = shop.api.get(f"{shop.base}/products/{B1}/costs")
    assert history.status_code == 200
    assert history.json() == {
        "barcode": B1,
        "product_known": True,
        "items": [
            {"valid_from": "2026-11-01", "unit_cost_excl_vat": "60.00", "vat_rate": 20},
            {"valid_from": "2026-10-01", "unit_cost_excl_vat": "55.25", "vat_rate": 10},
        ],
    }
    stored = admin_conn.execute(
        "SELECT entered_by, updated_at >= created_at FROM product_costs LIMIT 1"
    ).fetchone()
    assert stored is not None and stored[0] == shop.user_id and stored[1] is True


def test_put_unknown_barcode_is_accepted_with_product_known_false(shop: Shop) -> None:
    r = put_cost(shop, "HENUZ-SENKRON-YOK")
    assert r.status_code == 200 and r.json()["product_known"] is False
    history = shop.api.get(f"{shop.base}/products/HENUZ-SENKRON-YOK/costs").json()
    assert history["product_known"] is False and len(history["items"]) == 1


def test_history_known_product_without_costs_is_empty_and_unknown_is_404(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1)
    r = shop.api.get(f"{shop.base}/products/{B1}/costs")
    assert r.status_code == 200 and r.json() == {"barcode": B1, "product_known": True, "items": []}
    missing = shop.api.get(f"{shop.base}/products/{B3}/costs")
    assert missing.status_code == 404 and missing.json()["type"] == "urn:netkar:problem:not-found"


def test_put_audit_trail_has_barcode_and_date_but_no_amounts(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    put_cost(shop, B1, unit_cost_excl_vat="123.45")
    entries = audit_actions(admin_conn, shop)
    assert entries == [("product_cost.upserted", {"barcode": B1, "valid_from": "2026-10-01"})]
    dumped = admin_conn.execute("SELECT meta::text || coalesce(target, '') FROM audit_log").fetchall()
    assert "123.45" not in str(dumped) and "50.00" not in str(dumped)


@pytest.mark.parametrize(
    ("body", "field", "code"),
    [
        ({"unit_cost_excl_vat": "0"}, "unit_cost_excl_vat", "cost_not_positive"),
        ({"unit_cost_excl_vat": -1}, "unit_cost_excl_vat", "cost_not_positive"),
        ({"unit_cost_excl_vat": "10000000.01"}, "unit_cost_excl_vat", "cost_too_large"),
        ({"unit_cost_excl_vat": 1e30}, "unit_cost_excl_vat", "cost_too_large"),
        ({"unit_cost_excl_vat": "12.345"}, "unit_cost_excl_vat", "cost_too_many_decimals"),
        ({"unit_cost_excl_vat": 12.345}, "unit_cost_excl_vat", "cost_too_many_decimals"),
        ({"unit_cost_excl_vat": "abc"}, "unit_cost_excl_vat", "decimal_invalid"),
        ({"unit_cost_excl_vat": "1e3"}, "unit_cost_excl_vat", "decimal_invalid"),
        ({"unit_cost_excl_vat": "NaN"}, "unit_cost_excl_vat", "decimal_invalid"),
        ({"unit_cost_excl_vat": True}, "unit_cost_excl_vat", "decimal_invalid"),
        ({"unit_cost_excl_vat": None}, "unit_cost_excl_vat", "decimal_type"),
        ({"vat_rate": 5}, "vat_rate", "vat_rate_invalid"),
        ({"vat_rate": 0.2}, "vat_rate", "vat_rate_invalid"),
        ({"vat_rate": 21}, "vat_rate", "vat_rate_invalid"),
        ({"vat_rate": "yirmi"}, "vat_rate", "decimal_invalid"),
        ({"valid_from": "1999-12-31"}, "valid_from", "valid_from_out_of_range"),
        ({"valid_from": (TODAY + timedelta(days=367)).isoformat()}, "valid_from", "valid_from_out_of_range"),
        ({"valid_from": "2026-13-45"}, "valid_from", "date_from_datetime_parsing"),
        ({"valid_from": 1790000000}, "valid_from", "date_type"),
        ({"valid_from": None}, "valid_from", "date_type"),
        ({"fazladan": 1}, "fazladan", "extra_forbidden"),
    ],
)
def test_put_rejects_invalid_input_with_problem_details(
    shop: Shop, body: dict[str, Any], field: str, code: str
) -> None:
    r = put_cost(shop, **body)
    assert r.status_code == 422, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    problem = r.json()
    assert problem["type"] == "urn:netkar:problem:validation-error" and problem["status"] == 422
    assert {"field": field, "code": code} in problem["errors"], problem["errors"]
    assert "request_id" in problem and "input" not in r.text.lower()


def test_put_missing_fields_and_bad_barcode(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    r = shop.api.put(f"{shop.base}/products/{B1}/costs", {})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} == {
        "valid_from",
        "unit_cost_excl_vat",
        "vat_rate",
    }
    for bad in ("=1+1", "-x", "@a", "a%20b", "a" * 201, ".nokta", "a;b"):
        resp = shop.api.put(
            f"{shop.base}/products/{bad}/costs",
            {"valid_from": "2026-10-01", "unit_cost_excl_vat": "1", "vat_rate": 0},
        )
        assert resp.status_code in {404, 422}, bad  # 404: yol eşleşmez (örn. '/' içeren), 422: allowlist
    assert count_costs(admin_conn, shop) == 0


@pytest.mark.parametrize(
    "body",
    [
        {"valid_from": "2000-01-01", "unit_cost_excl_vat": "0.01", "vat_rate": 0},
        {
            "valid_from": (TODAY + timedelta(days=366)).isoformat(),
            "unit_cost_excl_vat": "10000000",
            "vat_rate": 1,
        },
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": 12.5, "vat_rate": 10.0},
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": "12.50", "vat_rate": "20"},
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": 7, "vat_rate": 20},
    ],
)
def test_put_boundaries_are_accepted(shop: Shop, body: dict[str, Any]) -> None:
    assert put_cost(shop, **body).status_code == 200


def test_put_float_json_number_keeps_exact_decimal(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    assert put_cost(shop, unit_cost_excl_vat=0.1).status_code == 200
    stored = admin_conn.execute("SELECT unit_cost_excl_vat FROM product_costs").fetchone()
    assert stored is not None and stored[0] == Decimal("0.1")


# --- roller ve kimlik ------------------------------------------------------------------------------------


def test_viewer_can_read_but_not_write(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    add_product(admin_conn, shop, B1)
    assert put_cost(shop).status_code == 200
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert shop.api.get(f"{shop.base}/products").status_code == 200
    assert shop.api.get(f"{shop.base}/products/{B1}/costs").status_code == 200
    assert shop.api.get(f"{shop.base}/product-costs/template.csv").status_code == 200
    denied = put_cost(shop, unit_cost_excl_vat="1.00")
    assert denied.status_code == 403 and denied.json()["type"] == "urn:netkar:problem:forbidden"
    imp = shop.api.post(
        f"{shop.base}/product-costs/import", None, files={"file": ("a.csv", b"x", "text/csv")}
    )
    assert imp.status_code == 403
    assert count_costs(admin_conn, shop) == 1


def test_admin_role_can_write(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    admin_conn.execute("UPDATE memberships SET role = 'admin'")
    assert put_cost(shop).status_code == 200


def test_endpoints_require_authentication(shop: Shop, make_api: Callable[..., Api]) -> None:
    anon = make_api()
    assert anon.get(f"{shop.base}/products").status_code == 401
    assert anon.get(f"{shop.base}/products/{B1}/costs").status_code == 401
    assert anon.get(f"{shop.base}/product-costs/template.csv").status_code == 401
    r = anon.put(
        f"{shop.base}/products/{B1}/costs",
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": "1", "vat_rate": 0},
    )
    assert r.status_code == 401


def test_put_requires_csrf_token(shop: Shop) -> None:
    r = shop.api.put(
        f"{shop.base}/products/{B1}/costs",
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": "1", "vat_rate": 0},
        csrf=False,
    )
    assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:csrf-failed"


# --- IDOR / RLS --------------------------------------------------------------------------------------------


def test_other_tenant_gets_404_on_every_endpoint_and_nothing_leaks(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    add_product(admin_conn, a, B1, "Gizli Ürün A")
    assert put_cost(a, B1, unit_cost_excl_vat="77.77").status_code == 200

    target = a.base  # B oturumu, A'nın hesap kimliğiyle
    assert b.api.get(f"{target}/products").status_code == 404
    assert b.api.get(f"{target}/products/{B1}/costs").status_code == 404
    assert b.api.get(f"{target}/product-costs/template.csv").status_code == 404
    body = {"valid_from": "2026-10-01", "unit_cost_excl_vat": "1.00", "vat_rate": 20}
    assert b.api.put(f"{target}/products/{B1}/costs", body).status_code == 404
    assert b.api.put(f"{target}/products/{B2}/costs", body).status_code == 404
    imp = b.api.post(
        f"{target}/product-costs/import",
        None,
        files={
            "file": ("a.csv", f"barkod;birim_maliyet_kdv_haric;kdv_orani\n{B1};1;20\n".encode(), "text/csv")
        },
        params={"dry_run": "false"},
    )
    assert imp.status_code == 404 and "Gizli" not in imp.text
    assert (
        b.api.get("/v1/marketplace-accounts/00000000-0000-0000-0000-000000000000/products").status_code == 404
    )

    # A'nın verisi değişmedi ve B hiçbir şey yazmadı.
    row = admin_conn.execute("SELECT unit_cost_excl_vat, count(*) OVER () FROM product_costs").fetchall()
    assert [(r[0], r[1]) for r in row] == [(Decimal("77.770000"), 1)]
    # B kendi hesabında A'nın barkodunu göremez.
    assert b.api.get(f"{b.base}/products").json()["items"] == []
    assert b.api.get(f"{b.base}/products/{B1}/costs").status_code == 404


def test_rls_hides_cost_rows_from_other_tenant_at_database_level(
    two_shops: tuple[Shop, Shop], database: Any, admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    assert put_cost(a, B1).status_code == 200
    with app_tx(database, str(b.tenant_id)) as conn:
        assert conn.execute("SELECT count(*) FROM product_costs").fetchone() == (0,)
        # B bağlamıyla A'nın hesabına yazma denemesi RLS WITH CHECK ile reddedilir.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, unit_cost_excl_vat, "
                "vat_rate, entered_by) VALUES (%s, %s, 'X', '2026-10-01', 1, 20, %s)",
                (a.tenant_id, a.account_id, b.user_id),
            )


# --- hız sınırı --------------------------------------------------------------------------------------------


def test_cost_write_is_rate_limited_per_tenant(make_shop: Callable[..., Shop]) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_cost_write_tenant=2)
    assert put_cost(shop).status_code == 200 and put_cost(shop).status_code == 200
    limited = put_cost(shop)
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert limited.json()["type"] == "urn:netkar:problem:rate-limited"


def test_template_is_rate_limited_per_tenant(make_shop: Callable[..., Shop]) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_cost_template_tenant=1)
    assert shop.api.get(f"{shop.base}/product-costs/template.csv").status_code == 200
    assert shop.api.get(f"{shop.base}/product-costs/template.csv").status_code == 429


# --- şablon ------------------------------------------------------------------------------------------------


def test_template_is_utf8_bom_attachment_with_products_and_empty_costs(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1, "Şık Çanta İğne")
    add_product(admin_conn, shop, B2, None)
    r = shop.api.get(f"{shop.base}/product-costs/template.csv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="maliyet_sablonu.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf")
    lines = r.content.decode("utf-8-sig").splitlines()
    assert lines[0] == "barkod;baslik;birim_maliyet_kdv_haric;kdv_orani;gecerlilik_tarihi"
    assert lines[1] == f"{B1};Şık Çanta İğne;;;" and lines[2] == f"{B2};;;;"
    assert len(lines) == 3 and "X-Template-Truncated" not in r.headers


def test_template_neutralizes_formula_injection(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    add_product(admin_conn, shop, "A1", "=1+1")
    add_product(admin_conn, shop, "A2", "+SUM(A1)")
    add_product(admin_conn, shop, "A3", "-2+3")
    add_product(admin_conn, shop, "A4", "@cmd")
    add_product(admin_conn, shop, "A5", "\t=tab")
    add_product(admin_conn, shop, "A6", "\r=cr")
    add_product(admin_conn, shop, "A7", "Normal = başlık")
    add_product(admin_conn, shop, "-NEG", "ok")
    text = shop.api.get(f"{shop.base}/product-costs/template.csv").content.decode("utf-8-sig")
    rows = {line.split(";")[0]: line for line in text.replace("\r\n", "\n").split("\n")[1:] if line}
    assert rows["A1"].startswith("A1;'=1+1;")
    assert rows["A2"].startswith("A2;'+SUM(A1);")
    assert rows["A3"].startswith("A3;'-2+3;")
    assert rows["A4"].startswith("A4;'@cmd;")
    assert "'\t=tab" in text and "'\r=cr" in text
    assert rows["A7"].startswith("A7;Normal = başlık;")  # ortadaki '=' dokunulmaz
    assert rows["'-NEG"].startswith("'-NEG;ok;")  # barkod hücresi de kaçırılır


def test_template_marks_truncation(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(3):
        add_product(admin_conn, shop, f"T{i}")
    monkeypatch.setattr(product_costs_module, "TEMPLATE_MAX_ROWS", 2)
    r = shop.api.get(f"{shop.base}/product-costs/template.csv")
    assert (
        r.headers["X-Template-Truncated"] == "true" and len(r.content.decode("utf-8-sig").splitlines()) == 3
    )
