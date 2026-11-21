"""Ürün listesi `net_profit` sıralaması (denetim AD-04, DB'siz).

Ayarsız ya da yarı ayarlı hesapta net kâr çoğu üründe null'dır. Kesin zararlı ürün (net kâr null, eksik giderler
hariç kâr negatif) bilinen değeriyle sıralanır ve belirsiz null'lardan (eksik giderler hariç kâr >= 0) önce gelir;
belirsizler her yönde sonda kalır. İmleç anahtarı sıralama değerinden türediği için kararlı kalır.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.services import profit_views as views
from tests.test_report_units import golden_result

D = Decimal
CODEC = views.CursorCodec(b"0123456789abcdef0123456789abcdef", UUID(int=1), UUID(int=2))


def row(barcode: str, net: str | None, known: str) -> views.ProductRow:
    base = golden_result("G01").products[0]
    totals = dataclasses.replace(
        base,
        barcode=barcode,
        net_profit=None if net is None else D(net),
        known_expenses_profit=D(known),
        cost_missing=net is None,
    )
    return views.ProductRow(totals, None, "estimated", 1, 0, 0)


def rows() -> list[views.ProductRow]:
    return [
        row("A1", "5.00", "5.00"),  # net kârlı
        row("B1", None, "75.00"),  # belirsiz (eksik giderler hariç kâr pozitif)
        row("C1", None, "-10.00"),  # kesin zarar (net kâr null)
        row("D1", "-50.00", "-50.00"),  # net zarar (hesaplanmış)
        row("E1", None, "-30.00"),  # kesin zarar (net kâr null)
        row("F1", None, "0.00"),  # belirsiz: sıfır zarar değildir
    ]


def barcodes(items: list[views.ProductRow]) -> list[str]:
    return [r.totals.barcode for r in items]


def test_certain_loss_with_null_net_profit_precedes_uncertain_ones_in_asc() -> None:
    ordered = views.order_rows(rows(), "net_profit", "asc")
    # en çok zarar önce (bilinen değerle), sonra kârlılar, belirsizler (barkod artan) sonda
    assert barcodes(ordered) == ["D1", "E1", "C1", "A1", "B1", "F1"]


def test_uncertain_rows_stay_last_in_desc_and_certain_losses_rank_among_losses() -> None:
    ordered = views.order_rows(rows(), "net_profit", "desc")
    assert barcodes(ordered) == ["A1", "C1", "E1", "D1", "B1", "F1"]


def test_unconfigured_account_ordering_is_no_longer_barcode_order() -> None:
    """PoC (A.3): iki ürün da net kâr null; kesin zararlı olan barkoda göre sonda kalıyordu."""
    unconfigured = [row("B1", None, "75.00"), row("B2", None, "-10.00")]
    assert barcodes(views.order_rows(unconfigured, "net_profit", "asc")) == ["B2", "B1"]


def test_sort_value_uses_the_known_bound_only_for_certain_losses() -> None:
    by_code = {r.totals.barcode: views.sort_value(r, "net_profit") for r in rows()}
    assert by_code == {
        "A1": D("5.00"),
        "B1": None,
        "C1": D("-10.00"),
        "D1": D("-50.00"),
        "E1": D("-30.00"),
        "F1": None,
    }
    # diğer sıralama alanları değişmedi
    assert (
        views.sort_value(row("X", None, "-10.00"), "net_margin")
        == row("X", None, "-10.00").totals.net_margin_percent
    )


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("limit", [1, 2, 3, 100])
def test_paging_walks_every_row_once_in_order_with_certain_losses(order: Any, limit: int) -> None:
    expected = barcodes(views.order_rows(rows(), "net_profit", order))
    seen: list[str] = []
    cursor = None
    for _ in range(20):
        page, cursor = views.product_page(rows(), "net_profit", order, limit, cursor, "fp", CODEC)
        seen += barcodes(page)
        if cursor is None:
            break
    assert seen == expected


def test_cursor_after_a_certain_loss_row_resumes_after_it() -> None:
    first, cursor = views.product_page(rows(), "net_profit", "asc", 2, None, "fp", CODEC)
    assert barcodes(first) == ["D1", "E1"] and cursor is not None
    second, _ = views.product_page(rows(), "net_profit", "asc", 10, cursor, "fp", CODEC)
    assert barcodes(second) == ["C1", "A1", "B1", "F1"]
