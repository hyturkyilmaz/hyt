"""Doğru cevap kartı: tohum sonrası rakamlar GERÇEK kâr motoru ve rapor servislerinden hesaplanır.

Plan (docs/ux/kullanici_testi_plani_S4.md §7.1): "Her görev için doğru ürün, doğru sipariş, doğru rakam kartı
tohumla birlikte üretilir; elle yazılmaz." Bu modül hiçbir rakam yazmaz: `period_profit` (besleyici + saf motor),
`profit_views` (ürün, sipariş, uyarı görünümleri; API uçlarının kullandığı işlevler) ve kayıtlı kâr ayarları
(`load_profit_settings`) çalıştırılır; sonuç markdown'a dökülür. Aynı değerler API'den de okunabilir (test bunu doğrular).

Veri tarihi ve dönem: kart `as_of` gününe göredir. Panelde "30 gün" seçilince dönem = (bugün - 29 gün, bugün).
Tohum verisi `as_of`'tan en çok 27 gün geriye uzandığı için `as_of`'tan sonraki 2 gün içinde de aynı rakamlar çıkar;
daha sonra betik yeniden çalıştırılır (tarihler kayar, kayıtlar çoğalmaz).

Parola, anahtar ve kişisel veri kartta YOKTUR (e-postalar uydurma `example.com` adresleridir).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.rls import tenant_transaction
from app.db.session import create_engine, create_sessionmaker
from app.models import CargoTariffRecord, ServiceFeeEstimateRecord
from app.profit import ProfitSettings
from app.profit.enums import Source, WarningCode
from app.profit.money import rnd
from app.profit.results import LineResult, ProductTotals
from app.services import profit_views as views
from app.services.profit_report import PeriodReport, period_profit
from app.services.profit_settings import SettingsBundle, load_profit_settings, to_profit_settings
from app.tools.demo_data import (
    EPOCH_DAY,
    INFO_CARD_SERVICE_FEE,
    INFO_CARD_TARIFF,
    INFO_CARD_TARIFF_AFTER_G3,
    SEED_VERSION,
)
from app.tools.seed_demo import SeededAccount, SeedResult

PERIOD_DAYS = 30
BADGES = {
    "net_profit": "Zarar",
    "known_expenses": "Bilinen giderlerle bile zarar",
    "contribution_before_cost": "Maliyet girilmese de zarar",
}
SOURCE_LABELS = {
    Source.ACTUAL: "Kesin",
    Source.ACTUAL_ALLOCATED: "Kesin",
    Source.ESTIMATED: "Tahmini",
    Source.ALLOCATED_ESTIMATE: "Tahmini",
    Source.USER: "Girdiğiniz",
    Source.MATCHED: "Eşleşen",
    Source.MISSING: "Eksik",
    Source.NONE: "Yok",
}
# Panelin uyarılar sayfasındaki dört kart ve ilgili kodlar (apps/web/src/lib/profit/alerts.ts).
ALERT_CARDS: tuple[tuple[str, WarningCode], ...] = (
    ("Zarar eden satışlar", WarningCode.LOSS),
    ("Beklenmeyen kesintiler", WarningCode.UNEXPECTED_DEDUCTION),
    ("Ürün maliyeti eksik", WarningCode.MISSING_COST),
    ("Kargo tarifesi eksik", WarningCode.CARGO_TARIFF_MISSING),
)


@dataclass(frozen=True, slots=True)
class LossProductFacts:
    barcode: str
    title: str | None
    reason: str
    badge: str
    value: Decimal  # sıralama değeri: net kâr, yoksa bilinen giderlerle kâr
    net_profit: Decimal | None
    known_profit: Decimal
    quantity: int
    net_sales: Decimal
    expenses: tuple[tuple[str, Decimal | None], ...]
    top_expense_excl_cost: str


@dataclass(frozen=True, slots=True)
class UnexpectedFacts:
    order_number: str
    difference: Decimal | None
    threshold: Decimal | None
    default_desi_used: bool | None
    breakdown: tuple[tuple[str, Decimal | None, Decimal | None, bool, Decimal | None], ...]


@dataclass(frozen=True, slots=True)
class OrderLineFacts:
    barcode: str
    title: str | None
    status: str
    quantity: int
    refunded_quantity: int
    pending_refund_quantity: int
    rows: tuple[tuple[str, Decimal | None, str], ...]  # (kalem, tutar KDV hariç, kaynak etiketi)
    net_profit: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OrderFacts:
    number: str
    lines: tuple[OrderLineFacts, ...]
    net_profit: Decimal | None
    known_expenses_profit: Decimal


@dataclass(slots=True)
class AccountFacts:
    """Bir hesabın cevap kartı verisi (testler bu değerleri API yanıtlarıyla karşılaştırır)."""

    key: str
    title: str
    email: str
    seller_id: str
    start: date
    end: date
    order_count: int
    line_count: int
    period_net_profit: Decimal | None
    period_known_profit: Decimal
    net_profit_partial: bool
    missing_cost_lines: int
    missing_shipping_lines: int
    missing_fee_lines: int
    full_lines_count: int
    full_lines_net_profit: Decimal
    loss_products: list[LossProductFacts] = field(default_factory=list)
    cost_missing_products: list[str] = field(default_factory=list)
    awaiting_orders: list[str] = field(default_factory=list)
    unexpected: list[UnexpectedFacts] = field(default_factory=list)
    alert_counts: dict[str, int] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    multi_order: OrderFacts | None = None
    after_g2: tuple[Decimal | None, bool] | None = None  # (dönem net kârı, kısmi mi)
    after_g3: tuple[Decimal | None, bool] | None = None


def period_for(as_of: date) -> tuple[date, date]:
    return as_of - timedelta(days=PERIOD_DAYS - 1), as_of


def _info_card_settings(tariff: tuple[tuple[Decimal, Decimal], ...]) -> ProfitSettings:
    """Bilgi kartındaki değerleri uygulamanın kendi dönüşüm yoluyla (KDV dahil -> hariç) motor ayarına çevirir."""
    record = CargoTariffRecord(
        agreement="trendyol",
        carrier="Trendyol Express",
        valid_from=EPOCH_DAY,
        price_includes_vat=True,
        brackets=[{"max_desi": format(d, "f"), "price": format(p, "f")} for d, p in tariff],
    )
    fee = ServiceFeeEstimateRecord(
        valid_from=EPOCH_DAY, amount=INFO_CARD_SERVICE_FEE, amount_includes_vat=True
    )
    return to_profit_settings(
        SettingsBundle(default_desi=None, revision=0, tariffs=(record,), fees=(fee,), expenses=())
    )


async def _report(
    sessions: async_sessionmaker[AsyncSession],
    acc: SeededAccount,
    start: date,
    end: date,
    settings: ProfitSettings | None = None,
) -> tuple[PeriodReport, dict[str, str | None]]:
    async with tenant_transaction(sessions, acc.tenant_id) as db:
        use = (
            settings
            if settings is not None
            else (await load_profit_settings(db, acc.tenant_id, acc.account_id)).settings
        )
        report = await period_profit(db, acc.tenant_id, acc.account_id, start, end, use)
        barcodes = sorted({line.barcode for line in report.result.lines})
        titles = await views.product_titles(db, acc.tenant_id, acc.account_id, barcodes)
    return report, titles


def _expenses(t: ProductTotals) -> tuple[tuple[str, Decimal | None], ...]:
    return (
        ("Ürün maliyeti", t.product_cost),
        ("Komisyon", t.commission),
        ("Kargo (gönderi)", t.shipping_outbound),
        ("Kargo (iade)", t.shipping_return),
        ("Platform hizmet bedeli", t.platform_service_fee),
        ("Ceza", t.penalty),
        ("Değişken giderler", t.variable_expenses),
        ("Reklam", t.advertising_spend),
    )


def _top_excl_cost(t: ProductTotals) -> str:
    candidates = [(n, v) for n, v in _expenses(t)[1:] if v is not None]
    return max(candidates, key=lambda item: item[1])[0] if candidates else "-"


def _line_facts(line: LineResult, titles: dict[str, str | None]) -> OrderLineFacts:
    i, s = line.items, line.sources
    rows: tuple[tuple[str, Decimal | None, str], ...] = (
        ("Net satış", i.net_sales_excl_vat, SOURCE_LABELS[s.sales]),
        ("Ürün maliyeti", i.product_cost, SOURCE_LABELS[s.product_cost]),
        ("Komisyon", i.commission, SOURCE_LABELS[s.commission]),
        ("Kargo (gönderi)", i.shipping_outbound, SOURCE_LABELS[s.shipping_outbound]),
        ("Kargo (iade)", i.shipping_return, SOURCE_LABELS[s.shipping_return]),
        ("Platform hizmet bedeli", i.platform_service_fee, SOURCE_LABELS[s.platform_service_fee]),
        ("Ceza", i.penalty, SOURCE_LABELS[s.penalty]),
        ("Değişken giderler", i.variable_expenses, SOURCE_LABELS[s.variable_expenses]),
        ("Reklam", i.advertising, SOURCE_LABELS[s.advertising]),
    )
    return OrderLineFacts(
        barcode=line.barcode,
        title=titles.get(line.barcode),
        status=line.status.value,
        quantity=line.quantity,
        refunded_quantity=line.refunded_quantity,
        pending_refund_quantity=line.pending_refund_quantity,
        rows=rows,
        net_profit=i.net_profit,
        warnings=tuple(w.value for w in line.warnings),
    )


def facts_from_report(
    acc: SeededAccount, report: PeriodReport, titles: dict[str, str | None], start: date, end: date
) -> AccountFacts:
    """Rapor ve görünüm işlevlerinden (API ile aynı) hesabın cevap verisi."""
    t = report.totals
    rows = views.build_product_rows(report.result)
    losses = []
    for row in rows:
        if row.loss_reason is None:
            continue
        p = row.totals
        value = p.net_profit if p.net_profit is not None else p.known_expenses_profit
        losses.append(
            LossProductFacts(
                barcode=p.barcode,
                title=titles.get(p.barcode),
                reason=row.loss_reason,
                badge=BADGES[row.loss_reason],
                value=value,
                net_profit=p.net_profit,
                known_profit=p.known_expenses_profit,
                quantity=p.quantity,
                net_sales=p.net_sales_excl_vat,
                expenses=_expenses(p),
                top_expense_excl_cost=_top_excl_cost(p),
            )
        )
    losses.sort(key=lambda f: (f.value, f.barcode))
    orders = views.build_order_rows(report.result)
    alerts = views.build_alerts(report.result)
    unexpected = [
        UnexpectedFacts(
            a.order_number or "",
            a.difference,
            a.threshold,
            a.default_desi_used,
            tuple((b.item, b.estimated, b.actual, b.compared, b.difference) for b in (a.breakdown or ())),
        )
        for a in alerts
        if a.code is WarningCode.UNEXPECTED_DEDUCTION
    ]
    unexpected.sort(key=lambda f: f.order_number)
    multi_number = acc.data.roles.get("multi_order")
    multi: OrderFacts | None = None
    if multi_number is not None:
        lines = views.sort_lines(line for line in report.result.lines if line.order_number == multi_number)
        totals = views.order_totals(lines)
        multi = OrderFacts(
            multi_number,
            tuple(_line_facts(line, titles) for line in lines),
            totals.net_profit,
            totals.known_expenses_profit,
        )
    full = t.full_lines
    return AccountFacts(
        key=acc.data.key,
        title=acc.data.title,
        email=acc.email,
        seller_id=acc.seller_id,
        start=start,
        end=end,
        order_count=t.order_count,
        line_count=t.line_count,
        period_net_profit=t.period_net_profit,
        period_known_profit=t.period_known_expenses_profit,
        net_profit_partial=t.net_profit_partial,
        missing_cost_lines=t.missing_line_counts.product_cost,
        missing_shipping_lines=t.missing_line_counts.outbound_shipping,
        missing_fee_lines=t.missing_line_counts.platform_service_fee,
        full_lines_count=full.line_count,
        full_lines_net_profit=full.net_profit,
        loss_products=losses,
        cost_missing_products=sorted(r.totals.barcode for r in rows if r.totals.cost_missing),
        awaiting_orders=sorted(o.order_number for o in orders if o.awaiting_payout),
        unexpected=unexpected,
        alert_counts={c.value: n for c, n in views.alert_counts(alerts).items()},
        roles=dict(acc.data.roles),
        multi_order=multi,
    )


async def compute_facts(
    sessions: async_sessionmaker[AsyncSession], accounts: list[SeededAccount], as_of: date
) -> list[AccountFacts]:
    start, end = period_for(as_of)
    out: list[AccountFacts] = []
    for acc in accounts:
        if acc.data.key == "a":
            # Hesap A: tohumlanmış ("ayarsız") durum esas alınır; katılımcı ayar girdikten sonra DB değişir.
            report, titles = await _report(sessions, acc, start, end, ProfitSettings())
            facts = facts_from_report(acc, report, titles, start, end)
            g2, _ = await _report(sessions, acc, start, end, _info_card_settings(INFO_CARD_TARIFF))
            g3, _ = await _report(sessions, acc, start, end, _info_card_settings(INFO_CARD_TARIFF_AFTER_G3))
            facts.after_g2 = (g2.totals.period_net_profit, g2.totals.net_profit_partial)
            facts.after_g3 = (g3.totals.period_net_profit, g3.totals.net_profit_partial)
        else:
            report, titles = await _report(sessions, acc, start, end)
            facts = facts_from_report(acc, report, titles, start, end)
        out.append(facts)
    return out


# ------------------------------------------------------------------------------------------- biçim


def tl(value: Decimal | None) -> str:
    """Türkçe para biçimi (1.234,56 ₺); None = hesaplanamadı."""
    if value is None:
        return "hesaplanamadı"
    text = f"{rnd(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} ₺"


def dash(value: Decimal | None) -> str:
    """Hesaplanamayan / karşılaştırmaya girmeyen değer için kısa çizgi."""
    return "-" if value is None else tl(value)


def pct(part: Decimal, whole: Decimal) -> str:
    return f"%{rnd(part / whole * 100):.2f}".replace(".", ",")


_ITEM_NAMES = {
    "commission": "Komisyon",
    "outbound_shipping": "Kargo (gönderi)",
    "platform_service_fee": "Platform hizmet bedeli",
}


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _name(title: str | None, barcode: str) -> str:
    return f"{title} (`{barcode}`)" if title else f"`{barcode}`"


def render_card(facts: list[AccountFacts], as_of: date, instance: int) -> str:
    a = next((f for f in facts if f.key == "a"), None)
    bs = [f for f in facts if f.key.startswith("b")]
    start, end = period_for(as_of)
    out: list[str] = [
        "# Demo doğru cevap kartı (moderatör)",
        "",
        "> Bu dosya `make seed-demo` ile ÜRETİLİR; rakamlar gerçek kâr motorundan ve rapor servislerinden gelir, "
        "elle yazılmaz. Elle düzenlemeyin, tohumu yeniden çalıştırın.",
        "",
        f"- Tohum sürümü: **{SEED_VERSION}**",
        f"- Veri tarihi (`as_of`): **{as_of.isoformat()}**, oturum no: **{instance}**",
        f'- Dönem (panelde "30 gün", uçlar dahil): **{start.isoformat()} - {end.isoformat()}**',
        "- Tutarlar KDV hariçtir (panelin kalem dökümü gibi). Veri `as_of` gününden en çok 27 gün geriye uzanır: "
        'tohumdan sonraki 2 gün içinde "30 gün" aynı rakamları verir; sonra betiği yeniden çalıştırın.',
        "- Parolalar bu dosyada YOKTUR; betik bunları yalnız çalıştığı anda ekrana yazar.",
        "",
        "## Hesaplar",
        "",
    ]
    out += _table(
        ["Hesap", "E-posta (uydurma)", "Satıcı no (uydurma)"],
        [[f.title, f.email, f.seller_id] for f in facts],
    )
    out.append("")
    if a is not None:
        out += _render_a(a)
    for b in bs:
        out += _render_b(b)
    out += _render_footer()
    return "\n".join(out) + "\n"


def _full_lines(f: AccountFacts) -> str:
    if not f.full_lines_count:
        return "yok (hiçbir satır eksiksiz değil)"
    return f"{tl(f.full_lines_net_profit)} ({f.full_lines_count} satır)"


def _render_a(a: AccountFacts) -> list[str]:
    out = [
        f"## {a.title}: G1, G2, G3",
        "",
        f"Dönem {a.start.isoformat()} - {a.end.isoformat()}; {a.order_count} sipariş, "
        f"{a.line_count} aktif satır. Ürün maliyetleri dolu; kargo tarifesi, hizmet bedeli ve varsayılan desi YOK.",
        "",
    ]
    out += ["### G1 Özet ekranına ilk bakış", ""]
    out += _table(
        ["Ekranda", "Doğru değer"],
        [
            [
                "Dönem net kârı",
                "hesaplanamadı (net kâr kısmi)" if a.period_net_profit is None else tl(a.period_net_profit),
            ],
            [
                "Eksik giderler hariç dönem kârı (kargo ve hizmet bedeli hariç)",
                f"**{tl(a.period_known_profit)}**",
            ],
            ["Kargosu eksik satır sayısı", str(a.missing_shipping_lines)],
            ["Hizmet bedeli eksik satır sayısı", str(a.missing_fee_lines)],
            ["Eksiksiz satırların net kârı", _full_lines(a)],
            ["Zarar ettiren ürün sayısı", str(len(a.loss_products))],
        ],
    )
    out += [
        "",
        "Doğru okuma: bilinen rakam NET KÂR DEĞİLDİR; kargo ve hizmet bedeli düşülünce azalır. "
        "Katılımcı kargo tarifesini ve hizmet bedelini girmesi gerektiğini söyler.",
        "",
        "### G2 İlk kurulum (bilgi kartı girildikten sonra)",
        "",
        "Bilgi kartı: Trendyol anlaşmalı, Trendyol Express; 0-2 desi 50 TL, 3-5 desi 60 TL, 6-10 desi 80 TL "
        "(KDV dahil); hizmet bedeli sipariş başına 10 TL (KDV dahil). Başlangıç tarihi dönemin ilk gününden önce olmalı.",
        "",
    ]
    if a.after_g2 is not None:
        net, partial = a.after_g2
        out += [
            f"- Doğru giriş sonrası dönem net kârı: **{tl(net)}** (kısmi mi: {'evet' if partial else 'hayır'}).",
            "",
        ]
    out += ["### G3 Geçmişi etkileyen değişiklik (3-5 desi 60 TL -> 65 TL)", ""]
    if a.after_g3 is not None and a.after_g2 is not None:
        n3, p3 = a.after_g3
        n2 = a.after_g2[0]
        delta = None if n3 is None or n2 is None else n3 - n2
        out += [
            f"- Değişiklik sonrası dönem net kârı: **{tl(n3)}** (kısmi mi: {'evet' if p3 else 'hayır'}); "
            f"fark: {tl(delta)}.",
            "- Pencerenin doğru anlatımı: geçmiş siparişlerin kâr rakamları değişir, eski rakamlı raporlar farklı "
            "olabilir, önceki değer ayar geçmişinde saklanır.",
            "",
        ]
    return out


def _render_b(b: AccountFacts) -> list[str]:
    tag = b.title
    out = [f"## {tag}: G4 - G8", ""]
    out += [
        f"Dönem {b.start.isoformat()} - {b.end.isoformat()}; {b.order_count} sipariş, {b.line_count} aktif satır.",
        "",
        "Not: Bu hesapta maliyeti girilmemiş iki ürün ve kendi kargo anlaşmasıyla giden (tarifesi tanımsız) bir ürün "
        'bulunduğundan DÖNEM net kârı kısmidir; panelde "Eksik giderler hariç dönem kârı" görünür (plan §7.1 şartnamesi).',
        "",
    ]
    out += _table(
        ["Dönem özeti", "Doğru değer"],
        [
            [
                "Dönem net kârı",
                "hesaplanamadı (kısmi)" if b.period_net_profit is None else tl(b.period_net_profit),
            ],
            ["Eksik giderler hariç dönem kârı", f"**{tl(b.period_known_profit)}**"],
            ["Eksiksiz satırların net kârı", _full_lines(b)],
            [
                "Maliyeti eksik satır / kargosu eksik satır",
                f"{b.missing_cost_lines} / {b.missing_shipping_lines}",
            ],
        ],
    )
    out += ["", "### G4 / G8a: en çok zarar ettiren ürün", ""]
    if b.loss_products:
        top = b.loss_products[0]
        out += [
            f"**Doğru ürün: {_name(top.title, top.barcode)}**; zarar: **{tl(top.value)}** "
            f'(rozet: "{top.badge}"), {top.quantity} adet.',
            f"Neden: ürün maliyeti dışındaki en büyük gider kalemi **{top.top_expense_excl_cost}**; "
            "kalem dökümüne aşağıdaki tablodan bakılır.",
            "",
        ]
        out += _table(
            ["Gider kalemi (KDV hariç, toplam)", "Tutar", "Net satışa oranı"],
            [
                [name, tl(v), "-" if v is None or not top.net_sales else pct(v, top.net_sales)]
                for name, v in top.expenses
            ]
            + [["Net satış", tl(top.net_sales), "%100,00"]],
        )
        out += ["", "Zarar rozetleri (üçü birbirinden farklıdır):", ""]
        out += _table(
            ["Ürün", "Rozet", "Zarar (net kâr ya da bilinen giderlerle kâr)", "Net kâr"],
            [[_name(p.title, p.barcode), p.badge, tl(p.value), tl(p.net_profit)] for p in b.loss_products],
        )
        out.append("")
    out += ["Maliyeti girilmemiş ürünler: " + ", ".join(f"`{x}`" for x in b.cost_missing_products), ""]

    out += ["### G5: çok ürünlü sipariş, kalem dökümü", ""]
    if b.multi_order is not None:
        out += [
            "İade: ekstrede iade satırı (Return) vardır ama iade kaydı (claim) henüz gelmemiştir; panelde "
            '"İade kaydı bekleniyor." notu görünür. Motor ürün maliyetini ihtiyatla gider bırakır (docs/12 K10).',
            "",
        ]
        m = b.multi_order
        out += [
            f"Sipariş no (tam yazılmalı): **`{m.number}`**. Sipariş toplamı net kâr: {tl(m.net_profit)}; "
            f"eksik giderler hariç kâr: {tl(m.known_expenses_profit)}.",
            "",
        ]
        for line in m.lines:
            out += [
                f"**{_name(line.title, line.barcode)}**: {line.quantity} adet, {line.refunded_quantity} adedi iade"
                + (
                    f", iade kaydı bekleyen adet: {line.pending_refund_quantity}"
                    if line.pending_refund_quantity
                    else ""
                )
                + f"; durum: {line.status}; net kâr: {tl(line.net_profit)}"
                + ("; uyarılar: " + ", ".join(line.warnings) if line.warnings else ""),
                "",
            ]
            out += _table(["Kalem", "Tutar (KDV hariç)", "Kaynak"], [[n, tl(v), s] for n, v, s in line.rows])
            out.append("")
    out += ["### G6 / G8b: ekstresi gelmeyen ve beklenmeyen kesintili siparişler", ""]
    out += [
        f'- "Ekstresi gelmedi" sipariş sayısı: **{len(b.awaiting_orders)}**',
        "  Sipariş no: " + ", ".join(f"`{n}`" for n in b.awaiting_orders),
    ]
    old = sorted(v for k, v in b.roles.items() if k.startswith("old_awaiting"))
    if old:
        out.append(
            "  Bunlardan kasıtlı olarak eski (19 gün ve daha eski) olanlar: "
            + ", ".join(f"`{n}`" for n in old)
        )
    out += [f'- "Beklenmeyen kesinti" sipariş sayısı: **{len(b.unexpected)}**', ""]
    for u in b.unexpected:
        out += [
            f"**`{u.order_number}`**: toplam fark {tl(u.difference)} (eşik {tl(u.threshold)})"
            + ("; kargo tahmini varsayılan desiyle yapıldı" if u.default_desi_used else ""),
            "",
        ]
        out += _table(
            ["Kalem", "Tahmini", "Kesin", "Farka girdi mi", "Fark"],
            [
                [_ITEM_NAMES.get(n, n), dash(e), dash(a2), "evet" if c else "hayır", dash(d)]
                for n, e, a2, c, d in u.breakdown
            ],
        )
        out.append("")
    out += [
        "### G7: uyarılar sayfası",
        "",
        "Dört kart ve satır sayıları (motorun ürettiği uyarılar, iptal satırlar hariç):",
        "",
    ]
    out += _table(
        ["Kart", "Kod", "Sayı"],
        [[title, f"`{code.value}`", str(b.alert_counts.get(code.value, 0))] for title, code in ALERT_CARDS],
    )
    out += ["", "Tüm kodlar: " + ", ".join(f"`{k}`: {v}" for k, v in sorted(b.alert_counts.items())), ""]
    return out


def _render_footer() -> list[str]:
    return [
        "## Notlar",
        "",
        "- Bu karttaki iki teknik varsayım (G2: ilk girişte onay penceresi çıkmaz; G3: mevcut tarifeyi düzenlemek geçmişi "
        "etkileyen onayı tetikler) motorun değil ayar servisinin davranışıdır; sınama testlerde vardır, yine de "
        "staging'de bir kez deneyin.",
        "- Her katılımcı için temiz Hesap A gerekir (G2 ve G3 ayarı değiştirir ve silinemez): "
        "`--instance N` ile yeni bir oturum üretin.",
        "- Bu veri uydurmadır; hiçbir gerçek kişi, mağaza ya da müşteri bilgisi yoktur.",
    ]


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


async def write_card(settings: Settings, result: SeedResult, path: Path) -> list[AccountFacts]:
    """Kartı hesaplar ve dosyaya yazar (parolasız). Hesaplanan veriyi döndürür."""
    assert settings.database_url
    engine = create_engine(settings.database_url, pool_size=2, max_overflow=0)
    try:
        facts = await compute_facts(create_sessionmaker(engine), result.accounts, result.options.as_of)
    finally:
        await engine.dispose()
    text = render_card(facts, result.options.as_of, result.options.instance)
    await asyncio.to_thread(_write_text, path, text)
    return facts


__all__ = ["AccountFacts", "compute_facts", "period_for", "render_card", "write_card"]
