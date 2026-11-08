"""S2 denetimi regresyon testleri: PoC'lerin (docs/security/poc_denetim_s2.py.txt) tersi.

Her test, denetimdeki bir bulgunun KAPANDIĞINI doğrular (PoC testleri bulgu varken geçiyordu; bunlar
düzeltme sonrası geçer). Rapor: docs/security/denetim_2026-11-07_S2.md, "Kapanış durumu".
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any
from uuid import uuid4

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import event

from app.core.config import Settings
from app.core.crypto import DecryptionError
from app.core.envelope import EnvelopeCipher, KeyRing
from app.db.rls import set_rls_context
from app.db.session import create_engine, create_sessionmaker
from app.integrations.trendyol import (
    TrendyolConfig,
    TrendyolError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolValidationError,
    TrendyolWaitBudgetError,
)
from app.integrations.trendyol import client as client_module
from app.integrations.trendyol.ratelimit import (
    EndpointGroup,
    RateLimiterRegistry,
    RateLimitWaitExceededError,
)
from app.models import MarketplaceAccount
from app.services.marketplace_accounts import (
    decrypt_credentials,
    default_client_factory,
    encrypt_secret,
    find_live_account,
)
from tests.conftest import Api, DatabaseInfo
from tests.test_envelope import new_key
from tests.test_marketplace_accounts import API_KEY, API_SECRET, URL, FakeTrendyol, body
from tests.test_rls_idor import app_tx
from tests.trendyol_helpers import (
    PII_SENTINELS,
    FakeTime,
    credentials,
    json_response,
    load_fixture,
    make_client,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


@pytest.fixture
def trendyol() -> FakeTrendyol:
    return FakeTrendyol()


@pytest.fixture
def make_ty_api(trendyol: FakeTrendyol, make_api: Callable[..., Api]) -> Callable[..., Api]:
    def _make(**overrides: Any) -> Api:
        return make_api(trendyol_client_factory=trendyol.factory, **overrides)

    return _make


def new_envelope() -> EnvelopeCipher:
    return EnvelopeCipher(KeyRing.parse(f"k1:{new_key()}", "k1"))


async def collect[T](iterator: Any) -> list[T]:
    return [item async for item in iterator]


# --- D-01: ham yanıt traceback çerçeve yerellerinde kalmaz -------------------------------------


def frame_leaks(exc: BaseException, suffix: str = "integrations/trendyol/client.py") -> list[str]:
    """İstemci çerçevelerinin yerellerinde (derinlemesine) bulunan PII sentinel değerleri."""
    found: set[str] = set()
    seen: set[int] = set()

    def check(text: str) -> None:
        found.update(s for s in PII_SENTINELS if s in text)

    def walk(obj: object, depth: int = 0) -> None:
        if depth > 8 or id(obj) in seen:
            return
        seen.add(id(obj))
        if isinstance(obj, str):
            check(obj)
        elif isinstance(obj, bytes | bytearray):
            check(bytes(obj).decode("latin-1"))
        elif isinstance(obj, dict):
            for key, value in obj.items():
                walk(key, depth + 1)
                walk(value, depth + 1)
        elif isinstance(obj, list | tuple | set | frozenset):
            for value in obj:
                walk(value, depth + 1)
        elif isinstance(obj, httpx.Response):
            try:
                walk(obj.content, depth + 1)
            except httpx.ResponseNotRead:
                pass
        else:
            check(repr(obj))

    seen_exc: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen_exc:
        seen_exc.add(id(current))
        tb: TracebackType | None = current.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename.endswith(suffix):
                walk(dict(tb.tb_frame.f_locals))
            tb = tb.tb_next
        current = current.__cause__ or current.__context__
    return sorted(found)


async def test_schema_error_leaves_no_pii_in_traceback_frame_locals() -> None:
    raw = load_fixture("shipment_packages_v2.json")
    raw["content"][0]["shipmentPackageId"] = "sayı-değil"  # şema hatası tetiklenir
    client, _ = make_client(lambda request: json_response(raw))
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.get_shipment_packages()
    assert frame_leaks(info.value) == []
    # Hata nesnesinin kendisi de temiz
    assert not any(s in f"{info.value!r} {info.value.args}" for s in PII_SENTINELS)


async def test_invalid_json_shape_leaves_no_pii_in_frame_locals() -> None:
    pii_list = json.dumps([{"customerFirstName": "SahteAd", "phone": "5550001122"}]).encode()
    client, _ = make_client(lambda request: httpx.Response(200, content=pii_list))
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.get_shipment_packages()
    assert frame_leaks(info.value) == []


async def test_page_model_failure_in_every_endpoint_family_leaves_no_pii() -> None:
    bad = {"content": [{"SahteAd": "SahteSoyad", "id": {"SahteMahalle": 1}}], "totalPages": "x"}
    client, _ = make_client(lambda request: json_response(bad))
    async with client:
        for call in (
            client.get_claims(),
            client.get_questions(),
            client.get_payment_orders(),
            client.get_cargo_invoice_items("F1"),
            client.filter_approved_products(),
            client.get_settlements(["Sale"], start=T0, end=T0 + timedelta(days=1)),
        ):
            with pytest.raises(TrendyolProtocolError) as info:
                await call
            assert frame_leaks(info.value) == []


# --- D-01: Sentry hazırlığı (Sentry'nin kendisi eklenmedi) -------------------------------------


def test_scrub_event_removes_locals_bodies_cookies_and_personal_headers() -> None:
    from app.core.privacy import scrub_event

    event_payload: dict[str, Any] = {
        "exception": {
            "values": [
                {
                    "type": "TrendyolProtocolError",
                    "value": "SahteAd iletide",
                    "stacktrace": {
                        "frames": [
                            {"function": "f", "vars": {"data": "SahteAd", "token": "x"}, "filename": "a.py"},
                            {"function": "g", "filename": "b.py"},
                        ]
                    },
                }
            ]
        },
        "request": {
            "url": "https://x.test/v1/y",
            "method": "POST",
            "data": {"api_key": "gizli"},
            "cookies": {"sid": "abc"},
            "query_string": "k=v",
            "headers": {
                "Authorization": "Basic abc",
                "Cookie": "sid=abc",
                "X-CSRF-Token": "t",
                "User-Agent": "ua",
            },
        },
        "user": {"id": "u1", "email": "a@b.c", "ip_address": "1.2.3.4", "username": "n"},
        "breadcrumbs": {"values": [{"message": "m", "data": {"SahteAd": 1}, "category": "log"}]},
        "extra": {"payload": "SahteAd"},
        "contexts": {"trace": {"trace_id": "t"}},
    }
    out = scrub_event(event_payload, {})
    assert out is not None
    frames = out["exception"]["values"][0]["stacktrace"]["frames"]
    assert all("vars" not in f for f in frames) and frames[0]["function"] == "f"
    assert "data" not in out["request"] and "cookies" not in out["request"]
    assert "query_string" not in out["request"]
    assert {k.lower() for k in out["request"]["headers"]} == {"user-agent"}
    assert out["user"] == {"id": "u1"}
    assert all("data" not in b for b in out["breadcrumbs"]["values"])
    assert "extra" not in out
    assert out["contexts"] == {"trace": {"trace_id": "t"}}
    assert "SahteAd" not in json.dumps(out).replace("SahteAd iletide", "")


def test_scrub_event_tolerates_sparse_events() -> None:
    from app.core.privacy import scrub_event

    assert scrub_event({}, {}) == {}
    assert scrub_event({"exception": {"values": [{"type": "X"}]}, "request": {}}, {}) == {
        "exception": {"values": [{"type": "X"}]},
        "request": {},
    }


def test_sentry_options_are_privacy_preserving() -> None:
    from app.core.privacy import scrub_event, sentry_init_options

    options = sentry_init_options()
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["before_send"] is scrub_event
    assert callable(options["before_breadcrumb"])
    crumb = options["before_breadcrumb"]({"message": "m", "data": {"k": "SahteAd"}}, {})
    assert "data" not in crumb


# --- D-02: bağlantı doğrulamada bekleme bütçesi ------------------------------------------------


def test_validation_request_does_not_sleep_long_on_retry_after(
    make_ty_api: Callable[..., Api], trendyol: FakeTrendyol, admin_conn: psycopg.Connection
) -> None:
    api = make_ty_api()
    api.signup_and_login("o@example.com", tenant="Mağaza")
    trendyol.status = 429
    trendyol.headers = {"Retry-After": "3600"}
    r = api.post(URL, body())
    assert r.status_code == 503 and r.json()["type"].endswith("marketplace-busy")
    assert r.headers["retry-after"] == "30"
    assert sum(trendyol.fake.sleeps) <= 5.0
    audit = admin_conn.execute(
        "SELECT meta FROM audit_log WHERE action = 'marketplace_account.validation_failed'"
    ).fetchall()
    assert audit == [({"reason": "rate_limited"},)]


async def test_shared_limiter_penalty_does_not_stall_other_tenant_beyond_budget() -> None:
    fake = FakeTime()
    shared = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return json_response({}, 429, {"Retry-After": "60"})
        return json_response(load_fixture("inventory_and_price.json"))

    config = TrendyolConfig(max_retries=0, max_total_wait=5.0)
    first, _ = make_client(handler, fake=fake, limiter=shared, config=config)
    async with first:
        with pytest.raises(TrendyolRateLimitedError):
            await first.verify_connection()
    second, _ = make_client(handler, fake=fake, limiter=shared, config=config)
    async with second:
        with pytest.raises(TrendyolWaitBudgetError):
            await second.verify_connection()
    # Beklemeden vazgeçildi, Trendyol'a ikinci istek gitmedi, toplam uyku bütçeyi aşmadı
    assert calls["n"] == 1 and sum(fake.sleeps) <= 5.0


async def test_limiter_acquire_respects_max_wait_without_consuming_tokens() -> None:
    fake = FakeTime()
    limiter = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)
    limiter.penalize("2738", EndpointGroup.PRODUCT_READ, "op", 60.0)
    with pytest.raises(RateLimitWaitExceededError):
        await limiter.acquire("2738", EndpointGroup.PRODUCT_READ, "op", max_wait=2.0)
    assert fake.sleeps == []  # hiç uyunmadı
    # Sınır yeterliyse bekler
    waited = await limiter.acquire("2738", EndpointGroup.PRODUCT_READ, "op", max_wait=120.0)
    assert waited == pytest.approx(60.0)


async def test_sync_jobs_may_still_wait_long_when_budget_is_unlimited() -> None:
    fake = FakeTime()
    responses = iter([json_response({}, 429, {"Retry-After": "45"}), json_response({"content": []})])
    client, _ = make_client(
        lambda request: next(responses),
        fake=fake,
        config=TrendyolConfig(max_retries=2, max_total_wait=None),
    )
    async with client:
        await client.get_payment_orders()
    assert max(fake.sleeps) >= 45.0  # senkron işte uzun bekleme serbest


async def test_budget_exceeded_on_5xx_and_network_errors_keeps_natural_error_types() -> None:
    config = TrendyolConfig(max_retries=3, max_total_wait=0.2, backoff_base=1.0)
    client, fake = make_client(lambda request: json_response({}, 503), config=config)
    async with client:
        with pytest.raises(TrendyolError) as info:
            await client.verify_connection()
    assert not isinstance(info.value, TrendyolRateLimitedError) and fake.sleeps == []

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    client, fake = make_client(boom, config=config)
    async with client:
        with pytest.raises(TrendyolNetworkError):
            await client.verify_connection()
    assert fake.sleeps == []


def test_default_factory_applies_wait_budget_and_retries(settings: Settings) -> None:
    factory = default_client_factory(settings)
    client = factory(credentials(), max_retries=1, max_wait=5.0)
    assert client._config.max_total_wait == 5.0 and client._config.max_retries == 1
    unlimited = factory(credentials())
    assert unlimited._config.max_total_wait is None


def test_slow_trendyol_hits_total_deadline_and_returns_502(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection
) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return json_response(load_fixture("inventory_and_price.json"))

    def factory(creds: Any, *, max_retries: int | None = None, max_wait: float | None = None) -> Any:
        from app.integrations.trendyol import TrendyolClient

        return TrendyolClient(creds, TrendyolConfig(max_retries=0), transport=httpx.MockTransport(slow))

    api = make_api(trendyol_client_factory=factory, trendyol_validation_deadline_seconds=0.2)
    api.signup_and_login("slow@example.com", tenant="Mağaza")
    r = api.post(URL, body())
    assert r.status_code == 502 and r.json()["type"].endswith("marketplace-unavailable")
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
    reasons = admin_conn.execute(
        "SELECT meta FROM audit_log WHERE action = 'marketplace_account.validation_failed'"
    ).fetchall()
    assert reasons == [({"reason": "unavailable"},)]


# --- D-03: çözme, özyineleme, boyut ve JSON hataları Trendyol hata türlerine eşlenir -------------


def gzip_broken(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, stream=httpx.ByteStream(b"gzip-degil"), headers={"Content-Encoding": "gzip"})


async def test_decoding_error_maps_to_protocol_error_without_chaining() -> None:
    client, _ = make_client(gzip_broken)
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.verify_connection()
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert "Authorization" not in repr(info.value)


async def test_deeply_nested_json_maps_to_protocol_error() -> None:
    deep = b'{"a":' + b"[" * 100_000 + b"]" * 100_000 + b"}"
    client, _ = make_client(lambda request: httpx.Response(200, content=deep))
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.verify_connection()
    assert info.value.__cause__ is None and info.value.__context__ is None


@pytest.mark.parametrize("content", [b"", b"{", b"\xff\xfe", b"[]", b'"x"', b"null", b"1e999999999999"])
async def test_non_object_or_malformed_bodies_map_to_protocol_error(content: bytes) -> None:
    client, _ = make_client(lambda request: httpx.Response(200, content=content))
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await client.verify_connection()


async def test_oversized_body_is_rejected_before_parsing() -> None:
    big = b'{"content": [], "pad": "' + b"a" * 4096 + b'"}'
    config = TrendyolConfig(max_retries=0, max_response_bytes=1024)
    client, _ = make_client(lambda request: httpx.Response(200, content=big), config=config)
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await client.verify_connection()
    # Content-Length ile de erken ret (gövde okunmadan)
    client, _ = make_client(
        lambda request: httpx.Response(200, content=b"{}", headers={"Content-Length": "999999"}),
        config=config,
    )
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await client.verify_connection()


async def test_body_just_under_the_limit_is_accepted() -> None:
    payload = json.dumps({"content": [], "totalElements": 0}).encode()
    config = TrendyolConfig(max_retries=0, max_response_bytes=len(payload))
    client, _ = make_client(lambda request: httpx.Response(200, content=payload), config=config)
    async with client:
        assert (await client.filter_inventory_and_price()).total_elements == 0


async def test_non_2xx_bodies_are_not_read() -> None:
    class Exploding(httpx.AsyncByteStream):
        async def __aiter__(self) -> Any:
            raise AssertionError("hata yanıtının gövdesi okunmamalı")
            yield b""  # pragma: no cover

    client, _ = make_client(
        lambda request: httpx.Response(403, stream=Exploding()), config=TrendyolConfig(max_retries=0)
    )
    async with client:
        with pytest.raises(TrendyolError) as info:
            await client.verify_connection()
    assert info.value.status == 403


@pytest.mark.parametrize(
    "handler_name", ["gzip", "deep", "oversized"]
)  # uç nokta: 502 + denetim kaydı (500 değil)
def test_connect_endpoint_maps_response_errors_to_502_and_audits(
    handler_name: str,
    make_ty_api: Callable[..., Api],
    trendyol: FakeTrendyol,
    admin_conn: psycopg.Connection,
) -> None:
    handlers: dict[str, Callable[[httpx.Request], httpx.Response]] = {
        "gzip": gzip_broken,
        "deep": lambda r: httpx.Response(200, content=b"[" * 100_000 + b"]" * 100_000),
        "oversized": lambda r: httpx.Response(200, content=b"{" + b" " * (21 * 1024 * 1024) + b"}"),
    }
    trendyol.handler = handlers[handler_name]  # type: ignore[method-assign,assignment]
    api = make_ty_api()
    api.signup_and_login(f"d{handler_name}@example.com", tenant="Mağaza")
    r = api.post(URL, body())
    assert r.status_code == 502 and r.json()["type"].endswith("marketplace-unavailable")
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
    audit = admin_conn.execute(
        "SELECT action, meta FROM audit_log WHERE action LIKE 'marketplace_account.%'"
    ).fetchall()
    assert audit == [("marketplace_account.validation_failed", {"reason": "unavailable"})]


# --- D-04: AAD kiracıyı, platformu ve satıcıyı bağlar --------------------------------------------


def make_account(envelope: EnvelopeCipher, **overrides: Any) -> MarketplaceAccount:
    base: dict[str, Any] = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "platform": "trendyol",
        "seller_id": "1111",
    }
    base.update(overrides)
    account = MarketplaceAccount(**base)
    account.api_key_encrypted = encrypt_secret(envelope, account, "api_key", SecretStr(API_KEY))
    account.api_secret_encrypted = encrypt_secret(envelope, account, "api_secret", SecretStr(API_SECRET))
    return account


def test_aad_binds_tenant_platform_seller_account_and_field() -> None:
    envelope = new_envelope()
    original = make_account(envelope)
    creds = decrypt_credentials(envelope, original)
    assert creds.api_key.get_secret_value() == API_KEY and creds.seller_id == "1111"

    def moved(**changes: Any) -> MarketplaceAccount:
        values: dict[str, Any] = {
            "id": original.id,
            "tenant_id": original.tenant_id,
            "platform": original.platform,
            "seller_id": original.seller_id,
            "api_key_encrypted": original.api_key_encrypted,
            "api_secret_encrypted": original.api_secret_encrypted,
        }
        values.update(changes)
        return MarketplaceAccount(**values)

    for changes in ({"tenant_id": uuid4()}, {"seller_id": "2222"}, {"id": uuid4()}, {"platform": "hepsi"}):
        with pytest.raises(DecryptionError):
            decrypt_credentials(envelope, moved(**changes))
    # Alanlar yer değiştirirse de çözülmez
    with pytest.raises(DecryptionError):
        decrypt_credentials(
            envelope,
            moved(
                api_key_encrypted=original.api_secret_encrypted,
                api_secret_encrypted=original.api_key_encrypted,
            ),
        )


# --- D-05: netkar_app yetkileri daraldı; find_live_account şifreli sütunları yüklemez -----------


NEEDED_UPDATE = {
    "api_key_encrypted",
    "api_secret_encrypted",
    "api_key_last4",
    "status",
    "last_validated_at",
    "updated_at",
    "revoked_at",
}


def privileges(admin_conn: psycopg.Connection) -> dict[str, tuple[bool, bool]]:
    rows = admin_conn.execute(
        "SELECT column_name, has_column_privilege('netkar_app', 'marketplace_accounts', column_name, 'SELECT'),"
        " has_column_privilege('netkar_app', 'marketplace_accounts', column_name, 'UPDATE') "
        "FROM information_schema.columns WHERE table_name = 'marketplace_accounts'"
    ).fetchall()
    return {name: (sel, upd) for name, sel, upd in rows}


def test_app_role_may_update_only_needed_columns(admin_conn: psycopg.Connection) -> None:
    priv = privileges(admin_conn)
    assert {c for c, (_, upd) in priv.items() if upd} == NEEDED_UPDATE
    for column in ("id", "tenant_id", "platform", "seller_id", "created_by", "created_at"):
        assert priv[column][1] is False, column
    # Okuma: netkar_app şifreli sütunlar HARİÇ her şeyi okur (D-05 kapandı, migrasyon 0006; ADR-0005 §6).
    assert {c for c, (sel, _) in priv.items() if not sel} == {"api_key_encrypted", "api_secret_encrypted"}


def test_app_role_cannot_rewrite_identity_columns(
    make_ty_api: Callable[..., Api], database: DatabaseInfo
) -> None:
    api = make_ty_api()
    api.signup_and_login("p@example.com", tenant="Mağaza")
    account_id = api.post(URL, body()).json()["id"]
    tenant = api.get("/v1/me").json()["tenant"]["id"]
    for column, value in (
        ("seller_id", "'9999'"),
        ("created_at", "'2000-01-01'"),
        ("tenant_id", f"'{uuid4()}'"),
        ("created_by", f"'{uuid4()}'"),
        ("platform", "'trendyol'"),
    ):
        with app_tx(database, tenant) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"UPDATE marketplace_accounts SET {column} = {value} WHERE id = %s", (account_id,))
    # Gerekli sütunlar çalışmaya devam eder
    with app_tx(database, tenant) as conn:
        n = conn.execute(
            "UPDATE marketplace_accounts SET status = 'invalid', updated_at = now() WHERE id = %s",
            (account_id,),
        ).rowcount
        assert n == 1


def test_connect_reconnect_and_revoke_flows_work_with_narrow_grants(
    make_ty_api: Callable[..., Api], admin_conn: psycopg.Connection
) -> None:
    api = make_ty_api()
    api.signup_and_login("flow@example.com", tenant="Mağaza")
    account_id = api.post(URL, body()).json()["id"]
    admin_conn.execute("UPDATE marketplace_accounts SET status = 'invalid'")
    assert api.post(URL, body(api_key="YeniAnahtar123456")).status_code == 201
    assert api.post(f"{URL}/{account_id}/revoke").status_code == 200
    assert api.post(URL, body()).status_code == 201


async def test_find_live_account_does_not_select_encrypted_columns(
    make_ty_api: Callable[..., Api], database: DatabaseInfo
) -> None:
    api = make_ty_api()
    api.signup_and_login("f@example.com", tenant="Mağaza")
    api.post(URL, body())
    tenant_id = api.get("/v1/me").json()["tenant"]["id"]
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _capture(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
        statements.append(statement)

    from uuid import UUID

    try:
        async with create_sessionmaker(engine)() as session:
            await set_rls_context(session, UUID(tenant_id))
            account = await find_live_account(session, UUID(tenant_id), "2738")
            assert account is not None and account.seller_id == "2738"
            await session.rollback()
    finally:
        await engine.dispose()
    select_sql = " ".join(s for s in statements if "marketplace_accounts" in s)
    assert select_sql and "api_key_encrypted" not in select_sql and "api_secret_encrypted" not in select_sql


def test_grant_migration_is_reversible(alembic_cfg: Config, admin_conn: psycopg.Connection) -> None:
    try:
        command.downgrade(alembic_cfg, "0004")
        priv = privileges(admin_conn)
        assert priv["tenant_id"][1] is True and priv["seller_id"][1] is True  # 0004'teki geniş yetki
        command.upgrade(alembic_cfg, "head")
        assert {c for c, (_, upd) in privileges(admin_conn).items() if upd} == NEEDED_UPDATE
    finally:
        command.upgrade(alembic_cfg, "head")


# --- D-06: platform geneli tavan ve kiracı başına limit --------------------------------------------


def test_global_cap_stops_outbound_validation_calls_across_tenants_and_ips(
    make_ty_api: Callable[..., Api], trendyol: FakeTrendyol, frozen_ratelimit_clock: float
) -> None:
    # Sınırlayıcı sabit dakika penceresi kullanır (ADR-0001). Test bir dakika sınırına denk gelirse
    # sayaç sıfırlanır ve 5 yerine 10 çağrı geçerdi (CI'da görüldü); saat fixture ile sabit.
    trendyol.status = 401
    sent, blocked = 0, 0
    for i in range(3):
        api = make_ty_api(peer=f"203.0.113.{10 + i}", rate_limit_marketplace_global_per_minute=5)
        api.signup_and_login(f"x{i}@example.com", tenant=f"Mağaza {i}")
        for j in range(10):
            r = api.post(URL, body(seller_id=str(1000 + j)))
            if r.status_code == 422:
                sent += 1
            else:
                assert r.status_code == 503 and r.json()["type"].endswith("marketplace-busy")
                assert int(r.headers["retry-after"]) >= 1
                blocked += 1
    assert sent == 5 and blocked == 25
    assert len(trendyol.requests) == 5  # sınır aşılınca Trendyol'a gidilmedi


def test_tenant_cap_is_checked_before_global_cap(
    make_ty_api: Callable[..., Api], trendyol: FakeTrendyol
) -> None:
    """Tek kiracı kendi sınırında durur ve platform sayacını tüketmeye devam etmez."""
    trendyol.status = 401
    api = make_ty_api(rate_limit_marketplace_tenant=2, rate_limit_marketplace_global_per_minute=3)
    api.signup_and_login("t@example.com", tenant="Mağaza")
    codes = [api.post(URL, body()).status_code for _ in range(6)]
    assert codes == [422, 422, 429, 429, 429, 429]
    other = make_ty_api(rate_limit_marketplace_tenant=2, rate_limit_marketplace_global_per_minute=3)
    other.signup_and_login("t2@example.com", tenant="Mağaza 2")
    assert other.post(URL, body()).status_code == 422  # genel sayaçta yer kaldı (2 kullanıldı)


# --- B-02: kargo faturası seri numarası -----------------------------------------------------------


@pytest.mark.parametrize(
    "serial",
    [
        ".",
        "..",
        "a..b",
        ".gizli",
        "a.",
        "../x",
        "a/b",
        "a\\b",
        "a b",
        "a?x",
        "a#x",
        "%2e%2e",
        "x" * 65,
        "ş",
        "",
    ],
)
async def test_cargo_serial_rejects_dot_segments_and_unsafe_characters(serial: str) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_cargo_invoice_items(serial)


@pytest.mark.parametrize("serial", ["FAT2026000123", "F1", "A-1_2", "A1.2", "1234567890", "x" * 64])
async def test_cargo_serial_accepts_documented_shapes(serial: str) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return json_response({"content": [], "totalPages": 0})

    client, _ = make_client(handler)
    async with client:
        await client.get_cargo_invoice_items(serial)
    assert seen == [f"/integration/finance/che/sellers/2738/cargo-invoice/{serial}/items"]


# --- B-04: ortam değişkenlerinden vekil ve CA güveni alınmaz --------------------------------------


def test_http_client_ignores_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/ca.pem")
    from app.integrations.trendyol import TrendyolClient

    client = TrendyolClient(credentials(), TrendyolConfig())  # taşıma verilmedi: gerçek taşıma kurulur
    assert client._http.trust_env is False
    assert client._http._mounts == {}  # ortamdan vekil bağlanmadı


# --- Kod kalitesi: totalPages yoksa sessiz durma yok -------------------------------------------


def paged(fixture: str, pages: list[int], *, total_pages: Any = "yok", total_elements: Any = None) -> Any:
    """`pages[i]`: i. sayfadaki kayıt sayısı. Kayıtlar fixture'ın ilk kaydından çoğaltılır."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        calls.append(page)
        data = load_fixture(fixture)
        template = data["content"][0]
        count = pages[page] if page < len(pages) else 0
        data["content"] = [json.loads(json.dumps(template)) for _ in range(count)]
        data.pop("totalPages", None)
        data.pop("totalElements", None)
        if total_pages != "yok":
            data["totalPages"] = total_pages
        if total_elements is not None:
            data["totalElements"] = total_elements
        return json_response(data)

    return handler, calls


