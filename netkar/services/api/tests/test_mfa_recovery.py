"""MFA yeniden doğrulama, tek kullanımlık kurtarma kodları, TOTP kapatma (denetim O-05; ASVS V2.5, V2.8, V3)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.security import (
    generate_recovery_codes,
    normalize_recovery_code,
    recovery_code_hash,
)
from app.db.rls import set_rls_context
from app.services.auth import consume_recovery_code
from tests.conftest import GOOD_PASSWORD, TEST_KEY, Api, DatabaseInfo, FakeClock

PW = {"password": GOOD_PASSWORD}
CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


def _enable(api: Api, clock: FakeClock) -> tuple[str, list[str]]:
    """TOTP'yi parola ile kurar; (sır, kurtarma kodları) döner. Saat bir adım ilerletilir."""
    setup = api.post("/v1/auth/totp/setup", PW)
    assert setup.status_code == 200
    secret = str(setup.json()["secret"])
    enabled = api.post("/v1/auth/totp/enable", {"code": clock.code(secret), **PW})
    assert enabled.status_code == 200
    clock.advance(30)
    return secret, list(enabled.json()["recovery_codes"])


def _user(
    make_api: Callable[..., Api], clock: FakeClock, email: str, **overrides: Any
) -> tuple[Api, str, list[str]]:
    api = make_api(**overrides)
    api.signup_and_login(email)
    secret, codes = _enable(api, clock)
    return api, secret, codes


def _wrong(clock: FakeClock, secret: str) -> str:
    return "000000" if clock.code(secret) != "000000" else "111111"


# --- üretim ve saklama -------------------------------------------------------------------------------
def test_generated_codes_are_unique_well_formed_and_normalizable() -> None:
    codes = generate_recovery_codes()
    assert len(codes) == len(set(codes)) == 10
    assert all(CODE_RE.match(c) for c in codes)
    assert normalize_recovery_code(codes[0].lower().replace("-", " ")) == codes[0].replace("-", "")
    assert normalize_recovery_code("kısa") is None
    assert normalize_recovery_code("0000-0000-0000") is None  # 0 ve O alfabede yok


def test_enable_returns_ten_codes_once_and_stores_only_keyed_hashes(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    api, _, codes = _user(make_api, clock, "kod@example.com")
    assert len(codes) == 10 and all(CODE_RE.match(c) for c in codes)
    me = api.get("/v1/me").json()
    assert me["totp_enabled"] is True and me["recovery_codes_remaining"] == 10
    assert "recovery_codes" not in me  # düz metin başka yerde dönmez
    rows = admin_conn.execute("SELECT code_hash, used_at, revoked_at FROM mfa_recovery_codes").fetchall()
    assert len(rows) == 10 and all(r[1] is None and r[2] is None for r in rows)
    stored = {r[0] for r in rows}
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in stored)
    plain = {c.replace("-", "") for c in codes} | set(codes)
    assert not (stored & plain)  # düz metin saklanmaz
    # özet kullanıcıya bağlı ve anahtarlı: aynı kod başka kullanıcı kimliğiyle başka özet verir
    import base64

    master = base64.b64decode(TEST_KEY)
    uid = UUID(me["user_id"])
    expected = {recovery_code_hash(master, uid, c.replace("-", "")) for c in codes}
    assert stored == expected
    assert recovery_code_hash(master, UUID(int=1), codes[0].replace("-", "")) not in stored
    audit = admin_conn.execute("SELECT meta FROM audit_log WHERE action = 'auth.totp_enabled'").fetchone()
    assert audit is not None and audit[0] == {"recovery_codes": 10}
    assert not any(c in str(audit) for c in codes)


