"""Kâr raporu görünüm katmanı (DB'siz): dönem çözümü, imleç, sıralama, uyarılar ve şema-motor uyumu.

Altın senaryolar saf motordan geçirilir; böylece görünüm hesapları (toplam gider, durum etiketi, uyarı
listesi) ve Pydantic şemaları motorun KABLO çıktısıyla (`schema_v1.to_wire`) karşılaştırılır.
"""

from __future__ import annotations

import base64
import dataclasses
import json
from datetime import date
from decimal import Decimal
from itertools import pairwise
from itertools import product as cartesian
from typing import Any, get_args
from uuid import UUID

import pytest

from app.api.v1 import profit_schemas as schemas
from app.profit import ProfitResult, calculate_profit
from app.profit import results as engine_results
from app.profit.enums import Status, WarningCode
from app.profit.schema_v1 import parse_input, to_wire
from app.services import profit_views as views
from tests.test_profit_golden import GOLDEN_FILES

D = Decimal
TODAY = date(2026, 11, 8)


def golden_result(prefix: str) -> ProfitResult:
    path = next(p for p in GOLDEN_FILES if p.stem.startswith(prefix))
    return calculate_profit(parse_input(json.loads(path.read_text(encoding="utf-8"))["girdi"]))


def all_results() -> list[tuple[str, ProfitResult]]:
    return [
        (p.stem[:3], calculate_profit(parse_input(json.loads(p.read_text(encoding="utf-8"))["girdi"])))
        for p in GOLDEN_FILES
    ]


# --- dönem çözümü ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "name", "expected"),
    [
        (None, None, None, (date(2026, 10, 10), TODAY)),  # varsayılan: 30 gün, bugün dahil
        (None, None, "today", (TODAY, TODAY)),
        (None, None, "7d", (date(2026, 11, 2), TODAY)),
        (None, None, "30d", (date(2026, 10, 10), TODAY)),
        ("2026-10-01", "2026-10-31", None, (date(2026, 10, 1), date(2026, 10, 31))),
        ("2026-10-01", "2026-10-01", None, (date(2026, 10, 1), date(2026, 10, 1))),
        ("2026-08-01", "2026-10-31", None, (date(2026, 8, 1), date(2026, 10, 31))),  # tam 92 gün
    ],
)
def test_resolve_period_valid(start: Any, end: Any, name: Any, expected: Any) -> None:
    assert views.resolve_period(start, end, name, TODAY) == expected


def test_resolve_period_without_default_returns_none() -> None:
    assert views.resolve_period(None, None, None, TODAY, default_range=None) is None
    assert views.resolve_period(None, None, "today", TODAY, default_range=None) == (TODAY, TODAY)


@pytest.mark.parametrize(
    ("start", "end", "name", "field", "code"),
    [
        ("2026-10-01", None, None, "end", "period_incomplete"),
        (None, "2026-10-01", None, "start", "period_incomplete"),
        ("2026-10-01", "2026-10-02", "7d", "range", "period_conflict"),
        (None, "2026-10-02", "7d", "range", "period_conflict"),
        ("2026-10-05", "2026-10-04", None, "end", "period_reversed"),
        ("2026-08-01", "2026-11-01", None, "end", "period_too_long"),  # 93 gün
        ("2026-1-5", "2026-10-04", None, "start", "date_invalid"),
        ("2026-02-30", "2026-03-04", None, "start", "date_invalid"),
        ("٢٠٢٦-١٠-٠١", "2026-10-04", None, "start", "date_invalid"),  # Arap-Hint rakamları
        ("2026-10-01", "2026-10-0٤", None, "end", "date_invalid"),
        ("1999-12-31", "2000-01-02", None, "start", "date_out_of_range"),
        ("2100-12-30", "2101-01-02", None, "end", "date_out_of_range"),
    ],
)
def test_resolve_period_invalid(start: Any, end: Any, name: Any, field: str, code: str) -> None:
    with pytest.raises(views.PeriodError) as caught:
        views.resolve_period(start, end, name, TODAY)
    assert (caught.value.field, caught.value.code) == (field, code)
    assert "2026" not in caught.value.message  # girdi değeri iletiye konmaz


# --- imleç --------------------------------------------------------------------------------------------


CODEC = views.CursorCodec(b"0123456789abcdef0123456789abcdef", UUID(int=1), UUID(int=2))