ITERATORS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "shipments": (
        "shipment_packages_v2.json",
        lambda c: c.iter_shipment_packages(T0, T0 + timedelta(days=1)),
    ),
    "claims": ("claims.json", lambda c: c.iter_claims()),
    "settlements": (
        "settlements.json",
        lambda c: c.iter_settlements(["Sale"], T0, T0 + timedelta(days=1)),
    ),
    "other_financials": (
        "other_financials.json",
        lambda c: c.iter_other_financials(["DeductionInvoices"], T0, T0 + timedelta(days=1)),
    ),
    "cargo": ("cargo_invoice_items.json", lambda c: c.iter_cargo_invoice_items("F1")),
    "questions": ("questions.json", lambda c: c.iter_questions(T0, T0 + timedelta(days=1))),
    "products": ("approved_products.json", lambda c: c.iter_approved_products()),
}


@pytest.mark.parametrize("name", sorted(ITERATORS))
async def test_missing_total_pages_continues_until_empty_page(name: str) -> None:
    fixture, build = ITERATORS[name]
    handler, calls = paged(fixture, [2, 3])
    client, _ = make_client(handler)
    async with client:
        items: list[Any] = await collect(build(client))
    assert len(items) == 5 and calls == [0, 1, 2]  # boş sayfaya kadar gidildi


