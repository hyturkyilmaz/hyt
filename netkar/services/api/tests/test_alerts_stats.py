"""İade oranı istatistiği (ADR-0009 §3.4, test listesi madde 5): z^2, küçük örneklem, Bonferroni kovaları."""

from __future__ import annotations

import math
import random
from datetime import date
from decimal import Decimal
from fractions import Fraction
from statistics import NormalDist

import pytest

from app.alerts.stats import (
    Z2_BUCKETS,
    Z2_OPEN_BUCKET,
    cohort_windows,
    critical_z2,
    has_enough_sample,
    rate_increase_test,
    two_proportion_z2,
)

D = Decimal
MIN5 = D("5")


# --------------------------------------------------------------------------- z^2 (bağımsız hesap)
def textbook_z2(x_cur: int, n_cur: int, x_base: int, n_base: int) -> Fraction:
    """Ders kitabı formülü, tam Fraction: z^2 = (pC - pB)^2 / (p (1 - p) (1/nC + 1/nB)), p havuzlu.

    Üretim kodunun sadeleştirilmiş tamsayı ifadesinden bağımsızdır."""
    p_cur, p_base = Fraction(x_cur, n_cur), Fraction(x_base, n_base)
    pooled = Fraction(x_cur + x_base, n_cur + n_base)
    return (p_cur - p_base) ** 2 / (pooled * (1 - pooled) * (Fraction(1, n_cur) + Fraction(1, n_base)))


def test_z2_matches_textbook_formula_in_exact_arithmetic() -> None:
    # pC=0,20 pB=0,05 p=0,10 fark=0,15: 0,0225 / (0,09 * 0,015) = 50/3 (elle)
    assert textbook_z2(20, 100, 10, 200) == Fraction(50, 3)
    # pC=0,30 pB=0,10 p=1/6 fark=0,2: 0,04 / (5/36 * 0,015) = 96/5 = 19,2 (elle)
    assert textbook_z2(30, 100, 20, 200) == Fraction(96, 5)
    assert textbook_z2(10, 100, 20, 200) == 0
    tolerance = Fraction(1, 10**20)
    rng = random.Random(7)
    for case in [(20, 100, 10, 200), (30, 100, 20, 200), (10, 100, 20, 200), (120, 2000, 160, 4000)] + [
        (rng.randint(1, n_c - 1), n_c, rng.randint(1, n_b - 1), n_b)
        for n_c, n_b in ((rng.randint(30, 500), rng.randint(60, 900)) for _ in range(300))
    ]:
        got = two_proportion_z2(*case)
        assert got is not None
        assert abs(Fraction(got) - textbook_z2(*case)) < tolerance, case


def test_z2_none_when_pooled_rate_is_zero_or_one_or_cohort_is_empty() -> None:
    assert two_proportion_z2(0, 100, 0, 200) is None
    assert two_proportion_z2(100, 100, 200, 200) is None
    # n = 0: sıfıra bölme yok, tanımsız (None) ve alarm yok
    assert two_proportion_z2(0, 0, 5, 100) is None
    assert two_proportion_z2(5, 100, 0, 0) is None
    assert two_proportion_z2(0, -1, 5, 100) is None
    empty = rate_increase_test(0, 0, 5, 100, critical=D("5.412"), min_diff_points=D("0"))
    assert (empty.alarm, empty.z_squared) == (False, None)


# --------------------------------------------------------------------------- Bonferroni kovaları
@pytest.mark.parametrize(
    ("k", "expected"),
    [
        (1, "5.412"),
        (2, "8.284"),
        (5, "8.284"),
        (6, "10.828"),
        (20, "10.828"),
        (21, "13.832"),
        (100, "13.832"),
        (101, "16.872"),
        (500, "16.872"),
        (501, "18.190"),
        (1000, "18.190"),
        (1001, "21.265"),
        (5000, "21.265"),
        (5001, "25.695"),
        (50000, "25.695"),
        (50001, "30.150"),
        (10**7, "30.150"),
    ],
)
def test_bucket_boundaries(k: int, expected: str) -> None:
    assert critical_z2(k) == D(expected)


def test_bucket_requires_positive_k() -> None:
    with pytest.raises(ValueError, match="k en az 1"):
        critical_z2(0)


