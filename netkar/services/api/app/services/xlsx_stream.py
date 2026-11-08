"""Dar, akışlı XLSX okuyucu (denetim S3 YK-01): yalnız ilk çalışma sayfasının hücre değerlerini okur.

Neden openpyxl değil: openpyxl bir `<row>` öğesinin tüm çocuklarını satır bitene kadar bellekte tutar, her
hücre için sütun kırpmasından ÖNCE sözlük üretir ve tanınmayan öğeleri hiç temizlemez. Bölüm sınırlarının
altında kalan küçük bir dosya yine de GB'larca bellek tüketebilir. Çalışma zamanında openpyxl ayrıştırma için
KULLANILMAZ (testlerde yalnız XLSX üretmek için kalır).

Tasarım:
- defusedxml `iterparse` (DTD ve varlık bildirimi yasak, XXE ve varlık genişletme kapalı); her öğe işlendikten
  sonra `clear()` edilir ve ebeveynden çıkarılır: bellek, dosya boyutundan bağımsız olarak sabittir.
- Çalışma kitabı ve ilişki dosyalarıyla ilk sayfanın ve paylaşılan dize tablosunun GERÇEK yolu çözülür.
  `[Content_Types].xml` Override kayıtları sabit adlarla çapraz denetlenir: içerik türü ile dosya adı
  uyuşmuyorsa (ör. dize tablosunun sayfa adına taşınması) dosya reddedilir.
- Sert tavanlar (aşımda 422): satır, satır başına sütun, toplam hücre, tanınmayan öğe, derinlik, paylaşılan
  dize sayısı, hücre metni uzunluğu ve toplam tutulan metin. Öğe sayımları `start` olayında yapılır; aşırı
  büyük dosya ayrıştırılmadan reddedilir.
- Tarih: styles.xml yalnız gerektiğinde (sayısal hücrede stil indeksi varsa), yalnız numFmts ve cellXfs için
  akışla okunur. Yerleşik tarih biçimleri 14-22 ve 45-47; özel biçimde y/m/d deseni. Tarih biçimli sayı
  `date` olur. Biçimsiz sayı tarih sayılmaz (belirsizlik hata verir, tahmin yok).
"""

from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from defusedxml import ElementTree as _defused  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from xml.etree.ElementTree import Element

_safe_iterparse = _defused.iterparse

MAIN_NS = frozenset(
    {
        "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "http://purl.oclc.org/ooxml/spreadsheetml/main",
    }
)
_KNOWN_NS = MAIN_NS | {
    "http://schemas.openxmlformats.org/package/2006/content-types",
    "http://schemas.openxmlformats.org/package/2006/relationships",
}
_REL_ID_ATTRS = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
    "{http://purl.oclc.org/ooxml/officeDocument/relationships}id",
)

_CT_WORKBOOK = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"
_CT_SHEET = "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"
_CT_SST = "application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"
_CT_STYLES = "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"
_FIXED_PARTS = {
    "/xl/workbook.xml": _CT_WORKBOOK,
    "/xl/styles.xml": _CT_STYLES,
    "/xl/sharedStrings.xml": _CT_SST,
}
_REDIRECTABLE = frozenset({_CT_WORKBOOK, _CT_STYLES, _CT_SST})
_SHEET_PART = re.compile(r"xl/worksheets/sheet[0-9]{1,4}\.xml")

MAX_DEPTH = 32
# Tek bir hücre veya paylaşılan dizede makul metin parçası (`<t>`, `<r>`) sayısı; fazlası bütçeden düşer.
MAX_RUNS = 16
# Hücre metni bu uzunlukta kesilir: barkod en çok 200, sayı 40, tarih 10 karakter; uzunu zaten geçersizdir.
MAX_CELL_CHARS = 256
_MAX_NUMBER_CHARS = 64
_MAX_REF_DIGITS = 9


