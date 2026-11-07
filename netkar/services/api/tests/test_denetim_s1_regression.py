"""Denetim S1 (docs/security/denetim_2026-11-06_S1.md) regresyon testleri.

Denetçinin PoC testleri (docs/security/poc_denetim_s1_7728f52.py.txt) bulgu VARKEN geçecek biçimde
yazılmıştı. Buradaki testler onların TERSİDİR: bulgu kapandığında geçer, geri gelirse kırılır.
Her test, kapattığı bulgunun numarasıyla adlandırılmıştır (y01, o01, o02, o03, o04, d04, d06, d08).
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core import security
from app.core.config import Settings
from app.core.logging import JsonFormatter, MaskingFilter, configure_logging, mask_text
from app.core.security import PasswordWorker, hash_password
from app.db.rls import set_rls_context
from app.db.session import create_engine
from app.services.auth import consume_totp_step
from tests.conftest import GOOD_PASSWORD, TEST_KEY, Api, DatabaseInfo, FakeClock
from tests.test_password_reset import NEW_PASSWORD, _token_from
from tests.test_totp import _enable_totp

TRUSTED_NET = [ipaddress.ip_network("172.16.0.0/12")]
WEB_PEER = "172.18.0.5"  # Next.js (BFF) konteynerinin API'ye görünen adresi


def _xff(value: str) -> dict[str, str]:
    return {"X-Forwarded-For": value}


# --- Y-01: istemci IP'si, vekil güveni, rate limit ------------------------------------------
@pytest.fixture(params=["cidr", "hops"])
def proxy_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Aynı davranışı veren iki güvenilir vekil yapılandırması."""
    if request.param == "cidr":
        return {"trusted_proxy_cidrs": TRUSTED_NET}
    return {"trusted_proxy_hops": 1}


def test_y01_spoofed_xff_cannot_bypass_ip_limit(
    make_api: Callable[..., Api], proxy_config: dict[str, Any]
) -> None:
    """PoC: en sağdaki XFF'yi döndürerek sınır aşılıyordu. Şimdi sol (sahte) değerler yok sayılır."""
    api = make_api(peer=WEB_PEER, rate_limit_login_ip=2, rate_limit_login_email=1000, **proxy_config)
    codes = [
        api.post(
            "/v1/auth/login",
            {"email": f"u{i}@example.com", "password": "x"},
            # Sol taraf istemcinin yazdığı sahte zincir, sağ taraf vekilin gördüğü gerçek istemci.
            headers=_xff(f"10.0.{i // 250}.{i % 250}, 203.0.113.7"),
        ).status_code
        for i in range(20)
    ]
    assert codes == [401, 401] + [429] * 18


def test_y01_untrusted_peer_cannot_use_xff(make_api: Callable[..., Api]) -> None:
    """Eş adres güvenilir listede değilse başlık (sağdaki değer dahil) yok sayılır."""
    api = make_api(peer="198.51.100.9", trusted_proxy_cidrs=TRUSTED_NET, rate_limit_login_ip=2)
    codes = [
        api.post(
            "/v1/auth/login", {"email": f"u{i}@example.com", "password": "x"}, headers=_xff(f"10.0.0.{i}")
        ).status_code
        for i in range(6)
    ]
    assert codes == [401, 401, 429, 429, 429, 429]


def test_y01_without_proxy_config_xff_is_ignored(make_api: Callable[..., Api]) -> None:
    api = make_api(rate_limit_login_ip=2)
    codes = [
        api.post(
            "/v1/auth/login", {"email": f"u{i}@example.com", "password": "x"}, headers=_xff(f"10.0.0.{i}")
        ).status_code
        for i in range(4)
    ]
    assert codes == [401, 401, 429, 429]


