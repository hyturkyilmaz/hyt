"""Akışlı XLSX okuyucusu (denetim S3 YK-01) ve şablon CSV kaçışı (YK-02, YK-03): birim testleri, DB gerekmez.

PoC dosyaları denetim raporundaki dört üreticidir (geniş satır, sayfada çöp öğe, `<si>` dışı öğe, Override ile
taşınan dize tablosu). Her biri hızlı (< 3 sn, eski kod 6 sn üstü) reddedilmeli ve tepe bellek (tracemalloc) 50 MB altında kalmalıdır.
"""

from __future__ import annotations

import csv
import io
import random
import string
import time
import tracemalloc
import zipfile
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

import pytest

from app.services import cost_import as ci
from app.services import xlsx_stream as xs
from app.services.product_costs import RuleError
from tests.product_cost_helpers import xlsx_bytes

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
TYPE_BASE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
TODAY = date(2026, 11, 8)
MB = 1024 * 1024
LETTERS = tuple(string.ascii_lowercase[:4])


# --- paket üreticisi -----------------------------------------------------------------------------------


def content_types(
    *, sst: bool = True, styles: bool = True, extra: str = "", sheet_ct: str = xs._CT_SHEET
) -> str:
    overrides = [
        f'<Override PartName="/xl/workbook.xml" ContentType="{xs._CT_WORKBOOK}"/>',
        f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{sheet_ct}"/>',
    ]
    if sst:
        overrides.append(f'<Override PartName="/xl/sharedStrings.xml" ContentType="{xs._CT_SST}"/>')
    if styles:
        overrides.append(f'<Override PartName="/xl/styles.xml" ContentType="{xs._CT_STYLES}"/>')
    return f'<?xml version="1.0"?><Types xmlns="{CT_NS}">{"".join(overrides)}{extra}</Types>'


def workbook_xml(*, date1904: bool = False, sheets: str | None = None) -> str:
    pr = '<workbookPr date1904="1"/>' if date1904 else "<workbookPr/>"
    body = sheets if sheets is not None else '<sheet name="S" sheetId="1" r:id="rId1"/>'
    return f'<?xml version="1.0"?><workbook xmlns="{MAIN}" xmlns:r="{REL}">{pr}<sheets>{body}</sheets></workbook>'


def workbook_rels(
    *,
    sheet_target: str = "worksheets/sheet1.xml",
    sst: str | None = "sharedStrings.xml",
    styles: str | None = "styles.xml",
    extra: str = "",
) -> str:
    items = [f'<Relationship Id="rId1" Type="{TYPE_BASE}/worksheet" Target="{sheet_target}"/>']
    if sst is not None:
        items.append(f'<Relationship Id="rId2" Type="{TYPE_BASE}/sharedStrings" Target="{sst}"/>')
    if styles is not None:
        items.append(f'<Relationship Id="rId3" Type="{TYPE_BASE}/styles" Target="{styles}"/>')
    return f'<?xml version="1.0"?><Relationships xmlns="{PKG_REL}">{"".join(items)}{extra}</Relationships>'


def sheet_xml(rows: str, *, tail: str = "") -> str:
    return f'<?xml version="1.0"?><worksheet xmlns="{MAIN}"><sheetData>{rows}</sheetData>{tail}</worksheet>'


def sst_xml(*strings: str) -> str:
    body = "".join(f"<si><t>{s}</t></si>" for s in strings)
    return f'<?xml version="1.0"?><sst xmlns="{MAIN}">{body}</sst>'


def styles_xml(*, custom: dict[int, str] | None = None, xfs: tuple[int, ...] = (0, 14, 164)) -> str:
    formats = custom if custom is not None else {164: "yyyy\\-mm\\-dd"}
    fmts = "".join(f'<numFmt numFmtId="{k}" formatCode="{v}"/>' for k, v in formats.items())
    cell_xfs = "".join(f'<xf numFmtId="{i}" fontId="0"/>' for i in xfs)
    return (
        f'<?xml version="1.0"?><styleSheet xmlns="{MAIN}"><numFmts count="1">{fmts}</numFmts>'
        f'<cellStyleXfs count="1"><xf numFmtId="14"/></cellStyleXfs><cellXfs count="3">{cell_xfs}</cellXfs></styleSheet>'
    )


