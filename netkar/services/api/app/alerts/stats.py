"""İade oranı artışı istatistiği: tek yönlü, havuzlu iki oran z testi (ADR-0009 §3.4).

Kural: `Decimal` ve tamsayı; float ve karekök YOK. Test, `z^2` ile yapılır: `z^2 >= z_kritik^2` ve `fark > 0`
birlikte `z >= z_kritik` demektir (z_kritik pozitif). Sabitler (ufuk, pencereler, küçük örneklem sınırları,
alfa) bilerek ayar değildir: yanlış ayarla istatistiği bozmamak için sabit tutulur.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

# Sabit ufuk (gün): yalnız sipariş gününden sonraki H gün içinde açılmış iade sayılır. Doğrulanmadı: pilot.
HORIZON_DAYS = 21
# Güncel kohort 28 gün, taban kohort 84 gün.
CURRENT_WINDOW_DAYS = 28
BASE_WINDOW_DAYS = 84

# Küçük örneklemde alarm yok.
MIN_CURRENT_LINES = 30
MIN_BASE_LINES = 60
MIN_CURRENT_RETURNED = 5
# Normal yaklaşım koşulu: her iki kohortta n*p >= 5 ve n*(1-p) >= 5 (havuzlu p).
NORMAL_APPROX_MIN = 5

# pC >= 1,5 * pB koşulu: 2 * pC >= 3 * pB.
RATIO_NUM = 3
RATIO_DEN = 2

# Bonferroni kovaları: (kova üst ucu k, tek yönlü alfa, z_kritik^2). Alfa kova üst ucu için 0,01 / k değerine
# eşit ya da ondan sıkıdır (ihtiyatlı). z_kritik^2 = inv_cdf(1 - alfa)^2 değeri `statistics.NormalDist` ile
# hesaplanıp 3 ondalığa YUKARI yuvarlanmıştır (yuvarlama hep sıkı yöndedir); test tabloyu bu yolla doğrular.
# Üst uçlar: 1, 5, 20, 100, 500, 1000, 5000, 50000 (ürün sayısı pratikte bunu aşmaz).
Z2_BUCKETS: tuple[tuple[int, Decimal, Decimal], ...] = (
    (1, Decimal("0.01"), Decimal("5.412")),
    (5, Decimal("0.002"), Decimal("8.284")),
    (20, Decimal("0.0005"), Decimal("10.828")),
    (100, Decimal("0.0001"), Decimal("13.832")),
    (500, Decimal("0.00002"), Decimal("16.872")),
    (1000, Decimal("0.00001"), Decimal("18.190")),
    (5000, Decimal("0.000002"), Decimal("21.265")),
    (50000, Decimal("0.0000002"), Decimal("25.695")),
)
# k > 50000: alfa 2e-8 (0,01 / 500000'e kadar geçerli; bu sınırın üstü gerçekçi değildir).
Z2_OPEN_BUCKET: tuple[Decimal, Decimal] = (Decimal("0.00000002"), Decimal("30.150"))


def critical_z2(k: int) -> Decimal:
    """`k` testli Bonferroni kovasının `z_kritik^2` değeri. `k >= 1` olmalı."""
    if k < 1:
        raise ValueError("k en az 1 olmalı")
    for upper, _alpha, z2 in Z2_BUCKETS:
        if k <= upper:
            return z2
    return Z2_OPEN_BUCKET[1]


def has_enough_sample(x_cur: int, n_cur: int, x_base: int, n_base: int) -> bool:
    """Küçük örneklem koşulları 1-3 (hepsi sağlanmalı). Tamsayı çapraz çarpımla, bölmesiz ve tam."""
    if n_cur < MIN_CURRENT_LINES or n_base < MIN_BASE_LINES or x_cur < MIN_CURRENT_RETURNED:
        return False
    total, hits = n_cur + n_base, x_cur + x_base
    # n * p >= 5  <=>  n * hits >= 5 * total ; n * (1 - p) >= 5  <=>  n * (total - hits) >= 5 * total
    for n in (n_cur, n_base):
        if n * hits < NORMAL_APPROX_MIN * total or n * (total - hits) < NORMAL_APPROX_MIN * total:
            return False
    return True


def _z2_parts(x_cur: int, n_cur: int, x_base: int, n_base: int) -> tuple[int, int] | None:
    """`z^2 = pay / payda` (tamsayılar) ya da tanımsızsa None.

    `z^2 = fark^2 / (p (1-p) (1/nC + 1/nB))` ifadesinin cebirsel sadeleşmiş hali:
    `(xC*nB - xB*nC)^2 * N / (nC * nB * X * (N - X))`, `N = nC + nB`, `X = xC + xB`.
    Tanımsız durumlar: bir kohortta `n <= 0` (örneklem yok) ya da `p = 0` / `p = 1` (payda sıfır).
    """
    if n_cur <= 0 or n_base <= 0:
        return None
    total, hits = n_cur + n_base, x_cur + x_base
    if hits == 0 or hits == total:
        return None
    cross = x_cur * n_base - x_base * n_cur
    return cross * cross * total, n_cur * n_base * hits * (total - hits)


def two_proportion_z2(x_cur: int, n_cur: int, x_base: int, n_base: int) -> Decimal | None:
    """Havuzlu iki oran testinin `z^2` değeri (tek Decimal bölme); tanımsızsa None (`_z2_parts`)."""
    parts = _z2_parts(x_cur, n_cur, x_base, n_base)
    if parts is None:
        return None
    with localcontext() as ctx:
        ctx.prec = 28
        return Decimal(parts[0]) / Decimal(parts[1])


@dataclass(frozen=True, slots=True)
class RateTest:
    """Bir kohort çiftinin test sonucu."""

    alarm: bool
    z_squared: Decimal | None


def rate_increase_test(
    x_cur: int,
    n_cur: int,
    x_base: int,
    n_base: int,
    *,
    critical: Decimal,
    min_diff_points: Decimal,
) -> RateTest:
    """Alarm: `fark > 0` VE `z^2 >= z_kritik^2` VE `fark >= min_fark` VE `pC >= 1,5 pB`.

    Karşılaştırmalar tamsayı çapraz çarpımla yapılır (`fark = cross / (nC*nB)`); küçük örneklem koşulları
    çağıranın işidir (`has_enough_sample`).
    """
    parts = _z2_parts(x_cur, n_cur, x_base, n_base)
    if parts is None:
        return RateTest(False, None)
    z2 = two_proportion_z2(x_cur, n_cur, x_base, n_base)
    cross = x_cur * n_base - x_base * n_cur
    numerator, denominator = parts
    crit = Fraction(critical)
    # z^2 >= kritik: tamsayı çapraz çarpım (karşılaştırmada yuvarlama yok).
    if cross <= 0 or numerator * crit.denominator < crit.numerator * denominator:
        return RateTest(False, z2)
    # fark >= min_fark: (cross / (nC*nB)) * 100 >= puan
    diff = Fraction(cross * 100, n_cur * n_base)
    enough_diff = diff >= Fraction(min_diff_points)
    # pC >= 1,5 pB: xC/nC * 2 >= xB/nB * 3
    big_ratio = x_cur * n_base * RATIO_DEN >= x_base * n_cur * RATIO_NUM
    return RateTest(enough_diff and big_ratio, z2)


def cohort_windows(as_of: date) -> tuple[date, date, date, date]:
    """Kohort pencereleri (ADR-0009 §3.4), yarı açık `[başlangıç, bitiş)`, sipariş günü olarak.

    Güncel: `[T-H-28, T-H)`; taban: `[T-H-28-84, T-H-28)`.
    Dönen: (güncel_baş, güncel_bit, taban_baş, taban_bit).
    """
    cur_end = as_of - timedelta(days=HORIZON_DAYS)
    cur_start = cur_end - timedelta(days=CURRENT_WINDOW_DAYS)
    base_start = cur_start - timedelta(days=BASE_WINDOW_DAYS)
    return cur_start, cur_end, base_start, cur_start
