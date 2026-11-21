"""Dört uyarı kuralı (ADR-0009 §3): saf fonksiyonlar, veritabanı ve I/O yok.

Para: tüm tutarlar `Decimal`, KDV hariç, kuruş. Satır ve ürün tutarları motorda zaten yuvarlanmış gelir;
kural yalnız toplar ve karşılaştırır. Yüzde gösterimi tek yuvarlama fonksiyonu olan `app.profit.money`
(`percent_of`, `rnd`) ile yapılır. `net_kar` null olan satır ya da ürün hiçbir kuralda 0 sayılmaz (K37).
Kural girdisi motor sonucu (`ProfitResult`) ve sayımlardır; motorun davranışı burada DEĞİŞMEZ.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.alerts.settings import AlertThresholds
from app.alerts.stats import (
    BASE_WINDOW_DAYS,
    CURRENT_WINDOW_DAYS,
    HORIZON_DAYS,
    cohort_windows,
    critical_z2,
    has_enough_sample,
    rate_increase_test,
)
from app.alerts.types import (
    ACCOUNT_SUBJECT,
    AlertCandidate,
    AlertRule,
    AlertScope,
    EvidenceValue,
    NotifyMode,
    RuleOutcome,
    RuleStatus,
    Severity,
    dedupe_key,
    freeze_evidence,
    normalize_account_id,
    order_line_subject,
    product_subject,
)
from app.profit.enums import Certainty, Source, Status, WarningCode
from app.profit.inputs import AdRecord
from app.profit.money import ZERO, percent_of, rnd
from app.profit.results import LineComparison, LineResult, ProfitResult

# Bildirim yükündeki iade neden kodu sayısı (yalnız kod, serbest metin yok).
MAX_REASON_CODES = 3


def _certainty(lines: Sequence[LineResult]) -> Certainty:
    """K40: tüm satırlar kesinse kesin; aksi halde (tahmini ya da eksik kalem) tahmini."""
    return (
        Certainty.CERTAIN if all(ln.certainty is Certainty.CERTAIN for ln in lines) else Certainty.ESTIMATED
    )


def _candidate(
    rule: AlertRule,
    account_id: str | UUID,
    scope: AlertScope,
    subject: str,
    severity: Severity,
    certainty: Certainty,
    notify: NotifyMode,
    evidence: dict[str, EvidenceValue],
) -> AlertCandidate:
    return AlertCandidate(
        rule=rule,
        scope=scope,
        subject=subject,
        dedupe_key=dedupe_key(rule, account_id, subject),
        severity=severity,
        certainty=certainty,
        notify=notify,
        evidence=freeze_evidence(evidence),
    )


# --------------------------------------------------------------------------- ZARARINA_SATIS (§3.1)
def evaluate_loss_making_sales(
    account_id: str | UUID, result: ProfitResult, thresholds: AlertThresholds
) -> RuleOutcome:
    """Ürünün (7 günlük dönem) iade etkisi olmadan zararda satış satırları.

    Satır: `ZARAR` uyarısı var, `adet_iade == 0`, `iade_kaydi_bekleyen_adet == 0`, durum iptal değil. İade
    içeren zarar satırı "iade zararı"dır ve iade oranı kuralına aittir. Toplam zarar = Σ satır `net_kar`
    (null ise `eksik_giderler_haric_kar`); eşiğin (`loss_min_amount`) altındaysa olay açılmaz.
    """
    normalize_account_id(account_id)  # geçersiz hesap kimliği baştan ValueError verir
    groups: dict[str, list[LineResult]] = {}
    for ln in result.lines:
        if ln.status is Status.CANCELLED or WarningCode.LOSS not in ln.warnings:
            continue
        if ln.refunded_quantity != 0 or ln.pending_refund_quantity != 0:
            continue
        groups.setdefault(ln.barcode.strip(), []).append(ln)

    candidates: list[AlertCandidate] = []
    for barcode, lines in groups.items():
        amounts = [
            ln.items.net_profit if ln.items.net_profit is not None else ln.items.known_expenses_profit
            for ln in lines
        ]
        total_loss = -sum(amounts, ZERO)
        if total_loss < thresholds.loss_min_amount:
            continue
        candidates.append(
            _candidate(
                AlertRule.LOSS_MAKING_SALE,
                account_id,
                AlertScope.PRODUCT,
                product_subject(barcode),
                Severity.HIGH,
                _certainty(lines),
                NotifyMode.NORMAL,
                {
                    "loss_line_count": len(lines),
                    "total_loss": total_loss,
                    "worst_line_loss": -min(amounts),
                    "has_missing_items": any(ln.missing_items for ln in lines),
                },
            )
        )
    return RuleOutcome(AlertRule.LOSS_MAKING_SALE, RuleStatus.EVALUATED, tuple(candidates))


# --------------------------------------------------------------------------- REKLAM_KARI_YIYOR (§3.2)
def _ad_share_hit(spend: Decimal, before_ads: Decimal, thresholds: AlertThresholds) -> bool:
    """`spend >= ad_min_spend` ve `spend * 100 >= ad_share_percent * before` (before > 0 çağıranda)."""
    return spend >= thresholds.ad_min_spend and spend * 100 >= thresholds.ad_share_percent * before_ads


def evaluate_ad_eats_profit(
    account_id: str | UUID,
    result: ProfitResult,
    ad_records: Sequence[AdRecord],
    thresholds: AlertThresholds,
) -> RuleOutcome:
    """Ürün reklamdan önce kârda; reklam payı bu kârın eşik yüzdesini yiyor (30 günlük dönem).

    `ad_records` boşsa kural "veri yok" döner ve uyarı üretmez. `before = net_kar + harcama`; `before <= 0`
    ise ürün zaten zararda (ZARARINA_SATIS kapsar) ve `net_kar` null ise kural çalışmaz. Koşul yalnız
    tahmini dağıtımla (`dagitim_tahmini`) sağlanıyorsa olay açılır ama bildirim üretilmez (K15). İlk sürümde
    reklam uyarısı her zaman "tahmini" etiketlidir (Excel yapısı, KDV ve atıf penceresi Doğrulanmadı).
    """
    normalize_account_id(account_id)  # geçersiz hesap kimliği baştan ValueError verir
    if not ad_records:
        return RuleOutcome(AlertRule.AD_EATS_PROFIT, RuleStatus.NO_DATA)

    matched: dict[str, Decimal] = {}
    for ln in result.lines:
        if ln.status is Status.CANCELLED:
            continue
        for detail in ln.ad_details:
            if detail.kind is Source.MATCHED:
                code = ln.barcode.strip()
                matched[code] = matched.get(code, ZERO) + detail.amount_excl_vat

    candidates: list[AlertCandidate] = []
    for product in result.products:
        if product.net_profit is None:
            continue
        spend = product.advertising_spend
        before_ads = product.net_profit + spend
        if before_ads <= 0 or not _ad_share_hit(spend, before_ads, thresholds):
            continue
        # Satışsız harcama barkodla eşlenmiştir (K15); satırlara dağıtılan eşleşen kısma eklenir.
        matched_spend = matched.get(product.barcode.strip(), ZERO) + product.advertising_without_sales
        notify = (
            NotifyMode.NORMAL if _ad_share_hit(matched_spend, before_ads, thresholds) else NotifyMode.NONE
        )
        candidates.append(
            _candidate(
                AlertRule.AD_EATS_PROFIT,
                account_id,
                AlertScope.PRODUCT,
                product_subject(product.barcode),
                Severity.MEDIUM,
                Certainty.ESTIMATED,
                notify,
                {
                    "ad_spend": spend,
                    "matched_ad_spend": matched_spend,
                    "estimated_ad_spend": spend - matched_spend,
                    "net_profit": product.net_profit,
                    "profit_before_ads": before_ads,
                    "ad_share_percent": percent_of(spend, before_ads) or ZERO,
                },
            )
        )
    return RuleOutcome(AlertRule.AD_EATS_PROFIT, RuleStatus.EVALUATED, tuple(candidates))


# --------------------------------------------------------------------------- BEKLENMEYEN_KESINTI (§3.3)
def _default_desi_explains_difference(comparison: LineComparison) -> bool:
    """Varsayılan desi bastırması yalnız fark kargodan geliyorsa geçerlidir.

    Kesin gönderi kargosu karşılaştırmaya girmediyse (`kargo_gonderi_kesin` yok) fark kargodan doğmaz: False.
    Aksi halde kargo dışı fark `fark - (kargo_kesin - kargo_tahmini)` tek başına motorun eşiğini aşıyorsa
    (ör. komisyon farkı) bastırma yok: False.
    """
    actual = comparison.shipping_outbound_actual
    estimated = comparison.shipping_outbound_estimated
    if actual is None or estimated is None:
        return False
    non_shipping = comparison.difference - (actual - estimated)
    return non_shipping <= comparison.threshold


def evaluate_unexpected_deduction(
    account_id: str | UUID, result: ProfitResult, thresholds: AlertThresholds
) -> RuleOutcome:
    """Motorun `BEKLENMEYEN_KESINTI` ürettiği satırlar (92 günlük dönem); yeni hesap yok.

    Motorun sabit eşikleri (5,00 TL, %5, 0,05) korunur. Olay her zaman açılır; bildirim eşiği ayrıdır:
    fark `deduction_notify_min` altındaysa yalnız özet; varsayılan desiyle tahmin edilmiş kargodan doğan fark
    (H10 önerisi) bildirime girmez, yalnız panelde kalır.
    """
    normalize_account_id(account_id)  # geçersiz hesap kimliği baştan ValueError verir
    candidates: list[AlertCandidate] = []
    for ln in result.lines:
        if ln.status is Status.CANCELLED or WarningCode.UNEXPECTED_DEDUCTION not in ln.warnings:
            continue
        comparison = ln.comparison
        if comparison is None:
            continue
        default_desi = comparison.shipping_estimate_default_desi
        if (
            default_desi
            and not thresholds.notify_default_desi_deductions
            and _default_desi_explains_difference(comparison)
        ):
            notify = NotifyMode.NONE
        elif comparison.difference < thresholds.deduction_notify_min:
            notify = NotifyMode.DIGEST_ONLY
        else:
            notify = NotifyMode.NORMAL
        candidates.append(
            _candidate(
                AlertRule.UNEXPECTED_DEDUCTION,
                account_id,
                AlertScope.ORDER_LINE,
                order_line_subject(ln.order_number, ln.package_id, ln.line_id),
                Severity.HIGH,
                Certainty.CERTAIN if ln.certainty is Certainty.CERTAIN else Certainty.ESTIMATED,
                notify,
                {
                    "difference": comparison.difference,
                    "threshold": comparison.threshold,
                    "default_desi_used": default_desi,
                    "commission_rate_differs": WarningCode.COMMISSION_RATE_DIFFERENT in ln.warnings,
                },
            )
        )
    return RuleOutcome(AlertRule.UNEXPECTED_DEDUCTION, RuleStatus.EVALUATED, tuple(candidates))


# --------------------------------------------------------------------------- IADE_ORANI_ARTISI (§3.4)
@dataclass(frozen=True, slots=True, kw_only=True)
class ReturnCohort:
    """Bir ürünün iki kohortu için sayımlar (sipariş satırı birimiyle; sorgu D3'ün işidir).

    `x` = en az bir kabul edilmiş iade kalemi olan satır sayısı, `n` = satır sayısı; her iki kohortta da
    yalnız sipariş gününden sonraki `HORIZON_DAYS` içinde açılmış iade sayılmıştır.
    """

    barcode: str
    current_lines: int
    current_returned: int
    base_lines: int
    base_returned: int
    # Yalnız neden kodları (serbest metin yok); en çok ilk 3'ü yüke girer.
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for lines, returned in (
            (self.current_lines, self.current_returned),
            (self.base_lines, self.base_returned),
        ):
            if not 0 <= returned <= lines:
                raise ValueError("iade sayısı 0 ile satır sayısı arasında olmalı")


def _return_candidate(
    account_id: str | UUID,
    scope: AlertScope,
    subject: str,
    counts: tuple[int, int, int, int],
    z_squared: Decimal | None,
    critical: Decimal,
    k: int,
    as_of: date,
    reason_codes: tuple[str, ...] | None,
) -> AlertCandidate:
    x_cur, n_cur, x_base, n_base = counts
    cur_start, cur_end, base_start, base_end = cohort_windows(as_of)
    evidence: dict[str, EvidenceValue] = {
        "current_lines": n_cur,
        "current_returned": x_cur,
        "base_lines": n_base,
        "base_returned": x_base,
        "current_rate_percent": percent_of(x_cur, n_cur) or ZERO,
        "base_rate_percent": percent_of(x_base, n_base) or ZERO,
        "z_squared": rnd(z_squared or ZERO),
        "critical_z_squared": critical,
        "tested_count": k,
        "horizon_days": HORIZON_DAYS,
        "current_window_days": CURRENT_WINDOW_DAYS,
        "base_window_days": BASE_WINDOW_DAYS,
        "current_start": cur_start.isoformat(),
        "current_end": cur_end.isoformat(),
        "base_start": base_start.isoformat(),
        "base_end": base_end.isoformat(),
    }
    if reason_codes is not None:
        evidence["reason_codes"] = ",".join(reason_codes[:MAX_REASON_CODES])
    return _candidate(
        AlertRule.RETURN_RATE_INCREASE,
        account_id,
        scope,
        subject,
        Severity.MEDIUM,
        # İstatistiksel çıkarım (olasılıksal sinyal) ve yalnız "Accepted" talepler sayılır: kesin değil.
        Certainty.ESTIMATED,
        NotifyMode.NORMAL,
        evidence,
    )


def evaluate_return_rate(
    account_id: str | UUID,
    as_of: date,
    cohorts: Sequence[ReturnCohort],
    thresholds: AlertThresholds,
) -> RuleOutcome:
    """İade oranı artışı: baz döneme karşı tek yönlü, havuzlu iki oran z testi (karekök ve float yok).

    Küçük örneklem koşullarını (`has_enough_sample`) geçen `k` ürün Bonferroni kovasına (`critical_z2(k)`)
    göre test edilir; hesap düzeyinde tüm ürünlerin toplamı `k = 1` ile ayrıca test edilir (kapsam hesap,
    konu `*`). `cohorts` boşsa "veri yok".
    """
    normalize_account_id(account_id)  # geçersiz hesap kimliği baştan ValueError verir
    if not cohorts:
        return RuleOutcome(AlertRule.RETURN_RATE_INCREASE, RuleStatus.NO_DATA)

    eligible = [
        c
        for c in cohorts
        if has_enough_sample(c.current_returned, c.current_lines, c.base_returned, c.base_lines)
    ]
    k = len(eligible)
    candidates: list[AlertCandidate] = []
    if k:
        critical = critical_z2(k)
        for c in eligible:
            counts = (c.current_returned, c.current_lines, c.base_returned, c.base_lines)
            test = rate_increase_test(
                *counts, critical=critical, min_diff_points=thresholds.return_min_diff_points
            )
            if test.alarm:
                candidates.append(
                    _return_candidate(
                        account_id,
                        AlertScope.PRODUCT,
                        product_subject(c.barcode),
                        counts,
                        test.z_squared,
                        critical,
                        k,
                        as_of,
                        c.reason_codes,
                    )
                )

    totals = (
        sum(c.current_returned for c in cohorts),
        sum(c.current_lines for c in cohorts),
        sum(c.base_returned for c in cohorts),
        sum(c.base_lines for c in cohorts),
    )
    if has_enough_sample(*totals):
        critical = critical_z2(1)
        test = rate_increase_test(
            *totals, critical=critical, min_diff_points=thresholds.return_min_diff_points
        )
        if test.alarm:
            candidates.append(
                _return_candidate(
                    account_id,
                    AlertScope.ACCOUNT,
                    ACCOUNT_SUBJECT,
                    totals,
                    test.z_squared,
                    critical,
                    1,
                    as_of,
                    None,
                )
            )
    return RuleOutcome(AlertRule.RETURN_RATE_INCREASE, RuleStatus.EVALUATED, tuple(candidates), k)
