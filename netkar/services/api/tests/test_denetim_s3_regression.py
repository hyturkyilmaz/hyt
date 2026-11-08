"""S3 denetimi regresyon testleri (maliyet içe aktarma): PoC'lerin tersi, bulgu KAPANDIĞINI doğrular.

Rapor: docs/security/denetim_2026-11-08_S3_maliyet.md (Ek A). Dosyalar bellekte küçük üretilir; hiçbir
test gerçek bellek şişirmez (PoC'deki 1,3 GB'lık ayrıştırma ASLA çalıştırılmaz: zip denetimi onu önler).
"""

from __future__ import annotations

import csv
import io
import re
import threading
import time
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import openpyxl.xml
import psycopg
import pytest
from starlette import formparsers

from app.api.v1 import product_costs as product_costs_module
from app.api.v1.product_costs import COST_IMPORT_PATH_PATTERN
from app.main import create_app
from app.services import cost_import as ci
from app.services.cost_import import parse_import as real_parse_import
from app.services.product_costs import RuleError
from tests.conftest import Api
from tests.product_cost_helpers import (
    B1,
    Shop,
    add_product,
    count_costs,
    csv_bytes,
    fixed_today,  # noqa: F401  (fixture)
    make_shop_factory,
    rewrite_zip,
    upload,
    xlsx_bytes,
)

pytestmark = pytest.mark.usefixtures("fixed_today")

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
TODAY = date(2026, 11, 8)


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


def small_xlsx() -> bytes:
    return xlsx_bytes([["barkod", "birim_maliyet_kdv_haric", "kdv_orani"], [B1, 5, 20]])


def with_part(name: str, content: bytes) -> bytes:
    """Geçerli bir XLSX'in `name` bölümünü değiştirir (yoksa ekler)."""
    base = small_xlsx()
    seen = False

    def edit(entry: str, data: bytes) -> bytes:
        nonlocal seen
        if entry == name:
            seen = True
            return content
        return data

    rewritten = rewrite_zip(base, edit)
    if seen:
        return rewritten
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(rewritten)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as t,
    ):
        for info in source.infolist():
            t.writestr(info.filename, source.read(info))
        t.writestr(name, content)
    return out.getvalue()


def styles_with(count: int, *, prefix: str = "") -> bytes:
    tag = f"{prefix}:xf" if prefix else "xf"
    root = f"{prefix}:styleSheet" if prefix else "styleSheet"
    ns = f'xmlns:{prefix}="{MAIN_NS}"' if prefix else f'xmlns="{MAIN_NS}"'
    body = f'<{tag} numFmtId="0" fontId="0"/>' * count
    return f'<?xml version="1.0"?><{root} {ns}><{prefix + ":" if prefix else ""}cellXfs>{body}</{prefix + ":" if prefix else ""}cellXfs></{root}>'.encode()


def shared_strings_with(count: int) -> bytes:
    # Her dize farklı: sıkıştırma oranı düşük kalır, böylece yalnız öğe sayısı sınırı sınanır.
    body = "".join(f"<si><t>s{i:x}</t></si>" for i in range(count))
    return f'<?xml version="1.0"?><sst xmlns="{MAIN_NS}">{body}</sst>'.encode()


# --- Y-01: bölüm izin listesi, bölüm sınırı, öğe sayısı ---------------------------------------------------


def test_y01_poc_2_5_million_xf_file_is_rejected_fast(shop: Shop) -> None:
    """Denetim A.1: küçük dosya, 2,5 milyon <xf>. Eskiden 22 sn ve ~1,3 GB; şimdi ayrıştırmaya girmeden red."""
    styles = b'<xf numFmtId="0" fontId="0"/>' * 2_500_000
    data = with_part("xl/styles.xml", styles)
    assert len(data) < 2 * 1024 * 1024  # 2 MiB yükleme sınırının altında
    started = time.perf_counter()
    r = upload(shop, data, "poc.xlsx")
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:import-file-invalid"
    assert time.perf_counter() - started < 1.0


