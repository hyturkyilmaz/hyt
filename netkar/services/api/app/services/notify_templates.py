"""Uyarı e-postası şablonları (ADR-0009 §7.1 ve §7.4): Türkçe, düz metin + basit HTML. Saf modül (I/O yok).

İçerik kuralları (testle korunur):
- Sipariş numarası ve son müşteri verisi (ad, adres, il, müşteri anahtarı) GİRMEZ; zaten girdi olarak da
  yoktur. Gövde yalnız kural adı ve sayısı, (tercih açıksa) toplam tutar, en çok 3 ürün başlığı ve sabit
  bağlantılardır.
- Tutar `show_amounts` kapalıyken gövdede ve konuda YOKTUR (düz metin ve HTML).
- Ürün başlığı Trendyol katalogundan gelir ve GÜVENİLMEZ veridir: kontrol ve biçim karakterleri (satır
  sonu, bidi geçersiz kılma, sıfır genişlik) temizlenir, bağlantı şemaları etkisizleştirilir, 80
  karaktere kısaltılır. HTML'de her dinamik değer `html.escape` ile kaçışlanır; düz metinde başlık satır
  sonu içeremez (başlık enjeksiyonu yok).
- Tanıtım içeriği yok (ADR §9: işlemsel ileti); sabit uyarı "parola istemeyiz" (ADR §10.1, oltalama).
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.alerts import AlertRule

TITLE_LIMIT = 80
MAX_TITLES = 3

# Bildirim bağlantıları için sabit web yolları (web uygulaması D7'de bu yolları sunar).
PANEL_PATH = "/panel/uyarilar"
SETTINGS_PATH = "/panel/ayarlar/bildirimler"
UNSUBSCRIBE_PAGE_PATH = "/bildirim-kapat"
UNSUBSCRIBE_API_PATH = "/api/v1/notifications/unsubscribe"

# Kural -> (cümle kalıbı, tutar etiketi). Kalıpta yalnız `{n}` yer tutucusu vardır.
_RULE_TEXT: dict[str, tuple[str, str | None]] = {
    AlertRule.LOSS_MAKING_SALE.value: ("{n} üründe zararına satış", "Toplam zarar"),
    AlertRule.UNEXPECTED_DEDUCTION.value: ("{n} sipariş satırında beklenmeyen kesinti", "Toplam fark"),
    AlertRule.AD_EATS_PROFIT.value: ("{n} üründe reklam harcaması kârı yiyor", "Reklam harcaması"),
    AlertRule.RETURN_RATE_INCREASE.value: ("{n} uyarı: iade oranı artışı", None),
}
_RULE_ORDER = tuple(_RULE_TEXT)
# Kural kısa adı (kapatma bağlantısı satırı).
_RULE_NAME: dict[str, str] = {
    AlertRule.LOSS_MAKING_SALE.value: "Zararına satış",
    AlertRule.UNEXPECTED_DEDUCTION.value: "Beklenmeyen kesinti",
    AlertRule.AD_EATS_PROFIT.value: "Reklam kârı yiyor",
    AlertRule.RETURN_RATE_INCREASE.value: "İade oranı artışı",
}
_ESTIMATED = "tahmini"
_SCHEME_SLASHES = re.compile(r":/{2,}")
_RISKY_SCHEME = re.compile(r"\b(javascript|vbscript|data)\s*:", re.IGNORECASE)
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class RuleLine:
    """Bir kuralın özeti: olay sayısı ve (varsa) toplam tutar (KDV hariç, TL)."""

    rule: str
    event_count: int
    total_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Şablonun girdisi (veritabanı ya da ayardan gelen güvenli alanlar)."""

    product_name: str
    kind: str  # instant | digest | test
    lines: tuple[RuleLine, ...]
    titles: tuple[str, ...]
    show_amounts: bool
    estimated: bool
    settings_revision: int | None
    panel_url: str
    settings_url: str
    # Kural -> web kapatma sayfası bağlantısı (imzalı token içerir).
    unsubscribe_links: Mapping[str, str]
    # `List-Unsubscribe` (RFC 8058): tek tık POST ucu.
    # None ise başlık eklenmez (birden çok kuralı olan anlık ileti: tek tık yalnız TEK kuralı kapatabilir).
    one_click_url: str | None


@dataclass(frozen=True, slots=True)
class RenderedEmail:
    """Üretilen ileti parçaları (alıcı adresi burada YOKTUR; gönderimde eklenir)."""

    subject: str
    text: str
    html: str
    headers: Mapping[str, str]


