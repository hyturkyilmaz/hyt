"""Trendyol: User-Agent/kimlik doğrulaması, yapılandırma, pencere bölme ve token bucket."""

from __future__ import annotations

import string
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import SecretStr

from app.integrations.trendyol import (
    TrendyolClient,
    TrendyolConfig,
    TrendyolConfigError,
    TrendyolCredentials,
    TrendyolEnvironment,
    TrendyolValidationError,
    build_user_agent,
    validate_integrator_name,
    validate_seller_id,
)
from app.integrations.trendyol.client import backoff_delay, parse_retry_after
from app.integrations.trendyol.ratelimit import (
    EndpointGroup,
    LimitSpec,
    RateLimiterRegistry,
    TokenBucket,
)
from app.integrations.trendyol.windows import check_span, split_window, to_epoch_ms
from tests.trendyol_helpers import API_KEY, API_SECRET, FakeTime, credentials

# --- User-Agent ------------------------------------------------------------------------------


def test_user_agent_format_is_seller_dash_integrator() -> None:
    assert build_user_agent("2738", "NetKar") == "2738 - NetKar"
    assert build_user_agent("123456", "SelfIntegration") == "123456 - SelfIntegration"


@given(
    seller=st.from_regex(r"[1-9][0-9]{0,17}", fullmatch=True),
    name=st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=30),
)
def test_user_agent_property(seller: str, name: str) -> None:
    assert build_user_agent(seller, name) == f"{seller} - {name}"


@pytest.mark.parametrize(
    "name",
    ["", "Net Kar", "NetKâr", "Net-Kar", "Net_Kar", "a" * 31, "Netkar\n", "Çiçek", " NetKar", "NetKar "],
)
def test_invalid_integrator_names_are_rejected(name: str) -> None:
    with pytest.raises(TrendyolConfigError):
        validate_integrator_name(name)
    with pytest.raises(TrendyolConfigError):
        build_user_agent("2738", name)


def test_integrator_name_boundary_is_30_chars() -> None:
    assert validate_integrator_name("a" * 30) == "a" * 30


@pytest.mark.parametrize("seller", ["", "0", "012", "abc", "12 3", "-5", "1" * 19, "１２３"])
def test_invalid_seller_ids_are_rejected(seller: str) -> None:
    with pytest.raises(TrendyolConfigError):
        validate_seller_id(seller)


def test_client_is_not_built_with_invalid_user_agent() -> None:
    # Geçersiz entegratör adı: yapılandırma düzeyinde reddedilir, istemci kurulamaz.
    with pytest.raises(TrendyolConfigError):
        TrendyolConfig(integrator_name="Net Kar")
    # Geçersiz satıcı kimliği: kimlik bilgisi nesnesi kurulamaz.
    with pytest.raises(TrendyolConfigError):
        credentials("abc")


def test_client_exposes_user_agent_without_secrets() -> None:
    client = TrendyolClient(credentials(), TrendyolConfig(integrator_name="NetKar"))
    assert client.user_agent == "2738 - NetKar"
    assert API_KEY not in repr(client.user_agent) and API_SECRET not in client.user_agent


@pytest.mark.parametrize(
    ("key", "secret"),
    [
        ("a:b", "sir12345"),  # kullanıcı adında ':' olamaz
        ("anahtar 1", "sir12345"),  # boşluk
        ("anahtar\r\nX: 1", "sir12345"),  # başlık enjeksiyonu
        ("anahtarç", "sir12345"),  # ASCII dışı
        ("", "sir12345"),
        ("anahtar1", ""),
        ("anahtar1", "sir 1"),
        ("anahtar1", "x" * 257),
    ],
)
def test_malformed_credentials_are_rejected(key: str, secret: str) -> None:
    with pytest.raises(TrendyolConfigError):
        TrendyolCredentials(seller_id="2738", api_key=SecretStr(key), api_secret=SecretStr(secret))


