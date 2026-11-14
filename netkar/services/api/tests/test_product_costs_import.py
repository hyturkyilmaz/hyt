"""Toplu maliyet içe aktarma: CSV/XLSX biçimleri, iki aşama, güvenlik sınırları, XXE, zip bombası, formül."""

from __future__ import annotations

import io
import struct
import zipfile
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from app.services import cost_import
from tests.conftest import Api
from tests.product_cost_helpers import (
    B1,
    B2,
    B3,
    HEADER_TR,
    Shop,
    add_product,
    audit_actions,
    count_costs,
    csv_bytes,
    fixed_today,  # noqa: F401  (fixture)
    make_shop_factory,
    rewrite_zip,
    upload,
    xlsx_bytes,
)

pytestmark = pytest.mark.usefixtures("fixed_today")


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


def costs_of(conn: psycopg.Connection[Any], shop: Shop) -> dict[tuple[str, date], tuple[Decimal, Decimal]]:
    rows = conn.execute(
        "SELECT barcode, valid_from, unit_cost_excl_vat, vat_rate FROM product_costs WHERE marketplace_account_id = %s",
        (shop.account_id,),
    ).fetchall()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


# --- iki aşama ---------------------------------------------------------------------------------------------


def test_dry_run_is_default_and_writes_nothing(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    add_product(admin_conn, shop, B1)
    r = upload(shop, csv_bytes(f"{B1};12,50;20;2026-10-01", f"{B2};3.5;10;"))
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["dry_run"] is True and report["committed"] is False and report["format"] == "csv"
    assert (report["total"], report["valid"], report["invalid"], report["skipped"]) == (2, 2, 0, 0)
    assert report["created"] is None and report["updated"] is None and report["errors"] == []
    assert report["unknown_barcodes"] == 1  # B2 ürün tablosunda yok (kabul edilir, uyarı olarak sayılır)
    assert count_costs(admin_conn, shop) == 0 and audit_actions(admin_conn, shop) == []
    explicit = upload(shop, csv_bytes(f"{B1};12,50;20;2026-10-01"), dry_run=True)
    assert explicit.json()["dry_run"] is True and count_costs(admin_conn, shop) == 0


def test_real_import_upserts_in_one_transaction_and_audits_counts(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    first = upload(shop, csv_bytes(f"{B1};12,50;20;2026-10-01", f"{B2};3.5;10;2026-10-01"), dry_run=False)
    assert first.status_code == 200, first.text
    assert first.json()["committed"] is True and (first.json()["created"], first.json()["updated"]) == (2, 0)
    assert costs_of(admin_conn, shop) == {
        (B1, date(2026, 10, 1)): (Decimal("12.5"), Decimal("20")),
        (B2, date(2026, 10, 1)): (Decimal("3.5"), Decimal("10")),
    }
    second = upload(shop, csv_bytes(f"{B1};15;10;2026-10-01", f"{B3};1;0;2026-10-02"), dry_run=False)
    assert (second.json()["created"], second.json()["updated"]) == (1, 1)
    assert costs_of(admin_conn, shop)[(B1, date(2026, 10, 1))] == (Decimal("15"), Decimal("10"))
    actions = audit_actions(admin_conn, shop)
    assert [a for a, _ in actions] == ["product_cost.imported", "product_cost.imported"]
    assert actions[0][1] == {
        "format": "csv", "total": 2, "valid": 2, "invalid": 0, "skipped": 0, "created": 2, "updated": 0, "partial": False,
    }  # fmt: skip
    assert "12.5" not in str(actions)  # tutarlar denetim kaydında yok


def test_errors_block_everything_unless_allow_partial(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    data = csv_bytes(f"{B1};12,50;20;2026-10-01", f"{B2};-5;20;2026-10-01", f"{B3};4;7;2026-10-01")
    blocked = upload(shop, data, dry_run=False)
    assert blocked.status_code == 422
    assert blocked.headers["content-type"].startswith("application/problem+json")
    problem = blocked.json()
    assert problem["type"] == "urn:netkar:problem:import-validation-failed"
    assert (
        problem["report"]["valid"] == 1
        and problem["report"]["invalid"] == 2
        and problem["report"]["committed"] is False
    )
    assert count_costs(admin_conn, shop) == 0 and audit_actions(admin_conn, shop) == []

    partial = upload(shop, data, dry_run=False, allow_partial=True)
    assert (
        partial.status_code == 200 and partial.json()["committed"] is True and partial.json()["created"] == 1
    )
    assert list(costs_of(admin_conn, shop)) == [(B1, date(2026, 10, 1))]
    assert (
        audit_actions(admin_conn, shop)[0][1]["partial"] is True
        and audit_actions(admin_conn, shop)[0][1]["invalid"] == 2
    )


def test_dry_run_reports_row_numbers_columns_and_turkish_reasons(shop: Shop) -> None:
    data = csv_bytes(
        f"{B1};10;20;2026-10-01",
        f"{B2};abc;20;2026-10-01",
        f"{B3};5;7;31.02.2026",
        ";5;20;2026-10-01",
        f"{B1};10;20;2026-10-01",
    )
    report = upload(shop, data).json()
    assert (report["total"], report["valid"], report["invalid"]) == (5, 1, 4)
    errors = {(e["row"], e["column"]): e["message"] for e in report["errors"]}
    assert errors[(3, "birim_maliyet_kdv_haric")].startswith("Sayı olarak okunamadı")
    assert errors[(4, "kdv_orani")].startswith("KDV oranı yüzde olarak")
    assert errors[(4, "gecerlilik_tarihi")].startswith("Tarih YYYY-AA-GG")
    assert errors[(5, "barkod")] == "Barkod boş olamaz."
    assert errors[(6, "barkod")] == "Aynı barkod ve geçerlilik tarihi satır 2'de zaten var."


# --- CSV biçimleri ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("12,5", "12.5"),
        ("12.5", "12.5"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1234.56", "1234.56"),
        ("1234,56", "1234.56"),
        ("1.234.567,5", "1234567.5"),
        ("1.234.567", "1234567"),
        ("100", "100"),
        ("0,05", "0.05"),
        ("12,50", "12.5"),
        ("12.500,00", "12500"),
    ],
)
def test_csv_decimal_formats_are_read_correctly(
    shop: Shop, admin_conn: psycopg.Connection[Any], cell: str, expected: str
) -> None:
    r = upload(shop, csv_bytes(f'{B1};"{cell}";20;2026-10-01'), dry_run=False)
    assert r.status_code == 200, (cell, r.text)
    assert costs_of(admin_conn, shop)[(B1, date(2026, 10, 1))][0] == Decimal(expected)


@pytest.mark.parametrize(
    ("cell", "fragment"),
    [
        ("1.234", "belirsiz"),
        ("1,234", "belirsiz"),
        ("12,345", "belirsiz"),
        ("1.2345", "2 ondalık"),
        ("0,123", "2 ondalık"),
        ("1,234,56", "okunamadı"),
        ("1.23,4.5", "okunamadı"),
        ("1.234,5,6", "okunamadı"),
        ("12,", "okunamadı"),
        ("-5", "okunamadı"),
        ("+5", "okunamadı"),
        ("1e3", "okunamadı"),
        ("12 TL", "okunamadı"),
        ("₺12", "okunamadı"),
        ("0", "sıfırdan büyük"),
        ("0,00", "sıfırdan büyük"),
        ("10.000.000,01", "10.000.000"),
        ("9" * 41, "okunamadı"),
    ],
)
def test_csv_ambiguous_or_invalid_numbers_are_rejected(shop: Shop, cell: str, fragment: str) -> None:
    report = upload(shop, csv_bytes(f'{B1};"{cell}";20;2026-10-01')).json()
    assert report["invalid"] == 1 and report["valid"] == 0, cell
    assert fragment in report["errors"][0]["message"], (cell, report["errors"])


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("2026-10-01", date(2026, 10, 1)),
        ("01.10.2026", date(2026, 10, 1)),
        ("31.12.2026", date(2026, 12, 31)),
        ("", date(2026, 11, 8)),
    ],
)
def test_csv_date_formats_and_empty_date_means_today_istanbul(
    shop: Shop, admin_conn: psycopg.Connection[Any], cell: str, expected: date
) -> None:
    assert upload(shop, csv_bytes(f"{B1};5;20;{cell}"), dry_run=False).status_code == 200
    assert list(costs_of(admin_conn, shop)) == [(B1, expected)]