def package(parts: dict[str, str | bytes | None] | None = None) -> bytes:
    """Küçük, geçerli bir XLSX paketi; `parts` ile bölümler değiştirilir/eklenir (None siler)."""
    files: dict[str, str | bytes | None] = {
        "[Content_Types].xml": content_types(),
        "xl/workbook.xml": workbook_xml(),
        "xl/_rels/workbook.xml.rels": workbook_rels(),
        "xl/worksheets/sheet1.xml": sheet_xml(""),
        "xl/sharedStrings.xml": sst_xml("a"),
        "xl/styles.xml": styles_xml(),
    }
    files.update(parts or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            if content is not None:
                archive.writestr(name, content)
    return out.getvalue()


def with_sheet(rows: str, **parts: Any) -> bytes:
    """Yalnız sayfa satırlarını değiştiren paket; ek bölümler `xl_workbook=...` gibi değil, doğrudan `package` ile."""
    return package({"xl/worksheets/sheet1.xml": sheet_xml(rows), **parts})


def read(data: bytes, limits: xs.StreamLimits | None = None) -> list[list[Any]]:
    return xs.read_first_sheet(data, limits or xs.StreamLimits())


def rejected(data: bytes, limits: xs.StreamLimits | None = None, kind: str = "invalid") -> xs.XlsxFormatError:
    with pytest.raises(xs.XlsxFormatError) as info:
        read(data, limits)
    assert info.value.kind == kind
    return info.value


def measure(action: Callable[[], Any]) -> tuple[float, float, Any]:
    """(süre sn, tracemalloc tepe MB, sonuç ya da istisna)."""
    tracemalloc.start()
    started = time.perf_counter()
    try:
        outcome: Any = action()
    except Exception as exc:
        outcome = exc
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / MB, outcome


# --- denetim PoC'leri ----------------------------------------------------------------------------------


def noisy(template: str, count: int, symbols: Sequence[str] = tuple(string.digits), seed: int = 7) -> str:
    """Rastgele seçilmiş şablon tekrarları: zip sıkıştırma oranı denetimlerini (<= 100) geçecek kadar gürültülü
    (denetim PoC'leri de bu yüzden rastgele öğe dizileri kullanır; düz tekrar zaten oran denetimine takılır)."""
    rnd = random.Random(seed)
    pool = [template.format(i) for i in symbols]
    return "".join(rnd.choices(pool, k=count))


def check_fast_and_small(data: bytes) -> None:
    """Dosya zip denetimini GEÇER (okuyucuya ulaşır); `parse_import` 422 verir, hızlı ve < 50 MB bellekle.

    Süre ve bellek ayrı koşularda ölçülür: tracemalloc her ayırmayı izlediği için süreyi birkaç kat şişirir."""
    ci.check_zip(data)  # PoC gerçekten okuyucunun işi: oran, boyut ve öğe sayısı ön taraması takılmaz
    started = time.perf_counter()
    with pytest.raises(ci.ImportFileError) as info:
        ci.parse_import("poc.xlsx", data, TODAY)
    elapsed = time.perf_counter() - started
    assert info.value.status == 422
    # Eski kod bu dosyalarda 6-7,5 sn ve 0,3-1,2 GB harcıyordu. Kapsam ölçümü açıkken yeni okuyucu
    # 0,8 sn'ye kadar çıkabiliyor (yüklü CI daha yavaş); eşik bu yüzden 3 sn. Asıl koruma bellek sınırı.
    assert elapsed < 3.0, f"{elapsed:.2f} sn"
    _, peak, outcome = measure(lambda: ci.parse_import("poc.xlsx", data, TODAY))
    assert isinstance(outcome, ci.ImportFileError), outcome
    assert peak < 50, f"{peak:.1f} MB"


def poc_wide_row() -> bytes:
    return with_sheet('<row r="1">' + noisy('<c s="{}"/>', 1_900_000) + "</row>")


def poc_sheet_junk() -> bytes:
    return package({"xl/worksheets/sheet1.xml": sheet_xml("", tail=noisy("<{}/>", 4_500_000, LETTERS))})


def poc_sheet_data_junk() -> bytes:
    row = '<row r="1"><c r="A1"/>' + noisy("<z{}/>", 3_400_000, LETTERS) + "</row>"
    return with_sheet(row)


def poc_sst_junk() -> bytes:
    """`<si>` dışı öğe seli, aranan dizeden ÖNCE gelir (okuyucu taramak zorunda kalır)."""
    cell = '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
    junk = f'<?xml version="1.0"?><sst xmlns="{MAIN}">{noisy("<q{}/>", 2_000_000, LETTERS)}<si><t>a</t></si></sst>'
    return with_sheet(cell, **{"xl/sharedStrings.xml": junk})


def poc_sst_redirect() -> bytes:
    """Dize tablosu `sheet2.xml` adına taşınıp Override ile sharedStrings türü verilir (openpyxl'i kandırırdı)."""
    big = f'<?xml version="1.0"?><sst xmlns="{MAIN}">{noisy("<si><t>{}</t></si>", 1_000_000, [f"{i:02x}" for i in range(256)])}</sst>'
    extra = f'<Override PartName="/xl/worksheets/sheet2.xml" ContentType="{xs._CT_SST}"/>'
    return package(
        {
            "[Content_Types].xml": content_types(sst=False, extra=extra),
            "xl/worksheets/sheet2.xml": big,
            "xl/sharedStrings.xml": None,
            "xl/_rels/workbook.xml.rels": workbook_rels(sst="worksheets/sheet2.xml"),
            "xl/worksheets/sheet1.xml": sheet_xml('<row r="1"><c r="A1" t="s"><v>0</v></c></row>'),
        }
    )


@pytest.mark.parametrize(
    "build",
    [poc_wide_row, poc_sheet_junk, poc_sheet_data_junk, poc_sst_junk, poc_sst_redirect],
    ids=["widerow", "sheetjunk", "sheetdatajunk", "sstjunk", "sstredirect"],
)
def test_poc_files_pass_the_zip_checks_but_are_rejected_fast_with_flat_memory(
    build: Callable[[], bytes],
) -> None:
    data = build()
    assert len(data) < 2 * MB  # yükleme sınırının altında
    check_fast_and_small(data)


def test_poc_sst_junk_is_rejected_by_the_unrecognized_element_budget() -> None:
    assert "tanınmayan" in rejected(poc_sst_junk()).detail


def test_poc_sst_redirect_is_rejected_by_the_override_cross_check() -> None:
    error = rejected(poc_sst_redirect())
    assert "beklenmeyen" in error.detail


def test_legit_large_workbook_streams_in_flat_memory() -> None:
    """10.000 satır x 4 sütun (paylaşılan dize, sayı, tarih): sabit bellek, < 50 MB tepe."""
    unique = [f"868{i:010d}" for i in range(10_000)]
    rows = "".join(
        f'<row r="{n}"><c r="A{n}" t="s"><v>{n - 1}</v></c><c r="B{n}"><v>{n}.5</v></c>'
        f'<c r="C{n}"><v>20</v></c><c r="D{n}" s="2"><v>46000</v></c></row>'
        for n in range(1, 10_001)
    )
    data = with_sheet(rows, **{"xl/sharedStrings.xml": sst_xml(*unique)})
    # Süre tracemalloc KAPALIYKEN ölçülür: tracemalloc her ayırmayı izleyip süreyi birkaç kat şişirir
    # (CI'da kapsamla birlikte 21 sn görüldü). Eşik yalnız ikinci dereceden bir bozulmayı yakalamak
    # içindir; 10.000 satırda ikinci dereceden okuyucu dakikalar sürerdi.
    started = time.perf_counter()
    first = read(data)
    elapsed = time.perf_counter() - started
    assert elapsed < 30, f"{elapsed:.1f} sn"
    _, peak, outcome = measure(lambda: read(data))
    assert outcome == first
    assert isinstance(outcome, list) and len(outcome) == 10_000
    assert outcome[0] == ["8680000000000", 1.5, 20, date(2025, 12, 9)]  # 46000 = 2025-12-09
    assert outcome[9_999][0] == "8680000009999"
    assert peak < 50, f"{peak:.1f} MB"


# --- mutlu yol -------------------------------------------------------------------------------------


def test_openpyxl_written_workbook_roundtrips() -> None:
    from datetime import datetime

    data = xlsx_bytes(
        [
            ["barkod", "maliyet", "kdv", "tarih"],
            ["8681000000011", 12.5, 20, datetime(2026, 10, 1)],
            [8681000000028, "1.234,56", "%10", date(2026, 10, 2)],
            [True, None, 0, None],
        ]
    )
    rows = read(data)
    assert rows[0] == ["barkod", "maliyet", "kdv", "tarih"]
    assert rows[1] == ["8681000000011", 12.5, 20, date(2026, 10, 1)]
    assert rows[2] == [8681000000028, "1.234,56", "%10", date(2026, 10, 2)]
    assert rows[3][0] is True and rows[3][1] is None and rows[3][2] == 0


def test_inline_strings_rich_text_and_phonetic_runs() -> None:
    rows = (
        '<row r="1"><c r="A1" t="inlineStr"><is><t>barkod</t></is></c>'
        '<c r="B1" t="inlineStr"><is><r><t>ma</t></r><r><rPr><b/></rPr><t>liyet</t></r><rPh><t>X</t></rPh></is></c>'
        '<c r="C1" t="inlineStr"><is/></c></row>'
    )
    assert read(with_sheet(rows)) == [["barkod", "maliyet", None]]


def test_shared_strings_rich_text_and_blank_references() -> None:
    sst = (
        f'<?xml version="1.0"?><sst xmlns="{MAIN}"><si><r><t>bar</t></r><r><rPr><i/></rPr><t>kod</t></r></si>'
        "<si><t>b</t><rPh><t>fon</t></rPh></si><si/></sst>"
    )
    rows = (
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c><c r="C1" t="s"/>'
        '<c r="D1" t="s"><v>2</v></c></row>'
    )
    assert read(with_sheet(rows, **{"xl/sharedStrings.xml": sst})) == [["barkod", "b", None, ""]]


def test_cell_types_bool_error_str_date_and_text_number() -> None:
    rows = (
        '<row r="1"><c r="A1" t="b"><v>1</v></c><c r="B1" t="b"><v>0</v></c><c r="C1" t="e"><v>#DIV/0!</v></c>'
        '<c r="D1" t="str"><v>sonuç</v></c><c r="E1" t="d"><v>2026-10-01T00:00:00</v></c>'
        '<c r="F1" t="d"><v>bozuk</v></c><c r="G1" t="b"/><c r="H1" t="d"/><c r="I1" t="str"/>'
        '<c r="J1"><v>1e3</v></c><c r="K1"><v>abc</v></c><c r="L1"><v>1e999</v></c><c r="M1"><v>-7</v></c>'
        '<c r="N1"><v></v></c><c r="O1" t="n"><v>.5</v></c></row>'
    )
    got = read(with_sheet(rows))[0]
    assert got[:4] == [True, False, "#DIV/0!", "sonuç"]
    assert got[4].year == 2026 and got[5] == "bozuk"
    assert got[6] is None and got[7] is None and got[8] is None
    assert got[9] == 1000.0 and got[10] == "abc" and got[11] == "1e999" and got[12] == -7
    assert got[13] is None and got[14] == 0.5


def test_formula_cells_return_cached_value_or_none() -> None:
    rows = '<row r="1"><c r="A1"><f>1+1</f><v>2</v></c><c r="B1"><f>2*50</f><v></v></c><c r="C1"><f>X</f></c></row>'
    assert read(with_sheet(rows)) == [[2, None, None]]


def test_row_and_column_gaps_keep_numbering() -> None:
    rows = '<row r="2"><c r="C2"><v>1</v></c></row><row r="5"><c r="A5"><v>2</v></c></row>'
    assert read(with_sheet(rows)) == [[], [None, None, 1], [], [], [2]]


def test_rows_without_references_use_sequence() -> None:
    rows = "<row><c><v>1</v></c><c><v>2</v></c></row><row><c><v>3</v></c></row>"
    assert read(with_sheet(rows)) == [[1, 2], [3]]


def test_only_first_sheet_is_read_and_relative_and_absolute_targets_resolve() -> None:
    two = '<sheet name="A" sheetId="1" r:id="rId1"/><sheet name="B" sheetId="2" r:id="rId9"/>'
    rows = '<row r="1"><c r="A1"><v>7</v></c></row>'
    assert read(with_sheet(rows, **{"xl/workbook.xml": workbook_xml(sheets=two)})) == [[7]]
    rels = workbook_rels(sheet_target="/xl/worksheets/sheet1.xml", sst="/xl/sharedStrings.xml")
    assert read(with_sheet(rows, **{"xl/_rels/workbook.xml.rels": rels})) == [[7]]


def test_no_styles_part_means_numbers_are_never_dates() -> None:
    rows = '<row r="1"><c r="A1" s="1"><v>46000</v></c></row>'
    data = with_sheet(
        rows,
        **{
            "[Content_Types].xml": content_types(styles=False),
            "xl/_rels/workbook.xml.rels": workbook_rels(styles=None),
            "xl/styles.xml": None,
        },
    )
    assert read(data) == [[46000]]


# --- tarih ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("yyyy\\-mm\\-dd", True),
        ("dd.mm.yyyy", True),
        ("DD/MM/YY", True),
        ("[$-F800]dddd\\,\\ mmmm\\ dd\\,\\ yyyy", True),
        ("General", False),
        ("Standard", False),
        ("0.00", False),
        ('0.00" TL"', False),
        ('0.00" gün"', False),  # tırnak içindeki d dikkate alınmaz
        ("0.00\\ \\m\\²", False),
        ("[Red]0.00", False),
        ("#,##0.00_);[Red](#,##0.00)", False),
        ("0.0*x", False),
        ("", False),
    ],
)
def test_is_date_format(code: str, expected: bool) -> None:
    assert xs.is_date_format(code) is expected