def test_cursor_round_trip_and_rejections() -> None:
    """Ayrıntılı mühür testleri (kiracı/hesap bağlama, kurcalama) `test_denetim_s4_kapanis.py` içindedir."""
    cursor = CODEC.encode("fp", ["0", "12.50", "8681000000011"])
    assert CODEC.decode(cursor, "fp", 3) == ["0", "12.50", "8681000000011"]
    assert "=" not in cursor  # URL güvenli, dolgusuz
    bad = [
        (cursor, "other", 3),  # başka sorgunun imleci
        (cursor, "fp", 2),  # parça sayısı uyuşmuyor
        ("!!!", "fp", 3),  # base64 değil
        (CODEC.encode("fp", ["x" * 201]), "fp", 1),  # parça çok uzun
    ]
    for value, fp, size in bad:
        with pytest.raises(views.CursorError):
            CODEC.decode(value, fp, size)
    for raw in (b"[1,2]", b"not json", b'{"f":"fp","k":"x"}', b'{"f":"fp","k":[1,2,3]}'):
        forged = base64.urlsafe_b64encode(raw).decode().rstrip("=")  # mühürsüz: etiket doğrulanamaz
        with pytest.raises(views.CursorError):
            CODEC.decode(forged, "fp", 3)


# --- ürün listesi: sıralama, süzgeç, sayfalama ----------------------------------------------------------


def synthetic_rows() -> list[views.ProductRow]:
    """11 ürün toplamı: eşit değerler (barkod ayırıcı), maliyeti eksik ve satışsız ürünler."""
    base = golden_result("G01").products[0]
    rows = []
    spec = [
        ("B05", "10.00", "10.00", 3),
        ("B02", "10.00", "10.00", 3),  # B05 ile eşit: barkod artan ayırır
        ("B09", "-4.00", "-8.00", 1),
        ("B01", "25.50", "30.00", 7),
        ("B07", None, None, 2),  # maliyet eksik: net kâr ve marj yok
        ("B03", "0.00", None, 0),  # net satış 0: marj yok
        ("B04", "-4.00", "-8.00", 5),  # B09 ile eşit değer
        ("B06", None, None, 2),
        ("B08", "10.00", "5.00", 3),
        ("B10", "99.99", "50.00", 9),
        ("B11", "-0.01", "-0.02", 4),
    ]
    for barcode, profit, margin, qty in spec:
        totals = dataclasses.replace(
            base,
            barcode=barcode,
            net_profit=None if profit is None else D(profit),
            net_margin_percent=None if margin is None else D(margin),
            net_sales_excl_vat=D(qty) * D("10.00"),
            quantity=qty,
            cost_missing=profit is None,
        )
        rows.append(views.ProductRow(totals, None, "estimated", qty, 0, 0))
    return rows


@pytest.mark.parametrize(("sort", "order"), list(cartesian(get_args(views.SortField), ("asc", "desc"))))
def test_order_is_total_stable_and_puts_unknowns_last(sort: Any, order: Any) -> None:
    rows = synthetic_rows()
    ordered = views.order_rows(rows, sort, order)
    assert sorted(r.totals.barcode for r in ordered) == sorted(r.totals.barcode for r in rows)
    values = [views.sort_value(r, sort) for r in ordered]
    known = [v for v in values if v is not None]
    assert values[: len(known)] == known and all(v is None for v in values[len(known) :])  # None sonda
    assert known == sorted(known, reverse=order == "desc")
    for a, b in pairwise(ordered):  # eşit değerde barkod HER ZAMAN artan
        if views.sort_value(a, sort) == views.sort_value(b, sort):
            assert a.totals.barcode < b.totals.barcode
    # girdi sırası sonucu etkilemez (kararlılık)
    assert views.order_rows(list(reversed(rows)), sort, order) == ordered


@pytest.mark.parametrize(("sort", "order"), list(cartesian(get_args(views.SortField), ("asc", "desc"))))
@pytest.mark.parametrize("limit", [1, 3, 4, 100])
def test_paging_walks_every_row_exactly_once_in_order(sort: Any, order: Any, limit: int) -> None:
    rows = synthetic_rows()
    expected = [r.totals.barcode for r in views.order_rows(rows, sort, order)]
    seen: list[str] = []
    cursor = None
    for _ in range(50):
        page, cursor = views.product_page(rows, sort, order, limit, cursor, "fp", CODEC)
        seen += [r.totals.barcode for r in page]
        if cursor is None:
            break
    assert seen == expected


def test_paging_survives_rows_changing_between_pages() -> None:
    """Keyset imleci: araya yeni ürün girse bile görülen ürün tekrarlanmaz, kalan sırayla devam eder."""
    rows = synthetic_rows()
    first, cursor = views.product_page(rows, "sales", "desc", 3, None, "fp", CODEC)
    shrunk = [r for r in rows if r.totals.barcode not in {x.totals.barcode for x in first[:1]}]
    second, _ = views.product_page(shrunk, "sales", "desc", 3, cursor, "fp", CODEC)
    assert not {r.totals.barcode for r in first} & {r.totals.barcode for r in second}