class XlsxFormatError(Exception):
    """Okuyucu hatası. `kind`: "invalid" (geçersiz dosya) veya "rows" (çok fazla satır)."""

    def __init__(self, detail: str, kind: str = "invalid") -> None:
        super().__init__(detail)
        self.detail = detail
        self.kind = kind


@dataclass(frozen=True, slots=True)
class StreamLimits:
    """Okuyucu tavanları (`ImportLimits` bunları doldurur)."""

    max_rows: int = 10_000  # başlık hariç dolu veri satırı
    max_physical_rows: int = 50_000  # boş satırlar dahil `<row>` sayısı ve son satır numarası
    max_columns: int = 50
    max_cells: int = 600_000
    max_other_elements: int = 50_000
    max_style_xfs: int = 10_000
    max_shared_strings: int = 200_000
    max_text_chars: int = 16_000_000


def _bad(detail: str) -> XlsxFormatError:
    return XlsxFormatError(detail)


# --- güvenli ayrıştırıcı ve olay akışı ---------------------------------------------------------------


def require_defusedxml() -> None:
    """Ayrıştırıcının gerçekten defusedxml olduğunu ve DTD/varlığı reddettiğini sınar (fail-closed)."""
    module = getattr(_safe_iterparse, "__module__", "") or ""
    if not module.startswith("defusedxml"):
        raise RuntimeError("XLSX ayrıştırıcısı defusedxml değil; XLSX içe aktarma güvenli değil.")
    probe = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>'
    try:
        for _ in _safe_iterparse(io.BytesIO(probe), forbid_dtd=True):
            pass
    except DefusedXmlException:
        return
    except Exception:  # noqa: S110  (başka hata: sınama başarısız sayılır, aşağıda RuntimeError)
        pass
    raise RuntimeError("defusedxml DTD/varlık bildirimini reddetmiyor; XLSX içe aktarma güvenli değil.")


_NAMES: dict[str, str] = {}


def _name(tag: str) -> str:
    """Bilinen ad alanındaki öğenin yerel adı; başka ad alanı veya bilinmeyen: "?"."""
    try:
        return _NAMES[tag]
    except KeyError:
        if tag[:1] == "{":
            namespace, _, local = tag[1:].partition("}")
            value = local if namespace in _KNOWN_NS else "?"
        else:
            value = "?"
        if len(_NAMES) < 4096:  # saldırgan etiket adlarıyla önbellek şişirilemez
            _NAMES[tag] = value
        return value


# Biten çocuklar ebeveynden bu kadarlık gruplar halinde çıkarılır (tek tek `remove` pahalıdır: ayrıştırıcı
# bir yığın öğeyi önden üretir, her çıkarma o listeyi kaydırır). Bellek yine sabittir.
_DETACH_BATCH = 64


def _events(
    archive: zipfile.ZipFile, part: str, max_elements: int
) -> Iterator[tuple[str, Element, list[Element]]]:
    """(olay, öğe, açık öğe yığını) üretir. Tüketici işini yaptıktan sonra bitmiş öğe temizlenir ve
    ebeveyninden çıkarılır (sabit bellek). Yığın, `end` olayında bitmiş öğeyi de içerir."""
    stack: list[Element] = []
    ended = [0] * (MAX_DEPTH + 2)  # derinlik başına: ebeveynde biten ama hâlâ bağlı çocuk sayısı
    count = 0
    try:
        with archive.open(part) as raw:
            for event, elem in _safe_iterparse(raw, events=("start", "end"), forbid_dtd=True):
                if event == "start":
                    count += 1
                    if count > max_elements:
                        raise _bad("XLSX bölümünde çok fazla öğe var.")
                    stack.append(elem)
                    depth = len(stack)
                    if depth > MAX_DEPTH:
                        raise _bad("XLSX bölümü çok derin iç içe.")
                    ended[depth] = 0
                    yield event, elem, stack
                else:
                    yield event, elem, stack
                    stack.pop()
                    elem.clear()
                    if stack:
                        parent_depth = len(stack)
                        ended[parent_depth] += 1
                        if ended[parent_depth] >= _DETACH_BATCH:
                            del stack[-1][: ended[parent_depth]]  # biten çocuklar ebeveynin ÖN ekidir
                            ended[parent_depth] = 0
    except XlsxFormatError:
        raise
    except (_defused.ParseError, DefusedXmlException, zipfile.BadZipFile, KeyError, ValueError):
        raise _bad("XLSX bölümü okunamadı.") from None