def test_is_date_format_is_linear_on_long_codes() -> None:
    started = time.perf_counter()
    assert xs.is_date_format('"' * 200_000 + "d") is False
    assert time.perf_counter() - started < 0.2


@pytest.mark.parametrize("builtin", [14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47])
def test_builtin_date_format_ids_convert_serial_numbers(builtin: int) -> None:
    styles = styles_xml(custom={164: "0.00"}, xfs=(0, builtin, 164))
    rows = (
        '<row r="1"><c r="A1" s="1"><v>45000</v></c><c r="B1" s="2"><v>45000</v></c>'
        '<c r="C1" s="0"><v>45000</v></c></row>'
    )
    got = read(with_sheet(rows, **{"xl/styles.xml": styles}))[0]
    assert got == [date(2023, 3, 15), 45000, 45000]  # 45000 = 2023-03-15


def test_custom_date_style_and_bad_style_indexes() -> None:
    rows = (
        '<row r="1"><c r="A1" s="2"><v>45000.75</v></c><c r="B1" s="9"><v>45000</v></c>'
        '<c r="C1" s="x"><v>45000</v></c></row>'
    )
    got = read(with_sheet(rows))[0]
    assert got == [date(2023, 3, 15), 45000, 45000]  # stil indeksi aralık dışı veya bozuk: tarih sayılmaz


