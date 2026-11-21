"""Bildirim şablonları (ADR-0009 D5, §7.1 ve §7.4): saf testler (veritabanı yok).

Kapsam: ürün başlığı temizliği (kontrol/biçim karakterleri, bağlantı şeması, kısaltma), HTML kaçışı, başlık
enjeksiyonu, tutar tercihi kapalıyken tutarın hiçbir yerde (konu, düz metin, HTML) olmaması, tr-TR tutar biçimi,
yük ayrıştırma ve birleştirme, `EmailMessage.headers` doğrulaması ve dosya arka ucunun yeni alanları.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.email import EmailMessage, FileEmailSender
from app.services.notify_templates import (
    TITLE_LIMIT,
    RenderContext,
    RuleLine,
    clean_title,
    format_try,
    lines_from_payload,
    merge_payloads,
    render_email,
)

LOSS = "ZARARINA_SATIS"
DEDUCTION = "BEKLENMEYEN_KESINTI"
ADS = "REKLAM_KARI_YIYOR"
RETURNS = "IADE_ORANI_ARTISI"


def context(**kw: object) -> RenderContext:
    base: dict[str, object] = {
        "product_name": "NetKâr",
        "kind": "instant",
        "lines": (RuleLine(LOSS, 3, Decimal("1234.50")),),
        "titles": (),
        "show_amounts": True,
        "estimated": False,
        "settings_revision": 12,
        "panel_url": "https://app.test.invalid/panel/uyarilar",
        "settings_url": "https://app.test.invalid/panel/ayarlar/bildirimler",
        "unsubscribe_links": {LOSS: "https://app.test.invalid/bildirim-kapat?token=AAA.BBB"},
        "one_click_url": "https://app.test.invalid/api/v1/notifications/unsubscribe?token=CCC.DDD",
    }
    base.update(kw)
    return RenderContext(**base)  # type: ignore[arg-type]


# ---- ürün başlığı temizliği ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Kırmızı  Tişört\r\nBcc: kotu@example.com", "Kırmızı Tişört Bcc: kotu@example.com"),
        ("A\x00B\x07C\x1bD", "ABCD"),  # NUL, BEL, ESC atılır
        ("Ürün‮Evil‬", "ÜrünEvil"),  # bidi geçersiz kılma atılır
        ("Sıfır​Genişlik⁠", "SıfırGenişlik"),
        ("Satır Ayırıcı Paragraf", "Satır Ayırıcı Paragraf"),
        ("\t  boşluklu   başlık  ", "boşluklu başlık"),
        ("Fırsat http://kotu.example/x tıkla", "Fırsat http kotu.example/x tıkla"),
        ("javascript:alert(1)", "javascript alert(1)"),
        ("", ""),
        ("\x00\x01​", ""),
    ],
)
def test_clean_title_strips_control_format_chars_and_defangs_links(raw: str, expected: str) -> None:
    assert clean_title(raw) == expected


def test_clean_title_truncates_to_the_limit_with_an_ellipsis() -> None:
    long = "a" * 200
    cleaned = clean_title(long)
    assert len(cleaned) == TITLE_LIMIT and cleaned.endswith("…") and cleaned[:-1] == "a" * (TITLE_LIMIT - 1)
    assert clean_title("b" * TITLE_LIMIT) == "b" * TITLE_LIMIT  # tam sınırda kısaltma yok
    assert clean_title("kısa") == "kısa"


# ---- tutar biçimi ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("0"), "0,00 TL"),
        (Decimal("5"), "5,00 TL"),
        (Decimal("1234.5"), "1.234,50 TL"),
        (Decimal("999.99"), "999,99 TL"),
        (Decimal("1000"), "1.000,00 TL"),
        (Decimal("-12"), "-12,00 TL"),
        (Decimal("1234567.89"), "1.234.567,89 TL"),
    ],
)
def test_format_try_uses_turkish_separators(amount: Decimal, expected: str) -> None:
    assert format_try(amount) == expected


# ---- içerik kuralları ------------------------------------------------------------------------------------------------


def test_instant_email_names_the_rule_and_count_and_carries_the_fixed_safety_text() -> None:
    mail = render_email(context())
    assert mail.subject == "NetKâr: 3 üründe zararına satış"
    assert "- 3 üründe zararına satış" in mail.text and "Toplam zarar: 1.234,50 TL" in mail.text
    assert "Tutarlar KDV hariçtir." in mail.text and "Kâr ayarı sürümü: 12" in mail.text
    assert "parolanızı hiçbir zaman istemez" in mail.text and "parolanızı hiçbir zaman istemez" in mail.html
    assert "https://app.test.invalid/panel/uyarilar" in mail.text
    assert "Zararına satış: https://app.test.invalid/bildirim-kapat?token=AAA.BBB" in mail.text
    assert mail.html.startswith("<!doctype html>") and 'lang="tr"' in mail.html
    assert "{n}" not in mail.text and "{n}" not in mail.html  # yer tutucu kalmadı


def test_headers_carry_the_one_click_unsubscribe_pair() -> None:
    mail = render_email(context())
    assert mail.headers == {
        "List-Unsubscribe": "<https://app.test.invalid/api/v1/notifications/unsubscribe?token=CCC.DDD>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    EmailMessage("a@example.com", "k", "g", headers=mail.headers)  # başlık denetiminden geçer


def test_no_one_click_url_means_no_unsubscribe_headers() -> None:
    mail = render_email(context(one_click_url=None))
    assert mail.headers == {} and "Zararına satış: https://" in mail.text  # gövde bağlantıları kalır


def test_digest_and_multi_rule_subjects() -> None:
    lines = (RuleLine(LOSS, 2, Decimal("10.00")), RuleLine(RETURNS, 1, None), RuleLine(DEDUCTION, 4, None))
    digest = render_email(context(kind="digest", lines=lines))
    assert digest.subject == "NetKâr: günlük uyarı özeti (7 uyarı)"
    assert "Son 24 saatteki uyarıların özeti" in digest.text
    instant = render_email(context(lines=lines))
    assert instant.subject == "NetKâr: 7 yeni uyarı"
    # Sıra sabittir (kural sırası), tutarı olmayan kural için tutar satırı yoktur.
    assert digest.text.index("zararına satış") < digest.text.index("beklenmeyen kesinti")
    assert digest.text.count("Toplam") == 1
    assert render_email(context(kind="test", lines=())).subject == "NetKâr: test bildirimi"
    assert render_email(context(lines=())).subject == "NetKâr: yeni uyarı"


@pytest.mark.parametrize("kind", ["instant", "digest"])
def test_amounts_are_absent_everywhere_when_the_preference_is_off(kind: str) -> None:
    lines = (RuleLine(LOSS, 3, Decimal("1234.50")), RuleLine(ADS, 1, Decimal("77.25")))
    mail = render_email(context(kind=kind, lines=lines, show_amounts=False))
    for part in (mail.subject, mail.text, mail.html):
        assert "TL" not in part and "1.234" not in part and "1234" not in part and "77,25" not in part
        assert "Toplam zarar" not in part and "Reklam harcaması:" not in part
    assert "KDV hariçtir" not in mail.text  # tutar yoksa KDV notu da yok
    # Aynı bağlamda tercih açıkken tutarlar görünür (testin kendisi anlamlı).
    shown = render_email(context(kind=kind, lines=lines, show_amounts=True))
    assert "1.234,50 TL" in shown.text and "77,25 TL" in shown.html


def test_estimated_certainty_adds_the_estimate_note() -> None:
    assert "tahminidir" in render_email(context(estimated=True)).text
    assert "tahminidir" not in render_email(context(estimated=False)).text


def test_titles_are_cleaned_limited_to_three_and_html_is_escaped() -> None:
    nasty = "<script>alert(\"x\")</script> & 'q'"
    titles = (nasty, "İkinci\r\nBcc: kotu@example.com", "Üçüncü", "Dördüncü")
    mail = render_email(context(titles=titles))
    assert "Dördüncü" not in mail.text and "Dördüncü" not in mail.html  # en çok 3
    line = next(ln for ln in mail.text.splitlines() if ln.startswith("Örnek ürünler:"))
    assert "İkinci Bcc: kotu@example.com" in line  # tek satıra indi: başlık enjeksiyonu yok
    assert not any(ln.startswith("Bcc:") for ln in mail.text.splitlines())
    assert "<script>" not in mail.html and "&lt;script&gt;" in mail.html and "&amp;" in mail.html
    assert "&quot;x&quot;" in mail.html and "&#x27;q&#x27;" in mail.html
    assert "\r" not in mail.subject and "\n" not in mail.subject


def test_hostile_values_never_become_markup_or_links_in_html() -> None:
    mail = render_email(
        context(
            titles=('"><a href="https://kotu.example">tıkla</a>',),
            unsubscribe_links={LOSS: 'https://app.test.invalid/x?"onmouseover="alert(1)'},
        )
    )
    assert 'href="https://kotu.example"' not in mail.html
    assert 'onmouseover="alert' not in mail.html  # tırnak kaçışlandı: öznitelikten çıkılamaz
    assert "&quot;onmouseover=&quot;" in mail.html


def test_no_order_number_or_customer_wording_in_any_part() -> None:
    mail = render_email(context(kind="digest", titles=("Ürün A",)))
    blob = (mail.subject + mail.text + mail.html).lower()
    for word in ("sipariş no", "siparis no", "müşteri", "musteri", "adres", "telefon", "tc kimlik"):
        assert word not in blob


# ---- yük ayrıştırma ve birleştirme -----------------------------------------------------------------------------------


def test_lines_from_payload_reads_the_outbox_shape_and_ignores_junk() -> None:
    payload = {
        "rule_counts": {LOSS: 2, DEDUCTION: 0, "BILINMEYEN": 5, RETURNS: True, ADS: -1},
        "event_count": 2,
        "certainty": "tahmini",
        "settings_revision": 7,
        LOSS: {"event_count": 2, "window_days": 7, "total_amount": "10.50"},
    }
    lines, estimated, revision = lines_from_payload(payload)
    assert lines == (RuleLine(LOSS, 2, Decimal("10.50")),)
    assert estimated is True and revision == 7
    empty, est2, rev2 = lines_from_payload({"rule_counts": "bozuk", "settings_revision": True})
    assert empty == () and est2 is False and rev2 is None
    bad_amount = {"rule_counts": {LOSS: 1}, LOSS: {"total_amount": "abc"}}
    assert lines_from_payload(bad_amount)[0] == (RuleLine(LOSS, 1, None),)
    infinite = {"rule_counts": {LOSS: 1}, LOSS: {"total_amount": "Infinity"}}
    assert lines_from_payload(infinite)[0] == (RuleLine(LOSS, 1, None),)
    assert lines_from_payload({"rule_counts": {LOSS: 1}, LOSS: {"total_amount": 5}})[0][0].total_amount == 5


def test_merge_payloads_sums_counts_and_amounts_and_keeps_the_worst_certainty() -> None:
    first = {
        "rule_counts": {LOSS: 1},
        "certainty": "kesin",
        "settings_revision": 3,
        LOSS: {"event_count": 1, "window_days": 7, "total_amount": "10.25"},
    }
    second = {
        "rule_counts": {LOSS: 2, RETURNS: 1},
        "certainty": "tahmini",
        "settings_revision": 5,
        LOSS: {"event_count": 2, "window_days": 7, "total_amount": "5.50"},
        RETURNS: {"event_count": 1, "window_days": 28},
    }
    merged = merge_payloads([first, second])
    assert merged["rule_counts"] == {LOSS: 3, RETURNS: 1} and merged["event_count"] == 4
    assert merged["certainty"] == "tahmini" and merged["settings_revision"] == 5
    assert merged[LOSS] == {"event_count": 3, "total_amount": "15.75"}
    assert RETURNS not in {k for k, v in merged.items() if isinstance(v, dict) and "total_amount" in v}
    assert merge_payloads([first])["certainty"] == "kesin"
    assert "settings_revision" not in merge_payloads([{"rule_counts": {LOSS: 1}}])


# ---- EmailMessage ve dosya arka ucu ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("List-Unsubscribe", "<https://x.example>\r\nBcc: kotu@example.com"),
        ("List-Unsubscribe", "değer\nyeni"),
        ("X-Test", "nul\x00"),
        ("Geçersiz Ad", "değer"),
        ("", "değer"),
        ("X:Y", "değer"),
        ("1Basla", "değer"),
    ],
)
def test_email_message_rejects_header_injection_and_bad_names(name: str, value: str) -> None:
    with pytest.raises(ValueError, match="geçersiz e-posta başlığı"):
        EmailMessage("a@example.com", "k", "g", headers={name: value})


def test_email_message_defaults_keep_the_old_three_field_form_valid() -> None:
    message = EmailMessage("a@example.com", "konu", "gövde")
    assert message.html is None and dict(message.headers) == {}


@pytest.mark.parametrize(
    ("to", "subject"),
    [
        ("a@example.com\r\nBcc: kotu@example.com", "k"),
        ("a@example.com\nBcc: x", "k"),
        ("a@example.com", "konu\r\nBcc: kotu@example.com"),
        ("a@example.com", "konu\x00"),
        ("a\x00@example.com", "k"),
    ],
)
def test_email_message_rejects_crlf_and_nul_in_recipient_and_subject(to: str, subject: str) -> None:
    with pytest.raises(ValueError, match="geçersiz e-posta alanı"):
        EmailMessage(to, subject, "g")


async def test_file_sender_records_the_idempotency_key_only_when_given(tmp_path: Path) -> None:
    path = tmp_path / "o" / "outbox.jsonl"
    sender = FileEmailSender(str(path))
    await sender.send(EmailMessage("a@example.com", "k", "g"), idempotency_key="satir-1")
    await sender.send(EmailMessage("a@example.com", "k2", "g2"))
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["idempotency_key"] == "satir-1" and "idempotency_key" not in second


def test_only_the_two_local_backends_count_as_local(tmp_path: Path) -> None:
    from app.core.email import InMemoryOutbox, is_local_sender

    class Network:
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None: ...

    assert is_local_sender(InMemoryOutbox()) and is_local_sender(FileEmailSender(str(tmp_path / "o.jsonl")))
    assert not is_local_sender(Network()) and not is_local_sender(None)


async def test_file_sender_writes_new_fields_only_when_present(tmp_path: Path) -> None:
    path = tmp_path / "out" / "outbox.jsonl"
    sender = FileEmailSender(str(path))
    await sender.send(EmailMessage("a@example.com", "k1", "g1"))
    await sender.send(
        EmailMessage(
            "a@example.com", "k2", "g2", html="<p>g2</p>", headers={"List-Unsubscribe": "<https://x>"}
        )
    )
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first == {"to": "a@example.com", "subject": "k1", "body": "g1"}  # eski biçim değişmedi
    assert second["html"] == "<p>g2</p>" and second["headers"] == {"List-Unsubscribe": "<https://x>"}