class _Budget:
    """Tanınmayan öğe sayacı: tavan aşılırsa XlsxFormatError."""

    __slots__ = ("count", "limit")

    def __init__(self, limit: int) -> None:
        self.count = 0
        self.limit = limit

    def hit(self) -> None:
        self.count += 1
        if self.count > self.limit:
            raise _bad("XLSX bölümünde çok fazla tanınmayan öğe var.")


# --- paket yapısı: içerik türleri, ilişkiler, çalışma kitabı ---------------------------------------------


def _read_content_types(archive: zipfile.ZipFile, limits: StreamLimits) -> dict[str, str]:
    overrides: dict[str, str] = {}
    other = _Budget(limits.max_other_elements)
    seen_root = False
    for event, elem, stack in _events(archive, "[Content_Types].xml", limits.max_other_elements + 1000):
        if event != "start":
            continue
        name = _name(elem.tag)
        if len(stack) == 1:
            if name != "Types":
                raise _bad("[Content_Types].xml kökü geçersiz.")
            seen_root = True
        elif len(stack) == 2 and name == "Override":
            part, content_type = elem.get("PartName"), elem.get("ContentType")
            if not part or not content_type or not part.startswith("/") or part in overrides:
                raise _bad("[Content_Types].xml Override kaydı geçersiz veya yinelenmiş.")
            overrides[part] = content_type
        elif not (len(stack) == 2 and name == "Default"):
            other.hit()
    if not seen_root:
        raise _bad("[Content_Types].xml boş.")
    return overrides


def _check_overrides(overrides: dict[str, str]) -> None:
    """İçerik türü ile dosya adı eşleşmesi: bölüm başka bir adla taşınamaz (denetim YK-01 sstredirect)."""
    for part, content_type in overrides.items():
        expected = _FIXED_PARTS.get(part)
        if expected is not None and content_type != expected:
            raise _bad("XLSX içerik türü dosya adıyla uyuşmuyor.")
        if content_type in _REDIRECTABLE and expected != content_type:
            raise _bad("XLSX bölümü beklenmeyen bir adla bildirilmiş.")
        if content_type == _CT_SHEET and not _SHEET_PART.fullmatch(part[1:]):
            raise _bad("XLSX sayfası beklenmeyen bir adla bildirilmiş.")
    if overrides.get("/xl/workbook.xml") != _CT_WORKBOOK:
        raise _bad("Dosya geçerli bir XLSX çalışma kitabı değil.")


def _resolve(target: str) -> str:
    """İlişki hedefini arşiv yoluna çevirir (`/xl/...` mutlak, aksi halde `xl/` altına göre)."""
    if not target or "\\" in target or ":" in target or "\x00" in target:
        raise _bad("XLSX ilişki hedefi geçersiz.")
    path = target[1:] if target.startswith("/") else posixpath.join("xl", target)
    path = posixpath.normpath(path)
    if path.startswith(("..", "/")):
        raise _bad("XLSX ilişki hedefi geçersiz.")
    return path


def _read_relationships(archive: zipfile.ZipFile, limits: StreamLimits) -> dict[str, tuple[str, str]]:
    rels: dict[str, tuple[str, str]] = {}
    other = _Budget(limits.max_other_elements)
    for event, elem, stack in _events(
        archive, "xl/_rels/workbook.xml.rels", limits.max_other_elements + 1000
    ):
        if event != "start":
            continue
        name = _name(elem.tag)
        if len(stack) == 2 and name == "Relationship":
            rid, rtype, target = elem.get("Id"), elem.get("Type"), elem.get("Target")
            if not rid or not rtype or not target or rid in rels:
                raise _bad("XLSX ilişki kaydı geçersiz veya yinelenmiş.")
            if (elem.get("TargetMode") or "Internal") != "Internal":
                raise _bad("XLSX dış ilişki içeriyor.")
            rels[rid] = (rtype, target)
        elif not (len(stack) == 1 and name == "Relationships"):
            other.hit()
    return rels