def test_unformatted_serial_is_ambiguous_and_rejected_by_the_validator() -> None:
    with pytest.raises(RuleError):
        ci._date_cell(45000)  # biçimsiz sayı tarih sayılmaz (tahmin yok)
    assert ci._date_cell(date(2023, 3, 15)) == date(2023, 3, 15)


def test_serial_to_date_edges() -> None:
    assert xs.serial_to_date(61, date1904=False) == date(1900, 3, 1)
    assert xs.serial_to_date(60, date1904=False) is None  # sahte 29 Şubat 1900
    assert xs.serial_to_date(0.5, date1904=False) is None
    assert xs.serial_to_date(3_000_000, date1904=False) is None
    assert xs.serial_to_date(float("nan"), date1904=False) is None
    assert xs.serial_to_date(0, date1904=True) == date(1904, 1, 1)
    assert xs.serial_to_date(-1, date1904=True) is None


def test_date1904_workbooks_use_the_1904_epoch() -> None:
    rows = '<row r="1"><c r="A1" s="1"><v>43538</v></c></row>'
    data = with_sheet(rows, **{"xl/workbook.xml": workbook_xml(date1904=True)})
    assert read(data) == [[date(2023, 3, 15)]]


def test_date_serial_out_of_range_stays_a_number() -> None:
    rows = '<row r="1"><c r="A1" s="1"><v>99999999</v></c></row>'
    assert read(with_sheet(rows)) == [[99999999]]


