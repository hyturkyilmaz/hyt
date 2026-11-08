"""Toplu maliyet dosyası (CSV ve XLSX): güvenli okuma, satır doğrulama ve CSV dışa aktarım yardımcıları.

Güvenlik (OWASP ASVS V12 dosya yükleme, G06):
- Uzantı VE içerik imzası denetlenir (XLSX: zip imzası `PK\\x03\\x04`; CSV: UTF-8 metin, NUL bayt yok).
- XLSX açılmadan önce zip denetlenir: girdi sayısı, bildirilen ve GERÇEK açılmış toplam boyut (<= 50 MB;
  başlıkta yalan söyleyen zip'e karşı akışla sayılır) ve sıkıştırma oranı (<= 100).
- openpyxl `read_only=True, data_only=True` ile okunur (formül değerlendirilmez, önbellek değeri okunur);
  defusedxml kuruludur ve openpyxl onu otomatik kullanır (XXE ve varlık genişletme kapalı).
- Satır sınırı 10.000. Barkod allowlist'tir (formül karakteriyle başlayamaz).
- Hata raporu hücre içeriğini yansıtmaz; yalnız kontrol karakterleri temizlenmiş ilk 20 karakter döner.
- Dışa aktarımda (`csv_safe_cell`) =, +, -, @, sekme, CR, LF ile başlayan hücrenin başına tek tırnak eklenir.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.product_costs import (
    FORMULA_PREFIXES,
    CostRow,
    RuleError,
    check_barcode,
    check_unit_cost,
    check_valid_from,
    check_vat_rate,
)

MAX_ROWS = 10_000
# Boş satırlara (Excel biçimli boş satırlar) tolerans: fiziksel satır tavanı. Aşılırsa dosya reddedilir.
MAX_PHYSICAL_ROWS = 50_000
MAX_COLUMNS = 50
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_ZIP_ENTRIES = 1000
_BIG_ENTRY = 1024 * 1024
MAX_REPORTED_ERRORS = 200
EXCERPT_LENGTH = 20
_MAX_NUMBER_TEXT = 40

COL_BARCODE = "barkod"
COL_COST = "birim_maliyet_kdv_haric"
COL_VAT = "kdv_orani"
COL_VALID_FROM = "gecerlilik_tarihi"
TEMPLATE_HEADER = (COL_BARCODE, "baslik", COL_COST, COL_VAT, COL_VALID_FROM)

# Başlık eşleme: Türkçe karakterler ASCII'ye, harf ve rakam dışı her şey silinir, küçük harf yapılır.
_ALIASES: dict[str, frozenset[str]] = {
    COL_BARCODE: frozenset({"barkod", "barcode", "urunbarkodu", "barkodno"}),
    COL_COST: frozenset(
        {
            "birimmaliyetkdvharic",
            "birimmaliyet",
            "maliyet",
            "unitcost",
            "unitcostexclvat",
            "unitcostexcludingvat",
        }
    ),
    COL_VAT: frozenset({"kdvorani", "kdv", "vatrate", "vat", "kdvoraniyuzde"}),
    COL_VALID_FROM: frozenset(
        {"gecerliliktarihi", "gecerlilik", "gecerliliktarih", "validfrom", "gecerlilikbaslangic"}
    ),
}
# Şablonda bulunan ve içe aktarmada yok sayılan bilgi sütunları (rapora "yok sayıldı" olarak yazılmaz).
_INFO_COLUMNS = frozenset({"baslik", "title", "urunbasligi", "urunadi"})
_TR_TABLE = str.maketrans("çğıöşüâîû", "cgiosuaiu")


class ImportFileError(Exception):
    """Dosya düzeyi hata (tüm içe aktarma reddedilir): HTTP durumu, başlık, slug, Türkçe ayrıntı."""

    def __init__(self, status: int, title: str, slug: str, detail: str) -> None:
        super().__init__(title)
        self.status = status
        self.title = title
        self.slug = slug
        self.detail = detail


def _invalid(detail: str) -> ImportFileError:
    return ImportFileError(422, "Dosya geçersiz", "import-file-invalid", detail)


@dataclass(frozen=True, slots=True)
class RowIssue:
    row: int
    column: str
    message: str
    value: str | None


@dataclass(slots=True)
class ImportParse:
    """Doğrulama sonucu: geçerli satırlar, sayaçlar ve (kırpılmış) hata listesi."""

    rows: list[CostRow] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)
    total: int = 0
    invalid: int = 0
    skipped: int = 0
    ignored_columns: list[str] = field(default_factory=list)
    errors_truncated: bool = False
    file_format: str = ""

    @property
    def valid(self) -> int:
        return len(self.rows)


# --- biçim ve içerik denetimi ---------------------------------------------------------------------


def detect_format(filename: str | None, data: bytes) -> str:
    """Uzantı + içerik imzası. Dönüş: "csv" veya "xlsx"; aksi halde ImportFileError."""
    name = (filename or "").lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    if extension not in {"csv", "xlsx"}:
        raise ImportFileError(
            415,
            "Desteklenmeyen dosya türü",
            "import-unsupported-type",
            "Yalnız .csv veya .xlsx dosyası yüklenebilir.",
        )
    if not data:
        raise _invalid("Dosya boş.")
    if extension == "xlsx":
        if not data.startswith(b"PK\x03\x04"):
            raise _invalid("Dosya içeriği XLSX (zip) imzasına sahip değil.")
        return "xlsx"
    if data.startswith(b"PK") or b"\x00" in data:
        raise _invalid("Dosya içeriği CSV metni değil (ikili veri).")
    return "csv"


def check_zip(data: bytes) -> None:
    """Zip bombası ve bozuk arşiv denetimi (openpyxl açmadan ÖNCE)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ZIP_ENTRIES:
                raise _invalid("XLSX arşivi geçersiz (girdi sayısı).")
            declared = sum(info.file_size for info in infos)
            if declared > MAX_ZIP_UNCOMPRESSED:
                raise _invalid("XLSX açıldığında çok büyük (en çok 50 MB).")
            if declared > MAX_ZIP_RATIO * len(data):
                raise _invalid("XLSX sıkıştırma oranı olağandışı yüksek.")
            for info in infos:
                if info.file_size >= _BIG_ENTRY and info.file_size > MAX_ZIP_RATIO * max(
                    info.compress_size, 1
                ):
                    raise _invalid("XLSX içindeki bir dosyanın sıkıştırma oranı olağandışı yüksek.")
            # Başlıkta bildirilen boyuta güvenilmez: gerçek açılım akışla sayılır ve tavanda kesilir.
            actual = 0
            for info in infos:
                with archive.open(info) as stream:
                    while chunk := stream.read(65536):
                        actual += len(chunk)
                        if actual > MAX_ZIP_UNCOMPRESSED:
                            raise _invalid("XLSX açıldığında çok büyük (en çok 50 MB).")
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names or "xl/workbook.xml" not in names:
                raise _invalid("Dosya geçerli bir XLSX çalışma kitabı değil.")
    except ImportFileError:
        raise
    except Exception:
        # BadZipFile, şifreli girdi, bozuk akış vb.: ayrıntı sızdırılmaz.
        raise _invalid("XLSX arşivi okunamadı.") from None