def clean_title(raw: str, limit: int = TITLE_LIMIT) -> str:
    """Güvenilmez ürün başlığını temizler: kontrol/biçim karakterleri atılır, boşluk sadeleşir, kısaltılır.

    - Satır sonu ve sekme boşluğa çevrilir; Unicode `C*` kategorileri (kontrol, biçim: bidi geçersiz kılma,
      sıfır genişlik, kullanım dışı) ve satır/paragraf ayırıcıları atılır.
    - `://` ve `javascript:` gibi şemalar etkisizleştirilir (metin istemcilerinde otomatik bağlantı olmasın).
    - `limit` karakteri aşarsa son karakter yerine `…` konur.
    """
    out: list[str] = []
    for char in raw:
        category = unicodedata.category(char)
        if char in "\t\r\n" or category in {"Zl", "Zp", "Zs"}:
            out.append(" ")
        elif not category.startswith("C"):
            out.append(char)
    text = _SPACES.sub(" ", "".join(out)).strip()
    text = _SCHEME_SLASHES.sub(" ", text)
    text = _RISKY_SCHEME.sub(lambda m: m.group(1) + " ", text)
    text = _SPACES.sub(" ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def format_try(amount: Decimal) -> str:
    """tr-TR tutar biçimi: `1.234,50 TL` (kuruş, tek yuvarlama yok: gelen değer zaten kuruştur)."""
    sign = "-" if amount < 0 else ""
    whole, _, cents = f"{abs(amount):.2f}".partition(".")
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{'.'.join(groups)},{cents} TL"


def _decimal(value: Any) -> Decimal | None:
    """Yük tutarını güvenle Decimal'e çevirir (metin kabul; geçersizse yok sayılır)."""
    if not isinstance(value, str | int) or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return parsed if parsed.is_finite() else None


def lines_from_payload(payload: Mapping[str, Any]) -> tuple[tuple[RuleLine, ...], bool, int | None]:
    """Outbox yükünden (ADR §4.4 izin listesi) kural satırları, tahmini bayrağı ve ayar sürümü.

    Yük tutarlıdır ama yine de savunmacı okunur: bilinmeyen kural ve geçersiz sayı atlanır.
    """
    counts = payload.get("rule_counts")
    counts = counts if isinstance(counts, Mapping) else {}
    lines: list[RuleLine] = []
    for rule in _RULE_ORDER:
        raw = counts.get(rule)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw <= 0:
            continue
        entry = payload.get(rule)
        amount = _decimal(entry.get("total_amount")) if isinstance(entry, Mapping) else None
        lines.append(RuleLine(rule, raw, amount))
    revision = payload.get("settings_revision")
    return (
        tuple(lines),
        payload.get("certainty") == _ESTIMATED,
        revision if isinstance(revision, int) and not isinstance(revision, bool) else None,
    )


def _subject(ctx: RenderContext) -> str:
    total = sum(line.event_count for line in ctx.lines)
    if ctx.kind == "test":
        return f"{ctx.product_name}: test bildirimi"
    if ctx.kind == "digest":
        return f"{ctx.product_name}: günlük uyarı özeti ({total} uyarı)"
    if not ctx.lines:
        return f"{ctx.product_name}: yeni uyarı"
    if len(ctx.lines) == 1:
        phrase = _RULE_TEXT[ctx.lines[0].rule][0].format(n=ctx.lines[0].event_count)
        return f"{ctx.product_name}: {phrase}"
    return f"{ctx.product_name}: {total} yeni uyarı"


def _item_lines(ctx: RenderContext) -> list[tuple[str, str | None]]:
    """(cümle, tutar satırı ya da None) çiftleri. Tutar tercihi kapalıyken ikinci öğe hep None."""
    items: list[tuple[str, str | None]] = []
    for line in ctx.lines:
        phrase, label = _RULE_TEXT[line.rule]
        amount = None
        if ctx.show_amounts and label is not None and line.total_amount is not None:
            amount = f"{label}: {format_try(line.total_amount)}"
        items.append((phrase.format(n=line.event_count), amount))
    return items


def _footnotes(ctx: RenderContext) -> list[str]:
    notes: list[str] = []
    if ctx.show_amounts and any(line.total_amount is not None for line in ctx.lines):
        notes.append("Tutarlar KDV hariçtir.")
    if ctx.estimated:
        notes.append("Bazı değerler tahminidir; veriler netleştikçe değişebilir.")
    if ctx.settings_revision is not None:
        notes.append(f"Kâr ayarı sürümü: {ctx.settings_revision}")
    return notes


def render_email(ctx: RenderContext) -> RenderedEmail:
    """İletiyi üretir (düz metin + HTML + `List-Unsubscribe` başlıkları)."""
    subject = _subject(ctx)
    intro = {
        "instant": "Hesabınızda yeni uyarılar var:",
        "digest": "Son 24 saatteki uyarıların özeti:",
        "test": "Bu, bildirim ayarlarınızı denemek için gönderilen bir test iletisidir.",
    }.get(ctx.kind, "Hesabınızda yeni uyarılar var:")
    items = _item_lines(ctx)
    titles = tuple(title for title in (clean_title(t) for t in ctx.titles) if title)[:MAX_TITLES]
    notes = _footnotes(ctx)
    safety = (
        "Bu e-posta yalnızca hesabınızdaki uyarılar hakkında bilgi verir. "
        f"{ctx.product_name} sizden parolanızı hiçbir zaman istemez."
    )
    off_rules = [rule for rule in _RULE_ORDER if rule in ctx.unsubscribe_links]

    text_lines = ["Merhaba,", "", intro, ""]
    for sentence, amount in items:
        text_lines.append(f"- {sentence}")
        if amount:
            text_lines.append(f"  {amount}")
    if titles:
        text_lines += ["", "Örnek ürünler: " + "; ".join(titles)]
    if notes:
        text_lines += ["", *notes]
    text_lines += ["", f"Uyarıları panelde görün: {ctx.panel_url}"]
    if off_rules:
        text_lines += ["", "Bu bildirimleri e-postayla almak istemiyorsanız tek tıkla kapatın:"]
        text_lines += [f"- {_RULE_NAME[rule]}: {ctx.unsubscribe_links[rule]}" for rule in off_rules]
    text_lines += ["", f"Bildirim tercihleri: {ctx.settings_url}", "", safety]

    esc = html.escape
    body: list[str] = [f"<p>Merhaba,</p><p>{esc(intro)}</p>", "<ul>"]
    for sentence, amount in items:
        extra = f"<br>{esc(amount)}" if amount else ""
        body.append(f"<li>{esc(sentence)}{extra}</li>")
    body.append("</ul>")
    if titles:
        body.append(f"<p>Örnek ürünler: {esc('; '.join(titles))}</p>")
    if notes:
        body.append("<p>" + "<br>".join(esc(n) for n in notes) + "</p>")
    body.append(f'<p><a href="{esc(ctx.panel_url, quote=True)}">Uyarıları panelde görün</a></p>')
    if off_rules:
        body.append("<p>Bu bildirimleri e-postayla almak istemiyorsanız tek tıkla kapatın:</p><ul>")
        for rule in off_rules:
            link = esc(ctx.unsubscribe_links[rule], quote=True)
            body.append(f'<li><a href="{link}">{esc(_RULE_NAME[rule])}</a></li>')
        body.append("</ul>")
    settings_link = esc(ctx.settings_url, quote=True)
    body.append(
        f'<p><a href="{settings_link}">Bildirim tercihleri</a></p><p><small>{esc(safety)}</small></p>'
    )
    document = (
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        f"<title>{esc(subject)}</title></head>"
        '<body style="font-family: Arial, Helvetica, sans-serif; line-height: 1.5; color: #1f2933;">'
        + "".join(body)
        + "</body></html>"
    )
    headers: dict[str, str] = {}
    if ctx.one_click_url is not None:
        headers = {
            "List-Unsubscribe": f"<{ctx.one_click_url}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        }
    return RenderedEmail(subject, "\n".join(text_lines) + "\n", document, headers)


def merge_payloads(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Aynı kullanıcıya birleştirilen anlık satırların yüklerini toplar (sessiz saat birikimi, ADR §7.3).

    Çıktı yük biçimiyle (`rule_counts`, kural başına `event_count`/`total_amount`, `certainty`, sürümler)
    aynıdır;
    yalnız işlenir, saklanmaz.
    """
    counts: dict[str, int] = {}
    amounts: dict[str, Decimal] = {}
    certainty = "kesin"
    settings_revision: int | None = None
    for payload in payloads:
        lines, estimated, revision = lines_from_payload(payload)
        for line in lines:
            counts[line.rule] = counts.get(line.rule, 0) + line.event_count
            if line.total_amount is not None:
                amounts[line.rule] = amounts.get(line.rule, Decimal(0)) + line.total_amount
        if estimated:
            certainty = _ESTIMATED
        if revision is not None:
            settings_revision = revision if settings_revision is None else max(settings_revision, revision)
    merged: dict[str, Any] = {
        "rule_counts": counts,
        "event_count": sum(counts.values()),
        "certainty": certainty,
    }
    if settings_revision is not None:
        merged["settings_revision"] = settings_revision
    for rule, total in amounts.items():
        merged[rule] = {"event_count": counts[rule], "total_amount": format(total, "f")}
    return merged