# --- sınırlar ve reddedilenler ----------------------------------------------------------------------


def test_too_many_non_blank_rows_is_rejected_with_rows_kind() -> None:
    limits = xs.StreamLimits(max_rows=3)
    rows = "".join(f'<row r="{n}"><c r="A{n}"><v>1</v></c></row>' for n in range(1, 6))
    rejected(with_sheet(rows), limits, kind="rows")
    ok = "".join(f'<row r="{n}"><c r="A{n}"><v>1</v></c></row>' for n in range(1, 5))  # 3 veri + 1 başlık
    assert len(read(with_sheet(ok), limits)) == 4


def test_parse_import_maps_row_limit_to_422_too_many_rows() -> None:
    rows = "".join(f'<row r="{n}"><c r="A{n}"><v>1</v></c></row>' for n in range(1, ci.MAX_ROWS + 3))
    with pytest.raises(ci.ImportFileError) as info:
        ci.parse_import("m.xlsx", with_sheet(rows), TODAY)
    assert info.value.status == 422 and info.value.slug == "import-too-many-rows"


def test_blank_rows_are_tolerated_up_to_the_physical_limit() -> None:
    limits = xs.StreamLimits(max_rows=2, max_physical_rows=10)
    blanks = "".join(f'<row r="{n}"/>' for n in range(1, 9))
    assert len(read(with_sheet(blanks), limits)) == 8
    many = "".join(f'<row r="{n}"/>' for n in range(1, 13))
    rejected(with_sheet(many), limits, kind="rows")
    rejected(with_sheet('<row r="999"/>'), limits, kind="rows")


def test_more_than_fifty_cells_in_a_row_is_rejected() -> None:
    cells = "".join(f"<c><v>{i}</v></c>" for i in range(51))
    rejected(with_sheet(f"<row>{cells}</row>"))
    fifty = "".join(f"<c><v>{i}</v></c>" for i in range(50))
    assert len(read(with_sheet(f"<row>{fifty}</row>"))[0]) == 50


def test_value_beyond_column_fifty_is_rejected_but_blank_is_ignored() -> None:
    far = '<row r="1"><c r="A1"><v>1</v></c><c r="BA1"><v>2</v></c></row>'  # BA = 53. sütun
    rejected(with_sheet(far))
    blank = '<row r="1"><c r="A1"><v>1</v></c><c r="BA1" s="1"/><c r="BB1" t="inlineStr"><is><t> </t></is></c></row>'
    assert read(with_sheet(blank)) == [[1]]


def test_total_cell_limit_and_other_element_limit_and_depth() -> None:
    rows = "".join(f'<row r="{n}"><c r="A{n}"/><c r="B{n}"/></row>' for n in range(1, 4))
    rejected(with_sheet(rows), xs.StreamLimits(max_cells=5))
    rejected(
        package({"xl/worksheets/sheet1.xml": sheet_xml("", tail="<a/>" * 20)}),
        xs.StreamLimits(max_other_elements=10),
    )
    deep = "<a>" * 40 + "</a>" * 40
    rejected(package({"xl/worksheets/sheet1.xml": sheet_xml("", tail=deep)}))


def test_repeated_cell_children_and_runs_count_as_unrecognized() -> None:
    limits = xs.StreamLimits(max_other_elements=5)
    twice = '<row r="1"><c r="A1"><v>1</v><v>2</v><v>3</v><v>4</v><v>5</v><v>6</v><v>7</v></c></row>'
    rejected(with_sheet(twice), limits)
    runs = '<row r="1"><c r="A1" t="inlineStr"><is>' + "<t>x</t>" * 30 + "</is></c></row>"
    rejected(with_sheet(runs), limits)
    big_runs = f'<?xml version="1.0"?><sst xmlns="{MAIN}"><si>{"<t>x</t>" * 30}</si></sst>'
    cell = '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
    rejected(with_sheet(cell, **{"xl/sharedStrings.xml": big_runs}), limits)


def test_text_budget_and_long_cells() -> None:
    long_text = "x" * 5000
    rows = (
        f'<row r="1"><c r="A1" t="inlineStr"><is><t>{long_text}</t></is></c>'
        f'<c r="B1" t="str"><v>{long_text}</v></c></row>'
    )
    got = read(with_sheet(rows))
    assert len(got[0][0]) == xs.MAX_CELL_CHARS and len(got[0][1]) == xs.MAX_CELL_CHARS
    rejected(with_sheet(rows), xs.StreamLimits(max_text_chars=300))
    shared = '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>0</v></c></row>'
    data = with_sheet(shared, **{"xl/sharedStrings.xml": sst_xml("y" * 100)})
    rejected(data, xs.StreamLimits(max_text_chars=150))
    num = '<row r="1"><c r="A1"><v>' + "9" * 80 + "</v></c></row>"
    rejected(with_sheet(num), xs.StreamLimits(max_text_chars=10))