# --- okuma (ham hücre satırları) --------------------------------------------------------------------


def _read_csv(data: bytes) -> list[list[Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _invalid("CSV dosyası UTF-8 kodlamasında olmalıdır.") from None
    first_line = text.split("\n", 1)[0]
    # Türkçe Excel ';' ile kaydeder; başlık satırındaki en sık ayırıcı seçilir (eşitlikte ';').
    delimiter = max((";", ",", "\t"), key=lambda d: first_line.count(d))
    rows: list[list[Any]] = []
    try:
        for record in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True):
            rows.append(record[:MAX_COLUMNS])
            if len(rows) > MAX_PHYSICAL_ROWS + 1:
                raise _invalid("Dosyada çok fazla satır var.")
    except csv.Error:
        raise _invalid("CSV dosyası ayrıştırılamadı.") from None
    return rows


def _read_xlsx(data: bytes) -> list[list[Any]]:
    from openpyxl import load_workbook  # yavaş içe aktarma yalnız gerektiğinde

    check_zip(data)
    rows: list[list[Any]] = []
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            sheet = workbook.worksheets[0]
            for record in sheet.iter_rows(values_only=True, max_col=MAX_COLUMNS):
                rows.append(list(record))
                if len(rows) > MAX_PHYSICAL_ROWS + 1:
                    raise _invalid("Dosyada çok fazla satır var.")
        finally:
            workbook.close()
    except ImportFileError:
        raise
    except Exception:
        # defusedxml'in reddettiği varlık bildirimleri (XXE) dahil her okuma hatası: ayrıntı sızdırılmaz.
        raise _invalid("XLSX çalışma kitabı okunamadı.") from None
    return rows


# --- hücre dönüşümleri ------------------------------------------------------------------------------


def normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("İ", "i").replace("I", "i").lower()
    return re.sub(r"[^a-z0-9]", "", text.translate(_TR_TABLE))


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def excerpt(value: Any) -> str | None:
    """Hata raporu için hücrenin kontrol karakterlerinden arındırılmış ilk 20 karakteri."""
    if is_blank(value):
        return None
    cleaned = "".join(ch for ch in str(value) if not unicodedata.category(ch).startswith("C")).strip()
    return cleaned[:EXCERPT_LENGTH] or None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip("﻿  \t\r\n")


_NUMBER_CHARS = re.compile(r"\d[\d.,]*")


def _group_pattern(sep: str) -> re.Pattern[str]:
    return re.compile(rf"[1-9]\d{{0,2}}(?:{re.escape(sep)}\d{{3}})+")


def parse_decimal_text(text: str) -> Decimal:
    """ "1.234,56" ve "1234.56" gibi biçimleri okur; belirsizse RuleError (tahmin yok).

    Tek ayırıcı ve tam 3 hane ("1.234", "1,234") binlik mi ondalık mı belirsizdir: reddedilir.
    """
    bad = RuleError("number_invalid", "Sayı olarak okunamadı (yalnız rakam, '.' ve ',' kullanın).")
    ambiguous = RuleError(
        "number_ambiguous",
        "Sayı belirsiz: binlik ve ondalık ayırıcı ayırt edilemiyor (örn. 1.234 veya 1,234).",
    )
    if len(text) > _MAX_NUMBER_TEXT or not _NUMBER_CHARS.fullmatch(text):
        raise bad
    has_dot, has_comma = "." in text, "," in text
    if not has_dot and not has_comma:
        return Decimal(text)
    if has_dot and has_comma:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        left, _, right = text.rpartition(decimal_sep)
        if not right or not right.isdigit() or not _group_pattern(thousands).fullmatch(left):
            raise bad
        return Decimal(f"{left.replace(thousands, '')}.{right}")
    sep = "." if has_dot else ","
    parts = text.split(sep)
    if len(parts) > 2:
        if _group_pattern(sep).fullmatch(text):
            return Decimal(text.replace(sep, ""))  # yalnız binlik olabilir
        raise bad
    left, right = parts
    if not right:
        raise bad
    if len(right) == 3 and len(left) <= 3 and not left.startswith("0"):
        raise ambiguous
    return Decimal(f"{left}.{right}")


def _decimal_cell(value: Any, *, percent: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise RuleError("number_invalid", "Sayı olarak okunamadı.")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise RuleError("number_invalid", "Sayı olarak okunamadı.")
        return Decimal(repr(value))  # en kısa gidiş-dönüş gösterimi; ikili gürültü taşınmaz
    if isinstance(value, str):
        text = _text(value)
        if percent:
            text = text.removeprefix("%").removesuffix("%").strip()
        try:
            return parse_decimal_text(text)
        except InvalidOperation:  # pragma: no cover - desen doğrulaması sonrası oluşmaz
            raise RuleError("number_invalid", "Sayı olarak okunamadı.") from None
    raise RuleError("number_invalid", "Sayı olarak okunamadı.")


_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TR_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def _date_cell(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    bad = RuleError("date_invalid", "Tarih YYYY-AA-GG veya GG.AA.YYYY biçiminde olmalıdır.")
    if not isinstance(value, str):
        raise bad
    text = _text(value)
    try:
        if _ISO_DATE.fullmatch(text):
            return date.fromisoformat(text)
        if _TR_DATE.fullmatch(text):
            return date(int(text[6:]), int(text[3:5]), int(text[:2]))
    except ValueError:
        raise bad from None
    raise bad


def _barcode_cell(value: Any) -> str:
    if isinstance(value, bool):
        raise RuleError("barcode_invalid", "Barkod geçerli değil.")
    if isinstance(value, int):
        text = str(value)
    elif isinstance(value, float):
        if not value.is_integer() or abs(value) >= 1e15:
            raise RuleError("barcode_invalid", "Barkod geçerli değil.")
        text = str(int(value))
    elif isinstance(value, str):
        text = _text(value)
    else:
        raise RuleError("barcode_invalid", "Barkod geçerli değil.")
    return check_barcode(text)


# --- doğrulama --------------------------------------------------------------------------------------


def _map_columns(header: Sequence[Any]) -> tuple[dict[str, int], list[str]]:
    mapping: dict[str, int] = {}
    ignored: list[str] = []
    for index, raw in enumerate(header):
        key = normalize_header(raw)
        if not key:
            continue
        canonical = next((name for name, aliases in _ALIASES.items() if key in aliases), None)
        if canonical is None:
            if key not in _INFO_COLUMNS and len(ignored) < 20:
                ignored.append(excerpt(raw) or "?")
            continue
        if canonical in mapping:
            raise _invalid(f"'{canonical}' sütunu birden fazla kez geçiyor.")
        mapping[canonical] = index
    missing = [name for name in (COL_BARCODE, COL_COST, COL_VAT) if name not in mapping]
    if missing:
        raise _invalid(f"Zorunlu sütun(lar) bulunamadı: {', '.join(missing)}.")
    return mapping, ignored


def validate_rows(raw_rows: list[list[Any]], today: date) -> ImportParse:
    """Başlığı eşler, satırları tek tek doğrular. Hiçbir şey yazmaz."""
    if not raw_rows or all(is_blank(cell) for cell in raw_rows[0]):
        raise _invalid("Başlık satırı bulunamadı.")
    mapping, ignored = _map_columns(raw_rows[0])
    result = ImportParse(ignored_columns=ignored)
    seen: dict[tuple[str, date], int] = {}

    def cell(row: list[Any], column: str) -> Any:
        index = mapping.get(column)
        return row[index] if index is not None and index < len(row) else None

    def add_issue(row_no: int, column: str, message: str, value: Any) -> None:
        if len(result.issues) < MAX_REPORTED_ERRORS:
            result.issues.append(RowIssue(row_no, column, message, excerpt(value)))
        else:
            result.errors_truncated = True

    for row_no, row in enumerate(raw_rows[1:], start=2):
        if all(is_blank(c) for c in row):
            continue
        result.total += 1
        if result.total > MAX_ROWS:
            raise ImportFileError(
                422,
                "Dosyada çok fazla satır var",
                "import-too-many-rows",
                "Dosya en çok 10.000 veri satırı içerebilir.",
            )
        raw = {column: cell(row, column) for column in (COL_BARCODE, COL_COST, COL_VAT, COL_VALID_FROM)}
        if not is_blank(raw[COL_BARCODE]) and all(
            is_blank(raw[c]) for c in (COL_COST, COL_VAT, COL_VALID_FROM)
        ):
            result.skipped += 1  # şablonda maliyeti doldurulmamış satır
            continue
        parsed = _parse_row(raw, today)
        for column, (message, value) in parsed.errors.items():
            add_issue(row_no, column, message, value)
        if parsed.row is not None:
            key = (parsed.row.barcode, parsed.row.valid_from)
            if key in seen:
                add_issue(
                    row_no,
                    COL_BARCODE,
                    f"Aynı barkod ve geçerlilik tarihi satır {seen[key]}'de zaten var.",
                    raw[COL_BARCODE],
                )
                parsed = _ParsedRow(None, {COL_BARCODE: ("", None)})
            else:
                seen[key] = row_no
        if parsed.row is None:
            result.invalid += 1
        else:
            result.rows.append(parsed.row)
    return result


@dataclass(slots=True)
class _ParsedRow:
    row: CostRow | None
    errors: dict[str, tuple[str, Any]]


def _parse_row(raw: dict[str, Any], today: date) -> _ParsedRow:
    """Bir satırın tüm alanlarını doğrular; her sütun için en fazla bir hata toplar."""
    errors: dict[str, tuple[str, Any]] = {}

    def run(column: str, action: Callable[[], Any]) -> Any:
        try:
            return action()
        except RuleError as exc:
            errors[column] = (exc.message, raw[column])
            return None

    barcode = run(
        COL_BARCODE,
        lambda: _barcode_cell(_present(raw[COL_BARCODE], "barcode_missing", "Barkod boş olamaz.")),
    )
    cost = run(COL_COST, lambda: check_unit_cost(_decimal_cell(_present(raw[COL_COST]))))
    vat = run(COL_VAT, lambda: check_vat_rate(_decimal_cell(_present(raw[COL_VAT]), percent=True)))
    if is_blank(raw[COL_VALID_FROM]):
        valid_from: date | None = today  # boş tarih = bugün (İstanbul)
    else:
        valid_from = run(COL_VALID_FROM, lambda: check_valid_from(_date_cell(raw[COL_VALID_FROM]), today))
    if errors or barcode is None or cost is None or vat is None or valid_from is None:
        return _ParsedRow(None, errors)
    return _ParsedRow(CostRow(barcode, valid_from, cost, vat), errors)


def _present(value: Any, code: str = "value_missing", message: str = "Bu alan boş olamaz.") -> Any:
    if is_blank(value):
        raise RuleError(code, message)
    return value


def parse_import(filename: str | None, data: bytes, today: date) -> ImportParse:
    """Biçimi doğrular, dosyayı okur ve satırları doğrular (CPU işi: iş parçacığı havuzunda çağrılır)."""
    kind = detect_format(filename, data)
    raw_rows = _read_xlsx(data) if kind == "xlsx" else _read_csv(data)
    result = validate_rows(raw_rows, today)
    result.file_format = kind
    return result


# --- dışa aktarım -----------------------------------------------------------------------------------


def csv_safe_cell(value: str | None) -> str:
    """CSV/formül enjeksiyonu (OWASP): tehlikeli önekli hücrenin başına tek tırnak eklenir."""
    text = value or ""
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def build_template_csv(products: Sequence[tuple[str, str | None]]) -> bytes:
    """UTF-8 BOM'lu, ';' ayraçlı şablon (Türkçe Excel). Maliyet, KDV ve tarih sütunları boştur."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(TEMPLATE_HEADER)
    for barcode, title in products:
        writer.writerow([csv_safe_cell(barcode), csv_safe_cell(title), "", "", ""])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