def test_y01_poc_with_random_xfs_passes_old_checks_but_not_the_part_limit() -> None:
    """Denetimdeki asıl dosya: toplam (<50 MiB) ve oran (<100) denetimlerini geçer; bölüm sınırı reddeder."""
    import random

    rnd = random.Random(7)
    variants = [f'<xf numFmtId="{i}" fontId="0"/>'.encode() for i in range(4)]
    styles = b"".join(rnd.choices(variants, k=1_600_000))  # ~ 48 MB açılmış
    data = with_part("xl/styles.xml", styles)
    assert len(styles) < ci.MAX_ZIP_UNCOMPRESSED and len(styles) < ci.MAX_ZIP_RATIO * len(data)
    started = time.perf_counter()
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.parse_import("poc.xlsx", data, TODAY)
    assert time.perf_counter() - started < 1.0


def test_y01_poc_shared_strings_bomb_is_rejected_fast(shop: Shop) -> None:
    data = with_part("xl/sharedStrings.xml", b"<si><t>abc</t></si>" * 2_700_000)
    assert len(data) < 2 * 1024 * 1024
    started = time.perf_counter()
    assert upload(shop, data, "poc2.xlsx").status_code == 422
    assert time.perf_counter() - started < 1.0


def test_y01_style_element_count_limit_is_enforced_before_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bölüm sınırının altında kalan ama çok öğeli styles.xml: openpyxl hiç çağrılmaz."""
    import openpyxl

    def boom(*a: Any, **k: Any) -> Any:  # pragma: no cover - çağrılırsa test düşer
        raise AssertionError("openpyxl çağrılmamalıydı")

    monkeypatch.setattr(openpyxl, "load_workbook", boom)
    for prefix in ("", "x"):  # ad alanı önekli sürüm de sayılır
        ci.check_zip(with_part("xl/styles.xml", styles_with(10_000, prefix=prefix)))
        with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
            ci.check_zip(with_part("xl/styles.xml", styles_with(10_001, prefix=prefix)))
        with pytest.raises(ci.ImportFileError):
            ci.parse_import("m.xlsx", with_part("xl/styles.xml", styles_with(10_001, prefix=prefix)), TODAY)


def test_y01_shared_string_count_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    ci.check_zip(with_part("xl/sharedStrings.xml", shared_strings_with(200_000)))
    with pytest.raises(ci.ImportFileError):
        ci.check_zip(with_part("xl/sharedStrings.xml", shared_strings_with(200_001)))


def test_y01_unknown_parts_are_rejected_and_known_extras_pass() -> None:
    for name in ("xl/embeddings/oleObject1.bin", "customXml/item1.xml", "xl/media/image1.png", "evil.txt"):
        with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
            ci.check_zip(with_part(name, b"<x/>"))
    for name in ("docProps/custom.xml", "xl/calcChain.xml", "xl/worksheets/_rels/sheet1.xml.rels"):
        ci.check_zip(with_part(name, b"<x/>"))
    ci.check_zip(small_xlsx())  # openpyxl'in kendi çıktısı olduğu gibi geçer


def test_y01_duplicate_entry_names_are_rejected() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(small_xlsx())) as source, zipfile.ZipFile(out, "w") as target:
        for info in source.infolist():
            target.writestr(info.filename, source.read(info))
        with pytest.warns(UserWarning):
            target.writestr("xl/styles.xml", b"<styleSheet/>")  # ikinci styles.xml
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.check_zip(out.getvalue())


def test_y01_non_utf8_xml_cannot_hide_elements_from_the_scan() -> None:
    utf16 = ("﻿" + styles_with(10_001).decode()).encode("utf-16")
    with pytest.raises(ci.ImportFileError):
        ci.check_zip(with_part("xl/styles.xml", utf16))
    nul = b"<\x00?\x00" + styles_with(5)
    with pytest.raises(ci.ImportFileError):
        ci.check_zip(with_part("xl/sharedStrings.xml", nul))
    ci.check_zip(with_part("xl/styles.xml", b"\xef\xbb\xbf" + styles_with(5)))  # UTF-8 BOM serbest


def test_y01_part_size_limits_come_from_limits_object() -> None:
    limits = ci.ImportLimits(
        max_styles_bytes=500, max_shared_strings_bytes=600, max_sheet_bytes=700, max_other_part_bytes=800
    )
    for name, size in (
        ("xl/styles.xml", 501),
        ("xl/sharedStrings.xml", 601),
        ("xl/worksheets/sheet1.xml", 701),
        ("docProps/core.xml", 801),
    ):
        padded = b"<a>" + b"x" * size + b"</a>"
        with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
            ci.check_zip(with_part(name, padded), limits)


def test_y01_streaming_count_does_not_trust_the_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bildirilen boyut küçük, gerçek akış büyükse bölüm sınırı gerçek sayıyla uygulanır."""
    limits = ci.ImportLimits(max_styles_bytes=1000)
    data = with_part("xl/styles.xml", b"<styleSheet/>")  # başlıkta küçük
    real_open = zipfile.ZipFile.open

    def lying_open(self: zipfile.ZipFile, name: Any, *a: Any, **k: Any) -> Any:
        info_name = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if info_name == "xl/styles.xml":
            return io.BytesIO(b"<styleSheet>" + b"x" * 5000 + b"</styleSheet>")
        return real_open(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "open", lying_open)
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.check_zip(data, limits)