@dataclass(frozen=True, slots=True)
class _Workbook:
    sheet_rid: str
    date1904: bool


def _read_workbook(archive: zipfile.ZipFile, limits: StreamLimits) -> _Workbook:
    """İlk sayfanın ilişki kimliği ve tarih sistemi. Belge sonuna kadar okunur (küçük, tavanlı): bozuk
    çalışma kitabı, ilk sayfadan sonra bile olsa reddedilir."""
    date1904 = False
    first_rid: str | None = None
    other = _Budget(limits.max_other_elements)
    for event, elem, stack in _events(archive, "xl/workbook.xml", limits.max_other_elements + 1000):
        if event != "start":
            continue
        name = _name(elem.tag)
        depth = len(stack)
        if depth == 1:
            if name != "workbook":
                raise _bad("Çalışma kitabı kökü geçersiz.")
        elif depth == 2 and name == "workbookPr":
            date1904 = (elem.get("date1904") or "").lower() in {"1", "true"}
        elif depth == 3 and name == "sheet" and _name(stack[1].tag) == "sheets":
            if first_rid is None:  # yalnız ilk sayfa (openpyxl worksheets[0] ile aynı)
                first_rid = next((elem.get(a) for a in _REL_ID_ATTRS if elem.get(a)), None)
                if not first_rid:
                    raise _bad("İlk çalışma sayfasının ilişki kimliği yok.")
        elif not (depth == 2 and name in {"sheets", "fileVersion", "fileSharing"}):
            other.hit()
    if first_rid is None:
        raise _bad("Çalışma kitabında sayfa yok.")
    return _Workbook(first_rid, date1904)


def _part_for(
    rels: dict[str, tuple[str, str]], kind: str, expected: str, overrides: dict[str, str], content_type: str
) -> str | None:
    """`kind` türündeki ilişkinin hedefi; sabit ada ve Override içerik türüne uymuyorsa XlsxFormatError."""
    found = [target for rtype, target in rels.values() if rtype.rsplit("/", 1)[-1] == kind]
    if not found:
        return None
    if len(found) > 1:
        raise _bad(f"XLSX birden çok {kind} ilişkisi içeriyor.")
    path = _resolve(found[0])
    if path != expected or overrides.get("/" + path) != content_type:
        raise _bad("XLSX bölümünün adı veya içerik türü beklenenle uyuşmuyor.")
    return path


# --- tarih biçimi -------------------------------------------------------------------------------------

_BUILTIN_DATE_FORMATS = frozenset({*range(14, 23), 45, 46, 47})
# Tırnaklı metin, kaçışlı karakter, köşeli parantezli bölüm (renk, yerel ayar, [h]) ve _x / *x doldurucuları.
_FORMAT_NOISE = re.compile(r'"[^"]*"|\\.|\[[^\]]*\]|_.|\*.')
_DATE_LETTER = re.compile(r"[ymd]", re.IGNORECASE)


def is_date_format(code: str) -> bool:
    """Özel sayı biçiminde y/m/d deseni var mı (doğrusal zaman; kod ilk 256 karakterle sınırlı)."""
    code = code[:MAX_CELL_CHARS]
    if code.lower() in {"general", "standard", "genel"}:
        return False
    return _DATE_LETTER.search(_FORMAT_NOISE.sub("", code)) is not None


