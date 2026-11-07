"""Para yardımcıları: yuvarlama sınırları, KDV ayrımı, en büyük kalan dağıtımı (K01, K02, K24)."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.profit.money import (
    allocate,
    fmt,
    percent_of,
    ratio,
    rnd,
    split_exclusive,
    split_inclusive,
    to_decimal,
)

D = Decimal

cents = st.integers(min_value=-10_000_000, max_value=10_000_000).map(lambda c: D(c).scaleb(-2))
weights_st = st.lists(
    st.integers(min_value=0, max_value=100_000).map(lambda c: D(c).scaleb(-2)), min_size=1, max_size=12
)


# --------------------------------------------------------------------------- to_decimal
@pytest.mark.parametrize("bad", [1.5, True, None, [1], b"1"])
def test_to_decimal_rejects_float_bool_and_other_types(bad: object) -> None:
    with pytest.raises(TypeError):
        to_decimal(bad)


def test_to_decimal_accepts_str_int_decimal() -> None:
    assert to_decimal("12.50") == D("12.50")
    assert to_decimal(3) == D("3")
    value = D("1.10")
    assert to_decimal(value) is value


# --------------------------------------------------------------------------- rnd (K01)
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.005", "0.01"),  # yarım kuruş yukarı
        ("0.004", "0.00"),
        ("-0.005", "-0.01"),  # negatifte sıfırdan uzağa
        ("-0.004", "0.00"),
        ("10.025", "10.03"),  # banker yuvarlaması 10.02 verirdi
        ("2.675", "2.68"),
        ("-10.025", "-10.03"),
        ("0.015", "0.02"),
        ("0.025", "0.03"),
        ("1234567.894999", "1234567.89"),
        ("0", "0.00"),
    ],
)
def test_rnd_round_half_up_boundaries(raw: str, expected: str) -> None:
    assert fmt(rnd(D(raw))) == expected


def test_rnd_never_returns_negative_zero_and_keeps_two_decimals() -> None:
    assert str(rnd(D("-0.004"))) == "0.00"
    assert rnd(5).as_tuple().exponent == -2
    assert str(rnd(Fraction(1, 3))) == "0.33"
    assert str(rnd(Fraction(-1, 3))) == "-0.33"


def test_rnd_is_exact_on_fraction_boundaries() -> None:
    # 12.03 / 1.20 = 10.025 tam sınırdır; ikili/bağlam hatası olmamalı.
    assert split_inclusive(D("12.03"), D("20")) == (D("10.03"), D("2.00"))
    # 1/3 kuruş altı kalan yuvarlamaya karışmaz.
    assert rnd(Fraction(1, 200)) == D("0.01")
    assert rnd(Fraction(1, 200) - Fraction(1, 10**30)) == D("0.00")


@given(cents)
def test_rnd_is_idempotent_and_odd_symmetric(value: Decimal) -> None:
    assert rnd(value) == value
    assert rnd(-value) == -rnd(value)


# --------------------------------------------------------------------------- KDV ayrımı (K02)
@pytest.mark.parametrize(
    ("gross", "rate", "net", "vat"),
    [
        ("499.90", "20", "416.58", "83.32"),
        ("275.00", "10", "250.00", "25.00"),
        ("180.00", "1", "178.22", "1.78"),
        ("0.00", "20", "0.00", "0.00"),
        ("-120.00", "20", "-100.00", "-20.00"),
    ],
)
def test_split_inclusive_examples(gross: str, rate: str, net: str, vat: str) -> None:
    assert split_inclusive(D(gross), D(rate)) == (D(net), D(vat))


def test_split_exclusive_vat_is_rounded_from_exact_net() -> None:
    assert split_exclusive(D("178.225"), D("1")) == (D("178.23"), D("1.78"))
    assert split_exclusive(D("100"), D("20")) == (D("100.00"), D("20.00"))


@given(cents, st.sampled_from([D("0"), D("1"), D("10"), D("20")]))
def test_split_inclusive_parts_sum_to_rounded_gross(gross: Decimal, rate: Decimal) -> None:
    net, vat = split_inclusive(gross, rate)
    assert net + vat == rnd(gross)


# --------------------------------------------------------------------------- dağıtım (K24)
def test_allocate_largest_remainder_examples() -> None:
    assert allocate(D("40.00"), [1, 1, 1]) == [D("13.34"), D("13.33"), D("13.33")]
    assert allocate(D("8.00"), [1, 1, 1]) == [D("2.67"), D("2.67"), D("2.66")]
    assert allocate(D("85.00"), [D("2"), D("3")]) == [D("34.00"), D("51.00")]


def test_allocate_tie_goes_to_first_item() -> None:
    assert allocate(D("0.01"), [1, 1, 1]) == [D("0.01"), D("0.00"), D("0.00")]


def test_allocate_empty_zero_and_negative_weights() -> None:
    assert allocate(D("10.00"), []) == []
    # hepsi sıfır: eşit ağırlık
    assert allocate(D("1.00"), [0, 0, 0]) == [D("0.34"), D("0.33"), D("0.33")]
    # negatif ağırlık 0 sayılır
    assert allocate(D("10.00"), [-5, 1, 1]) == [D("0.00"), D("5.00"), D("5.00")]
    assert allocate(D("10.00"), [-1, -2]) == [D("5.00"), D("5.00")]


def test_allocate_negative_total_keeps_sign_and_sum() -> None:
    parts = allocate(D("-40.00"), [1, 1, 1])
    assert parts == [D("-13.34"), D("-13.33"), D("-13.33")]
    assert sum(parts) == D("-40.00")


def test_allocate_rounds_total_to_cents_first() -> None:
    assert sum(allocate(D("10.005"), [1, 2])) == D("10.01")
    assert allocate(Fraction(1, 3), [1]) == [D("0.33")]


def test_allocate_zero_total_and_single_item() -> None:
    assert allocate(D("0"), [3, 4]) == [D("0.00"), D("0.00")]
    assert allocate(D("7.77"), [5]) == [D("7.77")]


@given(cents, weights_st)
def test_allocate_preserves_total(total: Decimal, weights: list[Decimal]) -> None:
    parts = allocate(total, weights)
    assert len(parts) == len(weights)
    assert sum(parts) == rnd(total)


@given(cents, weights_st)
def test_allocate_is_within_one_cent_of_exact_share(total: Decimal, weights: list[Decimal]) -> None:
    parts = allocate(total, weights)
    fractions = [Fraction(w) for w in weights]
    weight_sum = sum(fractions, Fraction(0))
    for part, weight in zip(parts, fractions, strict=True):
        share = Fraction(total) * weight / weight_sum if weight_sum else Fraction(total) / len(weights)
        assert abs(Fraction(part) - share) <= Fraction(1, 100)


@given(cents, st.lists(st.integers(min_value=-1000, max_value=1000).map(D), min_size=1, max_size=8))
def test_allocate_with_negative_weights_still_preserves_total(total: Decimal, weights: list[Decimal]) -> None:
    parts = allocate(total, weights)
    assert sum(parts) == rnd(total)
    assert all((p <= 0) == (total <= 0) or p == 0 for p in parts)


@given(cents, weights_st)
def test_allocate_sign_symmetry(total: Decimal, weights: list[Decimal]) -> None:
    assert allocate(-total, weights) == [-p if p else p for p in allocate(total, weights)]


@given(st.lists(st.integers(min_value=1, max_value=50).map(D), min_size=1, max_size=6), cents)
def test_allocate_vat_and_net_split_separately_keep_both_sums(weights: list[Decimal], gross: Decimal) -> None:
    net, vat = split_inclusive(gross, D("20"))
    nets, vats = allocate(net, weights), allocate(vat, weights)
    assert sum(nets) == net
    assert sum(vats) == vat
    assert sum(nets) + sum(vats) == rnd(gross)


# --------------------------------------------------------------------------- oranlar ve biçim
def test_percent_and_ratio() -> None:
    assert percent_of(D("119.09"), D("416.58")) == D("28.59")
    assert percent_of(D("1"), D("0")) is None
    assert ratio(D("1499.70"), D("120.00")) == D("12.50")
    assert ratio(D("1"), D("0.00")) is None
    assert percent_of(D("-100"), D("333.25")) == D("-30.01")


def test_fmt() -> None:
    assert fmt(None) is None
    assert fmt(D("4.1")) == "4.10"
    assert fmt(D("-0.004")) == "0.00"
    assert fmt(D("1000000")) == "1000000.00"