def test_y01_valid_workbook_still_imports_end_to_end(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    r = upload(shop, small_xlsx(), "m.xlsx", dry_run=False)
    assert r.status_code == 200 and r.json()["created"] == 1
    assert count_costs(admin_conn, shop) == 1


def test_y01_limits_are_configurable_from_settings(make_shop: Callable[..., Shop]) -> None:
    tight = make_shop("t@example.com", "T", cost_import_max_style_xfs=3)
    ok = upload(tight, small_xlsx(), "m.xlsx")  # openpyxl çıktısı birkaç xf içerir
    assert ok.status_code in {200, 422}
    many = with_part("xl/styles.xml", styles_with(4))
    assert upload(tight, many, "m.xlsx").status_code == 422


# --- Y-01 (d): eşzamanlılık ---------------------------------------------------------------------------------------


class BlockedParse:
    """`parse_import`'ı bir olay beklemeye zorlar (ayrı iş parçacığında çalışır)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.real = real_parse_import
        monkeypatch.setattr(product_costs_module, "parse_import", self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.entered.set()
        assert self.release.wait(10)
        return self.real(*args, **kwargs)


def run_in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, list[Any]]:
    box: list[Any] = []
    thread = threading.Thread(target=lambda: box.append(fn()))
    thread.start()
    return thread, box


def test_y01_second_concurrent_import_of_same_tenant_is_rejected(
    shop: Shop, monkeypatch: pytest.MonkeyPatch, admin_conn: psycopg.Connection[Any]
) -> None:
    blocked = BlockedParse(monkeypatch)
    data = csv_bytes(f"{B1};5;20;2026-10-01")
    thread, box = run_in_thread(lambda: upload(shop, data, dry_run=False))
    try:
        assert blocked.entered.wait(10)
        second = upload(shop, data)
        assert second.status_code == 429
        assert second.json()["type"] == "urn:netkar:problem:import-in-progress"
        assert int(second.headers["Retry-After"]) >= 1
    finally:
        blocked.release.set()
        thread.join(15)
    assert box[0].status_code == 200 and count_costs(admin_conn, shop) == 1
    assert upload(shop, data).status_code == 200  # kilit bırakıldı


def test_y01_tenant_lock_is_released_after_failures(shop: Shop) -> None:
    assert upload(shop, b"PK\x03\x04bozuk", "m.xlsx").status_code == 422
    assert upload(shop, csv_bytes(f"{B1};5;20;2026-10-01")).status_code == 200
    assert shop.api.client.app.state.import_gate.active_tenants == 0  # type: ignore[attr-defined]


def test_y01_process_wide_parse_limit_answers_503_with_retry_after(shop: Shop) -> None:
    import asyncio

    gate = shop.api.client.app.state.import_gate  # type: ignore[attr-defined]

    async def occupy() -> None:
        for _ in range(gate.parallelism):
            await gate._slots.acquire()

    asyncio.run(occupy())  # tüm ayrıştırma yuvaları dolu
    r = upload(shop, csv_bytes(f"{B1};5;20;2026-10-01"))
    assert r.status_code == 503 and r.json()["type"] == "urn:netkar:problem:import-busy"
    assert int(r.headers["Retry-After"]) >= 1
    for _ in range(gate.parallelism):
        gate._slots.release()
    assert upload(shop, csv_bytes(f"{B1};5;20;2026-10-01")).status_code == 200


def test_y01_default_parse_concurrency_is_two(shop: Shop) -> None:
    assert shop.api.client.app.state.import_gate.parallelism == 2  # type: ignore[attr-defined]


# --- O-01: ayrıştırma sırasında bağlantı tutulmaz -------------------------------------------------------


def idle_in_transaction(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE usename = 'netkar_app' AND state LIKE 'idle in transaction%'"
    ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("dry_run", [True, False])
def test_o01_no_transaction_is_open_while_the_file_is_parsed(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, dry_run: bool
) -> None:
    observed: list[int] = []
    real = real_parse_import

    def spying_parse(*args: Any, **kwargs: Any) -> Any:
        observed.append(idle_in_transaction(admin_conn))
        return real(*args, **kwargs)

    monkeypatch.setattr(product_costs_module, "parse_import", spying_parse)
    r = upload(shop, csv_bytes(f"{B1};5;20;2026-10-01"), dry_run=dry_run)
    assert r.status_code == 200
    assert observed == [0]  # ayrıştırma sırasında "idle in transaction" bağlantı yok
    assert count_costs(admin_conn, shop) == (0 if dry_run else 1)


def test_o01_rls_context_is_rebuilt_after_parsing(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    """Bağlam yeniden kurulmazsa yazma RLS'e takılırdı; iki kiracı ayrı kalır."""
    a = make_shop("a@example.com", "A")
    b = make_shop("b@example.com", "B")
    assert upload(a, csv_bytes(f"{B1};5;20;2026-10-01"), dry_run=False).status_code == 200
    assert upload(b, csv_bytes(f"{B1};7;20;2026-10-01"), dry_run=False).status_code == 200
    rows = admin_conn.execute("SELECT tenant_id, unit_cost_excl_vat FROM product_costs").fetchall()
    assert {(r[0], int(r[1])) for r in rows} == {(a.tenant_id, 5), (b.tenant_id, 7)}


# --- D-01: kimlik doğrulama gövde ayrıştırmadan önce ---------------------------------------------------


@pytest.fixture
def parse_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = formparsers.MultiPartParser.parse

    async def counting(self: Any) -> Any:
        calls.append(1)
        return await real(self)

    monkeypatch.setattr(formparsers.MultiPartParser, "parse", counting)
    return calls


def test_d01_unauthenticated_upload_is_rejected_before_multipart_parsing(
    shop: Shop, make_api: Callable[..., Api], parse_calls: list[int]
) -> None:
    anon = make_api()
    big = csv_bytes(*[f"B{i};1;20;2026-10-01" for i in range(40_000)])[: 2 * 1024 * 1024]
    url = f"{shop.base}/product-costs/import"
    r = anon.post(url, None, files={"file": ("m.csv", big, "text/csv")})
    assert r.status_code == 401 and r.json()["type"] == "urn:netkar:problem:unauthorized"
    sneaky = "/v1/marketplace-accounts/" + "-" * 36 + "/product-costs/import"
    assert anon.post(sneaky, None, files={"file": ("m.csv", big, "text/csv")}).status_code in {401, 413, 422}
    assert parse_calls == []  # gövde hiç ayrıştırılmadı


def test_d01_forbidden_and_foreign_account_never_parse_the_body(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], parse_calls: list[int]
) -> None:
    a = make_shop("a@example.com", "A")
    b = make_shop("b@example.com", "B")
    data = csv_bytes(f"{B1};5;20;2026-10-01")
    foreign = b.api.post(f"{a.base}/product-costs/import", None, files={"file": ("m.csv", data, "text/csv")})
    assert foreign.status_code == 404
    assert parse_calls == []
    admin_conn.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = %s", (a.user_id,))
    assert upload(a, data).status_code == 403
    assert parse_calls == []
    admin_conn.execute("UPDATE memberships SET role = 'admin' WHERE user_id = %s", (a.user_id,))
    assert upload(a, data).status_code == 200
    assert parse_calls == [1]  # yetkili istekte ayrıştırma yapılır