def test_style_and_shared_string_count_limits_in_the_stream() -> None:
    rows = '<row r="1"><c r="A1" s="1"><v>1</v></c></row>'
    rejected(with_sheet(rows, **{"xl/styles.xml": styles_xml()}), xs.StreamLimits(max_style_xfs=2))
    fmts = styles_xml(custom={164: "d", 165: "d", 166: "d"})
    rejected(with_sheet(rows, **{"xl/styles.xml": fmts}), xs.StreamLimits(max_style_xfs=2))
    refs = '<row r="1"><c r="A1" t="s"><v>2</v></c></row>'
    rejected(
        with_sheet(refs, **{"xl/sharedStrings.xml": sst_xml("a", "b", "c")}),
        xs.StreamLimits(max_shared_strings=2),
    )


def test_styles_other_elements_are_budgeted_and_xf_elsewhere_is_ignored() -> None:
    rows = '<row r="1"><c r="A1" s="1"><v>45000</v></c></row>'
    junk = (
        f'<?xml version="1.0"?><styleSheet xmlns="{MAIN}"><fonts>{"<font/>" * 50}</fonts>'
        '<cellStyleXfs><xf numFmtId="14"/></cellStyleXfs>'
        '<cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs></styleSheet>'
    )
    data = with_sheet(rows, **{"xl/styles.xml": junk})
    rejected(data, xs.StreamLimits(max_other_elements=10))
    assert read(data) == [[date(2023, 3, 15)]]
    rejected(with_sheet(rows, **{"xl/styles.xml": f'<x xmlns="{MAIN}"/>'}))


def test_shared_string_index_errors() -> None:
    for value in ("7", "-1", "x", "1" * 12):  # tabloda yok, negatif, sayı değil, çok uzun
        rows = f'<row r="1"><c r="A1" t="s"><v>{value}</v></c></row>'
        rejected(with_sheet(rows))
    rows = '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
    no_sst = with_sheet(
        rows,
        **{
            "[Content_Types].xml": content_types(sst=False),
            "xl/_rels/workbook.xml.rels": workbook_rels(sst=None),
            "xl/sharedStrings.xml": None,
        },
    )
    rejected(no_sst)
    rejected(with_sheet(rows, **{"xl/sharedStrings.xml": f'<?xml version="1.0"?><x xmlns="{MAIN}"/>'}))


def test_bad_cell_attributes_and_ordering() -> None:
    rejected(with_sheet('<row r="1"><c r="1A"><v>1</v></c></row>'))
    rejected(with_sheet('<row r="1"><c r="ABCD1"><v>1</v></c></row>'))
    rejected(with_sheet('<row r="1"><c r="B1"/><c r="A1"/></row>'))
    rejected(with_sheet('<row r="2"/><row r="1"/>'))
    rejected(with_sheet('<row r="x"/>'))
    rejected(with_sheet('<row r="1"><c t="zz"><v>1</v></c></row>'))
    rejected(package({"xl/worksheets/sheet1.xml": f'<x xmlns="{MAIN}"/>'}))


# --- paket yapısı, Override ve ilişkiler ---------------------------------------------------------------


def test_override_content_type_must_match_the_file_name() -> None:
    rows = '<row r="1"><c r="A1"><v>1</v></c></row>'

    def build(content: str) -> bytes:
        return with_sheet(rows, **{"[Content_Types].xml": content})

    rejected(build(content_types().replace(xs._CT_SST, xs._CT_STYLES)))  # sharedStrings adı başka türle
    foo = f'<Override PartName="/xl/foo.xml" ContentType="{xs._CT_SST}"/>'
    rejected(build(content_types(extra=foo)))  # sharedStrings türü başka ad
    other = f'<Override PartName="/xl/other.xml" ContentType="{xs._CT_SHEET}"/>'
    rejected(build(content_types(extra=other)))  # sayfa türü sayfa deseni dışında bir ada
    rejected(build(content_types(sheet_ct="text/plain")))  # ilk sayfa başka tür
    workbook = f'<Override PartName="/xl/workbook.xml" ContentType="{xs._CT_WORKBOOK}"/>'
    rejected(build(content_types().replace(workbook, "")))  # çalışma kitabı Override'ı yok
    dup = f'<Override PartName="/xl/styles.xml" ContentType="{xs._CT_STYLES}"/>'
    rejected(build(content_types(extra=dup)))  # yinelenen PartName
    rejected(build(content_types(extra='<Override PartName="xl/x.xml" ContentType="a/b"/>')))
    rejected(build(content_types(extra="<Override/>")))
    rejected(build(f'<Other xmlns="{CT_NS}"/>'))  # yanlış kök
    ok = content_types(
        extra=f'<Default Extension="xml" ContentType="application/xml"/><Foo xmlns="{CT_NS}"/>'
    )
    assert read(build(ok)) == [[1]]  # geçerli Default ve tanınmayan öğe tolere edilir
    rejected(build(ok), xs.StreamLimits(max_other_elements=0))