class _DateStyles:
    """cellXfs indeksinden "tarih biçimli mi" bilgisi."""

    __slots__ = ("custom", "xf_formats")

    def __init__(self) -> None:
        self.custom: dict[int, bool] = {}
        self.xf_formats: list[int] = []

    def is_date(self, index: int) -> bool:
        if not 0 <= index < len(self.xf_formats):
            return False
        fmt = self.xf_formats[index]
        return fmt in _BUILTIN_DATE_FORMATS or self.custom.get(fmt, False)


def _read_styles(archive: zipfile.ZipFile, part: str, limits: StreamLimits) -> _DateStyles:
    styles = _DateStyles()
    other = _Budget(limits.max_other_elements)
    in_xfs_done = False
    for event, elem, stack in _events(
        archive, part, limits.max_other_elements + limits.max_style_xfs * 2 + 20_000
    ):
        depth = len(stack)
        name = _name(elem.tag)
        if event == "start":
            if depth == 1:
                if name != "styleSheet":
                    raise _bad("styles.xml kökü geçersiz.")
            elif depth == 3 and name in {"numFmt", "xf"}:
                pass  # aşağıda `end` olayında işlenir (sayım orada)
            elif not (depth == 2 and name in {"numFmts", "cellXfs"}):
                other.hit()
            continue
        if depth == 3 and name == "numFmt" and _name(stack[1].tag) == "numFmts":
            fmt_id, code = elem.get("numFmtId"), elem.get("formatCode")
            if fmt_id and fmt_id.isdigit() and len(fmt_id) <= _MAX_REF_DIGITS and code is not None:
                if len(styles.custom) >= limits.max_style_xfs:
                    raise _bad("XLSX stil tablosu çok büyük.")
                styles.custom[int(fmt_id)] = is_date_format(code)
        elif depth == 3 and name == "xf" and _name(stack[1].tag) == "cellXfs":
            fmt_id = elem.get("numFmtId") or "0"
            if len(styles.xf_formats) >= limits.max_style_xfs:
                raise _bad("XLSX stil tablosu çok büyük.")
            styles.xf_formats.append(
                int(fmt_id) if fmt_id.isdigit() and len(fmt_id) <= _MAX_REF_DIGITS else 0
            )
        elif depth == 3 and name == "xf":
            other.hit()
        elif depth == 2 and name == "cellXfs":
            in_xfs_done = True
        if in_xfs_done:
            break  # numFmts şemada cellXfs'ten önce gelir; gerisini okumaya gerek yok
    return styles


# --- hücre değerleri ----------------------------------------------------------------------------------