def test_y01_distinct_real_clients_do_not_consume_each_others_limit(
    make_api: Callable[..., Api], proxy_config: dict[str, Any]
) -> None:
    """PoC: BFF arkasında tüm kullanıcılar tek kovaydı; bir saldırgan herkesi 429'a düşürüyordu."""
    api = make_api(peer=WEB_PEER, rate_limit_login_ip=3, rate_limit_login_email=1000, **proxy_config)
    attacker, victim = _xff("203.0.113.7"), _xff("198.51.100.20")
    assert (
        api.post(
            "/v1/auth/register",
            {"email": "kurban@example.com", "password": GOOD_PASSWORD, "tenant_name": "Kurban"},
            headers=victim,
        ).status_code
        == 202
    )
    spam = [
        api.post("/v1/auth/login", {"email": f"spam{i}@example.com", "password": "x"}, headers=attacker)
        for i in range(5)
    ]
    assert [r.status_code for r in spam] == [401, 401, 401, 429, 429]
    ok = api.post(
        "/v1/auth/login", {"email": "kurban@example.com", "password": GOOD_PASSWORD}, headers=victim
    )
    assert ok.status_code == 200


def test_y01_ipv6_clients_are_bucketed_by_slash_64(make_api: Callable[..., Api]) -> None:
    api = make_api(peer=WEB_PEER, trusted_proxy_hops=1, rate_limit_login_ip=2, rate_limit_login_email=1000)

    def attempt(address: str) -> int:
        return int(
            api.post(
                "/v1/auth/login", {"email": "a@example.com", "password": "x"}, headers=_xff(address)
            ).status_code
        )

    assert [attempt("2001:db8:1:1::1"), attempt("2001:db8:1:1::2")] == [401, 401]
    assert attempt("2001:db8:1:1:ffff::9") == 429  # aynı /64: aynı kova
    assert attempt("2001:db8:1:2::1") == 401  # başka /64


def test_y01_audit_ip_hash_follows_real_client_not_proxy(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection
) -> None:
    api = make_api(peer=WEB_PEER, trusted_proxy_hops=1)
    api.register("a@example.com")
    api.register("b@example.com")
    assert (
        api.post(
            "/v1/auth/login",
            {"email": "a@example.com", "password": GOOD_PASSWORD},
            headers=_xff("203.0.113.7"),
        ).status_code
        == 200
    )
    other = make_api(peer=WEB_PEER, trusted_proxy_hops=1)
    assert (
        other.post(
            "/v1/auth/login",
            {"email": "b@example.com", "password": GOOD_PASSWORD},
            headers=_xff("203.0.113.8"),
        ).status_code
        == 200
    )
    hashes = [r[0] for r in admin_conn.execute("SELECT ip_hash FROM sessions ORDER BY created_at")]
    assert len(hashes) == 2 and hashes[0] != hashes[1]


def test_y01_proxy_settings_parse_from_environment(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 172.16.0.0/12")
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    loaded = Settings(  # type: ignore[call-arg]
        database_url=settings.database_url, data_encryption_key=TEST_KEY, environment="test"
    )
    assert [str(n) for n in loaded.trusted_proxy_cidrs] == ["10.0.0.0/8", "172.16.0.0/12"]
    assert loaded.trusted_proxy_hops == 2
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "bu-bir-cidr-degil")
    with pytest.raises(ValidationError):
        Settings(database_url=settings.database_url, data_encryption_key=TEST_KEY)  # type: ignore[call-arg]