@pytest.mark.parametrize("name", sorted(ITERATORS))
async def test_missing_total_pages_stops_when_total_elements_is_reached(name: str) -> None:
    fixture, build = ITERATORS[name]
    handler, calls = paged(fixture, [2, 3], total_elements=5)
    client, _ = make_client(handler)
    async with client:
        items: list[Any] = await collect(build(client))
    assert len(items) == 5 and calls == [0, 1]


@pytest.mark.parametrize("name", sorted(ITERATORS))
async def test_missing_pages_raise_instead_of_silent_truncation(name: str) -> None:
    fixture, build = ITERATORS[name]
    handler, _ = paged(fixture, [2], total_elements=5000)  # 5000 denmiş, 2 gelmiş, sonra boş
    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolProtocolError, match="eksik"):
            await collect(build(client))


@pytest.mark.parametrize("name", sorted(ITERATORS))
async def test_endless_pagination_is_bounded_and_raises(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture, build = ITERATORS[name]
    monkeypatch.setattr(client_module, "_MAX_ITER_PAGES", 4)
    handler, calls = paged(fixture, [1] * 50)  # bitmeyen sayfalama, totalPages yok
    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolProtocolError, match="sınır"):
            await collect(build(client))
    assert len(calls) <= 5


async def test_known_total_pages_behaviour_is_unchanged() -> None:
    handler, calls = paged("claims.json", [2, 2, 2], total_pages=2)
    client, _ = make_client(handler)
    async with client:
        assert len(await collect(client.iter_claims())) == 4
    assert calls == [0, 1]