def test_d01_body_limit_still_applies_to_unauthenticated_requests(
    shop: Shop, make_api: Callable[..., Api]
) -> None:
    anon = make_api()
    huge = bytes(2 * 1024 * 1024 + 128 * 1024)
    r = anon.post(f"{shop.base}/product-costs/import", None, files={"file": ("m.csv", huge, "text/csv")})
    assert r.status_code == 413
    sneaky = "/v1/marketplace-accounts/" + "-" * 36 + "/product-costs/import"
    r2 = anon.post(sneaky, None, files={"file": ("m.csv", bytes(20_000), "text/csv")})
    assert r2.status_code == 413  # UUID olmayan yol küçük (8 KiB) sınıra düşer


def test_d01_path_pattern_accepts_only_canonical_uuids() -> None:
    pattern = re.compile(COST_IMPORT_PATH_PATTERN)
    ok = "/v1/marketplace-accounts/c667c73c-ecd7-4de1-aa94-c5247a61e8ad/product-costs/import"
    assert pattern.fullmatch(ok) and pattern.fullmatch(
        ok.upper()
        .replace("/V1/", "/v1/")
        .replace("MARKETPLACE-ACCOUNTS", "marketplace-accounts")
        .replace("PRODUCT-COSTS", "product-costs")
        .replace("IMPORT", "import")
    )
    for bad in (
        "/v1/marketplace-accounts/" + "-" * 36 + "/product-costs/import",
        "/v1/marketplace-accounts/" + "a" * 36 + "/product-costs/import",
        "/v1/marketplace-accounts/c667c73cecd74de1aa94c5247a61e8ad/product-costs/import",
        "/v1/marketplace-accounts/c667c73c-ecd7-4de1-aa94-c5247a61e8ad/product-costs/import/",
        "/v1/marketplace-accounts/c667c73c-ecd7-4de1-aa94-c5247a61e8aG/product-costs/import",
    ):
        assert not pattern.fullmatch(bad)


