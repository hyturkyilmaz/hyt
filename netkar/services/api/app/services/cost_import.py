"""Toplu maliyet dosyası (CSV ve XLSX): güvenli okuma, satır doğrulama ve CSV dışa aktarım yardımcıları.

Güvenlik (OWASP ASVS V12 dosya yükleme, G06):
- Uzantı VE içerik imzası denetlenir (XLSX: zip imzası `PK\\x03\\x04`; CSV: UTF-8 metin, NUL bayt yok).
- XLSX açılmadan önce zip denetlenir: girdi sayısı, bildirilen ve GERÇEK açılmış toplam boyut (<= 50 MB;
  başlıkta yalan söyleyen zip'e karşı akışla sayılır) ve sıkıştırma oranı (<= 100).
- Bölüm izin listesi (yalnız gereken OOXML bölümleri), BÖLÜM başına açılmış boyut sınırı ve openpyxl'e
  verilmeden önce styles.xml (<xf>) ile sharedStrings.xml (<si>) için akışla öğe sayısı ön taraması
  (denetim S3 Y-01: küçük dosya, devasa bellek). Sınırlar `ImportLimits` ve config'tedir.
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
from typing import TYPE_CHECKING, Any

from app.services.product_costs import (
    FORMULA_PREFIXES,
    CostRow,
    RuleError,
    check_barcode,
    check_unit_cost,
    check_valid_from,
    check_vat_rate,
)

if TYPE_CHECKING:
    from app.core.config import Settings

MAX_ROWS = 10_000
# Boş satırlara (Excel biçimli boş satırlar) tolerans: fiziksel satır tavanı. Aşılırsa dosya reddedilir.
MAX_PHYSICAL_ROWS = 50_000
MAX_COLUMNS = 50
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_ZIP_ENTRIES = 1000
_BIG_ENTRY = 1024 * 1024
_CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class ImportLimits:
    """XLSX bölüm sınırları ve öğe sayısı tavanları (varsayılanlar `Settings` ile aynıdır)."""

    max_styles_bytes: int = 1024 * 1024
    max_shared_strings_bytes: int = 10 * 1024 * 1024
    max_sheet_bytes: int = 20 * 1024 * 1024
    max_other_part_bytes: int = 256 * 1024
    max_style_xfs: int = 10_000
    max_shared_strings: int = 200_000

    @classmethod
    def from_settings(cls, settings: Settings) -> ImportLimits:
        return cls(
            max_styles_bytes=settings.cost_import_max_styles_bytes,
            max_shared_strings_bytes=settings.cost_import_max_shared_strings_bytes,
            max_sheet_bytes=settings.cost_import_max_sheet_bytes,
            max_other_part_bytes=settings.cost_import_max_other_part_bytes,
            max_style_xfs=settings.cost_import_max_style_xfs,
            max_shared_strings=settings.cost_import_max_shared_strings,
        )


DEFAULT_LIMITS = ImportLimits()

_STYLES = "xl/styles.xml"
_SHARED_STRINGS = "xl/sharedStrings.xml"
# openpyxl'in okuduğu ve Excel'in yazdığı zararsız bölümler. Listede olmayan her bölüm (gömülü nesne,
# makro, görsel, özel XML vb.) reddedilir: işlevi yok, yalnız saldırı yüzeyi.
_ALLOWED_PARTS = frozenset(
    {
        "[Content_Types].xml",
        "_rels/.rels",
        "xl/workbook.xml",
        "xl/_rels/workbook.xml.rels",
        _STYLES,
        _SHARED_STRINGS,
        "xl/calcChain.xml",  # Excel yazar; openpyxl okumaz, yalnız boyutu sınırlı
    }
)
_ALLOWED_PART_PATTERNS = (
    re.compile(r"xl/worksheets/sheet[0-9]{1,4}\.xml"),
    re.compile(r"xl/worksheets/_rels/sheet[0-9]{1,4}\.xml\.rels"),
    re.compile(r"docProps/[A-Za-z0-9_.-]{1,64}"),
    re.compile(r"xl/theme/[A-Za-z0-9_.-]{1,64}"),
)
_SHEET_PART = re.compile(r"xl/worksheets/sheet[0-9]{1,4}\.xml")
# Ad alanı önekli etiketler de sayılır (<x:xf ...>): openpyxl etiketi ad alanına göre eşler, önek serbesttir.
_XF_TAG = re.compile(rb"<(?:[A-Za-z_][\w.\-]*:)?xf(?=[\s/>])")
_SI_TAG = re.compile(rb"<(?:[A-Za-z_][\w.\-]*:)?si(?=[\s/>])")
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


def _part_limit(name: str, limits: ImportLimits) -> int | None:
    """Bölümün açılmış boyut sınırı; izin listesinde değilse None."""
    if name == _STYLES:
        return limits.max_styles_bytes
    if name == _SHARED_STRINGS:
        return limits.max_shared_strings_bytes
    if _SHEET_PART.fullmatch(name):
        return limits.max_sheet_bytes
    if name in _ALLOWED_PARTS or any(p.fullmatch(name) for p in _ALLOWED_PART_PATTERNS):
        return limits.max_other_part_bytes
    return None


def _count_elements(buffer: bytes, pattern: re.Pattern[bytes], maximum: int) -> int:
    """Etiket sayısı; tavan aşılır aşılmaz durur."""
    count = 0
    for _ in pattern.finditer(buffer):
        count += 1
        if count > maximum:
            break
    return count


def _scan_part(name: str, buffer: bytes, limits: ImportLimits) -> None:
    """styles.xml ve sharedStrings.xml için öğe sayısı ön taraması (openpyxl'den ÖNCE)."""
    # UTF-16/32 gövdeler bayt düzeyinde etiket aramasından kaçar: ASCII uyumlu (UTF-8) olmayanı reddet.
    if buffer.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in buffer[:8]:
        raise _invalid("XLSX bölümü UTF-8 değil.")
    if name == _STYLES and _count_elements(buffer, _XF_TAG, limits.max_style_xfs) > limits.max_style_xfs:
        raise _invalid("XLSX stil tablosu çok büyük.")
    if (
        name == _SHARED_STRINGS
        and _count_elements(buffer, _SI_TAG, limits.max_shared_strings) > limits.max_shared_strings
    ):
        raise _invalid("XLSX paylaşılan dize tablosu çok büyük.")


def check_zip(data: bytes, limits: ImportLimits = DEFAULT_LIMITS) -> None:
    """Zip bombası, bölüm izin listesi, bölüm sınırları ve öğe sayısı denetimi (openpyxl açmadan ÖNCE)."""
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
            names = [info.filename for info in infos]
            if len(set(names)) != len(names):
                raise _invalid("XLSX arşivinde aynı ada sahip birden çok girdi var.")
            caps: dict[str, int] = {}
            for info in infos:
                if info.is_dir() and info.file_size == 0:
                    continue
                cap = _part_limit(info.filename, limits)
                if cap is None:
                    raise _invalid("XLSX içinde izin verilmeyen bölüm var.")
                if info.file_size > cap:
                    raise _invalid("XLSX içindeki bir bölüm izin verilen boyuttan büyük.")
                caps[info.filename] = cap
            if "[Content_Types].xml" not in caps or "xl/workbook.xml" not in caps:
                raise _invalid("Dosya geçerli bir XLSX çalışma kitabı değil.")
            # Başlıktaki boyuta güvenilmez: gerçek açılım akışla sayılır, bölüm ve toplam tavanında kesilir.
            actual = 0
            for info in infos:
                cap = caps.get(info.filename)
                if cap is None:
                    continue
                scanned = info.filename in {_STYLES, _SHARED_STRINGS}
                buffer = bytearray() if scanned else None
                part = 0
                with archive.open(info) as stream:
                    while chunk := stream.read(_CHUNK):
                        part += len(chunk)
                        actual += len(chunk)
                        if part > cap:
                            raise _invalid("XLSX içindeki bir bölüm izin verilen boyuttan büyük.")
                        if actual > MAX_ZIP_UNCOMPRESSED:
                            raise _invalid("XLSX açıldığında çok büyük (en çok 50 MB).")
                        if buffer is not None:
                            buffer.extend(chunk)
                if buffer is not None:
                    _scan_part(info.filename, bytes(buffer), limits)
    except ImportFileError:
        raise
    except Exception:
        # BadZipFile, şifreli girdi, bozuk akış vb.: ayrıntı sızdırılmaz.
        raise _invalid("XLSX arşivi okunamadı.") from None


def require_defusedxml() -> None:
    """XXE ve varlık genişletme korumasını (defusedxml) zorunlu kılar; kapalıysa RuntimeError (fail-closed).

    openpyxl defusedxml'i yalnız kuruluysa ve OPENPYXL_DEFUSEDXML ortam değişkeni kapatılmadıysa kullanır.
    Hem bayrağa hem de gerçekte kullanılan ayrıştırıcının modülüne bakılır.
    """
    import openpyxl.xml
    import openpyxl.xml.functions as functions

    if not openpyxl.xml.DEFUSEDXML or not functions.fromstring.__module__.startswith("defusedxml"):
        raise RuntimeError("openpyxl defusedxml olmadan çalışıyor; XLSX içe aktarma güvenli değil.")


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


def _read_xlsx(data: bytes, limits: ImportLimits = DEFAULT_LIMITS) -> list[list[Any]]:
    from openpyxl import load_workbook  # yavaş içe aktarma yalnız gerektiğinde

    try:
        require_defusedxml()
    except RuntimeError:
        raise ImportFileError(
            503,
            "İçe aktarma şu an kullanılamıyor",
            "import-unavailable",
            "XLSX içe aktarma geçici olarak kapalı. CSV kullanın veya destekle iletişime geçin.",
        ) from None
    check_zip(data, limits)
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


_NUMBER_CHARS = re.compile(r"[0-9][0-9.,]*")


def _group_pattern(sep: str) -> re.Pattern[str]:
    return re.compile(rf"[1-9][0-9]{{0,2}}(?:{re.escape(sep)}[0-9]{{3}})+")


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


# Yalnız ASCII rakam: \d Arapça-Hint ve tam genişlik rakamları da eşler (denetim S3 B-01).
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TR_DATE = re.compile(r"[0-9]{2}\.[0-9]{2}\.[0-9]{4}")


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


def parse_import(
    filename: str | None, data: bytes, today: date, limits: ImportLimits = DEFAULT_LIMITS
) -> ImportParse:
    """Biçimi doğrular, dosyayı okur ve satırları doğrular (CPU işi: iş parçacığı havuzunda çağrılır).

    Veritabanına DOKUNMAZ: çağıran ayrıştırma sırasında bağlantı/işlem tutmamalıdır (denetim S3 O-01).
    """
    kind = detect_format(filename, data)
    raw_rows = _read_xlsx(data, limits) if kind == "xlsx" else _read_csv(data)
    result = validate_rows(raw_rows, today)
    result.file_format = kind
    return result


# --- dışa aktarım -----------------------------------------------------------------------------------


# Ayırıcıdan (; , sekme, satır sonu) hemen sonra (boşluklar serbest) gelen formül karakteri. Tam genişlik
# varyantlar (＝ ＋ － ＠) bazı yerel ayarlarda formül sayılabilir; sağlamlaştırma olarak onlar da kaçırılır.
# Hücrenin ilk karakteri olan ayırıcı (örn. başta sekme) baştaki tek tırnakla zaten kapsanır.
_INNER_FORMULA = re.compile(r"(?<=[\s\S])([;,\t\r\n]\s*)(?=[=+\-@＝＋－＠])")
_LEADING_FORMULA = re.compile(r"\s*[=+\-@＝＋－＠]")


def csv_safe_cell(value: str | None) -> str:
    """CSV/formül enjeksiyonu (OWASP): tehlikeli önekli hücrenin başına tek tırnak eklenir.

    Excel dosyayı farklı liste ayırıcısıyla ("," yerine ";" gibi) açıp hücreyi bölebilir; bu yüzden
    hücre içinde herhangi bir ayırıcıdan sonra gelen =, +, -, @ karakterinden önce de tek tırnak konur.
    """
    text = value or ""
    text = _INNER_FORMULA.sub(lambda m: f"{m.group(1)}'", text)
    if text.startswith(FORMULA_PREFIXES) or _LEADING_FORMULA.match(text):
        return f"'{text}"
    return text


def build_template_csv(products: Sequence[tuple[str, str | None]]) -> bytes:
    """UTF-8 BOM'lu, ';' ayraçlı şablon (Türkçe Excel). Maliyet, KDV ve tarih sütunları boştur.

    Tüm hücreler tırnaklanır (QUOTE_ALL): ayırıcı uyuşmazlığında bile alan sınırları korunur.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_ALL)
    writer.writerow(TEMPLATE_HEADER)
    for barcode, title in products:
        writer.writerow([csv_safe_cell(barcode), csv_safe_cell(title), "", "", ""])
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
