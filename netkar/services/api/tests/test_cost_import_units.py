"""Maliyet dosyası ayrıştırıcısının saf birim testleri (veritabanı gerekmez)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.services import cost_import as ci
from app.services.product_costs import (
    RuleError,
    check_barcode,
    check_unit_cost,
    check_valid_from,
    check_vat_rate,
)

TODAY = date(2026, 11, 8)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7", "7"),
        ("1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),
        ("1.234.567", "1234567"),
        ("0,5", "0.5"),
        ("5.25", "5.25"),
    ],
)
def test_parse_decimal_text_ok(text: str, expected: str) -> None:
    assert ci.parse_decimal_text(text) == Decimal(expected)


@pytest.mark.parametrize(
    "text", ["", "abc", "1.234", "1,234", "1,2,3", "1.23.45", "1.234,", ".5", ",5", "1 234", "0.123.456"]
)
def test_parse_decimal_text_rejects(text: str) -> None:
    with pytest.raises(RuleError):
        ci.parse_decimal_text(text)


def test_decimal_cell_types() -> None:
    assert ci._decimal_cell(5) == Decimal(5)
    assert ci._decimal_cell(Decimal("1.5")) == Decimal("1.5")
    assert ci._decimal_cell(12.35) == Decimal("12.35")
    assert ci._decimal_cell("%20", percent=True) == Decimal(20)
    for bad in (True, float("nan"), float("inf"), None, b"1", date(2026, 1, 1), ["1"]):
        with pytest.raises(RuleError):
            ci._decimal_cell(bad)


def test_date_cell_types() -> None:
    assert ci._date_cell(datetime(2026, 10, 1, 13, 5)) == date(2026, 10, 1)
    assert ci._date_cell(date(2026, 10, 1)) == date(2026, 10, 1)
    assert ci._date_cell(" 01.10.2026 ") == date(2026, 10, 1)
    for bad in (45931, 1.5, None, "2026-02-30", "00.00.0000"):
        with pytest.raises(RuleError):
            ci._date_cell(bad)


def test_barcode_cell_types() -> None:
    assert ci._barcode_cell(8681000000011) == "8681000000011"
    assert ci._barcode_cell(8681000000011.0) == "8681000000011"
    assert ci._barcode_cell("  ABC-1 ") == "ABC-1"
    for bad in (True, 1.5, 1e16, None, b"x", "=1", "", "ü"):
        with pytest.raises(RuleError):
            ci._barcode_cell(bad)


def test_rule_checks() -> None:
    assert check_barcode("A-1._b") == "A-1._b"
    assert check_unit_cost(Decimal("12.500")) == Decimal("12.50")
    assert check_valid_from(date(2000, 1, 1), TODAY) == date(2000, 1, 1)
    with pytest.raises(RuleError):
        check_unit_cost(Decimal("NaN"))
    with pytest.raises(RuleError):
        check_vat_rate(Decimal("NaN"))
    with pytest.raises(RuleError):
        check_barcode("a" * 201)


def test_header_normalization_and_excerpt() -> None:
    assert ci.normalize_header(" Birim Maliyet (KDV Hariç) ") == "birimmaliyetkdvharic"
    assert ci.normalize_header("GEÇERLİLİK TARİHİ") == "gecerliliktarihi"
    assert ci.normalize_header(None) == ""
    assert ci.excerpt(None) is None and ci.excerpt("  ") is None and ci.excerpt("\x00\x01") is None
    assert (
        ci.excerpt("ab\x07c‮d") == "abcd" and ci.excerpt("x" * 50) == "x" * 20 and ci.excerpt(12.5) == "12.5"
    )


def test_csv_safe_cell_and_template() -> None:
    for prefix in ("=", "+", "-", "@", "\t", "\r", "\n"):
        assert ci.csv_safe_cell(f"{prefix}x") == f"'{prefix}x"
    assert ci.csv_safe_cell("a=b") == "a=b" and ci.csv_safe_cell(None) == "" and ci.csv_safe_cell("") == ""
    out = ci.build_template_csv([("B1", "=HYPERLINK(1)"), ("B2", None)])
    assert (
        out.startswith(b"\xef\xbb\xbf") and b"B1;'=HYPERLINK(1);;;\r\n" in out and out.endswith(b"B2;;;;\r\n")
    )


def test_csv_reader_errors() -> None:
    with pytest.raises(ci.ImportFileError):
        ci._read_csv(b'barkod;maliyet\n"acik tirnak;1\n')  # strict: kapanmamış tırnak
    assert ci._read_csv(b"barkod,maliyet\nA,1") == [["barkod", "maliyet"], ["A", "1"]]


def test_validate_rows_requires_header() -> None:
    with pytest.raises(ci.ImportFileError):
        ci.validate_rows([], TODAY)
    with pytest.raises(ci.ImportFileError):
        ci.validate_rows([[None, ""]], TODAY)
    short = ci.validate_rows([["barkod", "maliyet", "kdv", "gecerlilik"], ["A1", "5"]], TODAY)  # kısa satır
    assert short.invalid == 1 and {i.column for i in short.issues} == {"kdv_orani"}