def test_credentials_repr_hides_secrets() -> None:
    text = f"{credentials()!r} {credentials()}"
    assert API_KEY not in text and API_SECRET not in text


# --- Yapılandırma ----------------------------------------------------------------------------


def test_default_environment_is_stage_and_live_is_explicit() -> None:
    assert TrendyolConfig().environment is TrendyolEnvironment.STAGE
    assert TrendyolConfig().base_url == "https://stageapigw.trendyol.com"
    live = TrendyolConfig(environment=TrendyolEnvironment.LIVE)
    assert live.base_url == "https://apigw.trendyol.com"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"connect_timeout": 0},
        {"read_timeout": -1},
        {"max_retries": -1},
        {"max_retries": 11},
        {"backoff_base": 0},
        {"backoff_base": 5, "backoff_cap": 1},
        {"retry_after_cap": 0},
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, float]) -> None:
    with pytest.raises(TrendyolConfigError):
        TrendyolConfig(**kwargs)  # type: ignore[arg-type]


# --- Geri çekilme yardımcıları ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"), [("7", 7.0), (" 2.5 ", 2.5), ("0", 0.0), ("-1", None), ("abc", None), (None, None)]
)
def test_parse_retry_after(raw: str | None, expected: float | None) -> None:
    assert parse_retry_after(raw) == expected


@given(attempt=st.integers(0, 20), r=st.floats(0, 1))
def test_backoff_is_bounded_and_has_a_floor(attempt: int, r: float) -> None:
    delay = backoff_delay(attempt, base=1.0, cap=30.0, rng=lambda: r)
    ceiling = min(30.0, 2.0**attempt)
    assert ceiling / 2 <= delay <= ceiling
    assert delay <= 30.0


# --- Pencere yardımcıları --------------------------------------------------------------------

UTC_START = datetime(2026, 1, 1, tzinfo=UTC)


def test_to_epoch_ms_requires_timezone() -> None:
    assert to_epoch_ms(datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)) == 1000
    with pytest.raises(TrendyolValidationError):
        to_epoch_ms(datetime(2026, 1, 1))


def test_check_span_rejects_reversed_and_too_long() -> None:
    check_span(UTC_START, UTC_START + timedelta(days=15), timedelta(days=15), "x")
    with pytest.raises(TrendyolValidationError):
        check_span(UTC_START, UTC_START - timedelta(seconds=1), timedelta(days=15), "x")
    with pytest.raises(TrendyolValidationError):
        check_span(UTC_START, UTC_START + timedelta(days=15, seconds=1), timedelta(days=15), "x")


def test_split_window_40_days_into_three_finance_windows() -> None:
    end = UTC_START + timedelta(days=40)
    windows = split_window(UTC_START, end, timedelta(days=15))
    assert len(windows) == 3
    assert windows[0][0] == UTC_START and windows[-1][1] == end
    for a, b in pairwise(windows):
        assert a[1] == b[0]  # komşu pencereler sınır anını paylaşır: boşluk yok
    for start, finish in windows:
        assert finish - start < timedelta(days=15)  # "15 günden uzun olamaz" sınırına değmez


def test_split_window_short_and_degenerate_ranges() -> None:
    assert split_window(UTC_START, UTC_START, timedelta(days=15)) == [(UTC_START, UTC_START)]
    one_day = UTC_START + timedelta(days=1)
    assert split_window(UTC_START, one_day, timedelta(days=15)) == [(UTC_START, one_day)]
    with pytest.raises(TrendyolValidationError):
        split_window(one_day, UTC_START, timedelta(days=15))
    with pytest.raises(TrendyolValidationError):
        split_window(UTC_START, one_day, timedelta(milliseconds=1))


