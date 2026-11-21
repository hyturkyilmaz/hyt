"""Elle hesaplanmış altın senaryolar (ADR-0009 §12): her senaryonun hesabı yorumda, beklenen değerler sabit.

G01-G12 elle kurulmuş motor çıktısı üzerinde; G13-G16 gerçek motor (`calculate_profit`) çıktısı üzerinde
(motor davranışına dokunulmaz, yalnız okunur).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from decimal import Decimal

import pytest

from app.alerts import (
    AlertScope,
    AlertThresholds,
    NotifyMode,
    ReturnCohort,
    RuleOutcome,
    RuleStatus,
    evaluate_ad_eats_profit,
    evaluate_loss_making_sales,
    evaluate_return_rate,
    evaluate_unexpected_deduction,
)
from app.profit import calculate_profit
from app.profit.enums import Certainty, Source, WarningCode
from app.profit.inputs import AdRecord, CostRecord
from app.profit.results import AdDetail
from tests.alerts_helpers import make_comparison, make_line, make_product, make_result
from tests.profit_helpers import data, line, order, ret, sale

D = Decimal
ACCOUNT = "0b7e5f3a-9c1d-4e2f-a6b8-123456789abc"
T = AlertThresholds()
AS_OF = date(2026, 11, 20)
RECORD = AdRecord("AD1", date(2026, 10, 1), date(2026, 10, 31), D("1.00"), False, barcode="A")

Expected = list[tuple[str, NotifyMode, dict[str, object]]]


def _ret(*cohorts: tuple[str, tuple[int, int, int, int]]) -> list[ReturnCohort]:
    return [
        ReturnCohort(barcode=b, current_lines=n_c, current_returned=x_c, base_lines=n_b, base_returned=x_b)
        for b, (x_c, n_c, x_b, n_b) in cohorts
    ]


def _ad(
    net: str, spend: str, matched: str = "0.00", unsold: str = "0.00", th: AlertThresholds = T
) -> RuleOutcome:
    details = (AdDetail("AD1", Source.MATCHED, D(matched)),) if D(matched) else ()
    result = make_result(
        (make_line("A", "1.00", warnings=(), ad_details=details),), (make_product("A", net, spend, unsold),)
    )
    return evaluate_ad_eats_profit(ACCOUNT, result, (RECORD,), th)


def _ded(*diffs: tuple[str, bool]) -> RuleOutcome:
    lines = tuple(
        make_line(
            "A",
            "10.00",
            warnings=(WarningCode.UNEXPECTED_DEDUCTION,),
            comparison=make_comparison(
                diff, "5.00", default, "0.00" if default else None, diff if default else None
            ),
            order_number=f"O{i}",
            package_id=1,
            line_id=i,
        )
        for i, (diff, default) in enumerate(diffs, start=1)
    )
    return evaluate_unexpected_deduction(ACCOUNT, make_result(lines), T)


def _loss(*nets: str, **kw: object) -> RuleOutcome:
    lines = tuple(make_line("A", n, line_id=i, **kw) for i, n in enumerate(nets, start=1))  # type: ignore[arg-type]
    return evaluate_loss_making_sales(ACCOUNT, make_result(lines), T)


GOLDEN: list[tuple[str, Callable[[], RuleOutcome], Expected]] = [
    (
        "G01 zarar: iki zarar satiri, toplam 3,00 + 4,50 = 7,50, en kotu 4,50",
        lambda: _loss("-3.00", "-4.50"),
        [
            (
                "urun:A",
                NotifyMode.NORMAL,
                {"total_loss": D("7.50"), "worst_line_loss": D("4.50"), "loss_line_count": 2},
            )
        ],
    ),
    ("G02 zarar: toplam 4,99 esik altinda", lambda: _loss("-2.49", "-2.50"), []),
    (
        "G03 zarar: toplam tam 5,00 esikte acar",
        lambda: _loss("-2.50", "-2.50"),
        [("urun:A", NotifyMode.NORMAL, {"total_loss": D("5.00")})],
    ),
    ("G04 zarar: iadeli zarar satiri (-100,00) dislanir", lambda: _loss("-100.00", refunded=1), []),
    (
        "G05 reklam: net 0,00 harcama 80,00 oncesi 80,00 pay %100 sinirda acar",
        lambda: _ad("0.00", "80.00", matched="80.00"),
        [("urun:A", NotifyMode.NORMAL, {"profit_before_ads": D("80.00"), "ad_share_percent": D("100.00")})],
    ),
    (
        "G06 reklam: net 0,01 harcama 80,00 oncesi 80,01 pay %99,99 acmaz",
        lambda: _ad("0.01", "80.00", matched="80.00"),
        [],
    ),
    (
        "G07 reklam: net 70,00 harcama 70,00 oncesi 140,00 pay %50 (esik %50) tahmini dagitim bildirimsiz",
        lambda: _ad("70.00", "70.00", th=T.with_overrides({"ad_share_percent": D("50")})),
        [("urun:A", NotifyMode.NONE, {"ad_share_percent": D("50.00"), "estimated_ad_spend": D("70.00")})],
    ),
    (
        "G08 kesinti: 9,99 ozet, 10,00 aninda, varsayilan desi 50,00 bildirimsiz",
        lambda: _ded(("9.99", False), ("10.00", False), ("50.00", True)),
        [
            ("satir:O1|1|1", NotifyMode.DIGEST_ONLY, {"difference": D("9.99")}),
            ("satir:O2|1|2", NotifyMode.NORMAL, {"difference": D("10.00")}),
            ("satir:O3|1|3", NotifyMode.NONE, {"default_desi_used": True}),
        ],
    ),
    (
        # pC=0,20 pB=0,05 p=0,10: z^2 = 0,0225 / (0,1*0,9*0,015) = 16,67 >= 5,410 (k=1); hesap toplami ayni
        "G09 iade: tek urun 20/100 ve 10/200 urun ve hesap alarmi",
        lambda: evaluate_return_rate(ACCOUNT, AS_OF, _ret(("A", (20, 100, 10, 200))), T),
        [
            ("urun:A", NotifyMode.NORMAL, {"z_squared": D("16.67"), "current_rate_percent": D("20.00")}),
            ("hesap:*", NotifyMode.NORMAL, {"z_squared": D("16.67"), "tested_count": 1}),
        ],
    ),
    (
        # k=101 -> kritik 16,867 > 16,67: urun alarmi yok; hesap: xC=1020 nC=10100 xB=2010 nB=20200 fark < 5 puan
        "G10 iade: ayni urun 100 yedekle k=101 Bonferroni alarmi susturur",
        lambda: evaluate_return_rate(
            ACCOUNT,
            AS_OF,
            _ret(("A", (20, 100, 10, 200)), *((f"F{i}", (10, 100, 20, 200)) for i in range(100))),
            T,
        ),
        [],
    ),
    (
        # nC=29 < 30: z^2 buyuk olsa da alarm yok
        "G11 iade: nC=29 kucuk orneklem alarm yok",
        lambda: evaluate_return_rate(ACCOUNT, AS_OF, _ret(("A", (20, 29, 10, 200))), T),
        [],
    ),
    (
        # pC=0,06 pB=0,04: fark tam 2 puan (esik 5) -> yok
        "G12 iade: fark 2 puan varsayilan 5 puan esiginin altinda",
        lambda: evaluate_return_rate(ACCOUNT, AS_OF, _ret(("A", (120, 2000, 160, 4000))), T),
        [],
    ),
]


@pytest.mark.parametrize(("name", "run", "expected"), GOLDEN, ids=[g[0].split(":")[0] for g in GOLDEN])
def test_golden_scenarios(name: str, run: Callable[[], RuleOutcome], expected: Expected) -> None:
    outcome = run()
    assert outcome.status is RuleStatus.EVALUATED, name
    assert [(c.subject, c.notify) for c in outcome.candidates] == [(s, n) for s, n, _ in expected], name
    for cand, (_, _, evidence) in zip(outcome.candidates, expected, strict=True):
        for key, value in evidence.items():
            assert cand.evidence[key] == value, f"{name}: {key}"


# --------------------------------------------------------------------------- gerçek motor çıktısı (G13-G16)
def test_g13_engine_loss_line() -> None:
    """Satış 120,00 (KDV dahil) = 100,00 hariç; komisyon 12,00 dahil = 10,00; kargo 45,00; hizmet bedeli 10,00;
    maliyet 150,00: 100 - 10 - 45 - 10 - 150 = -115,00."""
    a = line("A", price="120.00")
    o = order([a], number="O1")
    cost = CostRecord("A", date(2026, 1, 1), D("150.00"), D("20"))
    result = calculate_profit(data([o], costs=(cost,), settlements=(sale(o, a),)))
    outcome = evaluate_loss_making_sales(ACCOUNT, result, T)
    (cand,) = outcome.candidates
    assert cand.subject == "urun:A"
    assert cand.evidence["total_loss"] == D("115.00")
    assert cand.certainty is Certainty.ESTIMATED  # kargo ve hizmet bedeli tahmini


def test_g14_engine_ad_eats_profit() -> None:
    """Satis 240,00 = 200,00 hariç; komisyon 20,00; kargo 45,00; hizmet 10,00; maliyet 20,00; reklam 120,00:
    net = 200 - 20 - 45 - 10 - 20 - 120 = -15,00; reklam oncesi 105,00; pay 120/105 = %114,29 >= %100."""
    b = line("B", price="240.00")
    o = order([b], number="O2")
    cost = CostRecord("B", date(2026, 1, 1), D("20.00"), D("20"))
    ad = AdRecord("AD1", date(2026, 10, 1), date(2026, 10, 31), D("120.00"), False, barcode="B")
    result = calculate_profit(
        data([o], costs=(cost,), settlements=(sale(o, b),), ad_records=(ad,), catalog_barcodes=("B",))
    )
    # Ayni urun hem zararda hem reklam kari yiyor; reklam kurali yalniz reklam oncesi kari pozitif urunde calisir.
    outcome = evaluate_ad_eats_profit(ACCOUNT, result, (ad,), T)
    assert outcome.status is RuleStatus.EVALUATED
    (cand,) = outcome.candidates
    assert cand.evidence["profit_before_ads"] == D("105.00")
    assert cand.evidence["ad_share_percent"] == D("114.29")
    assert cand.evidence["matched_ad_spend"] == D("120.00")
    assert cand.notify is NotifyMode.NORMAL


def test_g15_engine_unexpected_deduction() -> None:
    """Tahmini komisyon %10 (12,00 dahil = 10,00 hariç); gerceklesen oran %19 (19,00 dahil = 15,83 hariç):
    fark = (19 - 12) / 1,2 = 5,83 > max(5,00, %5) ve > 0,05; bildirim esigi 10,00 altinda -> yalniz ozet."""
    c = line("C", price="120.00", commission="10")
    o = order([c], number="O3")
    cost = CostRecord("C", date(2026, 1, 1), D("10.00"), D("20"))
    high = sale(o, c, commission_rate=D("19"), commission_amount=D("19"), seller_revenue=D("101"))
    result = calculate_profit(data([o], costs=(cost,), settlements=(high,)))
    outcome = evaluate_unexpected_deduction(ACCOUNT, result, T)
    (cand,) = outcome.candidates
    assert cand.evidence["difference"] == D("5.83")
    assert cand.evidence["commission_rate_differs"] is True
    assert cand.notify is NotifyMode.DIGEST_ONLY
    assert cand.scope is AlertScope.ORDER_LINE


def test_g16_engine_refunded_loss_is_not_a_loss_making_sale() -> None:
    """Ayni zarar satirina iade kaydi eklenince (-205,00) iade zararidir: ZARARINA_SATIS kapsamindan cikar."""
    a = line("A", price="120.00")
    o = order([a], number="O1")
    cost = CostRecord("A", date(2026, 1, 1), D("150.00"), D("20"))
    result = calculate_profit(data([o], costs=(cost,), settlements=(sale(o, a), ret(o, a, "120.00"))))
    assert WarningCode.LOSS in result.lines[0].warnings
    assert evaluate_loss_making_sales(ACCOUNT, result, T).candidates == ()
