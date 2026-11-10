"""Kâr ayarları denetimi (9 Kasım 2026): API ve migrasyon bulguları (gerçek PostgreSQL).

AO-01 sürüm sayısı sınırı ve rapor süresi, AD-01 büyük JSON sayıları, AD-02 okuma hız sınırı,
AD-03 migrasyon 0007 downgrade veri koruması. PoC'ler denetim raporu Ek A'dadır.
"""

from __future__ import annotations

import time
import tracemalloc
from collections.abc import Callable
from datetime import date, timedelta
from decimal import InvalidOperation
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pydantic_core import PydanticCustomError

import tests.test_report_perf as perf
from app.api.v1 import profit_settings_schemas as schemas
from app.services import profit_settings as ps
from tests.conftest import Api
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.sync_helpers import make_seller
from tests.test_profit_settings_api import confirmed, seed_head
from tests.test_profit_settings_schema import TABLES, insert_all

pytestmark = pytest.mark.usefixtures("fixed_today")


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


def url(shop: Shop, suffix: str = "") -> str:
    return f"{shop.base}/profit-settings{suffix}"


def put_fee(shop: Shop, **over: Any) -> Any:
    # Başlangıç geçmiş olduğundan (K43) bu yardımcı geçmiş etkiyi varsayılan olarak onaylar (YT-07: etki tarihiyle).
    body = {
        "valid_from": "2026-10-01",
        "amount": "12.00",
        "amount_includes_vat": True,
    }
    body.update(over)
    return shop.api.put(url(shop, "/service-fee-estimates"), confirmed(body))


def revision_in_db(conn: psycopg.Connection[Any], shop: Shop) -> int | None:
    row = conn.execute(
        "SELECT revision FROM profit_settings WHERE marketplace_account_id = %s", (shop.account_id,)
    ).fetchone()
    return None if row is None else int(row[0])