@given(
    start_s=st.integers(0, 2_000_000_000),
    length_s=st.integers(0, 90 * 86400),
    max_days=st.integers(1, 30),
)
def test_split_window_covers_range_contiguously(start_s: int, length_s: int, max_days: int) -> None:
    start = datetime.fromtimestamp(start_s, UTC)
    end = start + timedelta(seconds=length_s)
    max_span = timedelta(days=max_days)
    windows = split_window(start, end, max_span)
    assert windows[0][0] == start and windows[-1][1] == end
    for a, b in pairwise(windows):
        assert a[1] == b[0]
    assert all(finish - begin < max_span for begin, finish in windows)


# --- Token bucket ----------------------------------------------------------------------------


def test_token_bucket_burst_then_refill() -> None:
    bucket = TokenBucket(per_minute=60, burst=2, now=0.0)  # saniyede 1 jeton
    assert bucket.wait_time(0.0) == 0.0
    bucket.take(0.0)
    bucket.take(0.0)
    assert bucket.wait_time(0.0) == pytest.approx(1.0)
    assert bucket.wait_time(0.5) == pytest.approx(0.5)
    assert bucket.wait_time(1.0) == 0.0
    # Kapasite aşılmaz: uzun bekleyiş yine en fazla 2 jeton verir.
    assert bucket.wait_time(100.0) == 0.0
    bucket.take(100.0)
    bucket.take(100.0)
    assert bucket.wait_time(100.0) > 0


def test_token_bucket_block_after_429() -> None:
    bucket = TokenBucket(per_minute=60, burst=5, now=0.0)
    bucket.block(0.0, 10.0)
    assert bucket.wait_time(0.0) == pytest.approx(10.0)
    assert bucket.wait_time(9.0) == pytest.approx(1.0)
    assert bucket.wait_time(10.0) == 0.0


async def test_orders_group_waits_after_burst_at_30_per_minute() -> None:
    fake = FakeTime()
    registry = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)
    for _ in range(5):  # burst = 5
        assert await registry.acquire("2738", EndpointGroup.ORDERS, "getShipmentPackages") == 0.0
    waited = await registry.acquire("2738", EndpointGroup.ORDERS, "getShipmentPackages")
    assert waited == pytest.approx(2.0)  # 30/dk = 0.5 jeton/sn


async def test_general_rule_50_requests_per_10_seconds() -> None:
    fake = FakeTime()
    registry = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)
    total = 0.0
    for _ in range(51):  # claims grubu geniş (1000/dk) ama genel kural 10 sn'de 50
        total += await registry.acquire("2738", EndpointGroup.CLAIMS, "getClaims")
    assert total == pytest.approx(0.2, abs=0.05)  # 51. istek ~1/5 sn bekler (5 istek/sn)


async def test_buckets_are_per_seller_and_per_group() -> None:
    fake = FakeTime()
    registry = RateLimiterRegistry(
        limits={EndpointGroup.FINANCE: LimitSpec(60, 1), EndpointGroup.QNA: LimitSpec(60, 1)},
        clock=fake.monotonic,
        sleep=fake.sleep,
    )
    assert await registry.acquire("1", EndpointGroup.FINANCE, "a") == 0.0
    assert await registry.acquire("2", EndpointGroup.FINANCE, "a") == 0.0  # başka satıcı etkilenmez
    assert await registry.acquire("1", EndpointGroup.QNA, "b") == 0.0  # başka grup etkilenmez
    assert await registry.acquire("1", EndpointGroup.FINANCE, "a") > 0.0  # aynı satıcı + grup bekler


async def test_penalize_blocks_other_calls_of_same_seller_and_group() -> None:
    fake = FakeTime()
    registry = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)
    await registry.acquire("1", EndpointGroup.FINANCE, "getSettlements")
    registry.penalize("1", EndpointGroup.FINANCE, "getSettlements", 7.0)
    assert await registry.acquire("1", EndpointGroup.FINANCE, "getSettlements") == pytest.approx(7.0)
    assert await registry.acquire("2", EndpointGroup.FINANCE, "getSettlements") == 0.0