def test_table_matches_normal_quantiles_rounded_up_and_bonferroni_alpha() -> None:
    """Tablo = inv_cdf(1 - alfa)^2, 3 ondalığa yukarı yuvarlanmış; alfa kova üst ucu için 0,01/k'dan küçük
    ya da eşit (Bonferroni'den gevşek değil)."""
    normal = NormalDist()
    rows = [*Z2_BUCKETS, (None, *Z2_OPEN_BUCKET)]
    for upper, alpha, table in rows:
        z = -normal.inv_cdf(float(alpha))  # = inv_cdf(1 - alfa), kuyruk tarafında daha hassas
        exact = z * z
        assert float(table) >= exact, (alpha, table, exact)
        assert float(table) - exact < 0.001, (alpha, table, exact)
        if upper is not None:
            assert alpha <= D("0.01") / upper
    uppers = [u for u, _, _ in Z2_BUCKETS]
    assert uppers == sorted(uppers)
    # k > 50000 için son kova 0,01/500000'e kadar sıkı
    assert Z2_OPEN_BUCKET[0] <= D("0.01") / 500000


# --------------------------------------------------------------------------- küçük örneklem
@pytest.mark.parametrize(
    ("counts", "ok"),
    [
        ((20, 100, 10, 200), True),
        ((6, 30, 12, 60), True),  # nC=30 ve nB=60 tam sınır; n*p = 30*18/90 = 6
        ((6, 29, 12, 60), False),  # nC=29
        ((6, 30, 12, 59), False),  # nB=59
        ((4, 100, 10, 200), False),  # xC=4
        ((5, 100, 10, 200), True),  # xC=5 sınır
        ((5, 30, 0, 60), False),  # n*p = 30*5/90 < 5 (normal yaklaşım)
        ((5, 30, 1, 60), False),  # nC*p = 30*6/90 = 2 < 5
        ((30, 30, 60, 60), False),  # p = 1: n*(1-p) = 0
        ((29, 30, 59, 60), False),  # n*(1-p) = 30*2/90 < 5
    ],
)
def test_small_sample_rules(counts: tuple[int, int, int, int], ok: bool) -> None:
    assert has_enough_sample(*counts) is ok


def test_normal_approximation_boundary_is_inclusive() -> None:
    # nC=30, nB=60, X=15: nC*p = 30*15/90 = 5 (tam sınır) ve nC*(1-p) = 25
    assert has_enough_sample(8, 30, 7, 60) is True
    # X=14: nC*p = 30*14/90 = 4,67 < 5
    assert has_enough_sample(7, 30, 7, 60) is False


# --------------------------------------------------------------------------- karar
def test_alarm_at_exact_critical_value_and_just_above() -> None:
    args = (30, 100, 20, 200)
    assert rate_increase_test(*args, critical=D("19.2"), min_diff_points=MIN5).alarm is True
    assert rate_increase_test(*args, critical=D("19.21"), min_diff_points=MIN5).alarm is False


def test_alarm_returns_rounded_input_values_for_evidence() -> None:
    test = rate_increase_test(20, 100, 10, 200, critical=D("5.412"), min_diff_points=MIN5)
    assert test.alarm is True
    assert test.z_squared is not None
    assert test.z_squared.quantize(D("0.01")) == D("16.67")


def test_min_diff_and_ratio_are_inclusive_boundaries() -> None:
    # pC=0,06 pB=0,04: fark tam 2 puan, oran tam 1,5; z^2 = 11,988
    args = (120, 2000, 160, 4000)
    crit = D("5.410")
    assert rate_increase_test(*args, critical=crit, min_diff_points=D("2")).alarm is True
    assert rate_increase_test(*args, critical=crit, min_diff_points=D("2.01")).alarm is False
    assert rate_increase_test(*args, critical=crit, min_diff_points=D("5")).alarm is False
    # oran 1,5 altına düşünce (xC=119: 0,0595 < 0,06) alarm yok
    assert rate_increase_test(119, 2000, 160, 4000, critical=crit, min_diff_points=D("0")).alarm is False


def test_ratio_condition_blocks_even_when_z_and_diff_pass() -> None:
    # pC=0,10 pB=0,07: oran 1,43 < 1,5; fark 3 puan >= 1; z^2 = 24,46
    result = rate_increase_test(300, 3000, 420, 6000, critical=D("5.412"), min_diff_points=D("1"))
    assert result.alarm is False
    assert result.z_squared is not None
    assert result.z_squared > D("24")


def test_decrease_never_alarms() -> None:
    result = rate_increase_test(5, 100, 30, 200, critical=D("5.412"), min_diff_points=D("0"))
    assert result.alarm is False
    assert result.z_squared is not None
    assert result.z_squared > D("6")  # iki yönlü anlamlı olurdu; tek yönlü kural alarm vermez


def test_equal_rates_no_alarm_and_degenerate_pool() -> None:
    assert rate_increase_test(10, 100, 20, 200, critical=D("5.412"), min_diff_points=D("0")).alarm is False
    degenerate = rate_increase_test(0, 100, 0, 200, critical=D("5.412"), min_diff_points=D("0"))
    assert degenerate.alarm is False
    assert degenerate.z_squared is None