_NUMBER = re.compile(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_EPOCH_1900 = date(1899, 12, 30)
_EPOCH_1904 = date(1904, 1, 1)
_MAX_SERIAL = 2_958_465  # 9999-12-31


class _Ref(int):
    """Paylaşılan dize indeksi (sayfa okunduktan sonra metne çözülür)."""

    __slots__ = ()


def _clip(text: str) -> str:
    return text[:MAX_CELL_CHARS]


def serial_to_date(value: float, *, date1904: bool) -> date | None:
    """Excel seri sayısı → tarih. 1900 sisteminde 61 öncesi (sahte 29 Şubat 1900 dahil) belirsizdir: None."""
    if not math.isfinite(value) or value > _MAX_SERIAL:
        return None
    if date1904:
        return _EPOCH_1904 + timedelta(days=math.floor(value)) if value >= 0 else None
    return _EPOCH_1900 + timedelta(days=math.floor(value)) if value >= 61 else None


def _parse_number(text: str) -> int | float | str:
    text = text.strip()
    if len(text) > _MAX_NUMBER_CHARS or not _NUMBER.fullmatch(text):
        return _clip(text)
    if text.lstrip("-").isdigit():
        return int(text)
    number = float(text)
    return number if math.isfinite(number) else _clip(text)


def _parse_iso_date(text: str) -> date | datetime | str:
    try:
        parsed = datetime.fromisoformat(text.strip()[:32])
    except ValueError:
        return _clip(text)
    return parsed


@dataclass(slots=True)
class _Cell:
    kind: str | None = None
    style: int = 0
    value: str | None = None
    inline: list[str] | None = None
    inline_chars: int = 0
    seen: int = 0
    runs: int = 0


class _SheetReader:
    """Sayfa olay akışını satırlara çevirir (durum makinesi)."""

    def __init__(
        self, archive: zipfile.ZipFile, part: str, limits: StreamLimits, workbook: _Workbook
    ) -> None:
        self.archive = archive
        self.part = part
        self.limits = limits
        self.date1904 = workbook.date1904
        self.rows: list[list[Any]] = []
        self.needed: set[int] = set()
        self.chars = 0
        self._styles: _DateStyles | None = None
        self.styles_loader: Any = None

    def _date_styles(self) -> _DateStyles:
        if self._styles is None:
            self._styles = self.styles_loader() if self.styles_loader else _DateStyles()
        return self._styles

    def _charge(self, text: str) -> None:
        self.chars += len(text)
        if self.chars > self.limits.max_text_chars:
            raise _bad("XLSX hücre metinleri toplamı çok büyük.")

    def _value(self, cell: _Cell) -> Any:
        kind, text = cell.kind, cell.value
        if kind in (None, "n"):
            if text is None or not text.strip():
                return None
            number = _parse_number(text)
            if isinstance(number, str):
                self._charge(number)
            elif cell.style and self._date_styles().is_date(cell.style):
                return serial_to_date(float(number), date1904=self.date1904) or number
            return number
        if kind == "s":
            if text is None or not text.strip():
                return None
            index = text.strip()
            if not index.isdigit() or len(index) > _MAX_REF_DIGITS:
                raise _bad("Paylaşılan dize indeksi geçersiz.")
            self.needed.add(int(index))
            return _Ref(int(index))
        if kind == "inlineStr":
            joined = _clip("".join(cell.inline)) if cell.inline else None
            if joined is not None:
                self._charge(joined)
            return joined
        if kind in ("str", "e"):
            clipped = None if text is None else _clip(text)
            if clipped is not None:
                self._charge(clipped)
            return clipped
        if kind == "b":
            return None if text is None else text.strip() in {"1", "true"}
        if kind == "d":
            return None if text is None or not text.strip() else _parse_iso_date(text)
        raise _bad("Bilinmeyen hücre türü.")

    def read(self) -> list[list[Any]]:
        limits = self.limits
        max_elements = limits.max_cells * 4 + limits.max_other_elements + limits.max_physical_rows + 1000
        other = _Budget(limits.max_other_elements)
        names: list[str] = []
        cells = row_elements = non_blank_rows = last_row = 0
        row_values: list[Any] = []
        row_cells = next_col = col = 0
        cell = _Cell()
        for event, elem, _stack in _events(self.archive, self.part, max_elements):
            if event == "start":
                names.append(_name(elem.tag))
                kind = _SHEET_KINDS.get(tuple(names))
                if len(names) == 1:
                    if names[0] != "worksheet":
                        raise _bad("Sayfa kökü geçersiz.")
                elif kind is None:
                    other.hit()
                elif kind == "row":
                    row_elements += 1
                    reference = elem.get("r")
                    if reference is None:
                        number = last_row + 1
                    elif reference.isdigit() and len(reference) <= _MAX_REF_DIGITS:
                        number = int(reference)
                    else:
                        raise _bad("Satır numarası geçersiz.")
                    if number <= last_row:
                        raise _bad("Satır sırası bozuk.")
                    if row_elements > limits.max_physical_rows + 1 or number > limits.max_physical_rows + 1:
                        raise XlsxFormatError("Dosyada çok fazla satır var.", "rows")
                    while len(self.rows) < number - 1:
                        self.rows.append([])  # atlanan satırlar boş sayılır (satır numarası korunur)
                    last_row = number
                    row_values, row_cells, next_col = [], 0, 0
                elif kind == "c":
                    cells += 1
                    row_cells += 1
                    if cells > limits.max_cells:
                        raise _bad("XLSX içinde çok fazla hücre var.")
                    if row_cells > limits.max_columns:
                        raise _bad(f"Bir satırda en çok {limits.max_columns} sütun olabilir.")
                    col = _column_index(elem.get("r"), next_col)
                    if col < next_col:
                        raise _bad("Hücre sırası bozuk.")
                    next_col = col + 1
                    style = elem.get("s") or ""
                    cell = _Cell(
                        kind=elem.get("t"),
                        style=int(style) if style.isdigit() and len(style) <= _MAX_REF_DIGITS else 0,
                    )
                elif kind in ("v", "is", "f"):
                    bit = _CELL_CHILD_BITS[kind]
                    if cell.seen & bit:
                        other.hit()  # hücre başına her çocuktan en çok biri; fazlası tanınmayan sayılır
                    cell.seen |= bit
                elif kind in ("t", "r"):
                    cell.runs += 1
                    if cell.runs > MAX_RUNS:
                        other.hit()  # tek hücrede sınırsız `<t>`/`<r>` seli de tanınmayan sayılır
                continue
            kind = _SHEET_KINDS.get(tuple(names))
            if kind == "v" and cell.seen & 1 and cell.value is None:
                cell.value = elem.text
            elif kind == "t" and elem.text:
                if cell.inline is None:
                    cell.inline = []
                if cell.inline_chars < MAX_CELL_CHARS:
                    cell.inline.append(elem.text[:MAX_CELL_CHARS])
                    cell.inline_chars += len(cell.inline[-1])
            elif kind == "c":
                value = self._value(cell)
                if col >= limits.max_columns:
                    if value is not None and not (isinstance(value, str) and not value.strip()):
                        raise _bad(f"Bir satırda en çok {limits.max_columns} sütun olabilir.")
                else:
                    if len(row_values) < col:
                        row_values.extend([None] * (col - len(row_values)))
                    row_values.append(value)
            elif kind == "row":
                if any(v is not None and not (isinstance(v, str) and not v.strip()) for v in row_values):
                    non_blank_rows += 1
                    if non_blank_rows > limits.max_rows + 1:
                        raise XlsxFormatError("Dosyada çok fazla satır var.", "rows")
                self.rows.append(row_values)
                row_values = []
            names.pop()
        return self.rows


_SHEET_KINDS: dict[tuple[str, ...], str] = {
    ("worksheet", "sheetData"): "data",
    ("worksheet", "sheetData", "row"): "row",
    ("worksheet", "sheetData", "row", "c"): "c",
    ("worksheet", "sheetData", "row", "c", "v"): "v",
    ("worksheet", "sheetData", "row", "c", "f"): "f",
    ("worksheet", "sheetData", "row", "c", "is"): "is",
    ("worksheet", "sheetData", "row", "c", "is", "t"): "t",
    ("worksheet", "sheetData", "row", "c", "is", "r"): "r",
    ("worksheet", "sheetData", "row", "c", "is", "r", "t"): "t",
}
_CELL_CHILD_BITS = {"v": 1, "is": 2, "f": 4}


def _column_index(reference: str | None, fallback: int) -> int:
    """ "B7" biçimli hücre başvurusundan sıfır tabanlı sütun; başvuru yoksa sıradaki sütun."""
    if not reference:
        return fallback
    letters = 0
    value = 0
    for char in reference:
        if "A" <= char <= "Z":
            letters += 1
            value = value * 26 + (ord(char) - 64)
        else:
            break
    if not 1 <= letters <= 3:
        raise _bad("Hücre başvurusu geçersiz.")
    return value - 1


def _read_shared_strings(archive: zipfile.ZipFile, needed: set[int], limits: StreamLimits) -> dict[int, str]:
    """Yalnız sayfanın başvurduğu dizeleri tutar; hepsi bulununca durur. Her `si` bitince temizlenir."""
    table: dict[int, str] = {}
    other = _Budget(limits.max_other_elements)
    remaining = set(needed)
    index = -1
    parts: list[str] = []
    length = runs = 0
    for event, elem, stack in _events(
        archive, "xl/sharedStrings.xml", limits.max_shared_strings * 40 + limits.max_other_elements
    ):
        depth = len(stack)
        name = _name(elem.tag)
        if event == "start":
            if depth == 1:
                if name != "sst":
                    raise _bad("sharedStrings.xml kökü geçersiz.")
            elif depth == 2 and name == "si":
                index += 1
                if index >= limits.max_shared_strings:
                    raise _bad("XLSX paylaşılan dize tablosu çok büyük.")
                parts, length, runs = [], 0, 0
            elif (depth == 3 and name in {"t", "r"} and _name(stack[1].tag) == "si") or (
                depth == 4 and name == "t" and _name(stack[2].tag) == "r"
            ):
                runs += 1
                if runs > MAX_RUNS:
                    other.hit()
            else:
                other.hit()  # <si> dışı veya tanınmayan öğe seli sayılır
            continue
        if (
            name == "t"
            and elem.text
            and length < MAX_CELL_CHARS
            and (
                (depth == 3 and _name(stack[1].tag) == "si")
                or (depth == 4 and _name(stack[2].tag) == "r" and _name(stack[1].tag) == "si")
            )
        ):
            parts.append(elem.text[:MAX_CELL_CHARS])
            length += len(parts[-1])
        elif depth == 2 and name == "si" and index in remaining:
            table[index] = _clip("".join(parts))
            remaining.discard(index)
            if not remaining:
                break
    if remaining:
        raise _bad("Paylaşılan dize indeksi tabloda yok.")
    return table


# --- giriş noktası ------------------------------------------------------------------------------------


def read_first_sheet(data: bytes, limits: StreamLimits = StreamLimits()) -> list[list[Any]]:
    """XLSX'in ilk çalışma sayfasını ham hücre satırları olarak okur (`check_zip` ÖNCE çağrılmış olmalı)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            overrides = _read_content_types(archive, limits)
            _check_overrides(overrides)
            workbook = _read_workbook(archive, limits)
            rels = _read_relationships(archive, limits)
            if workbook.sheet_rid not in rels:
                raise _bad("İlk çalışma sayfasının ilişkisi bulunamadı.")
            rel_type, target = rels[workbook.sheet_rid]
            sheet = _resolve(target)
            if rel_type.rsplit("/", 1)[-1] != "worksheet" or not _SHEET_PART.fullmatch(sheet):
                raise _bad("İlk sayfa bir çalışma sayfası değil.")
            if sheet not in names or overrides.get("/" + sheet) != _CT_SHEET:
                raise _bad("XLSX sayfasının içerik türü beklenenle uyuşmuyor.")
            shared = _part_for(rels, "sharedStrings", "xl/sharedStrings.xml", overrides, _CT_SST)
            styles_part = _part_for(rels, "styles", "xl/styles.xml", overrides, _CT_STYLES)
            for part in (shared, styles_part):
                if part is not None and part not in names:
                    raise _bad("XLSX ilişkisinin hedef bölümü yok.")
            reader = _SheetReader(archive, sheet, limits, workbook)
            if styles_part is not None:
                reader.styles_loader = lambda: _read_styles(archive, styles_part, limits)
            rows = reader.read()
            if reader.needed:
                if shared is None:
                    raise _bad("Paylaşılan dize tablosu yok.")
                table = _read_shared_strings(archive, reader.needed, limits)
                resolved = 0
                for row in rows:
                    for position, value in enumerate(row):
                        if type(value) is _Ref:
                            text = table[int(value)]
                            row[position] = text
                            resolved += len(text)
                            if resolved > limits.max_text_chars:
                                raise _bad("XLSX hücre metinleri toplamı çok büyük.")
            return rows
    except XlsxFormatError:
        raise
    except (zipfile.BadZipFile, KeyError, ValueError, OverflowError):
        raise _bad("XLSX çalışma kitabı okunamadı.") from None