def test_relationship_targets_are_validated() -> None:
    rows = '<row r="1"><c r="A1"><v>1</v></c></row>'

    def build(rels: str, **parts: Any) -> bytes:
        return with_sheet(rows, **{"xl/_rels/workbook.xml.rels": rels, **parts})

    for target in ("../../x", "worksheets\\sheet1.xml", "http://x/y.xml", "", "/../x.xml"):
        rejected(build(workbook_rels(sheet_target=target)))
    rejected(build(workbook_rels(sheet_target="styles.xml")))  # sayfa deseni dışı hedef
    rejected(build(workbook_rels(sheet_target="worksheets/sheet7.xml")))  # var olmayan sayfa
    rejected(build(workbook_rels(sst="worksheets/sheet1.xml")))  # sharedStrings başka yola yönlendirilmiş
    rejected(build(workbook_rels(styles="sharedStrings.xml")))
    dup = f'<Relationship Id="rId1" Type="{TYPE_BASE}/theme" Target="theme/theme1.xml"/>'
    rejected(build(workbook_rels(extra=dup)))
    ext = f'<Relationship Id="rId8" Type="{TYPE_BASE}/hyperlink" Target="http://x" TargetMode="External"/>'
    rejected(build(workbook_rels(extra=ext)))
    rejected(build(workbook_rels(extra="<Relationship/>")))
    second = f'<Relationship Id="rId5" Type="{TYPE_BASE}/sharedStrings" Target="sharedStrings.xml"/>'
    rejected(build(workbook_rels(extra=second)))
    rejected(build(workbook_rels().replace('/worksheet"', '/chartsheet"')))  # çalışma sayfası türünde değil
    odd = workbook_rels(extra="<Odd/>")
    assert read(build(odd)) == [[1]]
    rejected(build(odd), xs.StreamLimits(max_other_elements=0))
    for part in ("xl/sharedStrings.xml", "xl/styles.xml"):  # hedef bölüm arşivde yok
        rejected(with_sheet(rows, **{part: None}))
    missing = workbook_xml(sheets='<sheet name="S" sheetId="1" r:id="rId77"/>')
    rejected(with_sheet(rows, **{"xl/workbook.xml": missing}))  # kimlik ilişkilerde yok


def test_workbook_errors() -> None:
    def build(workbook: str) -> bytes:
        return package({"xl/workbook.xml": workbook})

    rejected(build(f'<x xmlns="{MAIN}"/>'))
    rejected(build(workbook_xml(sheets="")))
    rejected(build(workbook_xml(sheets='<sheet name="S" sheetId="1"/>')))
    junk = workbook_xml().replace("<sheets>", "<bookViews><a/><b/><c/></bookViews><sheets>")
    rejected(build(junk), xs.StreamLimits(max_other_elements=1))
    strict = workbook_xml().replace(REL, "http://purl.oclc.org/ooxml/officeDocument/relationships")
    assert read(build(strict)) == []


def test_malformed_xml_doctype_and_entities_are_rejected() -> None:
    bomb = '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
    body = f'<worksheet xmlns="{MAIN}"><sheetData>&b;</sheetData></worksheet>'
    rejected(package({"xl/worksheets/sheet1.xml": bomb + body}))
    xxe = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///nonexistent">]>'
    rejected(package({"xl/worksheets/sheet1.xml": xxe + body.replace("&b;", "&e;")}))
    rejected(package({"xl/worksheets/sheet1.xml": "<worksheet><sheetData></worksheet>"}))
    rejected(package({"[Content_Types].xml": ""}))  # boş belge
    rejected(package({"[Content_Types].xml": f'<?xml version="1.0"?><Types xmlns="{CT_NS}">'}))


def test_not_a_zip_and_missing_parts_are_rejected() -> None:
    rejected(b"PK\x03\x04bozuk")
    rejected(package({"xl/_rels/workbook.xml.rels": None}))


# --- defusedxml zorunluluğu -------------------------------------------------------------------------


def test_require_defusedxml_checks_the_real_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    xs.require_defusedxml()
    ci.require_defusedxml()
    import xml.etree.ElementTree as plain

    monkeypatch.setattr(xs, "_safe_iterparse", plain.iterparse)
    with pytest.raises(RuntimeError, match="defusedxml"):
        xs.require_defusedxml()
    with pytest.raises(ci.ImportFileError) as info:
        ci.parse_import("m.xlsx", xlsx_bytes([["barkod"]]), TODAY)
    assert info.value.status == 503


def test_require_defusedxml_detects_a_parser_that_accepts_doctype(monkeypatch: pytest.MonkeyPatch) -> None:
    import xml.etree.ElementTree as plain

    def lax(source: Any, events: Any = None, **_: Any) -> Any:
        return plain.iterparse(source, events)  # noqa: S314

    lax.__module__ = "defusedxml.ElementTree"  # adı uyar ama DTD'yi reddetmez
    monkeypatch.setattr(xs, "_safe_iterparse", lax)
    with pytest.raises(RuntimeError, match="reddetmiyor"):
        xs.require_defusedxml()

    def broken(source: Any, events: Any = None, **_: Any) -> Any:
        raise OSError("boom")

    broken.__module__ = "defusedxml.ElementTree"
    monkeypatch.setattr(xs, "_safe_iterparse", broken)
    with pytest.raises(RuntimeError, match="reddetmiyor"):
        xs.require_defusedxml()


