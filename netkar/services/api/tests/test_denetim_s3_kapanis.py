"""S3 kapanış turu (YK-01, YK-03) API düzeyi regresyon testleri: akışlı XLSX okuyucusu uçtan uca ve şablon üretimi.

Birim düzeyindeki ayrıntılı testler `test_cost_import_stream.py` içindedir. Burada yalnız HTTP yolu sınanır.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import psycopg
import pytest

from app.api.v1 import product_costs as product_costs_module
from app.services import cost_import
from tests.conftest import Api
from tests.product_cost_helpers import (
    B1,
    B2,
    Shop,
    add_product,
    fixed_today,  # noqa: F401  (fixture)
    make_shop_factory,
    upload,
)
from tests.test_cost_import_stream import (
    content_types,
    package,
    poc_sheet_junk,
    poc_sst_redirect,
    poc_wide_row,
    sheet_xml,
    sst_xml,
    styles_xml,
    with_sheet,
)

pytestmark = pytest.mark.usefixtures("fixed_today")


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


@pytest.mark.parametrize("build", [poc_wide_row, poc_sheet_junk, poc_sst_redirect])
def test_yk01_poc_uploads_get_422_fast_over_http(shop: Shop, build: Callable[[], bytes]) -> None:
    data = build()
    assert len(data) < 2 * 1024 * 1024
    started = time.perf_counter()
    r = upload(shop, data, "poc.xlsx")
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:import-file-invalid"
    assert time.perf_counter() - started < 5.0  # HTTP, kimlik, DB ve kapsam yükü dahil; eski kod 6 sn üstü
    # sonraki normal istek etkilenmez (kiracı kilidi ve yuva bırakıldı)
    assert upload(shop, b"barkod;birim_maliyet_kdv_haric;kdv_orani\r\n", "ok.csv").status_code == 200


def test_yk01_date_styled_serial_numbers_and_shared_strings_import_end_to_end(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    """Tarih sütunu Excel seri sayısı (46296 = 2026-10-01) ve tarih biçimli stil; barkod paylaşılan dize."""
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c>'
        '<c r="D1" t="s"><v>3</v></c></row>'
        f'<row r="2"><c r="A2" t="s"><v>4</v></c><c r="B2"><v>12.5</v></c><c r="C2"><v>20</v></c>'
        '<c r="D2" s="2"><v>46296</v></c></row>'
        f'<row r="3"><c r="A3" t="inlineStr"><is><t>{B2}</t></is></c><c r="B3"><v>7</v></c><c r="C3"><v>0</v></c>'
        '<c r="D3" s="1"><v>46296</v></c></row>'
        f'<row r="4"><c r="A4"><v>{int(B1) + 1}</v></c><c r="B4"><v>1</v></c><c r="C4"><v>20</v></c>'
        '<c r="D4"><v>46296</v></c></row>'
    )
    strings = sst_xml("barkod", "birim_maliyet_kdv_haric", "kdv_orani", "gecerlilik_tarihi", B1)
    data = package(
        {
            "[Content_Types].xml": content_types(),
            "xl/worksheets/sheet1.xml": sheet_xml(rows),
            "xl/sharedStrings.xml": strings,
            "xl/styles.xml": styles_xml(),
        }
    )
    for product in (B1, B2):
        add_product(admin_conn, shop, product)
    report = upload(shop, data, "seri.xlsx", dry_run=False, allow_partial=True).json()
    # B1 ve B2: biçimli tarih (stil 2 özel, stil 1 yerleşik 14) geçerli; son satır biçimsiz seri sayı: tarih hatası
    assert report["valid"] == 2 and report["invalid"] == 1, report
    assert [e["column"] for e in report["errors"]] == ["gecerlilik_tarihi"]
    rows_db = admin_conn.execute(
        "SELECT barcode, valid_from FROM product_costs WHERE marketplace_account_id = %s ORDER BY barcode",
        (shop.account_id,),
    ).fetchall()
    assert [(r[0], r[1]) for r in rows_db] == [(B1, date(2026, 10, 1)), (B2, date(2026, 10, 1))]


def test_yk01_too_many_columns_over_http_is_422(shop: Shop) -> None:
    cells = "".join(f"<c><v>{i}</v></c>" for i in range(51))
    r = upload(shop, with_sheet(f"<row>{cells}</row>"), "genis.xlsx")
    assert r.status_code == 422 and "50 sütun" in r.json()["detail"]


def test_yk03_template_is_built_off_the_event_loop(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    add_product(admin_conn, shop, B1, "Şık Çanta")
    real = cost_import.build_template_csv
    seen: list[int] = []

    def spy(products: Any) -> bytes:
        seen.append(threading.get_ident())
        return real(products)

    monkeypatch.setattr(product_costs_module, "build_template_csv", spy)
    r = shop.api.get(f"{shop.base}/product-costs/template.csv")
    assert r.status_code == 200 and B1 in r.content.decode("utf-8-sig")
    assert len(seen) == 1 and seen[0] != threading.get_ident()  # olay döngüsü iş parçacığında değil


def test_yk03_template_with_huge_tab_title_is_fast_and_truncated(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_product(admin_conn, shop, B1, "x" + "\t" * 200_000 + "y")
    started = time.perf_counter()
    r = shop.api.get(f"{shop.base}/product-costs/template.csv")
    assert r.status_code == 200 and time.perf_counter() - started < 2.0
    assert len(r.content) < 4096  # başlık 500 karakterde kesildi