# --------------------------------------------------------------------------- tablo kritik değerinin iki yanı
# (k, sayımlar (xC, nC, xB, nB), alarm, elle hesaplanmış z^2). nC=100, nB=200. Hepsi küçük örneklemi geçer ve
# fark >= 5 puan, oran >= 1,5; karar yalnız z^2'nin gerçek tablo değerine (5,412 ... 16,872) göre yerine bağlıdır.
STRADDLE = [
    (1, (14, 100, 12, 200), False, 5.390),  # 5,390 < 5,412
    (1, (21, 100, 22, 200), True, 5.429),  # 5,429 >= 5,412
    (5, (14, 100, 10, 200), False, 7.337),  # 7,337 < 8,284
    (5, (15, 100, 10, 200), True, 8.727),  # 8,727 >= 8,284
    (20, (16, 100, 10, 200), False, 10.191),  # 10,191 < 10,828
    (20, (17, 100, 10, 200), True, 11.722),  # 11,722 >= 10,828
    (100, (18, 100, 10, 200), False, 13.314),  # 13,314 < 13,832
    (100, (19, 100, 10, 200), True, 14.964),  # 14,964 >= 13,832
    (500, (20, 100, 10, 200), False, 16.667),  # 16,667 < 16,872
    (500, (21, 100, 10, 200), True, 18.419),  # 18,419 >= 16,872
]


@pytest.mark.parametrize(("k", "counts", "alarm", "z2_value"), STRADDLE)
def test_real_table_values_decide_both_sides(
    k: int, counts: tuple[int, int, int, int], alarm: bool, z2_value: float
) -> None:
    assert has_enough_sample(*counts)
    assert float(textbook_z2(*counts)) == pytest.approx(z2_value, abs=5e-4)  # yorumdaki kalan değer
    result = rate_increase_test(*counts, critical=critical_z2(k), min_diff_points=MIN5)
    assert result.alarm is alarm


# --------------------------------------------------------------------------- float referansı
def test_decision_function_agrees_with_float_reference() -> None:
    """`rate_increase_test` (Decimal/tamsayı) dört koşulun hepsinde float + karekök referansıyla aynı yönde
    karar verir (referans yalnız test içinde)."""
    rng = random.Random(20261120)
    alarms = quiet = 0
    for _ in range(4000):
        n_cur, n_base = rng.randint(30, 600), rng.randint(60, 1200)
        base_rate = rng.random() * 0.25
        x_base = min(n_base, round(n_base * base_rate))
        x_cur = min(n_cur, round(n_cur * base_rate * (0.5 + rng.random() * 3)))
        z2 = two_proportion_z2(x_cur, n_cur, x_base, n_base)
        if z2 is None:
            continue
        p = (x_cur + x_base) / (n_cur + n_base)
        p_cur, p_base = x_cur / n_cur, x_base / n_base
        z = (p_cur - p_base) / math.sqrt(p * (1 - p) * (1 / n_cur + 1 / n_base))
        for k, min_points in ((1, 5), (7, 5), (50, 3), (101, 5), (800, 2)):
            crit_z = math.sqrt(float(critical_z2(k)))
            diff_points = (p_cur - p_base) * 100
            if (
                abs(z - crit_z) < 1e-9
                or abs(diff_points - min_points) < 1e-9
                or abs(p_cur - 1.5 * p_base) < 1e-12
            ):
                continue  # eşitlik sınırında kayan nokta kararı güvenilmez
            reference = z > 0 and z >= crit_z and diff_points >= min_points and p_cur >= 1.5 * p_base
            got = rate_increase_test(
                x_cur, n_cur, x_base, n_base, critical=critical_z2(k), min_diff_points=D(min_points)
            )
            assert got.alarm is reference, (x_cur, n_cur, x_base, n_base, k)
            alarms += reference
            quiet += not reference
    assert alarms > 100
    assert quiet > 1000


# --------------------------------------------------------------------------- kohort pencereleri
def test_cohort_windows_for_a_known_day() -> None:
    # T = 2026-11-20, H = 21: güncel [09-22 - 28, 10-30) -> sipariş günü [2026-10-02, 2026-10-30)
    cur_start, cur_end, base_start, base_end = cohort_windows(date(2026, 11, 20))
    assert (cur_start, cur_end) == (date(2026, 10, 2), date(2026, 10, 30))
    assert (base_start, base_end) == (date(2026, 7, 10), date(2026, 10, 2))