def test_runtime_parse_path_does_not_use_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    import openpyxl

    def boom(*a: Any, **k: Any) -> Any:
        raise AssertionError("openpyxl çalışma zamanında kullanılmamalı")

    monkeypatch.setattr(openpyxl, "load_workbook", boom)
    result = ci.parse_import(
        "m.xlsx", xlsx_bytes([["barkod", "maliyet", "kdv"], ["8681000000011", 5, 20]]), TODAY
    )
    assert result.valid == 1 and result.file_format == "xlsx"


def test_import_limits_carry_the_stream_settings() -> None:
    limits = ci.ImportLimits(max_sheet_cells=7, max_other_elements=8, max_text_chars=9)
    stream = limits.stream
    assert (stream.max_cells, stream.max_other_elements, stream.max_text_chars) == (7, 8, 9)
    assert stream.max_columns == ci.MAX_COLUMNS and stream.max_physical_rows == ci.MAX_PHYSICAL_ROWS


# --- YK-02 / YK-03: şablon CSV kaçışı --------------------------------------------------------------------

DANGER = ("=", "+", "-", "@", "＝", "＋", "－", "＠")


def fields_under_all_delimiters(line: str) -> list[str]:
    out: list[str] = []
    for delimiter in (",", ";", "\t"):
        for row in csv.reader(io.StringIO(line, newline=""), delimiter=delimiter):
            out.extend(row)
            for field in row:
                out.extend(field.replace(";", ",").replace("\t", ",").split(","))
    return out


@pytest.mark.parametrize(
    "title",
    [
        'x,"=1+1,y',
        'x;"=1+1;y',
        "x, =1+1",
        'x," =SUM(1;2),y',
        'x,"  "=1',
        "x,'=1",
        "x;＝1",
        'x,""""-2',
        "x,\t@a",
        "x\n=1",
        "x\r\n+1",
        '"=1',
        ' "=1',
        "=1",
        # Not: "\t=1" burada yok; baştaki sekme tek tırnakla kapsanır ("'\t=1", eski kural) ve tırnaklı alan
        # içinde sekmeye böyle körü körüne bölen bir okuyucu CSV'yi zaten bozar.
    ],
)
def test_template_has_no_bare_formula_fragment_under_any_delimiter(title: str) -> None:
    data = ci.build_template_csv([("A1", title)]).decode("utf-8-sig")
    for line in data.replace("\r\n", "\n").split("\n")[1:]:
        for field in fields_under_all_delimiters(line):
            stripped = field.lstrip().lstrip('"').lstrip()
            assert not stripped.startswith(DANGER) or field.lstrip().startswith("'"), (title, field)
    rows = list(csv.reader(io.StringIO(data, newline=""), delimiter=";"))
    assert rows[1][0] == "A1" and len(rows[1]) == 5  # dosya kendi ayrıştırıcımızla bozulmadan okunur


@pytest.mark.parametrize(
    ("raw", "safe"),
    [
        ('x,"=1+1,y', "x,\"'=1+1,y"),
        ('x;"=1+1;y', "x;\"'=1+1;y"),
        ("x, =1+1", "x, '=1+1"),
        ("x;  +1", "x;  '+1"),
        (" =1", "' =1"),
        ('"=1', "'\"=1"),
        ("\t=1", "'\t=1"),
        ("\tabc", "'\tabc"),
        ("=x,=y", "'=x,'=y"),
        ("a=b, c-d; e@f", "a=b, c-d; e@f"),
        ("Ürün A - B", "Ürün A - B"),
        ("x;'=1", "x;'=1"),
        ("", ""),
        (None, ""),
        ("normal", "normal"),
        ("x, =1", "x, '=1"),
        ("x,​＝1", "x,​'＝1"),
    ],
)
def test_csv_safe_cell_cases(raw: str | None, safe: str) -> None:
    assert ci.csv_safe_cell(raw) == safe


@pytest.mark.parametrize("filler", ["\t", " ", '"', '\t "', ",\t", "x"])
def test_csv_safe_cell_is_linear_on_adversarial_input(filler: str) -> None:
    for text in (filler * 200_000, "x" + filler * 200_000 + "y", filler * 100_000 + "=1"):
        started = time.perf_counter()
        out = ci.csv_safe_cell(text)
        assert time.perf_counter() - started < 0.2
        assert len(out) <= ci.MAX_TEMPLATE_CELL_CHARS * 2 + 1


def test_template_cell_is_truncated_and_a_huge_tab_title_is_fast() -> None:
    title = "x" + "\t" * 200_000 + "y"
    started = time.perf_counter()
    data = ci.build_template_csv([("A1", title), ("A2", "b" * 900)])
    assert time.perf_counter() - started < 0.2
    rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), delimiter=";"))
    assert len(rows[1][1]) == ci.MAX_TEMPLATE_CELL_CHARS and rows[2][1] == "b" * ci.MAX_TEMPLATE_CELL_CHARS
    assert ci.csv_safe_cell("8681000000011") == "8681000000011"  # barkod (<= 200) kesilmez