# --- O-01: TOTP tekrar kullanımı --------------------------------------------------------------
def test_o01_totp_code_replay_rejected(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    owner = make_api()
    owner.signup_and_login("replay@example.com")
    secret = _enable_totp(owner, clock)
    code = clock.code(secret)

    first = make_api()
    assert first.login("replay@example.com").json()["status"] == "totp_required"
    assert first.post("/v1/auth/totp/verify", {"code": code}).status_code == 200

    second = make_api()  # saldırgan aynı kodu yeniden kullanır
    assert second.login("replay@example.com").json()["status"] == "totp_required"
    replay = second.post("/v1/auth/totp/verify", {"code": code})
    assert replay.status_code == 401 and replay.json()["type"].endswith("invalid-code")
    assert second.get("/v1/me").status_code == 401

    stored = admin_conn.execute("SELECT totp_last_step FROM users").fetchone()
    assert stored == (int(clock.now // 30),)
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log")]
    assert "auth.totp_replay" in actions

    # Bir sonraki zaman adımının kodu geçerlidir.
    clock.advance(30)
    assert second.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200


def test_o01_older_time_step_rejected_after_newer_one(make_api: Callable[..., Api], clock: FakeClock) -> None:
    owner = make_api()
    owner.signup_and_login("older@example.com")
    secret = _enable_totp(owner, clock)

    api = make_api()
    api.login("older@example.com")
    assert api.post("/v1/auth/totp/verify", {"code": clock.code(secret, steps=1)}).status_code == 200
    api2 = make_api()
    api2.login("older@example.com")
    assert api2.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 401


def test_o01_enable_consumes_its_time_step(make_api: Callable[..., Api], clock: FakeClock) -> None:
    owner = make_api()
    owner.signup_and_login("enable@example.com")
    setup = owner.post("/v1/auth/totp/setup").json()["secret"]
    code = clock.code(setup)
    assert owner.post("/v1/auth/totp/enable", {"code": code}).status_code == 204
    fresh = make_api()
    fresh.login("enable@example.com")
    assert fresh.post("/v1/auth/totp/verify", {"code": code}).status_code == 401


async def test_o01_concurrent_use_of_same_step_lets_only_one_win(
    make_api: Callable[..., Api], database: DatabaseInfo
) -> None:
    owner = make_api()
    owner.signup_and_login("race@example.com")
    me = owner.get("/v1/me").json()
    user_id, tenant_id = me["user_id"], me["tenant"]["id"]
    engine = create_async_engine(database.app_url.render_as_string(hide_password=False))
    try:

        async def attempt() -> bool:
            async with engine.connect() as conn:
                session = AsyncSession(bind=conn)
                await set_rls_context(session, UUID(tenant_id), UUID(user_id))
                won = await consume_totp_step(session, UUID(user_id), 123456)
                await session.commit()
                return won

        results = await asyncio.gather(*(attempt() for _ in range(6)))
    finally:
        await engine.dispose()
    assert sorted(results) == [False] * 5 + [True]


# --- O-02: TOTP kaba kuvvet kilidi -------------------------------------------------------------
def _totp_user(
    make_api: Callable[..., Api], clock: FakeClock, email: str, **overrides: Any
) -> tuple[Api, str]:
    api = make_api(**overrides)
    api.signup_and_login(email)
    secret = _enable_totp(api, clock)
    api.post("/v1/auth/logout")
    assert api.login(email).json()["status"] == "totp_required"
    return api, secret


def test_o02_account_locks_after_consecutive_failures(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    api, secret = _totp_user(make_api, clock, "lock@example.com", totp_max_failures=3)
    wrong = "000000" if clock.code(secret) != "000000" else "111111"
    assert [api.post("/v1/auth/totp/verify", {"code": wrong}).status_code for _ in range(3)] == [401] * 3
    # Eşik aşıldı: doğru kod bile kabul edilmez
    locked = api.post("/v1/auth/totp/verify", {"code": clock.code(secret)})
    assert locked.status_code == 429
    assert locked.headers["content-type"].startswith("application/problem+json")
    assert locked.json()["type"].endswith("totp-locked") and int(locked.headers["retry-after"]) > 0
    assert api.get("/v1/me").status_code == 401

    row = admin_conn.execute(
        "SELECT totp_failed_count, totp_locked_until > now() FROM users WHERE email = 'lock@example.com'"
    ).fetchone()
    assert row == (3, True)
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions.count("auth.totp_failed") == 3 and actions.count("auth.totp_locked") == 1

    # Kilit süresi dolunca doğru kod geçer ve sayaç sıfırlanır
    admin_conn.execute("UPDATE users SET totp_locked_until = now() - interval '1 second'")
    assert api.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200
    assert admin_conn.execute("SELECT totp_failed_count, totp_locked_until FROM users").fetchone() == (
        0,
        None,
    )


def test_o02_counter_restarts_after_lock_expiry_and_resets_on_success(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    api, secret = _totp_user(make_api, clock, "restart@example.com", totp_max_failures=2)
    wrong = "000000" if clock.code(secret) != "000000" else "111111"
    api.post("/v1/auth/totp/verify", {"code": wrong})
    api.post("/v1/auth/totp/verify", {"code": wrong})  # kilitlendi
    admin_conn.execute("UPDATE users SET totp_locked_until = now() - interval '1 second'")
    # Süresi dolmuş kilitten sonra tek hata yeniden kilitlemez (sayaç 1'den başlar)
    assert api.post("/v1/auth/totp/verify", {"code": wrong}).status_code == 401
    assert admin_conn.execute("SELECT totp_failed_count, totp_locked_until FROM users").fetchone() == (
        1,
        None,
    )
    assert api.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200
    assert admin_conn.execute("SELECT totp_failed_count FROM users").fetchone() == (0,)


def test_o02_replays_also_count_as_failures(make_api: Callable[..., Api], clock: FakeClock) -> None:
    owner = make_api()
    owner.signup_and_login("replaylock@example.com")
    secret = _enable_totp(owner, clock)
    code = clock.code(secret)
    ok = make_api(totp_max_failures=2)
    ok.login("replaylock@example.com")
    assert ok.post("/v1/auth/totp/verify", {"code": code}).status_code == 200
    attacker = make_api(totp_max_failures=2)
    attacker.login("replaylock@example.com")
    assert [attacker.post("/v1/auth/totp/verify", {"code": code}).status_code for _ in range(3)] == [
        401,
        401,
        429,
    ]


def test_o02_default_lock_policy_matches_audit_recommendation() -> None:
    defaults = Settings.model_fields
    assert defaults["totp_max_failures"].default == 5
    assert defaults["totp_lock_seconds"].default == 15 * 60


# --- O-03: argon2 olay döngüsünü bloklamaz -----------------------------------------------------
async def test_o03_argon2_does_not_block_event_loop(
    make_app: Callable[..., object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parola özeti olay döngüsünün dışında çalışır; döngü özet süresince takılmaz.

    Gerçek argon2 süresi CI makinesinin yüküne göre 30-150 ms arasında oynadığından kıyas gürültülüydü.
    Burada özet, süresi bilinen (0,2 sn) ve GIL'i bırakan bir sahte işle değiştirilir; argon2-cffi de
    hesap sırasında GIL'i bırakır. İki bağımsız kanıt aranır:
    1) Özet, olay döngüsünün iş parçacığında ÇALIŞMAZ (belirlenimci).
    2) Olay döngüsündeki en uzun bekleme, tek özet süresinin yarısının altında kalır. Bloklu
       uygulamada her özet döngüyü en az 0,2 sn durdurur; pay 2 kattır.
    """
    hash_seconds = 0.2
    hash_threads: list[int] = []

    def slow_burn(password: str) -> None:
        hash_threads.append(threading.get_ident())
        time.sleep(hash_seconds)

    monkeypatch.setattr(security, "burn_password_verification", slow_burn)
    app = make_app(rate_limit_login_ip=1000, rate_limit_login_email=1000)
    loop_thread = threading.get_ident()

    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):  # type: ignore[attr-defined]
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
            csrf = (await client.get("/v1/auth/csrf")).json()["csrf_token"]
            headers = {"X-CSRF-Token": csrf}
            done = asyncio.Event()

            async def login(i: int) -> int:
                r = await client.post(
                    "/v1/auth/login", json={"email": f"x{i}@example.com", "password": "x"}, headers=headers
                )
                return r.status_code

            async def ticker() -> float:
                # 5 ms aralıklı uyanır; beklenenden fazla geçen süre döngünün takıldığı süredir.
                worst = 0.0
                while not done.is_set():
                    t = time.perf_counter()
                    await asyncio.sleep(0.005)
                    worst = max(worst, time.perf_counter() - t - 0.005)
                return worst

            tick_task = asyncio.create_task(ticker())
            try:
                results = await asyncio.gather(*(login(i) for i in range(8)))
            finally:
                done.set()
            worst_lag = await tick_task

    assert results == [401] * 8
    assert len(hash_threads) == 8, "her bilinmeyen kullanıcı girişi bir özet maliyeti ödemeli"
    assert loop_thread not in hash_threads, "parola özeti olay döngüsünün iş parçacığında çalıştı"
    assert worst_lag < 0.5 * hash_seconds, f"olay döngüsü {worst_lag * 1000:.0f} ms takıldı"


async def test_o03_password_worker_limits_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    lock, state = threading.Lock(), {"active": 0, "peak": 0}

    def slow_hash(password: str) -> str:
        with lock:
            state["active"] += 1
            state["peak"] = max(state["peak"], state["active"])
        time.sleep(0.05)
        with lock:
            state["active"] -= 1
        return f"h:{password}"

    monkeypatch.setattr(security, "hash_password", slow_hash)
    worker = PasswordWorker(concurrency=2)
    results = await asyncio.gather(*(worker.hash(f"p{i}") for i in range(8)))
    assert results == [f"h:p{i}" for i in range(8)]
    assert state["peak"] == 2


async def test_o03_password_worker_verify_and_burn() -> None:
    worker = PasswordWorker(concurrency=1)
    hashed = await worker.hash("kalem-defter-1234")
    assert await worker.verify(hashed, "kalem-defter-1234") is True
    assert await worker.verify(hashed, "yanlis") is False
    await worker.burn("herhangi")


# --- O-04: gövde boyutu ve sıra ----------------------------------------------------------------
def _post_raw(api: Api, path: str, body: bytes) -> Any:
    return api.client.post(
        path, content=body, headers={"Content-Type": "application/json", "X-CSRF-Token": api.csrf()}
    )


def test_o04_oversized_body_rejected_with_413(api: Api, admin_conn: psycopg.Connection) -> None:
    """PoC: ~4 MB gövde tamamen ayrıştırılıp 422 dönüyordu. Şimdi 413 ve işleyici çağrılmaz."""
    pad = "[" + ",".join(["0"] * 2_000_000) + "]"
    body = '{"email":"a@example.com","password":"x","pad":' + pad + "}"
    r = _post_raw(api, "/v1/auth/login", body.encode())
    assert r.status_code == 413
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"].endswith("payload-too-large")
    assert admin_conn.execute("SELECT count(*) FROM rate_limits").fetchone() == (0,)  # işleyiciye girilmedi


def test_o04_auth_endpoints_limited_to_64_kib(api: Api) -> None:
    def body_of(size: int) -> bytes:
        prefix = b'{"email":"a@example.com","password":"x","pad":"'
        suffix = b'"}'
        return prefix + b"a" * (size - len(prefix) - len(suffix)) + suffix

    assert _post_raw(api, "/v1/auth/login", body_of(64 * 1024 + 1)).status_code == 413
    # Sınırın altı gövde boyut denetimini geçer (şema ek alanı 422 ile reddeder, 413 değil)
    assert _post_raw(api, "/v1/auth/login", body_of(64 * 1024)).status_code == 422


def test_o04_general_limit_is_configurable_and_applies_outside_auth(make_api: Callable[..., Api]) -> None:
    api = make_api(max_request_body_bytes=2048, max_auth_body_bytes=512)
    assert _post_raw(api, "/v1/baska-uc", b"x" * 2049).status_code == 413
    assert _post_raw(api, "/v1/baska-uc", b"x" * 2048).status_code == 404
    assert _post_raw(api, "/v1/auth/login", b"x" * 513).status_code == 413


def test_o04_streamed_body_without_content_length_is_limited(make_api: Callable[..., Api]) -> None:
    api = make_api(max_auth_body_bytes=1024)

    def chunks() -> Iterator[bytes]:
        for _ in range(8):
            yield b"a" * 512

    r = api.client.post(
        "/v1/auth/login",
        content=chunks(),
        headers={"Content-Type": "application/json", "X-CSRF-Token": api.csrf()},
    )
    assert r.status_code == 413


def test_o04_rate_limit_runs_before_body_is_parsed(make_api: Callable[..., Api]) -> None:
    """429 alacak istek gövdesi ayrıştırılmadan reddedilir: geçersiz gövde 422 değil 429 döner."""
    api = make_api(rate_limit_login_ip=1)
    assert api.post("/v1/auth/login", {"email": "a@example.com", "password": "x"}).status_code == 401
    r = api.post("/v1/auth/login", {"bu": "gecersiz-govde"})
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.headers["x-request-id"] and r.json()["request_id"]


# --- D-04: log maskeleme -----------------------------------------------------------------------
def _json_log(exc: BaseException) -> dict[str, Any]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(MaskingFilter())
    logger = logging.getLogger("regression.mask")
    logger.handlers = [handler]
    logger.propagate = False
    try:
        raise exc
    except BaseException:
        logger.exception("yakalanmamış hata")
    return dict(json.loads(stream.getvalue()))


def test_d04_argon2_hash_and_email_in_sqlalchemy_error_are_masked() -> None:
    argon = hash_password("gizli-parola-123456")
    exc = OperationalError(
        "SELECT * FROM auth_gate.register_account(%(e)s, %(h)s, %(n)s, %(d)s)",
        {"e": "kisi@example.com", "h": argon, "n": "Mağaza", "d": 14},
        Exception("server closed the connection unexpectedly"),
    )
    out = _json_log(exc)
    assert "kisi@example.com" not in out["exc"]
    assert argon not in out["exc"] and "$argon2id$" not in out["exc"]


def test_d04_hex_digests_are_masked() -> None:
    digest = "a" * 64
    assert digest not in mask_text(f"parametre h={digest} bitti")


def test_d04_unicode_email_is_masked() -> None:
    masked = mask_text("kullanıcı ğüşı@örnek.com.tr giriş yaptı; çağrı@örnek.org de")
    assert "ğüşı" not in masked and "çağrı" not in masked and "örnek" not in masked
    assert masked.count("***") == 2


async def test_d04_engine_hides_bound_parameters_in_errors(settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            with pytest.raises(DBAPIError) as exc:
                await conn.execute(
                    text("SELECT CAST(:v AS text) || (1 / 0)::text"), {"v": "kisi@example.com"}
                )
    finally:
        await engine.dispose()
    assert "kisi@example.com" not in str(exc.value) and "[parameters:" not in str(exc.value)


def test_d04_uvicorn_loggers_flow_through_masking_root_handler(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO")
    for name in ("uvicorn", "uvicorn.error"):
        assert logging.getLogger(name).handlers == [] and logging.getLogger(name).propagate is True
    logging.getLogger("uvicorn.error").error("hata ali.veli@example.com password=Cok-Gizli-1")
    out = capsys.readouterr().out
    assert "ali.veli" not in out and "Cok-Gizli-1" not in out
    assert json.loads(out.strip().splitlines()[-1])["logger"] == "uvicorn.error"


# --- D-06: parola sıfırlamada tüm oturumlar iptal ----------------------------------------------
def test_d06_password_reset_revokes_every_session(
    make_api: Callable[..., Api], outbox: Any, admin_conn: psycopg.Connection
) -> None:
    first, second = make_api(), make_api()
    first.signup_and_login("coklu@example.com")
    assert second.login("coklu@example.com").status_code == 200
    assert first.get("/v1/me").status_code == second.get("/v1/me").status_code == 200

    victim = make_api()
    assert victim.post("/v1/auth/password-reset/request", {"email": "coklu@example.com"}).status_code == 202
    token = _token_from(outbox, "coklu@example.com")
    assert (
        victim.post(
            "/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )

    assert first.get("/v1/me").status_code == second.get("/v1/me").status_code == 401
    active = admin_conn.execute("SELECT count(*) FROM sessions WHERE revoked_at IS NULL").fetchone()
    assert active == (0,)


# --- D-08: üretimde güvensiz varsayılanlar açılışı durdurur -------------------------------------
@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"email_backend": "file"}, "EMAIL_BACKEND"),
        ({"email_backend": "memory"}, "EMAIL_BACKEND"),
        ({"email_backend": "file", "debug": True}, "DEBUG"),
    ],
)
def test_d08_production_rejects_unsafe_defaults(
    settings: Settings, overrides: dict[str, Any], needle: str
) -> None:
    values = {**settings.model_dump(), "environment": "prod", **overrides}
    with pytest.raises(ValidationError) as exc:
        Settings.model_validate(values)
    assert needle in str(exc.value)


def test_d08_debug_is_allowed_outside_production(settings: Settings) -> None:
    values = {**settings.model_dump(), "environment": "dev", "debug": True}
    assert Settings.model_validate(values).debug is True


def test_d08_debug_flag_reaches_fastapi(make_app: Callable[..., Any]) -> None:
    assert make_app(debug=True).debug is True
    assert make_app().debug is False