# --- yeniden doğrulama: kurulum ve etkinleştirme ----------------------------------------------------
def test_setup_and_enable_require_the_current_password(
    api: Api, clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    api.signup_and_login("reauth@example.com")
    assert api.post("/v1/auth/totp/setup").status_code == 422  # parola alanı zorunlu
    bad = api.post("/v1/auth/totp/setup", {"password": "yanlis-parola-1234"})
    assert bad.status_code == 403 and bad.json()["type"].endswith("reauth-failed")
    assert admin_conn.execute("SELECT totp_secret_encrypted FROM users").fetchone() == (None,)
    secret = str(api.post("/v1/auth/totp/setup", PW).json()["secret"])
    code = clock.code(secret)
    assert api.post("/v1/auth/totp/enable", {"code": code}).status_code == 422
    wrong_pw = api.post("/v1/auth/totp/enable", {"code": code, "password": "yanlis-parola-1234"})
    assert wrong_pw.status_code == 403
    assert api.get("/v1/me").json()["totp_enabled"] is False  # parolasız/yanlış parolayla etkinleşmez
    assert api.post("/v1/auth/totp/enable", {"code": code, **PW}).status_code == 200
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions.count("auth.reauth_failed") == 2


def test_failed_reauth_is_rate_limited_and_locks_through_existing_machinery(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection
) -> None:
    api = make_api(totp_max_failures=3, rate_limit_totp_user=50)
    api.signup_and_login("kilit@example.com")
    bad = {"password": "yanlis-parola-1234"}
    assert [api.post("/v1/auth/totp/setup", bad).status_code for _ in range(3)] == [403, 403, 403]
    locked = api.post("/v1/auth/totp/setup", PW)  # doğru parola bile kilitliyken kabul edilmez
    assert locked.status_code == 429 and locked.json()["type"].endswith("totp-locked")
    assert int(locked.headers["retry-after"]) > 0
    assert admin_conn.execute("SELECT totp_locked_until > now() FROM users").fetchone() == (True,)

    limited = make_api(rate_limit_totp_user=2, totp_max_failures=100)
    limited.signup_and_login("hiz@example.com")
    statuses = [
        limited.post("/v1/auth/totp/setup", {"password": "yanlis-parola-1234"}).status_code for _ in range(4)
    ]
    assert statuses == [403, 403, 429, 429]


# --- girişte kurtarma kodu --------------------------------------------------------------------------
def test_login_with_recovery_code_is_single_use_and_audited(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    owner, secret, codes = _user(make_api, clock, "giris@example.com")
    owner.post("/v1/auth/logout")

    first = make_api()
    assert first.login("giris@example.com").json() == {"status": "totp_required"}
    # küçük harf ve boşlukla da kabul edilir; yanlış biçim 422 değil 401 (numaralandırma yok)
    assert first.post("/v1/auth/totp/verify", {"code": "ABCD-EFGH-JKLM"}).status_code == 401
    ok = first.post("/v1/auth/totp/verify", {"code": codes[0].lower().replace("-", " ")})
    assert ok.status_code == 200 and ok.json() == {"status": "ok"}
    me = first.get("/v1/me").json()
    assert me["recovery_codes_remaining"] == 9 and me["totp_enabled"] is True

    second = make_api()
    second.login("giris@example.com")
    reused = second.post("/v1/auth/totp/verify", {"code": codes[0]})
    assert reused.status_code == 401 and reused.json()["type"].endswith("invalid-code")
    assert second.get("/v1/me").status_code == 401
    # başka bir kod hâlâ çalışır; TOTP de çalışmaya devam eder
    assert second.post("/v1/auth/totp/verify", {"code": codes[1]}).status_code == 200
    third = make_api()
    third.login("giris@example.com")
    assert third.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200

    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions.count("auth.recovery_code_used") == 2
    assert actions.count("auth.login_recovery") == 2 and actions.count("auth.recovery_failed") == 2
    meta = admin_conn.execute(
        "SELECT meta FROM audit_log WHERE action = 'auth.recovery_code_used' ORDER BY id"
    ).fetchall()
    assert [m[0] for m in meta] == [{"remaining": 9}, {"remaining": 8}]
    dump = str(admin_conn.execute("SELECT meta, target FROM audit_log").fetchall())
    assert not any(c in dump for c in codes)
    used = admin_conn.execute("SELECT count(*) FROM mfa_recovery_codes WHERE used_at IS NOT NULL").fetchone()
    assert used == (2,)  # satırlar silinmez, işaretlenir


def test_wrong_recovery_codes_share_the_totp_lock(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    owner, _, codes = _user(make_api, clock, "bf@example.com", totp_max_failures=3, rate_limit_totp_user=50)
    owner.post("/v1/auth/logout")
    api = make_api(totp_max_failures=3, rate_limit_totp_user=50)
    api.login("bf@example.com")
    guesses = ["AAAA-AAAA-AAAA", "BBBB-BBBB-BBBB", "CCCC-CCCC-CCCC"]
    assert [api.post("/v1/auth/totp/verify", {"code": g}).status_code for g in guesses] == [401, 401, 401]
    blocked = api.post("/v1/auth/totp/verify", {"code": codes[0]})  # doğru kod bile kilitliyken geçmez
    assert blocked.status_code == 429 and blocked.json()["type"].endswith("totp-locked")
    assert admin_conn.execute(
        "SELECT count(*) FROM mfa_recovery_codes WHERE used_at IS NOT NULL"
    ).fetchone() == (0,)


def test_recovery_code_does_not_work_without_totp_or_for_another_user(
    make_api: Callable[..., Api], clock: FakeClock
) -> None:
    a, _, codes_a = _user(make_api, clock, "a@example.com")
    plain = make_api()
    plain.signup_and_login("b@example.com")
    plain.post("/v1/auth/logout")
    assert plain.login("b@example.com").json() == {"status": "ok"}  # TOTP'siz kullanıcı doğrudan girer
    b2, _, _ = _user(make_api, clock, "c@example.com")
    b2.post("/v1/auth/logout")
    attacker = make_api()
    assert attacker.login("c@example.com").json() == {"status": "totp_required"}
    # A'nın kodu C'nin girişinde işe yaramaz (özet kullanıcıya bağlı)
    assert attacker.post("/v1/auth/totp/verify", {"code": codes_a[0]}).status_code == 401
    a.post("/v1/auth/logout")
    assert a.login("a@example.com").json() == {"status": "totp_required"}
    assert a.post("/v1/auth/totp/verify", {"code": codes_a[0]}).status_code == 200


async def test_concurrent_use_of_the_same_recovery_code_lets_only_one_win(
    make_api: Callable[..., Api], clock: FakeClock, database: DatabaseInfo
) -> None:
    owner, _, codes = _user(make_api, clock, "yaris@example.com")
    me = owner.get("/v1/me").json()
    user_id, tenant_id = UUID(me["user_id"]), UUID(me["tenant"]["id"])
    import base64

    code_hash = recovery_code_hash(base64.b64decode(TEST_KEY), user_id, codes[0].replace("-", ""))
    engine = create_async_engine(database.app_url.render_as_string(hide_password=False))
    try:

        async def attempt() -> bool:
            async with engine.connect() as conn:
                session = AsyncSession(bind=conn)
                await set_rls_context(session, tenant_id, user_id)
                won = await consume_recovery_code(session, user_id, code_hash)
                await session.commit()
                return won

        results = await asyncio.gather(*(attempt() for _ in range(8)))
    finally:
        await engine.dispose()
    assert sorted(results) == [False] * 7 + [True]


# --- TOTP kapatma ve kod yenileme --------------------------------------------------------------------
def _two_sessions(
    make_api: Callable[..., Api], clock: FakeClock, email: str
) -> tuple[Api, Api, str, list[str]]:
    first, secret, codes = _user(make_api, clock, email)
    other = make_api()
    assert other.login(email).json() == {"status": "totp_required"}
    assert other.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200
    clock.advance(30)
    assert other.get("/v1/me").status_code == 200
    return first, other, secret, codes


def test_disable_requires_password_and_current_code_and_revokes_other_sessions(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    first, other, secret, codes = _two_sessions(make_api, clock, "kapat@example.com")
    body = {"password": GOOD_PASSWORD, "code": clock.code(secret)}
    assert (
        first.post(
            "/v1/auth/totp/disable", {"password": "yanlis-parola-1234", "code": body["code"]}
        ).status_code
        == 403
    )
    wrong_code = first.post("/v1/auth/totp/disable", {**PW, "code": _wrong(clock, secret)})
    assert wrong_code.status_code == 403 and wrong_code.json()["type"].endswith("invalid-code")
    assert first.post("/v1/auth/totp/disable", PW).status_code == 422  # kod zorunlu
    assert first.get("/v1/me").json()["totp_enabled"] is True and other.get("/v1/me").status_code == 200

    assert first.post("/v1/auth/totp/disable", body).status_code == 204
    me = first.get("/v1/me")
    assert me.status_code == 200  # çağıran oturum açık kalır
    assert me.json()["totp_enabled"] is False and me.json()["recovery_codes_remaining"] == 0
    assert other.get("/v1/me").status_code == 401  # diğer oturum iptal edildi
    row = admin_conn.execute(
        "SELECT totp_enabled, totp_secret_encrypted IS NULL, totp_last_step IS NULL FROM users"
    ).fetchone()
    assert row == (False, True, True)
    # kodlar geçersiz kılındı (silinmedi)
    assert admin_conn.execute("SELECT count(*), count(revoked_at) FROM mfa_recovery_codes").fetchone() == (
        10,
        10,
    )
    meta = admin_conn.execute("SELECT meta FROM audit_log WHERE action = 'auth.totp_disabled'").fetchone()
    assert meta is not None and meta[0] == {"other_sessions_revoked": 1}
    # TOTP'siz doğrudan giriş; yeniden kurulum mümkün; eski kurtarma kodları ölü
    fresh = make_api()
    assert fresh.login("kapat@example.com").json() == {"status": "ok"}
    assert first.post("/v1/auth/totp/disable", {**PW, "code": "123456"}).status_code == 409
    secret2, codes2 = _enable(first, clock)
    assert secret2 != secret and set(codes2).isdisjoint(codes)
    first.post("/v1/auth/logout")
    again = make_api()
    again.login("kapat@example.com")
    assert again.post("/v1/auth/totp/verify", {"code": codes[0]}).status_code == 401


def test_disable_accepts_a_recovery_code_as_the_second_factor(
    make_api: Callable[..., Api], clock: FakeClock
) -> None:
    api, _, codes = _user(make_api, clock, "kayip@example.com")  # authenticator kaybedildi
    assert api.post("/v1/auth/totp/disable", {**PW, "code": codes[3]}).status_code == 204
    assert api.get("/v1/me").json()["totp_enabled"] is False


def test_regenerate_replaces_codes_revokes_other_sessions_and_needs_reauth(
    make_api: Callable[..., Api], clock: FakeClock, admin_conn: psycopg.Connection
) -> None:
    first, other, secret, old = _two_sessions(make_api, clock, "yenile@example.com")
    assert (
        first.post("/v1/auth/totp/recovery-codes", {**PW, "code": _wrong(clock, secret)}).status_code == 403
    )
    assert (
        first.post(
            "/v1/auth/totp/recovery-codes", {"password": "yanlis-parola-1234", "code": clock.code(secret)}
        ).status_code
        == 403
    )
    assert other.get("/v1/me").status_code == 200  # başarısız yenileme hiçbir şeyi değiştirmedi
    fresh = first.post("/v1/auth/totp/recovery-codes", {**PW, "code": clock.code(secret)})
    assert fresh.status_code == 200
    new = list(fresh.json()["recovery_codes"])
    assert len(new) == 10 and set(new).isdisjoint(old) and all(CODE_RE.match(c) for c in new)
    assert other.get("/v1/me").status_code == 401 and first.get("/v1/me").status_code == 200
    assert first.get("/v1/me").json()["recovery_codes_remaining"] == 10
    assert admin_conn.execute(
        "SELECT count(*) FILTER (WHERE revoked_at IS NULL), count(*) FILTER (WHERE revoked_at IS NOT NULL) "
        "FROM mfa_recovery_codes"
    ).fetchone() == (10, 10)
    first.post("/v1/auth/logout")
    login = make_api()
    login.login("yenile@example.com")
    assert login.post("/v1/auth/totp/verify", {"code": old[0]}).status_code == 401  # eski kod ölü
    assert login.post("/v1/auth/totp/verify", {"code": new[0]}).status_code == 200


def test_mfa_change_endpoints_require_authentication_and_enabled_totp(api: Api) -> None:
    body = {**PW, "code": "123456"}
    assert api.post("/v1/auth/totp/disable", body).status_code == 401
    assert api.post("/v1/auth/totp/recovery-codes", body).status_code == 401
    api.signup_and_login("yok@example.com")
    assert api.post("/v1/auth/totp/disable", body).status_code == 409
    assert api.post("/v1/auth/totp/recovery-codes", body).status_code == 409
    assert api.get("/v1/me").json()["recovery_codes_remaining"] == 0


# --- RLS, yetki ve migrasyon 0019 ---------------------------------------------------------------------
def test_recovery_codes_are_isolated_per_user_and_least_privileged(
    make_api: Callable[..., Api], clock: FakeClock, database: DatabaseInfo
) -> None:
    a, _, _ = _user(make_api, clock, "iz1@example.com")
    b, _, _ = _user(make_api, clock, "iz2@example.com")
    uid_a, uid_b = a.get("/v1/me").json()["user_id"], b.get("/v1/me").json()["user_id"]
    with psycopg.connect(database.app_dsn(), autocommit=False) as conn:
        assert conn.execute("SELECT count(*) FROM mfa_recovery_codes").fetchone() == (0,)  # bağlam yok
        conn.execute("SELECT set_config('app.user_id', %s, true)", (uid_b,))
        rows = conn.execute("SELECT DISTINCT user_id::text FROM mfa_recovery_codes").fetchall()
        assert rows == [(uid_b,)]  # yalnız kendi kodları
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM mfa_recovery_codes")
        conn.rollback()
        conn.execute("SELECT set_config('app.user_id', %s, true)", (uid_b,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE mfa_recovery_codes SET code_hash = 'x'")
        conn.rollback()
        conn.execute("SELECT set_config('app.user_id', %s, true)", (uid_b,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE mfa_recovery_codes SET user_id = %s", (uid_a,))
        conn.rollback()
    with psycopg.connect(database.worker_dsn()) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM mfa_recovery_codes")


def test_revoke_other_sessions_function_refuses_other_users(
    make_api: Callable[..., Api], database: DatabaseInfo
) -> None:
    a = make_api()
    a.signup_and_login("o1@example.com")
    b = make_api()
    b.signup_and_login("o2@example.com")
    uid_a, uid_b = a.get("/v1/me").json()["user_id"], b.get("/v1/me").json()["user_id"]
    with psycopg.connect(database.app_dsn()) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (uid_b,))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT auth_gate.revoke_other_sessions(%s, gen_random_uuid())", (uid_a,))
    assert a.get("/v1/me").status_code == 200


def _trigger_exists(conn: psycopg.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname = 'users_totp_requires_verified_email'"
        ).fetchone()
        is not None
    )


def test_migration_0019_is_reversible_and_least_privileged(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    def table_state() -> tuple[bool, bool, bool]:
        return admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'mfa_recovery_codes', 'DELETE'),"
            " has_table_privilege('netkar_app', 'mfa_recovery_codes', 'SELECT'),"
            " (SELECT relforcerowsecurity FROM pg_class WHERE relname = 'mfa_recovery_codes')"
        ).fetchone()  # type: ignore[return-value]

    assert table_state() == (False, True, True)
    assert admin_conn.execute(
        "SELECT has_function_privilege('netkar_app', 'auth_gate.revoke_other_sessions(uuid, uuid)', 'EXECUTE'),"
        " has_function_privilege('public', 'auth_gate.revoke_other_sessions(uuid, uuid)', 'EXECUTE')"
    ).fetchone() == (True, False)
    assert _trigger_exists(admin_conn)

    command.downgrade(alembic_cfg, "0018")
    assert admin_conn.execute("SELECT to_regclass('public.mfa_recovery_codes')").fetchone() == (None,)
    assert not _trigger_exists(admin_conn)
    assert admin_conn.execute(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'auth_gate' AND p.proname = 'revoke_other_sessions'"
    ).fetchone() == (0,)
    assert admin_conn.execute("SELECT to_regclass('public.users')").fetchone() != (
        None,
    )  # veri tabloları durur

    command.upgrade(alembic_cfg, "head")
    assert table_state() == (False, True, True) and _trigger_exists(admin_conn)


# --- (D) doğrulanmamış hesapta TOTP: veritabanı tetikleyicisi -----------------------------------------
def _new_user(conn: psycopg.Connection, email: str, verified: bool) -> str:
    row = conn.execute(
        "INSERT INTO users (email, password_hash, email_verified_at) "
        "VALUES (%s, 'x', CASE WHEN %s THEN now() END) RETURNING id::text",
        (email, verified),
    ).fetchone()
    assert row is not None
    return str(row[0])


def test_trigger_blocks_totp_on_unverified_accounts_for_new_writes(admin_conn: psycopg.Connection) -> None:
    unverified = _new_user(admin_conn, "u1@example.com", verified=False)
    verified = _new_user(admin_conn, "v1@example.com", verified=True)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE users SET totp_enabled = true WHERE id = %s", (unverified,))
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(
            "INSERT INTO users (email, password_hash, totp_enabled) VALUES ('u2@example.com', 'x', true)"
        )
    # doğrulanmış hesap serbest; doğrulamayı geri almak (TOTP açıkken) engellenir
    admin_conn.execute("UPDATE users SET totp_enabled = true WHERE id = %s", (verified,))
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE users SET email_verified_at = NULL WHERE id = %s", (verified,))
    # doğrulanmamış hesapta kapalı kalan TOTP ve diğer sütun güncellemeleri etkilenmez
    admin_conn.execute("UPDATE users SET totp_failed_count = 2 WHERE id = %s", (unverified,))


def test_legacy_unverified_totp_rows_are_untouched_by_the_trigger_and_rule_stays_legacy_only(
    make_api: Callable[..., Api], outbox: Any, admin_conn: psycopg.Connection
) -> None:
    """0017 öncesi satır (doğrulanmamış + TOTP etkin) tetikleyiciyle OLUŞTURULAMAZ; yalnız tetikleyici kapalıyken
    (eski veriyi taklit) var olabilir ve sonraki sıradan güncellemeler (zaman adımı, sayaç) onu bozmaz. Böylece
    0018'in "sıfırlama etkin TOTP'yi korur" kuralı yalnız bu eski hesaplara özgüdür."""
    legacy = _new_user(admin_conn, "eski@example.com", verified=False)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE users SET totp_enabled = true WHERE id = %s", (legacy,))
    admin_conn.execute("ALTER TABLE users DISABLE TRIGGER users_totp_requires_verified_email")
    admin_conn.execute(
        "UPDATE users SET totp_enabled = true, totp_secret_encrypted = 'v1:x' WHERE id = %s", (legacy,)
    )
    admin_conn.execute("ALTER TABLE users ENABLE TRIGGER users_totp_requires_verified_email")
    # eski satırın başka sütunları güncellenebilir (giriş denemesi sayacı, zaman adımı)
    admin_conn.execute("UPDATE users SET totp_last_step = 9, totp_failed_count = 1 WHERE id = %s", (legacy,))
    assert admin_conn.execute(
        "SELECT totp_enabled, totp_last_step FROM users WHERE id = %s", (legacy,)
    ).fetchone() == (True, 9)
    # yeni akış (API) doğrulanmamış hesapta bu duruma ulaşamaz
    api = make_api()
    api.signup_and_login("yeni@example.com", verified=False)
    assert api.post("/v1/auth/totp/setup", PW).status_code == 403
    assert admin_conn.execute(
        "SELECT count(*) FROM users WHERE email_verified_at IS NULL AND totp_enabled"
    ).fetchone() == (1,)  # yalnız taklit edilen eski satır