@pytest.mark.parametrize(
    "forged",
    [
        ["2", "1", "B1"],  # bayrak geçersiz
        ["0", "abc", "B1"],  # sayı değil
        ["0", "NaN", "B1"],  # sonlu değil
        ["0", "Infinity", "B1"],
    ],
)
def test_product_cursor_with_forged_value_is_rejected(forged: list[str]) -> None:
    with pytest.raises(views.CursorError):
        views.product_page(synthetic_rows(), "net_profit", "asc", 5, CODEC.encode("fp", forged), "fp", CODEC)


def test_filters() -> None:
    rows = synthetic_rows()
    assert {r.totals.barcode for r in views.filter_rows(rows, "loss")} == {"B09", "B04", "B11"}
    assert {r.totals.barcode for r in views.filter_rows(rows, "missing_cost")} == {"B07", "B06"}
    assert len(views.filter_rows(rows, "all")) == len(rows)


# --- altın senaryolarla görünüm doğruluğu -----------------------------------------------------------------


def test_product_total_expenses_equal_net_sales_minus_net_profit_in_every_golden_scenario() -> None:
    checked = 0
    for scenario, result in all_results():
        for row in views.build_product_rows(result):
            t = row.totals
            if t.net_profit is None:
                assert row.total_expenses is None and t.cost_missing, scenario
                continue
            assert row.total_expenses is not None
            assert t.net_sales_excl_vat - row.total_expenses == t.net_profit, (scenario, t.barcode)
            checked += 1
    assert checked >= 40  # tarama gerçekten çalıştı


def test_basis_labels_follow_line_statuses() -> None:
    labels: dict[str, int] = {}
    for scenario, result in all_results():
        for row in views.build_product_rows(result):
            statuses = {line.status for line in result.lines if line.barcode == row.totals.barcode} - {
                Status.CANCELLED
            }
            if not statuses:
                expected = "none"
            elif statuses == {Status.ESTIMATED}:
                expected = "estimated"
            elif Status.ESTIMATED not in statuses:
                expected = "settled"
            else:
                expected = "mixed"
            assert row.basis == expected, (scenario, row.totals.barcode)
            labels[row.basis] = labels.get(row.basis, 0) + 1
            assert row.estimated_lines + row.settled_lines + row.adjusted_lines == sum(
                1
                for line in result.lines
                if line.barcode == row.totals.barcode and line.status != Status.CANCELLED
            )
    assert {"estimated", "settled"} <= set(labels)


def test_basis_helper_branches() -> None:
    assert [views._basis(*a) for a in ((0, 0, 0), (2, 0, 0), (0, 1, 1), (1, 0, 1))] == [
        "none",
        "estimated",
        "settled",
        "mixed",
    ]


def test_alerts_come_only_from_engine_warnings_and_carry_amounts() -> None:
    g13 = views.build_alerts(golden_result("G13"))
    unexpected = [a for a in g13 if a.code is WarningCode.UNEXPECTED_DEDUCTION]
    assert len(unexpected) == 1 and unexpected[0].scope == "line"
    assert unexpected[0].difference == D("15.00") and unexpected[0].threshold == D("5.37")  # docs/12 §6
    # Her uyarı motorun satır ya da dönem uyarısıdır (uydurma yok), iptal satırı uyarı üretmez.
    for scenario, result in all_results():
        allowed: set[tuple[WarningCode, int | str]] = {(code, "period") for code in result.period.warnings}
        allowed |= {
            (code, line.line_id)
            for line in result.lines
            for code in line.warnings
            if line.status != Status.CANCELLED
        }
        got = {(a.code, "period" if a.scope == "period" else a.line_id) for a in views.build_alerts(result)}
        assert got == allowed, scenario
    loss = [a for a in views.build_alerts(golden_result("G12")) if a.code is WarningCode.LOSS]
    assert all(a.net_profit is not None and a.net_profit < 0 for a in loss)


def test_alerts_are_sorted_deterministically_and_paged() -> None:
    alerts = views.build_alerts(golden_result("G23"))
    assert alerts == sorted(alerts, key=views._alert_key)
    walked, cursor = [], None
    for _ in range(100):
        page, cursor = views.alerts_page(alerts, 2, cursor, "fp", CODEC)
        walked += page
        if cursor is None:
            break
    assert walked == alerts
    assert sum(views.alert_counts(alerts).values()) == len(alerts)
    with pytest.raises(views.CursorError):
        views.alerts_page(alerts, 2, CODEC.encode("fp", ["x", "A", "1", "1", "1"]), "fp", CODEC)