def test_d01_openapi_still_documents_the_multipart_file(shop: Shop) -> None:
    spec = shop.api.get("/v1/openapi.json").json()
    op = spec["paths"]["/v1/marketplace-accounts/{account_id}/product-costs/import"]["post"]
    assert "multipart/form-data" in op["requestBody"]["content"]


# --- D-02: şablon CSV formül kaçışı ----------------------------------------------------------------------


def split_naive(line: str) -> list[str]:
    """Liste ayırıcısı ',' veya ';' veya sekme olan bir Excel'in satırı körü körüne bölmesi."""
    return re.split(r"[,;\t]", line)


@pytest.mark.parametrize(
    "title",
    [
        "x,=1+1,y",
        "x;=1+1;y",
        "x,+1,y",
        "x;-1;y",
        "x,@SUM(1),y",
        "x\t=1",
        "x, =1",
        "x; =1",
        "x,＝1",
        "=1",
        " =1",
        "x;'=1",
    ],
)
def test_d02_template_has_no_formula_fragment_under_any_delimiter(
    shop: Shop, admin_conn: psycopg.Connection[Any], title: str
) -> None:
    add_product(admin_conn, shop, "A1", title)
    text = shop.api.get(f"{shop.base}/product-costs/template.csv").content.decode("utf-8-sig")
    for line in text.replace("\r\n", "\n").split("\n")[1:]:
        for part in split_naive(line):
            stripped = part.lstrip().lstrip('"').lstrip()
            assert not stripped.startswith(("=", "+", "-", "@", "＝", "＋", "－", "＠")), (title, part)
    # dosya, kendi ayrıştırıcımızla da bozulmadan okunur
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[1][0] == "A1" and len(rows[1]) == 5