@pytest.mark.parametrize(
    "cell",
    [
        "2026-1-5",
        "5.10.2026",
        "10/05/2026",
        "2026-10-01T00:00",
        "1 Ekim 2026",
        "45931",
        "2026-02-30",
        "1999-12-31",
        "2028-01-01",
    ],
)
def test_csv_bad_dates_are_rejected(shop: Shop, cell: str) -> None:
    report = upload(shop, csv_bytes(f"{B1};5;20;{cell}")).json()
    assert report["invalid"] == 1 and report["errors"][0]["column"] == "gecerlilik_tarihi"


@pytest.mark.parametrize(
    ("cell", "ok"),
    [
        ("20", True),
        ("%20", True),
        ("20%", True),
        ("0", True),
        ("1", True),
        ("10", True),
        ("0,20", False),
        ("0.2", False),
        ("8", False),
        ("18", False),
        ("", False),
    ],
)
def test_vat_rate_values(shop: Shop, cell: str, ok: bool) -> None:
    report = upload(shop, csv_bytes(f"{B1};5;{cell};2026-10-01")).json()
    assert (report["valid"] == 1) is ok, report


def test_delimiters_bom_and_header_synonyms(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    variants = [
        csv_bytes(f"{B1};5,5;20;2026-10-01", bom=True),
        csv_bytes(f'{B1},"5,5",20,2026-10-01', header="barcode,unit_cost,vat_rate,valid_from"),
        csv_bytes(
            f"{B1}\t5,5\t20\t2026-10-01",
            header="Barkod\tBirim Maliyet (KDV Hariç)\tKDV Oranı\tGeçerlilik Tarihi",
        ),
        csv_bytes(f"{B1};5,5;20;2026-10-01", header="BARKOD;BİRİM MALİYET;KDV;GEÇERLİLİK"),
        csv_bytes(f"{B1};5,5;20", header="barkod;maliyet;kdv"),  # tarih sütunu yok: bugün
    ]
    for data in variants:
        r = upload(shop, data)
        assert r.status_code == 200 and r.json()["valid"] == 1 and r.json()["invalid"] == 0, (data, r.text)


def test_unknown_columns_are_ignored_but_listed_and_title_is_silent(shop: Shop) -> None:
    data = csv_bytes(f"{B1};Ürün;5;20;x", header="barkod;baslik;maliyet;kdv;gizli=sutun")
    report = upload(shop, data).json()
    assert report["valid"] == 1 and report["ignored_columns"] == ["gizli=sutun"]


def test_missing_required_or_duplicate_columns_reject_the_file(shop: Shop) -> None:
    missing = upload(shop, csv_bytes(f"{B1};5", header="barkod;maliyet"))
    assert missing.status_code == 422 and "kdv_orani" in missing.json()["detail"]
    assert missing.json()["type"] == "urn:netkar:problem:import-file-invalid"
    dup = upload(shop, csv_bytes(f"{B1};5;20", header="barkod;maliyet;birim_maliyet_kdv_haric;kdv;extra"))
    assert dup.status_code == 422 and "birden fazla" in dup.json()["detail"]
    assert upload(shop, b"\n\n").status_code == 422
    assert upload(shop, b"").status_code == 422


def test_blank_rows_and_untouched_template_rows_are_skipped(shop: Shop) -> None:
    data = csv_bytes(";;;", f"{B1};;;", f"{B2};5;20;", "", ";;;;")
    report = upload(shop, data).json()
    assert (report["total"], report["valid"], report["invalid"], report["skipped"]) == (2, 1, 0, 1)


def test_partially_filled_row_without_barcode_is_an_error(shop: Shop) -> None:
    report = upload(shop, csv_bytes(";5;20;2026-10-01")).json()
    assert report["invalid"] == 1 and report["errors"][0]["column"] == "barkod"


def test_template_roundtrip_imports_filled_rows(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    add_product(admin_conn, shop, B1, "Şık Çanta")
    add_product(admin_conn, shop, B2, "Kemer")
    template = shop.api.get(f"{shop.base}/product-costs/template.csv").content
    untouched = upload(shop, template).json()
    assert (untouched["valid"], untouched["invalid"], untouched["skipped"]) == (0, 0, 2)
    # Şablon artık tüm hücreleri tırnaklar (QUOTE_ALL): doldurulacak satır tırnaklı biçimiyle aranır.
    filled = template.decode("utf-8-sig").replace(
        f'"{B1}";"Şık Çanta";"";"";""', f'"{B1}";"Şık Çanta";"49,90";"20";"01.10.2026"'
    )
    assert filled != template.decode("utf-8-sig")
    r = upload(shop, filled.encode("utf-8"), dry_run=False)
    assert r.status_code == 200 and r.json()["created"] == 1 and r.json()["skipped"] == 1
    assert costs_of(admin_conn, shop) == {(B1, date(2026, 10, 1)): (Decimal("49.9"), Decimal("20"))}


# --- XLSX ----------------------------------------------------------------------------------------------------------


def test_xlsx_with_typed_cells_dates_and_numbers(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    data = xlsx_bytes(
        [
            ["barkod", "birim_maliyet_kdv_haric", "kdv_orani", "gecerlilik_tarihi"],
            [int(B1), 12.5, 20, datetime(2026, 10, 1, 0, 0)],
            [B2, "1.234,56", "%10", "01.10.2026"],
            [B3, 7, 0, None],
            [None, None, None, None],
        ]
    )
    r = upload(shop, data, "maliyet.xlsx", dry_run=False)
    assert r.status_code == 200, r.text
    assert r.json()["format"] == "xlsx" and r.json()["created"] == 3
    assert costs_of(admin_conn, shop) == {
        (B1, date(2026, 10, 1)): (Decimal("12.5"), Decimal("20")),
        (B2, date(2026, 10, 1)): (Decimal("1234.56"), Decimal("10")),
        (B3, date(2026, 11, 8)): (Decimal("7"), Decimal("0")),
    }
    assert audit_actions(admin_conn, shop)[0][1]["format"] == "xlsx"


def test_xlsx_percent_formatted_vat_cell_is_rejected_not_guessed(shop: Shop) -> None:
    data = xlsx_bytes([["barkod", "maliyet", "kdv"], [B1, 5, 0.2]])
    report = upload(shop, data, "m.xlsx").json()
    assert report["invalid"] == 1 and report["errors"][0]["column"] == "kdv_orani"


def test_xlsx_non_text_barcode_cells_are_rejected(shop: Shop) -> None:
    data = xlsx_bytes(
        [
            ["barkod", "maliyet", "kdv"],
            [123.5, 5, 20],
            [True, 5, 20],
            [datetime(2026, 1, 1), 5, 20],
        ]
    )
    report = upload(shop, data, "m.xlsx").json()
    assert report["invalid"] == 3 and report["valid"] == 0


def test_xlsx_formula_cells_are_not_evaluated(shop: Shop) -> None:
    """Önbellek değeri okunur (formül değerlendirilmez); openpyxl ile yazılan formülün önbelleği yoktur (boş)."""
    data = xlsx_bytes(
        [["barkod", "maliyet", "kdv"], ["=1+1", 5, 20], [B1, "=2*50", 20], ['=HYPERLINK("http://x")', 5, 20]]
    )
    report = upload(shop, data, "m.xlsx").json()
    assert report["valid"] == 0 and report["invalid"] == 3
    assert {e["column"] for e in report["errors"]} == {"barkod", "birim_maliyet_kdv_haric"}


def test_xlsx_xxe_and_entity_expansion_are_rejected(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    cost_import.require_defusedxml()  # okuyucunun ayrıştırıcısı defusedxml ve DTD'yi reddediyor
    import importlib.metadata

    assert importlib.metadata.version("defusedxml")  # kurulu
    base = xlsx_bytes([["barkod", "maliyet", "kdv"], [B1, 5, 20]])
    doctype = b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'

    def inject(name: str, content: bytes) -> bytes:
        if name != "xl/worksheets/sheet1.xml":
            return content
        head, _, rest = content.partition(b"?>")
        return head + b"?>" + doctype + rest

    r = upload(shop, rewrite_zip(base, inject), "x.xlsx", dry_run=False)
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:import-file-invalid"
    assert "passwd" not in r.text and "root:" not in r.text
    assert count_costs(admin_conn, shop) == 0

    laughs = b'<!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'

    def inject_laughs(name: str, content: bytes) -> bytes:
        if name != "xl/workbook.xml":
            return content
        head, _, rest = content.partition(b"?>")
        return head + b"?>" + laughs + rest

    assert upload(shop, rewrite_zip(base, inject_laughs), "x.xlsx").status_code == 422


# --- dosya güvenliği ------------------------------------------------------------------------------------------------


def test_extension_and_signature_must_agree(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    csv = csv_bytes(f"{B1};5;20;2026-10-01")
    xlsx = xlsx_bytes([["barkod", "maliyet", "kdv"], [B1, 5, 20]])
    assert upload(shop, csv, "m.xls").status_code == 415
    assert upload(shop, csv, "m.txt").status_code == 415
    assert upload(shop, csv, "m").status_code == 415
    assert upload(shop, xlsx, "m.exe").status_code == 415
    fake = upload(shop, csv, "m.xlsx")  # CSV içeriği XLSX adıyla: sahte imza
    assert fake.status_code == 422 and "imzasına" in fake.json()["detail"]
    zipped = upload(shop, xlsx, "m.csv")  # XLSX (zip) içeriği CSV adıyla
    assert zipped.status_code == 422 and "ikili" in zipped.json()["detail"]
    assert upload(shop, csv_bytes(f"{B1};5\x00;20"), "m.csv").status_code == 422  # NUL bayt
    assert upload(shop, "barkod;maliyet;kdv\n".encode("utf-16"), "m.csv").status_code == 422  # UTF-8 değil
    assert upload(shop, b"\xff\xfe\xfa\xfb", "m.csv").status_code == 422
    assert upload(shop, b"PK\x03\x04bozuk-zip", "m.xlsx").status_code == 422
    assert count_costs(admin_conn, shop) == 0


def test_xlsx_without_workbook_parts_is_rejected(shop: Shop) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("merhaba.txt", "sadece zip")
    assert upload(shop, buffer.getvalue(), "m.xlsx").status_code == 422


def _bomb(size: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/bomba.bin", bytes(size))
    return buffer.getvalue()


def test_zip_bomb_by_total_size_is_rejected(shop: Shop) -> None:
    data = _bomb(60 * 1024 * 1024)
    assert len(data) < 2 * 1024 * 1024  # 2 MB sınırının altında ama açılınca 60 MB
    r = upload(shop, data, "bomba.xlsx", dry_run=False)
    assert r.status_code == 422 and "çok büyük" in r.json()["detail"]


def test_zip_bomb_by_compression_ratio_is_rejected(shop: Shop) -> None:
    data = _bomb(20 * 1024 * 1024)  # 50 MB altında ama oran >> 100
    r = upload(shop, data, "bomba.xlsx")
    assert r.status_code == 422 and "sıkıştırma oranı" in r.json()["detail"]


def test_zip_with_lying_header_is_caught_by_real_decompression_count() -> None:
    """Merkezi dizinde boyutu küçük gösteren zip: bildirilen boyuta güvenilmez, gerçek açılım sayılır."""
    data = bytearray(_bomb(60 * 1024 * 1024))
    pos = 0
    while (pos := data.find(b"PK\x01\x02", pos)) != -1:
        name_len = struct.unpack_from("<H", data, pos + 28)[0]
        name = bytes(data[pos + 46 : pos + 46 + name_len])
        if name == b"xl/bomba.bin":
            struct.pack_into("<I", data, pos + 24, 1000)  # bildirilen açık boyut: 1000 bayt
            break
        pos += 4
    else:  # pragma: no cover
        pytest.fail("merkezi dizin girdisi bulunamadı")
    with pytest.raises(cost_import.ImportFileError, match="Dosya geçersiz"):
        cost_import.check_zip(bytes(data))


def test_zip_with_too_many_entries_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(cost_import.MAX_ZIP_ENTRIES + 1):
            archive.writestr(f"f{i}", "")
    with pytest.raises(cost_import.ImportFileError):
        cost_import.check_zip(buffer.getvalue())


def test_file_over_2mb_is_413(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    limit = 2 * 1024 * 1024
    # Dosya sınırı işleyicide: gövde sınırının (2 MiB + 64 KiB) altında ama dosya 2 MiB'den büyük.
    row = f"{B1};5;20;2026-10-01\r\n"
    exact = (HEADER_TR + "\r\n").encode() + row.encode() * ((limit - len(HEADER_TR) - 2) // len(row))
    exact = exact.ljust(limit, b" ")
    assert len(exact) == limit
    assert upload(shop, exact).status_code in {200, 422}  # tam 2 MiB sınırda kabul edilir (satır sınırı ayrı)
    over = exact + b" "
    r = upload(shop, over)
    assert r.status_code == 413 and r.json()["type"] == "urn:netkar:problem:payload-too-large"
    # Gövde sınırı ara katmanda: Content-Length üstündeyse işleyici hiç çağrılmaz.
    huge = upload(shop, bytes(limit + 128 * 1024))
    assert huge.status_code == 413 and huge.json()["type"] == "urn:netkar:problem:payload-too-large"
    assert count_costs(admin_conn, shop) == 0


def test_other_marketplace_paths_keep_the_small_body_limit(shop: Shop) -> None:
    r = shop.api.put(
        f"{shop.base}/products/{B1}/costs",
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": "1", "vat_rate": 0, "pad": "x" * 9000},
    )
    assert r.status_code == 413


def test_row_limit_is_10000(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    ok = csv_bytes(*[f"B{i};1;20;2026-10-01" for i in range(10_000)])
    r = upload(shop, ok)
    assert r.status_code == 200 and r.json()["valid"] == 10_000
    too_many = csv_bytes(*[f"B{i};1;20;2026-10-01" for i in range(10_001)])
    r2 = upload(shop, too_many, dry_run=False)
    assert r2.status_code == 422 and r2.json()["type"] == "urn:netkar:problem:import-too-many-rows"
    assert count_costs(admin_conn, shop) == 0
    big = upload(shop, ok, dry_run=False)
    assert big.status_code == 200 and big.json()["created"] == 10_000  # parçalı upsert tek işlemde


def test_physical_row_ceiling_rejects_endless_blank_rows(shop: Shop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cost_import, "MAX_PHYSICAL_ROWS", 5)
    r = upload(shop, csv_bytes(*([";;;"] * 10)))
    assert r.status_code == 422 and "çok fazla satır" in r.json()["detail"]
    xlsx = xlsx_bytes(
        [["barkod", "maliyet", "kdv"], *([[None, None, None]] * 3), *([[None, None, "x"]] * 10)]
    )
    assert upload(shop, xlsx, "m.xlsx").status_code == 422


def test_formula_barcodes_are_rejected_in_every_format(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    bad = ["=1+1", "+90555", "-cmd", "@SUM(A1)", "=cmd|' /C calc'!A0", "\t=x", "a b", "a;b", "a/b", "ü1"]
    lines = [f'"{b}";5;20;2026-10-01' for b in bad if ";" not in b]
    report = upload(shop, csv_bytes(*lines)).json()
    assert report["valid"] == 0 and report["invalid"] == len(lines)
    assert all(e["column"] == "barkod" for e in report["errors"])
    formula_msgs = [e["message"] for e in report["errors"] if "formül" in e["message"]]
    assert len(formula_msgs) == 6  # =, +, -, @ ve sekme önekli altı değer
    xlsx = xlsx_bytes([["barkod", "maliyet", "kdv"], *[[b, 5, 20] for b in bad]])
    assert upload(shop, xlsx, "m.xlsx", dry_run=False, allow_partial=True).json()["valid"] == 0
    assert count_costs(admin_conn, shop) == 0


def test_error_report_never_reflects_more_than_20_clean_chars(shop: Shop) -> None:
    payload = "=" + "A" * 50 + "\x07\x1b[31m‮\nSON"
    data = csv_bytes(
        f'"{payload}";5;20;2026-10-01', f'{B1};"{"9" * 30}x\x00";20;2026-10-01'.replace("\x00", "")
    )
    report = upload(shop, data).json()
    values = [e["value"] for e in report["errors"]]
    assert values and all(v is not None and len(v) <= 20 for v in values)
    assert all(not any(ord(c) < 32 or c in "‮\x7f" for c in v) for v in values)
    assert "SON" not in str(report) and "A" * 21 not in str(report)


def test_errors_are_capped_but_counts_are_exact(shop: Shop) -> None:
    data = csv_bytes(*[f"B{i};x;20;2026-10-01" for i in range(300)])
    report = upload(shop, data).json()
    assert report["invalid"] == 300 and len(report["errors"]) == 200 and report["errors_truncated"] is True


def test_import_is_rate_limited_per_tenant_including_dry_runs(make_shop: Callable[..., Shop]) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_cost_import_tenant=2)
    data = csv_bytes(f"{B1};5;20;2026-10-01")
    assert upload(shop, data).status_code == 200 and upload(shop, data, dry_run=False).status_code == 200
    limited = upload(shop, data)
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_missing_file_part_is_a_validation_problem(shop: Shop) -> None:
    r = shop.api.post(f"{shop.base}/product-costs/import", None, data={"x": "y"})
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:validation-error"
    assert (
        shop.api.post(
            f"{shop.base}/product-costs/import",
            None,
            files={"file": ("a.csv", b"x", "text/csv")},
            params={"dry_run": "belki"},
        ).status_code
        == 422
    )


def test_import_is_atomic_when_the_database_rejects_a_chunk(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parçalardan biri patlarsa hiçbir şey yazılmaz (tek işlem, 500 problem+json)."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services import product_costs

    monkeypatch.setattr(product_costs, "_CHUNK", 2)
    calls = {"n": 0}
    real_execute = AsyncSession.execute

    async def failing_execute(self: AsyncSession, statement: Any, *a: Any, **k: Any) -> Any:
        if "INSERT INTO product_costs" in str(statement):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("sahte veritabanı hatası")
        return await real_execute(self, statement, *a, **k)

    monkeypatch.setattr(AsyncSession, "execute", failing_execute)
    r = upload(shop, csv_bytes(*[f"B{i};1;20;2026-10-01" for i in range(5)]), dry_run=False)
    monkeypatch.setattr(AsyncSession, "execute", real_execute)
    assert r.status_code == 500 and r.headers["content-type"].startswith("application/problem+json")
    assert calls["n"] == 3 and count_costs(admin_conn, shop) == 0 and audit_actions(admin_conn, shop) == []