def test_every_engine_warning_code_has_a_message_and_unavailable_codes_are_not_engine_codes() -> None:
    assert set(views.ALERT_MESSAGES) == set(WarningCode)
    engine_codes = {c.value for c in WarningCode}
    assert not {code for code, _ in views.UNAVAILABLE_ALERTS} & engine_codes


def test_lines_page_orders_and_pages_and_rejects_foreign_cursors() -> None:
    lines = list(golden_result("G23").lines)
    walked, cursor = [], None
    for _ in range(20):
        page, cursor = views.lines_page(lines, 1, cursor, "fp", CODEC)
        walked += page
        if cursor is None:
            break
    assert walked == views.sort_lines(lines) and len(walked) == len(lines)
    with pytest.raises(views.CursorError):
        views.lines_page(lines, 1, CODEC.encode("fp", ["1", "abc", "2"]), "fp", CODEC)


def test_comparison_summary_and_order_totals() -> None:
    result = golden_result("G13")
    summary = views.comparison_summary(result.lines)
    assert summary.compared_line_count == 1 and summary.difference == D("15.00")
    assert summary.actual_total - summary.estimated_total == summary.difference
    totals = views.order_totals(result.lines)
    assert totals.net_profit == sum((line.items.net_profit or D("0") for line in result.lines), D("0"))
    assert totals.net_sales_excl_vat - (totals.total_expenses or D("0")) == totals.net_profit


def test_order_totals_never_invent_a_profit_when_a_cost_is_missing() -> None:
    seen_missing = seen_known = 0
    for scenario, result in all_results():
        for number in {line.order_number for line in result.lines}:
            lines = [line for line in result.lines if line.order_number == number]
            totals = views.order_totals(lines)
            active = [line for line in lines if line.status is not Status.CANCELLED]
            assert totals.line_count == len(active), scenario
            if any(line.items.net_profit is None for line in active):
                assert (totals.net_profit, totals.total_expenses, totals.cost_missing) == (None, None, True)
                seen_missing += 1
            else:
                assert totals.net_profit is not None and not totals.cost_missing
                seen_known += 1
    assert seen_missing and seen_known


def test_status_counts_include_every_status() -> None:
    counts = views.status_counts(golden_result("G23").lines)
    assert set(counts) == {s.value for s in Status} and sum(counts.values()) == len(
        golden_result("G23").lines
    )


# --- şema <-> motor kablo adı uyumu -------------------------------------------------------------------------

PAIRS: list[tuple[type, type[schemas.WireModel]]] = [
    (engine_results.LineItems, schemas.LineItemsOut),
    (engine_results.LineVat, schemas.LineVatOut),
    (engine_results.LineCashFlow, schemas.LineCashFlowOut),
    (engine_results.LineSources, schemas.LineSourcesOut),
    (engine_results.VariableExpenseDetail, schemas.VariableExpenseDetailOut),
    (engine_results.AdDetail, schemas.AdDetailOut),
    (engine_results.LineComparison, schemas.LineComparisonOut),
    (engine_results.LineResult, schemas.LineOut),
    (engine_results.ProductTotals, schemas.ProductTotalsOut),
    (engine_results.PeriodLevelExpenses, schemas.PeriodLevelExpensesOut),
    (engine_results.PeriodCashFlow, schemas.PeriodCashFlowOut),
    (engine_results.PeriodTotals, schemas.PeriodTotalsOut),
]


@pytest.mark.parametrize(("engine", "model"), PAIRS, ids=lambda x: getattr(x, "__name__", ""))
def test_schema_fields_and_wire_names_match_the_engine(engine: type, model: type[schemas.WireModel]) -> None:
    fields = dataclasses.fields(engine)
    assert list(model.model_fields) == [f.name for f in fields]  # aynı alanlar, aynı sırada
    assert [model.model_fields[f.name].serialization_alias for f in fields] == [
        f.metadata["wire"] for f in fields
    ]


def test_schema_output_equals_engine_wire_output_in_every_golden_scenario() -> None:
    def dump(model: Any) -> Any:
        return model.model_dump(mode="json", by_alias=True)

    lines = 0
    for scenario, result in all_results():
        for line in result.lines:
            assert dump(schemas.LineOut.model_validate(line)) == to_wire(line), scenario
            lines += 1
        for product in result.products:
            assert dump(schemas.ProductTotalsOut.model_validate(product)) == to_wire(product), scenario
        assert dump(schemas.PeriodTotalsOut.model_validate(result.period)) == to_wire(result.period), scenario
    assert lines >= 41
    assert get_args(schemas.Amount)[1].return_type is str  # para JSON'da dizge; float'a hiçbir yol yoktur