def test_d02_all_text_cells_are_quoted_and_roundtrip(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    add_product(admin_conn, shop, B1, 'Şık "çanta"; (2,5)')
    raw = shop.api.get(f"{shop.base}/product-costs/template.csv").content.decode("utf-8-sig")
    assert raw.splitlines()[1].startswith(f'"{B1}";"')
    rows = list(csv.reader(io.StringIO(raw), delimiter=";"))
    assert rows[0] == list(ci.TEMPLATE_HEADER) and rows[1][1] == 'Şık "çanta"; (2,5)'
    # doldurulmuş şablon geri yüklenir
    filled = raw.replace(f'"{B1}";"Şık ""çanta""; (2,5)";"";"";""', f'"{B1}";"x";"49,90";"20";"01.10.2026"')
    assert filled != raw
    report = upload(shop, filled.encode("utf-8-sig"), "s.csv").json()
    assert report["valid"] == 1 and report["invalid"] == 0


def test_d02_csv_safe_cell_inner_separators() -> None:
    assert ci.csv_safe_cell("x,=1+1,y") == "x,'=1+1,y"
    assert ci.csv_safe_cell("x;=1+1;y") == "x;'=1+1;y"
    assert ci.csv_safe_cell("x;  +1") == "x;  '+1"
    assert ci.csv_safe_cell(" =1") == "' =1"
    assert ci.csv_safe_cell("a=b, c-d; e@f") == "a=b, c-d; e@f"  # ayırıcıdan hemen sonra değilse dokunulmaz
    assert ci.csv_safe_cell("=x,=y") == "'=x,'=y"


# --- B-01: Unicode rakamlar -------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["١٢.٥٠", "１２.５０", "१२,५०", "1٢"])
def test_b01_unicode_digits_are_not_numbers(text: str) -> None:
    with pytest.raises(RuleError):
        ci.parse_decimal_text(text)
    with pytest.raises(RuleError):
        ci._decimal_cell(text)


@pytest.mark.parametrize("text", ["٢٠٢٦-١١-٠١", "０１.１１.２０２６", "2026-1١-01"])
def test_b01_unicode_digits_are_not_dates(text: str) -> None:
    with pytest.raises(RuleError):
        ci._date_cell(text)


@pytest.mark.parametrize("value", ["١٢.٥٠", "１２.５０"])
def test_b01_put_rejects_unicode_digit_cost(shop: Shop, value: str) -> None:
    r = shop.api.put(
        f"{shop.base}/products/{B1}/costs",
        {"valid_from": "2026-10-01", "unit_cost_excl_vat": value, "vat_rate": 20},
    )
    assert r.status_code == 422


def test_b01_ascii_numbers_and_dates_still_work() -> None:
    assert str(ci.parse_decimal_text("1.234,56")) == "1234.56"
    assert ci._date_cell("2026-10-01") == date(2026, 10, 1) and ci._date_cell("01.10.2026") == date(
        2026, 10, 1
    )


# --- B-02: defusedxml zorunlu ----------------------------------------------------------------------------


def test_b02_import_is_refused_when_defusedxml_is_off(shop: Shop, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openpyxl.xml, "DEFUSEDXML", False)
    r = upload(shop, small_xlsx(), "m.xlsx")
    assert r.status_code == 503 and r.json()["type"] == "urn:netkar:problem:import-unavailable"
    assert upload(shop, csv_bytes(f"{B1};5;20;2026-10-01")).status_code == 200  # CSV XML kullanmaz


def test_b02_startup_fails_closed_when_defusedxml_is_off(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_app(settings)  # normalde sorunsuz
    monkeypatch.setattr(openpyxl.xml, "DEFUSEDXML", False)
    with pytest.raises(RuntimeError, match="defusedxml"):
        create_app(settings)


def test_b02_openpyxl_parsers_really_come_from_defusedxml() -> None:
    ci.require_defusedxml()
    import openpyxl.xml.functions as functions

    assert functions.fromstring.__module__.startswith("defusedxml")


def test_b02_check_detects_a_swapped_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    import xml.etree.ElementTree as plain

    import openpyxl.xml.functions as functions

    monkeypatch.setattr(functions, "fromstring", plain.fromstring)
    with pytest.raises(RuntimeError, match="defusedxml"):
        ci.require_defusedxml()


# --- B-03: bağımlılık alt sınırı -------------------------------------------------------------------------


def test_b03_python_multipart_floor_matches_the_lock() -> None:
    root = Path(__file__).resolve().parent.parent
    pyproject = (root / "pyproject.toml").read_text()
    floor = re.search(r'"python-multipart>=([0-9.]+)"', pyproject)
    assert floor is not None
    lock = (root / "uv.lock").read_text()
    locked = re.search(r'name = "python-multipart"\nversion = "([0-9.]+)"', lock)
    assert locked is not None

    def as_tuple(v: str) -> tuple[int, ...]:
        return tuple(int(p) for p in v.split("."))

    assert as_tuple(floor.group(1)) >= (0, 0, 33) and as_tuple(locked.group(1)) >= as_tuple(floor.group(1))


# --- B-07: sıralı toplu yazım ----------------------------------------------------------------------------


async def test_b07_bulk_upsert_writes_rows_sorted_by_barcode_and_date() -> None:
    from decimal import Decimal
    from uuid import uuid4

    from app.services import product_costs as pc

    captured: list[list[tuple[str, date]]] = []

    class Result:
        def scalars(self) -> Result:
            return self

        def all(self) -> list[bool]:
            return [True] * len(captured[-1])

    class FakeDb:
        async def execute(self, stmt: Any) -> Result:
            params = stmt.compile().params
            count = sum(1 for key in params if key.startswith("barcode_m"))
            captured.append([(params[f"barcode_m{i}"], params[f"valid_from_m{i}"]) for i in range(count)])
            return Result()

    pairs = [
        ("B", date(2026, 1, 2)),
        ("A", date(2026, 3, 1)),
        ("B", date(2026, 1, 1)),
        ("A", date(2026, 2, 1)),
    ]
    rows = [pc.CostRow(b, d, Decimal(1), Decimal(20)) for b, d in pairs]
    created, updated = await pc.upsert_costs(FakeDb(), uuid4(), uuid4(), uuid4(), rows)  # type: ignore[arg-type]
    assert (created, updated) == (4, 0)
    assert captured == [sorted(pairs)]
    assert [r.barcode for r in rows][:2] == ["B", "A"]  # çağıranın listesi değiştirilmez


# --- check_zip kenar durumları ---------------------------------------------------------------------------


def test_zip_directory_entries_are_tolerated_but_required_parts_are_not_optional() -> None:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(small_xlsx())) as source, zipfile.ZipFile(out, "w") as target:
        target.writestr(zipfile.ZipInfo("xl/"), b"")  # boş dizin girdisi (bazı araçlar yazar)
        for info in source.infolist():
            target.writestr(info.filename, source.read(info))
    ci.check_zip(out.getvalue())
    only_props = io.BytesIO()
    with zipfile.ZipFile(only_props, "w") as target:
        target.writestr("docProps/core.xml", b"<x/>")  # izinli ama zorunlu bölümler yok
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.check_zip(only_props.getvalue())
    nonempty_dir = io.BytesIO()
    with zipfile.ZipFile(nonempty_dir, "w") as target:
        target.writestr(zipfile.ZipInfo("xl/"), b"icerik")
    with pytest.raises(ci.ImportFileError):
        ci.check_zip(nonempty_dir.getvalue())


def test_zip_per_entry_ratio_is_enforced_for_big_parts() -> None:
    """Toplam oran sınırının altında kalan ama tek başına aşırı sıkışan büyük bölüm reddedilir."""
    import os

    data = with_part("xl/worksheets/sheet2.xml", b"<sheetData>" + bytes(4 * 1024 * 1024) + b"</sheetData>")
    combined = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(combined, "w", zipfile.ZIP_DEFLATED) as t,
    ):
        for info in source.infolist():
            t.writestr(info.filename, source.read(info))
        # Rastgele (sıkışmayan) dolgu toplam oranı düşürür: yalnız bölüm başına oran denetimi kalır.
        t.writestr("docProps/dolgu.bin", os.urandom(200 * 1024))
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.check_zip(combined.getvalue(), ci.ImportLimits(max_other_part_bytes=10 * 1024 * 1024))


def test_zip_total_streaming_cap_counts_real_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Başlık küçük gösterir, akış büyüktür: toplam tavan gerçek bayt sayısıyla uygulanır."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as target:  # bildirilen toplam çok küçük
        for name in ("[Content_Types].xml", "xl/workbook.xml", "docProps/core.xml"):
            target.writestr(name, b"<x/>")
    data = buffer.getvalue()
    monkeypatch.setattr(ci, "MAX_ZIP_UNCOMPRESSED", 4000)
    real_open = zipfile.ZipFile.open

    def big_open(self: zipfile.ZipFile, name: Any, *a: Any, **k: Any) -> Any:
        info_name = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if info_name == "docProps/core.xml":
            return io.BytesIO(b"x" * 5000)
        return real_open(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "open", big_open)
    with pytest.raises(ci.ImportFileError, match="Dosya geçersiz"):
        ci.check_zip(data, ci.ImportLimits(max_other_part_bytes=1_000_000))