# --------------------------------------------------------------------------- AO-01: sürüm sayısı sınırı
def test_too_many_service_fee_versions_is_rejected(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    first = date(2020, 1, 1)
    seed_head(admin_conn, shop)
    admin_conn.cursor().executemany(
        "INSERT INTO service_fee_estimates (revision_from, tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
        "amount_includes_vat) VALUES (1, %s, %s, %s, %s, 10, false)",
        [
            (shop.tenant_id, shop.account_id, shop.user_id, first + timedelta(days=i))
            for i in range(ps.MAX_SERVICE_FEE_VERSIONS)
        ],
    )
    response = put_fee(shop, valid_from="2026-10-01")
    assert response.status_code == 422, response.text
    assert {"field": "valid_from", "code": "too_many_service_fee_versions"} in response.json()["errors"]
    assert revision_in_db(admin_conn, shop) == 1  # reddedilen yazım sürümü artırmadı
    # mevcut bir sürümü değiştirmek sınırdan etkilenmez
    assert put_fee(shop, valid_from=first.isoformat(), amount="99.00").status_code == 200


def test_service_fee_version_limit_matches_the_tariff_limit() -> None:
    assert ps.MAX_SERVICE_FEE_VERSIONS == ps.MAX_TARIFF_VERSIONS == 200


def test_summary_time_stays_linear_with_many_service_fee_versions(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    """PoC (A.1): 10.173 sürümde 5.000 siparişlik `summary` 76 sn (210 sürümde 1,6 sn) idi. Sınır üstü sürüm
    veritabanına doğrudan yazılır (eski veri ya da sınırı aşan betik); motor yine de sürüm sayısıyla çarpılmaz."""
    assert not tracemalloc.is_tracing()  # süre ölçümü izleme KAPALIYKEN
    big = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=1000)
    perf.seed_large(admin_conn, big)
    assert put_fee(big, valid_from="2000-01-01", amount="10", amount_includes_vat=False).status_code == 200

    def summary_seconds() -> float:
        started = time.perf_counter()
        response = big.api.get(f"{big.base}/profit/summary", params=perf.PERIOD)
        elapsed = time.perf_counter() - started
        assert response.status_code == 200, response.text
        return elapsed

    summary_seconds()  # ısınma
    t_one = summary_seconds()
    first = date(2000, 1, 2)
    days = [first + timedelta(days=i) for i in range((date(2027, 11, 8) - first).days)]
    admin_conn.cursor().executemany(
        "INSERT INTO service_fee_estimates (revision_from, tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
        "amount_includes_vat) VALUES (1, %s, %s, %s, %s, 10, false)",
        [(big.tenant_id, big.account_id, big.user_id, d) for d in days],
    )
    t_many = summary_seconds()
    print(f"\nPERF summary: 1 surum {t_one:.2f}s, {len(days) + 1} surum {t_many:.2f}s")
    # Geniş eşik (CI gürültüsü, 10.000 sürümün ORM yükü dahil); eski kod ~47 kat idi.
    assert t_many < 4 * t_one + 4.0, (t_many, t_one)


# --------------------------------------------------------------------------- AD-01: büyük JSON sayıları
HUGE_INT = "1" + "0" * 30  # 31 haneli tamsayı


def raw(shop: Shop, method: str, suffix: str, body: str) -> Any:
    call = shop.api.put if method == "PUT" else shop.api.post
    return call(url(shop, suffix), None, content=body.encode(), headers={"content-type": "application/json"})


def tariff_json(max_desi: str = "1", price: str = '"1"') -> str:
    return (
        '{"agreement":"trendyol","carrier":"X","valid_from":"2026-01-01","price_includes_vat":true,'
        f'"brackets":[{{"max_desi":{max_desi},"price":{price}}}]}}'
    )


def expense_json(**fields: str) -> str:
    body = {"name": '"x"', "kind": '"siparis_basi"', "amount_excl_vat": "1", "vat_rate": "20"}
    body.update({"valid_from": '"2026-01-01"'})
    body.update(fields)
    return "{" + ",".join(f'"{k}":{v}' for k, v in body.items()) + "}"


HUGE_CASES = [
    # (yöntem, yol, gövde, beklenen alan, beklenen kod)
    (
        "PUT",
        "/service-fee-estimates",
        f'{{"valid_from":"2026-01-01","amount":{HUGE_INT},"amount_includes_vat":true}}',
        "amount",
        "amount_out_of_range",
    ),
    (
        "PUT",
        "/service-fee-estimates",
        '{"valid_from":"2026-01-01","amount":1e30,"amount_includes_vat":true}',
        "amount",
        "amount_out_of_range",
    ),
    ("PUT", "/cargo-tariffs", tariff_json(max_desi=HUGE_INT), "brackets.0.max_desi", "desi_out_of_range"),
    ("PUT", "/cargo-tariffs", tariff_json(price="1e30"), "brackets.0.price", "price_out_of_range"),
    ("PUT", "/defaults", f'{{"default_desi":{HUGE_INT}}}', "default_desi", "desi_out_of_range"),
    ("PUT", "/defaults", '{"default_desi":1e40}', "default_desi", "desi_out_of_range"),
    (
        "POST",
        "/variable-expenses",
        expense_json(kind='"satis_yuzdesi"', percent="1e30", amount_excl_vat="null"),
        "percent",
        "percent_out_of_range",
    ),
    (
        "POST",
        "/variable-expenses",
        expense_json(amount_excl_vat=HUGE_INT),
        "amount_excl_vat",
        "amount_out_of_range",
    ),
]


@pytest.mark.parametrize(("method", "suffix", "body", "field", "code"), HUGE_CASES)
def test_huge_json_numbers_are_validation_errors_not_500(
    shop: Shop,
    admin_conn: psycopg.Connection[Any],
    method: str,
    suffix: str,
    body: str,
    field: str,
    code: str,
) -> None:
    response = raw(shop, method, suffix, body)
    assert response.status_code == 422, response.text
    assert {"field": field, "code": code} in response.json()["errors"], response.json()
    assert HUGE_INT not in response.text and "1e30" not in response.text  # girdi yansıtılmaz
    assert revision_in_db(admin_conn, shop) is None  # hiçbir şey yazılmadı


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_numbers_are_validation_errors(shop: Shop, literal: str) -> None:
    for suffix, body in (
        ("/defaults", f'{{"default_desi":{literal}}}'),
        (
            "/service-fee-estimates",
            f'{{"valid_from":"2026-01-01","amount":{literal},"amount_includes_vat":true}}',
        ),
    ):
        response = raw(shop, "PUT", suffix, body)
        assert response.status_code == 422, (suffix, response.text)


def test_validator_wrapper_turns_arithmetic_errors_into_validation_errors() -> None:
    """Genel güvence: kural işlevinden kaçan `decimal.InvalidOperation` pydantic hatasına çevrilir."""

    def exploding(_: object) -> object:
        raise InvalidOperation

    with pytest.raises(PydanticCustomError) as caught:
        schemas._run(exploding, 1)
    assert caught.value.type == "decimal_invalid"


# --------------------------------------------------------------------------- AD-02: okuma hız sınırı
def test_read_endpoints_are_rate_limited_per_tenant_with_a_separate_counter(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_read_tenant=3)
    assert shop.api.get(url(shop)).status_code == 200
    assert shop.api.get(url(shop, "/carriers")).status_code == 200  # iki uç aynı kiracı sayacını paylaşır
    assert shop.api.get(url(shop)).status_code == 200
    limited = shop.api.get(url(shop, "/carriers"))
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert limited.json()["type"] == "urn:netkar:problem:rate-limited"
    assert shop.api.get(url(shop)).status_code == 429
    keys = [
        r[0] for r in admin_conn.execute("SELECT key FROM rate_limits WHERE key LIKE 'profit-settings%%'")
    ]
    assert len(keys) == 1 and keys[0].startswith("profit-settings-read:tenant:")
    # yazma sayacı ayrıdır: okuma sınırı dolu olsa da yazım geçer
    assert put_fee(shop).status_code == 200


def test_read_limit_is_per_tenant_and_default_is_generous(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    a = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_read_tenant=1)
    b = make_shop("b@example.com", "Mağaza B", seller_id="9999", rate_limit_profit_settings_read_tenant=1)
    assert a.api.get(url(a)).status_code == 200
    assert a.api.get(url(a)).status_code == 429
    assert b.api.get(url(b)).status_code == 200  # başka kiracı etkilenmez


def test_unknown_account_is_404_before_the_limiter(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_read_tenant=1)
    other = "/v1/marketplace-accounts/00000000-0000-4000-8000-000000000001/profit-settings"
    assert shop.api.get(other).status_code == 404
    assert shop.api.get(other).status_code == 404  # sınıra sayılmaz: hesap yoksa sayaç yazılmaz
    assert shop.api.get(url(shop)).status_code == 200


# --------------------------------------------------------------------------- AD-03: downgrade veri koruması
def tables(conn: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}


def test_downgrade_is_refused_when_settings_data_exists(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", raising=False)
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    try:
        with pytest.raises(RuntimeError) as caught:
            command.downgrade(alembic_cfg, "0006")
        message = str(caught.value)
        # Mesaj Türkçe, hangi tabloda kaç satır olduğunu ve ne yapılacağını söyler.
        assert "0007" in message and "yedek" in message.lower()
        assert "NETKAR_ALLOW_SETTINGS_DATA_LOSS=1" in message
        assert "cargo_tariffs" in message
        # Hiçbir şey değişmedi: tablolar, veri, sürüm ve FORCE RLS yerinde.
        assert set(TABLES) <= tables(admin_conn)
        for table in TABLES:
            assert admin_conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,), table
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0007",)
        forced = admin_conn.execute(
            "SELECT bool_and(relforcerowsecurity) FROM pg_class WHERE relname = ANY(%s)", (list(TABLES),)
        ).fetchone()
        assert forced == (True,)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_with_explicit_flag_drops_the_data_and_is_reversible(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    monkeypatch.setenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", "1")
    try:
        command.downgrade(alembic_cfg, "0006")
        assert not (set(TABLES) & tables(admin_conn))
        command.upgrade(alembic_cfg, "head")
        assert admin_conn.execute("SELECT count(*) FROM cargo_tariffs").fetchone() == (0,)
    finally:
        command.upgrade(alembic_cfg, "head")


@pytest.mark.parametrize("value", ["0", "", "yes", "true", "2"])
def test_only_the_exact_flag_value_allows_data_loss(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    monkeypatch.setenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", value)
    try:
        with pytest.raises(RuntimeError):
            command.downgrade(alembic_cfg, "0006")
        assert set(TABLES) <= tables(admin_conn)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_of_empty_settings_tables_needs_no_flag(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", raising=False)
    try:
        command.downgrade(alembic_cfg, "0006")
        assert not (set(TABLES) & tables(admin_conn))
        assert {"products", "product_costs", "orders", "sync_runs"} <= tables(admin_conn)  # 0006 etkilenmedi
    finally:
        command.upgrade(alembic_cfg, "head")


def test_a_single_row_in_any_one_table_blocks_the_downgrade(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", raising=False)
    seller = make_seller(admin_conn)
    admin_conn.execute(
        "INSERT INTO service_fee_estimates (revision_from, tenant_id, marketplace_account_id, valid_from, amount, "
        "amount_includes_vat, entered_by) VALUES (1, %s, %s, '2026-01-01', 12, true, %s)",
        (seller.tenant_id, seller.account_id, seller.user_id),
    )
    try:
        with pytest.raises(RuntimeError) as caught:
            command.downgrade(alembic_cfg, "0006")
        assert "service_fee_estimates" in str(caught.value)
    finally:
        command.upgrade(alembic_cfg, "head")
