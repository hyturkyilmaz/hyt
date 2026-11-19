"""Yetki daraltma 2 (migrasyon 0024): sessions INSERT, memberships ve tenants yazma yetkileri.

Kapsam: yetki matrisi, sahte oturum INSERT'inin 42501'i, `auth_gate.create_session` işlevi (üyelik doğrulama,
sunucu üretimli alanlar, süre üst sınırı), rol yükseltme ve kimlik sütunu tetikleyicileri, mevcut akışların
çalışması ve 0024 upgrade/downgrade/upgrade döngüsü (sütun düzeyi ACL kalıntısı yok, veri silinmez).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from app.core.config import SESSION_ABSOLUTE_MAX_SECONDS, Settings
from tests.conftest import Api, DatabaseInfo
from tests.session_helpers import tenant_guard_disabled

SESSION_COLUMNS = (
    "id",
    "token_hash",
    "user_id",
    "tenant_id",
    "created_at",
    "last_seen_at",
    "expires_at",
    "revoked_at",
    "ip_hash",
    "user_agent",
)
MEMBERSHIP_COLUMNS = ("id", "user_id", "tenant_id", "role", "created_at")
TENANT_COLUMNS = ("id", "name", "plan", "status", "trial_ends_at", "currency", "locale", "created_at")
AUTH_SESSION_INSERT_COLUMNS = {
    "token_hash",
    "user_id",
    "tenant_id",
    "created_at",
    "last_seen_at",
    "expires_at",
    "ip_hash",
    "user_agent",
}
TOKEN_HASH = "a" * 64
IP_HASH = "b" * 32
CREATE_SESSION = "SELECT auth_gate.create_session(%s::uuid, %s::uuid, %s, %s, %s, %s)"


@contextmanager
def _app_tx(database: DatabaseInfo, tenant_id: str | None) -> Iterator[psycopg.Connection[Any]]:
    """Uygulama rolüyle işlem açar; kiracı bağlamı işlem yerel ayarlanır, çıkışta geri alınır."""
    with psycopg.connect(database.app_dsn()) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id or "",))
        yield conn
        conn.rollback()


@contextmanager
def _ctx_tx(
    database: DatabaseInfo, tenant_id: str | None, user_id: str | None
) -> Iterator[psycopg.Connection[Any]]:
    """Uygulama rolüyle, hem kiracı hem kullanıcı RLS bağlamı kurulu işlem (`_start_session` ile aynı)."""
    with psycopg.connect(database.app_dsn()) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id or "",))
        conn.execute("SELECT set_config('app.user_id', %s, true)", (user_id or "",))
        yield conn
        conn.rollback()


def _login(api: Api, email: str) -> tuple[str, str]:
    """Kayıt + giriş; (kullanıcı kimliği, kiracı kimliği)."""
    api.signup_and_login(email)
    me = api.get("/v1/me").json()
    return me["user_id"], me["tenant"]["id"]


def _two_accounts(make_api: Any) -> tuple[tuple[str, str], tuple[str, str]]:
    return _login(make_api(), "uye-a@example.com"), _login(make_api(), "uye-b@example.com")


def _table_priv(conn: psycopg.Connection[Any], role: str, table: str, priv: str) -> bool:
    row = conn.execute("SELECT has_table_privilege(%s, %s, %s)", (role, f"public.{table}", priv)).fetchone()
    assert row is not None
    return bool(row[0])


def _column_priv(conn: psycopg.Connection[Any], role: str, table: str, column: str, priv: str) -> bool:
    row = conn.execute(
        "SELECT has_column_privilege(%s, %s, %s, %s)", (role, f"public.{table}", column, priv)
    ).fetchone()
    assert row is not None
    return bool(row[0])


# ---- Yetki matrisi -------------------------------------------------------------------------------------------


def test_privilege_matrix_for_app_and_auth_roles(admin_conn: psycopg.Connection) -> None:
    # netkar_app: sessions'a INSERT YOK (tablo ve her sütun), UPDATE yalnız iki çalışma sütunu (0023), SELECT var.
    assert _table_priv(admin_conn, "netkar_app", "sessions", "SELECT")
    assert not _table_priv(admin_conn, "netkar_app", "sessions", "INSERT")
    for column in SESSION_COLUMNS:
        assert not _column_priv(admin_conn, "netkar_app", "sessions", column, "INSERT"), column
        expected = column in {"last_seen_at", "revoked_at"}
        assert _column_priv(admin_conn, "netkar_app", "sessions", column, "UPDATE") is expected, column
    # memberships ve tenants: yalnız SELECT (kodda yazma akışı yok).
    for table, columns in (("memberships", MEMBERSHIP_COLUMNS), ("tenants", TENANT_COLUMNS)):
        assert _table_priv(admin_conn, "netkar_app", table, "SELECT")
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _table_priv(admin_conn, "netkar_app", table, priv), (table, priv)
            for column in columns:
                if priv in ("INSERT", "UPDATE"):
                    assert not _column_priv(admin_conn, "netkar_app", table, column, priv), (
                        table,
                        column,
                        priv,
                    )
    # netkar_auth: oturumda yalnız gereken sütunlara INSERT; id ve revoked_at dışarıda (varsayılan değerler).
    assert not _table_priv(admin_conn, "netkar_auth", "sessions", "INSERT")
    for column in SESSION_COLUMNS:
        expected = column in AUTH_SESSION_INSERT_COLUMNS
        assert _column_priv(admin_conn, "netkar_auth", "sessions", column, "INSERT") is expected, column
    # auth_gate yolları (register_account vb.) için netkar_auth'un mevcut yetkileri korunur.
    assert _table_priv(admin_conn, "netkar_auth", "memberships", "INSERT")
    assert _table_priv(admin_conn, "netkar_auth", "tenants", "INSERT")
    assert _column_priv(admin_conn, "netkar_auth", "tenants", "trial_ends_at", "UPDATE")


def test_create_session_function_is_a_locked_down_security_definer(admin_conn: psycopg.Connection) -> None:
    row = admin_conn.execute(
        "SELECT p.prosecdef, r.rolname, p.proconfig, "
        " has_function_privilege('netkar_app', p.oid, 'EXECUTE'),"
        " has_function_privilege('public', p.oid, 'EXECUTE'),"
        " has_function_privilege('netkar_worker', p.oid, 'EXECUTE'),"
        " pg_get_functiondef(p.oid) "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = 'auth_gate' AND p.proname = 'create_session'"
    ).fetchone()
    assert row is not None
    secdef, owner, config, app_exec, public_exec, worker_exec, definition = row
    assert secdef is True and owner == "netkar_auth"
    assert config == ["search_path=pg_catalog, public, pg_temp"]
    assert (app_exec, public_exec, worker_exec) == (True, False, False)
    # Tek kaynak: koddaki mutlak süre üst sınırı ile işlevdeki sabit aynıdır.
    assert str(SESSION_ABSOLUTE_MAX_SECONDS) in definition
    assert Settings.model_fields["session_absolute_seconds"].default == SESSION_ABSOLUTE_MAX_SECONDS


# ---- Sahte oturum INSERT'i ------------------------------------------------------------------------------------


def test_forged_session_insert_by_app_role_is_denied_with_42501(
    make_api: Any, database: DatabaseInfo
) -> None:
    (user_a, tenant_a), (_, tenant_b) = _two_accounts(make_api)
    attempts = [
        # Kendi kiracısı, kendi kullanıcısı, 10 yıllık oturum.
        (
            "INSERT INTO sessions (token_hash, user_id, tenant_id, expires_at) "
            "VALUES (%s, %s, %s, now() + interval '3650 days')",
            (TOKEN_HASH, user_a, tenant_a),
            tenant_a,
        ),
        # Başka kiracı adına.
        (
            "INSERT INTO sessions (token_hash, user_id, tenant_id, expires_at) "
            "VALUES (%s, %s, %s, now() + interval '1 day')",
            (TOKEN_HASH, user_a, tenant_b),
            tenant_a,
        ),
        # Varsayılanlarla bile (tablo düzeyi INSERT yok).
        (
            "INSERT INTO sessions (token_hash, user_id, tenant_id, expires_at, revoked_at) "
            "VALUES (%s, %s, %s, now(), NULL)",
            (TOKEN_HASH, user_a, tenant_a),
            tenant_a,
        ),
    ]
    for statement, params, ctx_tenant in attempts:
        with _app_tx(database, ctx_tenant) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
                conn.execute(statement, params)  # type: ignore[call-overload]
            assert exc.value.sqlstate == "42501"


# ---- auth_gate.create_session ---------------------------------------------------------------------------------


def test_create_session_writes_only_server_generated_fields(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    (user_a, tenant_a), _ = _two_accounts(make_api)
    with _ctx_tx(database, tenant_a, user_a) as conn:
        row = conn.execute(
            CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, "x" * 200, 3600)
        ).fetchone()
        assert row is not None
        sid = row[0]
        created = conn.execute(
            "SELECT created_at = now(), last_seen_at = now(), expires_at = now() + interval '3600 seconds', "
            "revoked_at IS NULL, ip_hash, char_length(user_agent), user_id::text, tenant_id::text "
            "FROM sessions WHERE id = %s",
            (sid,),
        ).fetchone()
        assert created == (True, True, True, True, IP_HASH, 200, user_a, tenant_a)
        conn.commit()
    assert admin_conn.execute(
        "SELECT count(*) FROM sessions WHERE token_hash = %s", (TOKEN_HASH,)
    ).fetchone() == (1,)


def test_create_session_caps_the_absolute_lifetime(make_api: Any, database: DatabaseInfo) -> None:
    (user_a, tenant_a), _ = _two_accounts(make_api)
    with _ctx_tx(database, tenant_a, user_a) as conn:
        # İstemci 10 yıl istese de en çok sabit üst sınır (30 gün) verilir.
        row = conn.execute(
            CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 10 * 365 * 86400)
        ).fetchone()
        assert row is not None
        expires = conn.execute(
            "SELECT expires_at = now() + make_interval(secs => %s), user_agent IS NULL "
            "FROM sessions WHERE id = %s",
            (SESSION_ABSOLUTE_MAX_SECONDS, row[0]),
        ).fetchone()
        assert expires == (True, True)


def test_create_session_rejects_user_who_is_not_a_member_of_the_tenant(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    """Bağlam çağrıdaki değerlerle eşleşse bile üyelik yoksa reddedilir."""
    (user_a, tenant_a), (user_b, tenant_b) = _two_accounts(make_api)
    before = admin_conn.execute("SELECT count(*) FROM sessions").fetchone()
    cases = [
        (user_a, tenant_b),  # A kullanıcısı B kiracısında üye değil
        (user_b, tenant_a),
        ("00000000-0000-0000-0000-000000000001", tenant_a),  # var olmayan kullanıcı
        (user_a, "00000000-0000-0000-0000-000000000002"),  # var olmayan kiracı
    ]
    for user, tenant in cases:
        with _ctx_tx(database, tenant, user) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
                conn.execute(CREATE_SESSION, (user, tenant, TOKEN_HASH, IP_HASH, None, 3600))
            assert exc.value.sqlstate == "42501"
    assert admin_conn.execute("SELECT count(*) FROM sessions").fetchone() == before


def test_create_session_rejects_rls_context_mismatch_and_missing_context(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    """Geçerli üyelik bile olsa bağlamsız ya da başka kiracı/kullanıcı bağlamıyla çağrı 42501 alır."""
    (user_a, tenant_a), (user_b, tenant_b) = _two_accounts(make_api)
    before = admin_conn.execute("SELECT count(*) FROM sessions").fetchone()
    contexts = [
        (None, None),  # bağlamsız
        (tenant_a, None),  # kullanıcı bağlamı yok
        (None, user_a),  # kiracı bağlamı yok
        (tenant_b, user_a),  # başka kiracı bağlamı
        (tenant_a, user_b),  # başka kullanıcı bağlamı
        (tenant_b, user_b),  # tamamen başka (geçerli üye) bağlam
    ]
    for ctx_tenant, ctx_user in contexts:
        with _ctx_tx(database, ctx_tenant, ctx_user) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
                conn.execute(CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 3600))
            assert exc.value.sqlstate == "42501"
    assert admin_conn.execute("SELECT count(*) FROM sessions").fetchone() == before
    # Eşleşen bağlamla aynı çağrı başarılı olur.
    with _ctx_tx(database, tenant_a, user_a) as conn:
        assert conn.execute(CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 3600)).fetchone()


def test_create_session_rejects_malformed_arguments(make_api: Any, database: DatabaseInfo) -> None:
    (user_a, tenant_a), _ = _two_accounts(make_api)
    bad = [
        (TOKEN_HASH.upper(), IP_HASH, None, 3600),  # büyük harf hex
        ("kisa", IP_HASH, None, 3600),
        (TOKEN_HASH, IP_HASH, None, 0),
        (TOKEN_HASH, IP_HASH, None, -5),
        (TOKEN_HASH, None, None, 3600),  # ip özeti zorunlu
        (TOKEN_HASH, "kisa", None, 3600),
        (TOKEN_HASH, IP_HASH.upper(), None, 3600),
        (TOKEN_HASH, "b" * 64, None, 3600),  # yanlış uzunluk
        (TOKEN_HASH, IP_HASH, "x" * 201, 3600),  # user_agent çok uzun
    ]
    for token_hash, ip_hash, user_agent, seconds in bad:
        with _ctx_tx(database, tenant_a, user_a) as conn:
            with pytest.raises(psycopg.errors.InvalidParameterValue):
                conn.execute(CREATE_SESSION, (user_a, tenant_a, token_hash, ip_hash, user_agent, seconds))
    # Yinelenen token özeti benzersizlik kısıtına takılır (23505).
    with _ctx_tx(database, tenant_a, user_a) as conn:
        conn.execute(CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 3600))
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 3600))


def test_create_session_is_not_callable_by_the_worker_role(make_api: Any, database: DatabaseInfo) -> None:
    (user_a, tenant_a), _ = _two_accounts(make_api)
    with psycopg.connect(database.worker_dsn()) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(CREATE_SESSION, (user_a, tenant_a, TOKEN_HASH, IP_HASH, None, 3600))


# ---- memberships ------------------------------------------------------------------------------------------------


def test_app_role_cannot_write_memberships(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    (user_a, tenant_a), (user_b, _) = _two_accounts(make_api)
    statements = [
        ("UPDATE memberships SET role = 'owner' WHERE user_id = %s", (user_a,)),
        ("UPDATE memberships SET user_id = %s WHERE tenant_id = %s", (user_b, tenant_a)),
        ("UPDATE memberships SET tenant_id = tenant_id", ()),
        ("INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')", (user_b, tenant_a)),
        ("DELETE FROM memberships", ()),
    ]
    for statement, params in statements:
        with _app_tx(database, tenant_a) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement, params)  # type: ignore[call-overload]
    assert admin_conn.execute("SELECT count(*) FROM memberships").fetchone() == (2,)


@contextmanager
def _app_may_update(admin_conn: psycopg.Connection, table: str) -> Iterator[None]:
    """Tetikleyiciyi yetkiden bağımsız sınamak için GEÇİCİ olarak tablo düzeyi UPDATE verir, çıkışta geri alır."""
    statements = {
        "memberships": (
            "GRANT UPDATE ON memberships TO netkar_app",
            "REVOKE UPDATE ON memberships FROM netkar_app",
        ),
        "tenants": ("GRANT UPDATE ON tenants TO netkar_app", "REVOKE UPDATE ON tenants FROM netkar_app"),
    }
    grant, revoke = statements[table]
    admin_conn.execute(grant)  # type: ignore[call-overload]
    try:
        yield
    finally:
        admin_conn.execute(revoke)  # type: ignore[call-overload]


def test_membership_guard_blocks_role_escalation_and_identity_changes(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    (user_a, tenant_a), (user_b, _) = _two_accounts(make_api)
    admin_conn.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = %s", (user_a,))
    with _app_may_update(admin_conn, "memberships"):
        # Yetki geri verilmiş olsa bile tetikleyici: viewer -> admin ve viewer -> owner (kendi rolünü yükseltme) 42501.
        for role in ("admin", "owner"):
            with _app_tx(database, tenant_a) as conn:
                with pytest.raises(psycopg.errors.InsufficientPrivilege) as exc:
                    conn.execute("UPDATE memberships SET role = %s WHERE user_id = %s", (role, user_a))
                assert exc.value.sqlstate == "42501"
        # Kimlik sütunları değişmez (23514).
        for statement, params in (
            ("UPDATE memberships SET user_id = %s WHERE user_id = %s", (user_b, user_a)),
            ("UPDATE memberships SET tenant_id = gen_random_uuid() WHERE user_id = %s", (user_a,)),
            ("UPDATE memberships SET id = gen_random_uuid() WHERE user_id = %s", (user_a,)),
            ("UPDATE memberships SET created_at = now() - interval '1 day' WHERE user_id = %s", (user_a,)),
        ):
            with _app_tx(database, tenant_a) as conn:
                with pytest.raises(psycopg.errors.CheckViolation):
                    conn.execute(statement, params)  # type: ignore[call-overload]
        # Rol düşürme ve aynı değerle yeniden yazma serbesttir.
        with _app_tx(database, tenant_a) as conn:
            assert (
                conn.execute("UPDATE memberships SET role = 'viewer' WHERE user_id = %s", (user_a,)).rowcount
                == 1
            )
            assert (
                conn.execute("UPDATE memberships SET role = role WHERE user_id = %s", (user_a,)).rowcount == 1
            )
    assert admin_conn.execute(
        "SELECT role::text FROM memberships WHERE user_id = %s", (user_a,)
    ).fetchone() == ("viewer",)


def test_membership_identity_is_immutable_even_for_superuser(
    make_api: Any, admin_conn: psycopg.Connection
) -> None:
    (user_a, _), (user_b, _) = _two_accounts(make_api)
    for statement, params in (
        ("UPDATE memberships SET user_id = %s WHERE user_id = %s", (user_b, user_a)),
        ("UPDATE memberships SET tenant_id = gen_random_uuid() WHERE user_id = %s", (user_a,)),
        ("UPDATE memberships SET id = gen_random_uuid() WHERE user_id = %s", (user_a,)),
        ("UPDATE memberships SET created_at = created_at - interval '1 day' WHERE user_id = %s", (user_a,)),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(statement, params)  # type: ignore[call-overload]


def test_role_escalation_stays_possible_for_superuser_and_owner_role(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    """Operasyon/destek yolu (süper kullanıcı, netkar_owner) rol yükseltebilir; mevcut testler buna dayanır."""
    (user_a, _), (user_b, tenant_b) = _two_accounts(make_api)
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    admin_conn.execute("UPDATE memberships SET role = 'admin' WHERE user_id = %s", (user_a,))
    owner_dsn = database.owner_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(owner_dsn) as conn:
        # FORCE RLS owner için de geçerlidir: kiracı bağlamı gerekir. Yükseltme tetikleyiciden geçer.
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_b,))
        assert (
            conn.execute("UPDATE memberships SET role = 'owner' WHERE user_id = %s", (user_b,)).rowcount == 1
        )
        conn.commit()
    assert admin_conn.execute(
        "SELECT role::text FROM memberships WHERE user_id = %s", (user_a,)
    ).fetchone() == ("admin",)
    assert admin_conn.execute(
        "SELECT role::text FROM memberships WHERE user_id = %s", (user_b,)
    ).fetchone() == ("owner",)


# ---- tenants ------------------------------------------------------------------------------------------------------


def test_app_role_cannot_update_tenants(
    make_api: Any, database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    (_, tenant_a), _ = _two_accounts(make_api)
    for statement in (
        "UPDATE tenants SET name = 'ele gecirildi'",
        "UPDATE tenants SET plan = 'enterprise'",
        "UPDATE tenants SET status = 'active'",
        "UPDATE tenants SET trial_ends_at = now() + interval '10 years'",
        "UPDATE tenants SET created_at = now()",
        "UPDATE tenants SET id = gen_random_uuid()",
    ):
        with _app_tx(database, tenant_a) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)  # type: ignore[call-overload]
    assert admin_conn.execute("SELECT plan FROM tenants WHERE id = %s", (tenant_a,)).fetchone() == ("trial",)


def test_tenant_identity_is_immutable_even_for_superuser(
    make_api: Any, admin_conn: psycopg.Connection
) -> None:
    _two_accounts(make_api)
    for statement in (
        "UPDATE tenants SET id = gen_random_uuid()",
        "UPDATE tenants SET created_at = created_at - interval '1 day'",
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(statement)  # type: ignore[call-overload]
    # Diğer sütunlar ve aynı değerle yazım serbest; tetikleyici kapatılınca created_at kaydırılabilir (test yolu).
    assert admin_conn.execute("UPDATE tenants SET name = name, plan = 'pro'").rowcount == 2
    with tenant_guard_disabled(admin_conn):
        assert (
            admin_conn.execute("UPDATE tenants SET created_at = created_at - interval '1 day'").rowcount == 2
        )
    assert admin_conn.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgname = 'tenants_immutable_guard'"
    ).fetchone() == ("A",)


def test_tenant_guard_fires_in_replica_mode(make_api: Any, admin_conn: psycopg.Connection) -> None:
    _two_accounts(make_api)
    admin_conn.execute("SET session_replication_role = replica")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute("UPDATE tenants SET id = gen_random_uuid()")
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute("UPDATE memberships SET tenant_id = gen_random_uuid()")
    finally:
        admin_conn.execute("RESET session_replication_role")


# ---- Mevcut akışlar -----------------------------------------------------------------------------------------------


def test_existing_auth_tenant_and_membership_flows_still_work(
    make_api: Any, admin_conn: psycopg.Connection
) -> None:
    api = make_api()
    user, tenant = _login(api, "akis@example.com")
    assert api.get("/v1/me").status_code == 200
    members = api.get("/v1/tenant/members").json()
    assert [(m["user_id"], m["role"]) for m in members] == [(user, "owner")]
    sessions = api.get("/v1/tenant/sessions").json()
    assert len(sessions) == 1 and sessions[0]["current"] is True
    # Oturum satırı işlevle yazıldı: zamanlar ve süre kodla uyumlu (30 gün).
    row = admin_conn.execute(
        "SELECT expires_at - created_at, created_at = last_seen_at, revoked_at IS NULL, tenant_id::text FROM sessions"
    ).fetchone()
    assert row is not None
    assert row[0].total_seconds() == SESSION_ABSOLUTE_MAX_SECONDS and row[1:] == (True, True, tenant)
    # Çıkış, yeniden giriş (yeni oturum işlevle açılır) ve parola sıfırlama sonrası giriş sürer.
    assert api.post("/v1/auth/logout").status_code == 204
    assert api.get("/v1/me").status_code == 401
    assert api.login("akis@example.com").status_code == 200
    assert api.get("/v1/me").status_code == 200
    assert admin_conn.execute("SELECT count(*) FROM sessions").fetchone() == (2,)


# ---- 0024 upgrade / downgrade / upgrade ---------------------------------------------------------------------------


def test_migration_0024_roundtrip_restores_old_grants_and_leaves_no_acl_residue(
    make_api: Any, alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    api = make_api()
    _login(api, "dongu@example.com")

    def state() -> dict[str, Any]:
        def one(sql: str) -> Any:
            row = admin_conn.execute(sql).fetchone()  # type: ignore[call-overload]
            assert row is not None
            return row[0]

        return {
            "function": one(
                "SELECT to_regprocedure('auth_gate.create_session(uuid, uuid, text, text, text, integer)')::text"
            ),
            "trigger_memberships": admin_conn.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgname = 'memberships_immutable_guard'"
            ).fetchone(),
            "trigger_tenants": admin_conn.execute(
                "SELECT tgenabled FROM pg_trigger WHERE tgname = 'tenants_immutable_guard'"
            ).fetchone(),
            "trigger_functions": one(
                "SELECT count(*) FROM pg_proc WHERE proname IN "
                "('memberships_immutable_guard', 'tenants_immutable_guard')"
            ),
            "app_sessions_insert": _table_priv(admin_conn, "netkar_app", "sessions", "INSERT"),
            "app_memberships": (
                _table_priv(admin_conn, "netkar_app", "memberships", "INSERT"),
                _table_priv(admin_conn, "netkar_app", "memberships", "UPDATE"),
            ),
            "app_tenants_update": _table_priv(admin_conn, "netkar_app", "tenants", "UPDATE"),
            "auth_session_insert_cols": sorted(
                c for c in SESSION_COLUMNS if _column_priv(admin_conn, "netkar_auth", "sessions", c, "INSERT")
            ),
            # Ham ACL'ler: tablo (relacl) ve sütun (attacl) düzeyi, rol adlarıyla karşılaştırılabilir metin.
            "relacl": admin_conn.execute(
                "SELECT relname, relacl::text FROM pg_class WHERE relname IN ('sessions', 'memberships', 'tenants') "
                "AND relnamespace = 'public'::regnamespace ORDER BY relname"
            ).fetchall(),
            "attacl": admin_conn.execute(
                "SELECT c.relname, a.attname, a.attacl::text FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "WHERE c.relname IN ('sessions', 'memberships', 'tenants') AND c.relnamespace = 'public'::regnamespace "
                "AND a.attnum > 0 AND NOT a.attisdropped AND a.attacl IS NOT NULL ORDER BY 1, 2"
            ).fetchall(),
            "sessions_rows": one("SELECT count(*) FROM sessions"),
            "membership_rows": one("SELECT count(*) FROM memberships"),
            "tenant_rows": one("SELECT count(*) FROM tenants"),
        }

    upgraded = state()
    assert upgraded["function"] is not None
    assert upgraded["trigger_memberships"] == ("A",) and upgraded["trigger_tenants"] == ("A",)
    assert upgraded["app_sessions_insert"] is False
    assert upgraded["app_memberships"] == (False, False) and upgraded["app_tenants_update"] is False
    assert upgraded["auth_session_insert_cols"] == sorted(AUTH_SESSION_INSERT_COLUMNS)
    # memberships ve tenants üzerinde netkar_app için sütun düzeyi ACL yok (yalnız tablo düzeyi SELECT).
    # (tenants.trial_ends_at için netkar_auth'un sütun yetkisi 0018'den gelir ve kalır.)
    assert not [r for r in upgraded["attacl"] if r[0] in ("memberships", "tenants") and "netkar_app=" in r[2]]

    previous: dict[str, Any] | None = None
    for _ in range(2):
        command.downgrade(alembic_cfg, "0023")
        down = state()
        assert down["function"] is None
        assert down["trigger_memberships"] is None and down["trigger_tenants"] is None
        assert down["trigger_functions"] == 0
        # 0001'deki tablo düzeyi yetkiler geri geldi.
        assert down["app_sessions_insert"] is True
        assert down["app_memberships"] == (True, True) and down["app_tenants_update"] is True
        assert down["auth_session_insert_cols"] == []  # netkar_auth sessions INSERT'i geri alındı
        # attacl temizliği: memberships ve tenants için sütun ACL'i yok; sessions yalnız 0023'ün UPDATE sütunları.
        assert not [r for r in down["attacl"] if r[0] in ("memberships", "tenants") and "netkar_app=" in r[2]]
        for _table, _column, acl in (r for r in down["attacl"] if r[0] == "sessions"):
            assert all("a" not in privs for privs in re.findall(r"=([a-zA-Z*]*)/", acl)), (
                acl
            )  # INSERT kalıntısı yok
        # Veri silinmedi.
        assert (down["sessions_rows"], down["membership_rows"], down["tenant_rows"]) == (1, 1, 1)
        # İki downgrade aynı ham ACL durumunu üretir (kalıntı birikmez).
        if previous is not None:
            assert (down["relacl"], down["attacl"]) == (previous["relacl"], previous["attacl"])
        previous = down
        command.upgrade(alembic_cfg, "head")
        again = state()
        assert again["function"] == upgraded["function"]
        assert (again["relacl"], again["attacl"]) == (upgraded["relacl"], upgraded["attacl"])
        assert again["app_sessions_insert"] is False and again["app_tenants_update"] is False
        assert (again["sessions_rows"], again["membership_rows"], again["tenant_rows"]) == (1, 1, 1)