async def test_inflated_total_pages_beyond_window_is_protocol_error() -> None:
    """v2/orders: totalElements pencere içinde ama totalPages şişmiş; 50. sayfa istemci hatası değil
    protokol hatasıdır (denetim notu 2)."""
    handler, _ = paged("shipment_packages_v2.json", [1] * 60, total_pages=63, total_elements=100)
    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await collect(client.iter_shipment_packages(T0, T0 + timedelta(days=1)))


# --- Ek kapsam: akışla gövde sınırı, yapılandırma doğrulaması, akış/ürün sayfalama sınırları --------


async def test_oversized_streamed_body_without_content_length_is_rejected() -> None:
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self) -> Any:
            for _ in range(10):
                yield b" " * 400  # toplam 4000 bayt, Content-Length yok

    config = TrendyolConfig(max_retries=0, max_response_bytes=1024)
    client, _ = make_client(lambda request: httpx.Response(200, stream=Chunks()), config=config)
    async with client:
        with pytest.raises(TrendyolProtocolError, match="üst sınır"):
            await client.verify_connection()


@pytest.mark.parametrize("kwargs", [{"max_total_wait": -1.0}, {"max_response_bytes": 0}])
def test_config_rejects_invalid_budget_values(kwargs: dict[str, Any]) -> None:
    from app.integrations.trendyol import TrendyolConfigError

    with pytest.raises(TrendyolConfigError):
        TrendyolConfig(**kwargs)


async def test_endless_stream_cursor_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_MAX_ITER_PAGES", 3)
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        counter["n"] += 1
        data = load_fixture("shipment_packages_stream_p1.json")
        data.update(hasMore=True, nextCursor=f"c{counter['n']}")
        return json_response(data)

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolProtocolError, match="sınır"):
            await collect(client.iter_shipment_packages_stream(T0, T0 + timedelta(days=1)))


async def test_products_token_mode_stops_on_empty_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "0"))
        data = load_fixture("approved_products.json")
        data.update(totalPages=500, totalElements=50_000, nextPageToken="T")
        if page >= 99:
            data["content"] = []
        return json_response(data)

    client, _ = make_client(handler)
    async with client:
        items: list[Any] = await collect(client.iter_approved_products(size=100))
    assert len(items) == 99
