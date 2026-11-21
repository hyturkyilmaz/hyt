"""Dört kuralın sınır, küçük örneklem, Bonferroni ve "veri yok" testleri (ADR-0009 §12 madde 1-6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.alerts import (
    ACCOUNT_SUBJECT,
    AlertRule,
    AlertScope,
    AlertThresholds,
    NotifyMode,
    ReturnCohort,
    RuleOutcome,
    RuleStatus,
    Severity,
    dedupe_key,
    evaluate_ad_eats_profit,
    evaluate_loss_making_sales,
    evaluate_return_rate,
    evaluate_unexpected_deduction,
    order_line_subject,
    product_subject,
)
from app.profit.enums import Certainty, MissingItem, Source, Status, WarningCode
from app.profit.inputs import AdRecord
from app.profit.results import AdDetail, LineResult, ProfitResult
from tests.alerts_helpers import make_comparison, make_line, make_product, make_result

D = Decimal
ACCOUNT = "6f1c2b9e-3d4a-4c5b-8e7f-0a1b2c3d4e5f"
DEFAULTS = AlertThresholds()
AS_OF = date(2026, 11, 20)
AD_RECORD = AdRecord("AD1", date(2026, 10, 1), date(2026, 10, 31), D("60.00"), False, barcode="A")


# --------------------------------------------------------------------------- ZARARINA_SATIS
def test_loss_opens_for_refund_free_loss_lines_only() -> None:
    result = make_result(
        (
            make_line("A", "-3.00", line_id=1),
            make_line("A", "-4.50", line_id=2),
            make_line("A", "2.00", warnings=(), line_id=3),
            make_line("B", "-100.00", refunded=1, line_id=4),  # tam iade zararı: dışlanır (G16 benzeri)
            make_line("C", "-100.00", pending=1, line_id=5),  # iade kaydı bekleyen: dışlanır
            make_line("D", "-100.00", status=Status.CANCELLED, line_id=6),
        )
    )
    outcome = evaluate_loss_making_sales(ACCOUNT, result, DEFAULTS)
    assert outcome.status is RuleStatus.EVALUATED
    assert [c.subject for c in outcome.candidates] == ["urun:A"]
    cand = outcome.candidates[0]
    assert cand.rule is AlertRule.LOSS_MAKING_SALE
    assert cand.scope is AlertScope.PRODUCT
    assert cand.severity is Severity.HIGH
    assert cand.notify is NotifyMode.NORMAL
    assert cand.dedupe_key == dedupe_key(AlertRule.LOSS_MAKING_SALE, ACCOUNT, "urun:A")
    assert dict(cand.evidence) == {
        "loss_line_count": 2,
        "total_loss": D("7.50"),
        "worst_line_loss": D("4.50"),
        "has_missing_items": False,
    }
    assert cand.certainty is Certainty.CERTAIN


def test_loss_threshold_is_inclusive() -> None:
    below = evaluate_loss_making_sales(ACCOUNT, make_result((make_line("A", "-4.99"),)), DEFAULTS)
    exact = evaluate_loss_making_sales(ACCOUNT, make_result((make_line("A", "-5.00"),)), DEFAULTS)
    assert below.candidates == ()
    assert len(exact.candidates) == 1
    zero_floor = DEFAULTS.with_overrides({"loss_min_amount": D("0.00")})
    assert (
        len(
            evaluate_loss_making_sales(
                ACCOUNT, make_result((make_line("A", "-0.01"),)), zero_floor
            ).candidates
        )
        == 1
    )


def test_loss_uses_known_expenses_profit_when_net_profit_is_null() -> None:
    line = make_line(
        "A",
        None,
        known="-12.40",
        certainty=Certainty.MISSING,
        missing=(MissingItem.PRODUCT_COST,),
    )
    cand = evaluate_loss_making_sales(ACCOUNT, make_result((line,)), DEFAULTS).candidates[0]
    assert cand.evidence["total_loss"] == D("12.40")
    assert cand.evidence["has_missing_items"] is True
    assert cand.certainty is Certainty.ESTIMATED


def test_loss_with_estimated_line_is_labeled_estimated_and_groups_split_by_barcode() -> None:
    result = make_result(
        (
            make_line("A", "-6.00", certainty=Certainty.ESTIMATED, line_id=1),
            make_line("B", "-8.00", line_id=2),
        )
    )
    outcome = evaluate_loss_making_sales(ACCOUNT, result, DEFAULTS)
    assert [(c.subject, c.certainty) for c in outcome.candidates] == [
        ("urun:A", Certainty.ESTIMATED),
        ("urun:B", Certainty.CERTAIN),
    ]


def test_loss_empty_result_has_no_candidates() -> None:
    outcome = evaluate_loss_making_sales(ACCOUNT, make_result(), DEFAULTS)
    assert outcome.status is RuleStatus.EVALUATED
    assert outcome.candidates == ()


# --------------------------------------------------------------------------- REKLAM_KARI_YIYOR
def ad_result(
    net_profit: str | None, spend: str, unsold: str = "0.00", matched: str = "0.00"
) -> ProfitResult:
    details = (AdDetail("AD1", Source.MATCHED, D(matched)),) if D(matched) else ()
    return make_result(
        (make_line("A", "1.00", warnings=(), ad_details=details),),
        (make_product("A", net_profit, spend, unsold),),
    )


def run_ad(
    result: ProfitResult, thresholds: AlertThresholds = DEFAULTS, records: tuple[AdRecord, ...] = (AD_RECORD,)
) -> RuleOutcome:
    return evaluate_ad_eats_profit(ACCOUNT, result, records, thresholds)


def test_ad_no_records_is_no_data_and_never_alerts() -> None:
    result = ad_result("0.00", "80.00", matched="80.00")
    outcome = run_ad(result, records=())
    assert outcome.status is RuleStatus.NO_DATA
    assert outcome.candidates == ()
    # Veri varken aynı sonuç uyarı üretir: durum ayrımı gerçekten "veri yok"tan geliyor.
    assert len(run_ad(result).candidates) == 1


def test_ad_default_share_boundary_at_zero_profit_after_ads() -> None:
    # net_kar = 0,00, harcama 80,00: before = 80,00, 8000 >= 100 * 80 (sınır, açar)
    at_edge = run_ad(ad_result("0.00", "80.00", matched="80.00"))
    assert len(at_edge.candidates) == 1
    # net_kar = 0,01: before = 80,01, 8000 < 8001 (açmaz)
    assert run_ad(ad_result("0.01", "80.00", matched="80.00")).candidates == ()


def test_ad_blocking_conditions() -> None:
    assert run_ad(ad_result(None, "80.00")).candidates == ()  # net kâr null
    assert run_ad(ad_result("-100.00", "60.00")).candidates == ()  # before <= 0: ürün zaten zararda
    assert run_ad(ad_result("-60.00", "60.00")).candidates == ()  # before = 0
    assert run_ad(ad_result("0.00", "49.99")).candidates == ()  # ad_min_spend altı
    assert len(run_ad(ad_result("0.00", "50.00", matched="50.00")).candidates) == 1  # ad_min_spend sınırı


def test_ad_share_override_and_evidence() -> None:
    result = ad_result("40.00", "60.00", matched="60.00")  # before = 100, pay %60
    assert run_ad(result).candidates == ()
    half = DEFAULTS.with_overrides({"ad_share_percent": D("60")})
    cand = run_ad(result, half).candidates[0]
    assert cand.severity is Severity.MEDIUM
    assert cand.certainty is Certainty.ESTIMATED
    assert cand.notify is NotifyMode.NORMAL
    assert dict(cand.evidence) == {
        "ad_spend": D("60.00"),
        "matched_ad_spend": D("60.00"),
        "estimated_ad_spend": D("0.00"),
        "net_profit": D("40.00"),
        "profit_before_ads": D("100.00"),
        "ad_share_percent": D("60.00"),
    }
    assert run_ad(ad_result("40.00", "59.99"), half).candidates == ()


def test_ad_estimated_only_opens_event_without_notification() -> None:
    # tüm harcama dagitim_tahmini: koşul eşlenen kısımla sağlanmaz -> olay açılır, bildirim yok
    cand = run_ad(ad_result("0.00", "80.00")).candidates[0]
    assert cand.notify is NotifyMode.NONE
    assert cand.evidence["estimated_ad_spend"] == D("80.00")


def test_ad_matched_partial_spend_decides_notification() -> None:
    # harcama 80 (60 eşleşen + 20 tahmini), before 80: eşleşen 60 -> 6000 < 8000 -> bildirim yok
    assert run_ad(ad_result("0.00", "80.00", matched="60.00")).candidates[0].notify is NotifyMode.NONE
    # satışsız harcama eşleşmiş sayılır: 80 = 0 satırlı + 80 satışsız -> koşul eşleşenle sağlanır
    assert run_ad(ad_result("0.00", "80.00", unsold="80.00")).candidates[0].notify is NotifyMode.NORMAL


def test_ad_cancelled_line_details_are_ignored_and_other_details_not_matched() -> None:
    cancelled = make_line(
        "A",
        "1.00",
        warnings=(),
        status=Status.CANCELLED,
        ad_details=(AdDetail("AD1", Source.MATCHED, D("80.00")),),
    )
    estimated = make_line(
        "A", "1.00", warnings=(), ad_details=(AdDetail("AD2", Source.ALLOCATED_ESTIMATE, D("80.00")),)
    )
    result = make_result((cancelled, estimated), (make_product("A", "0.00", "80.00"),))
    assert run_ad(result).candidates[0].notify is NotifyMode.NONE


# --------------------------------------------------------------------------- BEKLENMEYEN_KESINTI
def deduction_line(
    difference: str,
    *,
    default_desi: bool = False,
    ship_estimated: str | None = None,
    ship_actual: str | None = None,
    line_id: int = 1,
    extra: tuple[WarningCode, ...] = (),
    certainty: Certainty = Certainty.CERTAIN,
    status: Status = Status.SETTLED,
) -> LineResult:
    return make_line(
        "A",
        "10.00",
        warnings=(WarningCode.UNEXPECTED_DEDUCTION, *extra),
        comparison=make_comparison(difference, "5.00", default_desi, ship_estimated, ship_actual),
        certainty=certainty,
        status=status,
        order_number="O9",
        package_id=77,
        line_id=line_id,
    )


def test_deduction_requires_engine_warning_and_open_event_always() -> None:
    plain = make_line("A", "10.00", warnings=(), comparison=make_comparison("50.00"), line_id=2)
    outcome = evaluate_unexpected_deduction(
        ACCOUNT, make_result((plain, deduction_line("7.50", line_id=3))), DEFAULTS
    )
    assert len(outcome.candidates) == 1
    cand = outcome.candidates[0]
    assert cand.scope is AlertScope.ORDER_LINE
    assert cand.subject == "satir:O9|77|3"
    assert cand.severity is Severity.HIGH
    assert cand.certainty is Certainty.CERTAIN
    # 7,50 < deduction_notify_min (10,00): olay açık, yalnız özet
    assert cand.notify is NotifyMode.DIGEST_ONLY
    assert dict(cand.evidence) == {
        "difference": D("7.50"),
        "threshold": D("5.00"),
        "default_desi_used": False,
        "commission_rate_differs": False,
    }


def test_deduction_notify_min_boundary() -> None:
    def notify(difference: str) -> NotifyMode:
        result = make_result((deduction_line(difference),))
        return evaluate_unexpected_deduction(ACCOUNT, result, DEFAULTS).candidates[0].notify

    assert notify("9.99") is NotifyMode.DIGEST_ONLY
    assert notify("10.00") is NotifyMode.NORMAL


def test_deduction_default_desi_is_panel_only_unless_enabled() -> None:
    # Fark tamamen kargodan: tahmin 40,00 (varsayılan desi), kesin 90,00 -> kargo farkı 50,00
    line = deduction_line("50.00", default_desi=True, ship_estimated="40.00", ship_actual="90.00")
    result = make_result((line,))
    assert evaluate_unexpected_deduction(ACCOUNT, result, DEFAULTS).candidates[0].notify is NotifyMode.NONE
    enabled = DEFAULTS.with_overrides({"notify_default_desi_deductions": True})
    assert evaluate_unexpected_deduction(ACCOUNT, result, enabled).candidates[0].notify is NotifyMode.NORMAL
    small = make_result(
        (deduction_line("2.00", default_desi=True, ship_estimated="1.00", ship_actual="3.00"),)
    )
    assert (
        evaluate_unexpected_deduction(ACCOUNT, small, enabled).candidates[0].notify is NotifyMode.DIGEST_ONLY
    )


def _notify_for(difference: str, ship_estimated: str | None, ship_actual: str | None) -> NotifyMode:
    line = deduction_line(
        difference,
        default_desi=True,
        ship_estimated=ship_estimated,
        ship_actual=ship_actual,
        extra=(WarningCode.COMMISSION_RATE_DIFFERENT,),
    )
    return evaluate_unexpected_deduction(ACCOUNT, make_result((line,)), DEFAULTS).candidates[0].notify


def test_deduction_default_desi_suppression_needs_shipping_to_explain_the_difference() -> None:
    # Komisyon farkı 40 TL + KOMISYON_ORANI_FARKLI + varsayılan desi, kesin kargo yok: bastırma YOK.
    assert _notify_for("40.00", None, None) is NotifyMode.NORMAL
    # Tahmin yok, kesin var: kargo farkı hesaplanamaz, bastırma yok.
    assert _notify_for("40.00", None, "10.00") is NotifyMode.NORMAL
    # Kargo farkı 10 TL, kargo dışı fark 40 TL > eşik 5,00: bastırma yok.
    assert _notify_for("50.00", "40.00", "50.00") is NotifyMode.NORMAL
    # Kargo dışı fark tam eşikte (15 - 10 = 5,00 <= 5,00): kargo açıklıyor, bastırılır.
    assert _notify_for("15.00", "40.00", "50.00") is NotifyMode.NONE
    # Kargo dışı fark eşiğin 1 kuruş üstünde (5,01): bastırma yok.
    assert _notify_for("15.01", "40.00", "50.00") is NotifyMode.NORMAL
    # Fark tamamen kargodan (50 = 90 - 40): bastırılır.
    assert _notify_for("50.00", "40.00", "90.00") is NotifyMode.NONE


def test_deduction_flags_commission_difference_and_estimated_certainty() -> None:
    line = deduction_line(
        "12.00", extra=(WarningCode.COMMISSION_RATE_DIFFERENT,), certainty=Certainty.ESTIMATED
    )
    cand = evaluate_unexpected_deduction(ACCOUNT, make_result((line,)), DEFAULTS).candidates[0]
    assert cand.evidence["commission_rate_differs"] is True
    assert cand.certainty is Certainty.ESTIMATED


def test_deduction_skips_cancelled_and_comparisonless_lines() -> None:
    cancelled = deduction_line("50.00", status=Status.CANCELLED, line_id=1)
    no_comparison = make_line("A", "10.00", warnings=(WarningCode.UNEXPECTED_DEDUCTION,), line_id=2)
    outcome = evaluate_unexpected_deduction(ACCOUNT, make_result((cancelled, no_comparison)), DEFAULTS)
    assert outcome.status is RuleStatus.EVALUATED
    assert outcome.candidates == ()


# --------------------------------------------------------------------------- IADE_ORANI_ARTISI
def cohort(barcode: str, counts: tuple[int, int, int, int], reasons: tuple[str, ...] = ()) -> ReturnCohort:
    x_cur, n_cur, x_base, n_base = counts
    return ReturnCohort(
        barcode=barcode,
        current_lines=n_cur,
        current_returned=x_cur,
        base_lines=n_base,
        base_returned=x_base,
        reason_codes=reasons,
    )


STRONG = (20, 100, 10, 200)  # z^2 = 16,67
FILLER = (10, 100, 20, 200)  # eşit oran, örneklem geçerli, z^2 = 0


def run_returns(cohorts: list[ReturnCohort], thresholds: AlertThresholds = DEFAULTS) -> RuleOutcome:
    return evaluate_return_rate(ACCOUNT, AS_OF, cohorts, thresholds)


def test_returns_no_cohorts_is_no_data() -> None:
    outcome = run_returns([])
    assert outcome.status is RuleStatus.NO_DATA
    assert outcome.candidates == ()
    assert outcome.tested_count == 0


def test_returns_product_and_account_alarm_with_evidence() -> None:
    outcome = run_returns([cohort("A", STRONG, ("DEFECT", "LATE", "WRONG", "EXTRA"))])
    assert outcome.status is RuleStatus.EVALUATED
    assert outcome.tested_count == 1
    product, account = outcome.candidates
    assert (product.scope, product.subject) == (AlertScope.PRODUCT, "urun:A")
    assert (account.scope, account.subject) == (AlertScope.ACCOUNT, "hesap:*")
    assert product.severity is Severity.MEDIUM
    assert product.certainty is Certainty.ESTIMATED  # istatistiksel çıkarım
    assert product.notify is NotifyMode.NORMAL
    assert dict(product.evidence) == {
        "current_lines": 100,
        "current_returned": 20,
        "base_lines": 200,
        "base_returned": 10,
        "current_rate_percent": D("20.00"),
        "base_rate_percent": D("5.00"),
        "z_squared": D("16.67"),
        "critical_z_squared": D("5.412"),
        "tested_count": 1,
        "horizon_days": 21,
        "current_window_days": 28,
        "base_window_days": 84,
        "current_start": "2026-10-02",
        "current_end": "2026-10-30",
        "base_start": "2026-07-10",
        "base_end": "2026-10-02",
        "reason_codes": "DEFECT,LATE,WRONG",  # yalnız ilk 3 kod
    }
    assert "reason_codes" not in account.evidence
    assert account.evidence["tested_count"] == 1
    assert account.dedupe_key == dedupe_key(AlertRule.RETURN_RATE_INCREASE, ACCOUNT, "hesap:*")


def test_returns_bonferroni_bucket_changes_decision() -> None:
    def barcodes(k_total: int) -> list[str]:
        outcome = run_returns([cohort("A", STRONG)] + [cohort(f"F{i}", FILLER) for i in range(k_total - 1)])
        assert outcome.tested_count == k_total
        return [c.subject for c in outcome.candidates if c.scope is AlertScope.PRODUCT]

    assert barcodes(1) == ["urun:A"]
    assert barcodes(5) == ["urun:A"]  # kritik 8,284 < 16,67
    assert barcodes(20) == ["urun:A"]  # 10,828
    assert barcodes(100) == ["urun:A"]  # 13,832 < 16,67
    assert barcodes(101) == []  # 16,872 > 16,67: alarm yok


def test_returns_account_total_is_tested_with_k_equal_one() -> None:
    # Ürünler tek başına örneklem şartını geçmez (nC=20), toplam (nC=100, nB=200) geçer ve alarm verir.
    parts = [cohort(f"P{i}", (4, 20, 2, 40)) for i in range(5)]
    outcome = run_returns(parts)
    assert outcome.tested_count == 0
    assert [(c.scope, c.subject) for c in outcome.candidates] == [(AlertScope.ACCOUNT, "hesap:*")]
    assert outcome.candidates[0].evidence["tested_count"] == 1


@pytest.mark.parametrize(
    "counts",
    [
        (20, 29, 10, 200),  # nC = 29
        (20, 100, 10, 59),  # nB = 59
        (4, 100, 1, 200),  # xC = 4
        (5, 30, 0, 60),  # normal yaklaşım koşulu (n*p < 5)
        (0, 100, 0, 200),  # p = 0
    ],
)
def test_returns_small_sample_never_alarms(counts: tuple[int, int, int, int]) -> None:
    outcome = run_returns([cohort("A", counts)])
    assert outcome.candidates == ()
    assert outcome.tested_count == 0


def test_returns_direction_ratio_and_min_diff_conditions() -> None:
    assert run_returns([cohort("A", (5, 100, 30, 200))]).candidates == ()  # düşüş
    assert (
        run_returns(
            [cohort("A", (300, 3000, 420, 6000))], DEFAULTS.with_overrides({"return_min_diff_points": D("1")})
        ).candidates
        == ()
    )  # oran 1,43
    boundary = (120, 2000, 160, 4000)  # tam 2 puan, tam 1,5 kat
    assert run_returns([cohort("A", boundary)]).candidates == ()
    two_points = DEFAULTS.with_overrides({"return_min_diff_points": D("2")})
    assert [c.scope for c in run_returns([cohort("A", boundary)], two_points).candidates] == [
        AlertScope.PRODUCT,
        AlertScope.ACCOUNT,
    ]


# --------------------------------------------------------------------------- girdi doğrulama ve anahtarlar
def test_return_cohort_validates_counts_and_requires_keywords() -> None:
    ok = ReturnCohort(barcode="A", current_lines=30, current_returned=30, base_lines=0, base_returned=0)
    assert ok.reason_codes == ()
    for bad in (
        {"current_lines": 10, "current_returned": 11, "base_lines": 10, "base_returned": 0},
        {"current_lines": 10, "current_returned": 0, "base_lines": 10, "base_returned": 11},
        {"current_lines": 10, "current_returned": -1, "base_lines": 10, "base_returned": 0},
        {"current_lines": 10, "current_returned": 0, "base_lines": 10, "base_returned": -1},
    ):
        with pytest.raises(ValueError, match="iade sayısı"):
            ReturnCohort(barcode="A", **bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ReturnCohort("A", 10, 1, 10, 1)  # type: ignore[misc]


def test_zero_sized_cohorts_are_safe() -> None:
    outcome = run_returns([cohort("A", (0, 0, 0, 0))])
    assert outcome.status is RuleStatus.EVALUATED
    assert outcome.candidates == ()


def test_subjects_are_scope_prefixed_and_barcode_is_stripped() -> None:
    result = make_result(
        (make_line(" A ", "-6.00", line_id=1), make_line("A", "-6.00", line_id=2)),
    )
    (cand,) = evaluate_loss_making_sales(ACCOUNT, result, DEFAULTS).candidates
    assert cand.subject == "urun:A"
    assert cand.evidence["loss_line_count"] == 2  # boşluklu ve boşluksuz barkod aynı ürün
    with pytest.raises(ValueError, match="barkod boş"):
        evaluate_loss_making_sales(ACCOUNT, make_result((make_line("  ", "-6.00"),)), DEFAULTS)


def test_account_id_is_normalized_and_validated() -> None:
    upper = ACCOUNT.upper()
    braces = "{" + ACCOUNT + "}"
    assert dedupe_key(AlertRule.LOSS_MAKING_SALE, upper, "urun:A") == dedupe_key(
        AlertRule.LOSS_MAKING_SALE, ACCOUNT, "urun:A"
    )
    assert dedupe_key(AlertRule.LOSS_MAKING_SALE, braces, "urun:A") == dedupe_key(
        AlertRule.LOSS_MAKING_SALE, UUID(ACCOUNT), "urun:A"
    )
    other = "11111111-2222-3333-4444-555555555555"
    assert dedupe_key(AlertRule.LOSS_MAKING_SALE, other, "urun:A") != dedupe_key(
        AlertRule.LOSS_MAKING_SALE, ACCOUNT, "urun:A"
    )
    # Aynı konu farklı kuralda farklı anahtar; ürün konusu hesap konusuyla çakışmaz.
    assert dedupe_key(AlertRule.AD_EATS_PROFIT, ACCOUNT, "urun:A") != dedupe_key(
        AlertRule.LOSS_MAKING_SALE, ACCOUNT, "urun:A"
    )
    assert product_subject("*") != ACCOUNT_SUBJECT
    assert order_line_subject(" O1 ", 2, 3) == "satir:O1|2|3"
    for evaluate_call in (
        lambda: evaluate_loss_making_sales("acc-1", make_result(), DEFAULTS),
        lambda: evaluate_ad_eats_profit("acc-1", make_result(), (), DEFAULTS),
        lambda: evaluate_unexpected_deduction("acc-1", make_result(), DEFAULTS),
        lambda: evaluate_return_rate("acc-1", AS_OF, [], DEFAULTS),
    ):
        with pytest.raises(ValueError, match=r"UUID|badly formed"):
            evaluate_call()
