"""RLS ve IDOR: bir kiracının oturumu başka kiracının verisini hiçbir yoldan göremez."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import pytest

from tests.conftest import Api, DatabaseInfo

TENANT_TABLES = ("memberships", "sessions", "audit_log")


@dataclass
class Tenant:
    api: Api
    tenant_id: str
    user_id: str
    email: str


@pytest.fixture
def two_tenants(make_api: Callable[..., Api]) -> tuple[Tenant, Tenant]:
    out = []
    for name in ("a", "b"):
        api = make_api()
        email = f"{name}@example.com"
        api.signup_and_login(email, tenant=f"Mağaza {name.upper()}")
        me = api.get("/v1/me").json()
        out.append(Tenant(api, me["tenant"]["id"], me["user_id"], email))
    return out[0], out[1]


@contextmanager
def app_tx(
    database: DatabaseInfo, tenant: str | None, user: str | None = None, dsn: str | None = None
) -> Iterator[psycopg.Connection[Any]]:
    """Uygulama rolüyle işlem açar ve RLS bağlamını işlem yerel ayarlar."""
    with psycopg.connect(dsn or database.app_dsn()) as conn:
        if tenant is not None:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        if user is not None:
            conn.execute("SELECT set_config('app.user_id', %s, true)", (user,))
        yield conn
        conn.rollback()


def test_endpoints_return_only_own_tenant_data(
    two_tenants: tuple[Tenant, Tenant], admin_conn: psycopg.Connection
) -> None:
    a, b = two_tenants
    me = a.api.get("/v1/me").json()
    assert me["tenant"]["id"] == a.tenant_id and me["user_id"] == a.user_id
    assert b.tenant_id not in str(me) and b.email not in str(me)

    members = a.api.get("/v1/tenant/members").json()
    assert [m["user_id"] for m in members] == [a.user_id]

    sessions = a.api.get("/v1/tenant/sessions").json()
    b_sessions = {
        str(r[0]) for r in admin_conn.execute("SELECT id FROM sessions WHERE tenant_id = %s", (b.tenant_id,))
    }
    assert sessions and not ({s["id"] for s in sessions} & b_sessions)
    assert {s["user_id"] for s in sessions} == {a.user_id}

    audit = a.api.get("/v1/tenant/audit?limit=200").json()
    a_audit = {
        r[0] for r in admin_conn.execute("SELECT id FROM audit_log WHERE tenant_id = %s", (a.tenant_id,))
    }
    assert {x["id"] for x in audit} == a_audit
    assert b.user_id not in str(audit) and b.tenant_id not in str(audit)


def test_client_supplied_tenant_hints_are_ignored(two_tenants: tuple[Tenant, Tenant]) -> None:
    a, b = two_tenants
    for path in ("/v1/me", "/v1/tenant/members", "/v1/tenant/audit", "/v1/tenant/sessions"):
        r = a.api.get(
            f"{path}{'&' if '?' in path else '?'}tenant_id={b.tenant_id}",
            headers={"X-Tenant-Id": b.tenant_id, "X-User-Id": b.user_id},
        )
        assert r.status_code == 200
        assert b.tenant_id not in r.text and b.user_id not in r.text and b.email not in r.text


def test_cannot_use_other_tenants_session_via_forged_cookie(two_tenants: tuple[Tenant, Tenant]) -> None:
    a, _ = two_tenants
    token = a.api.client.cookies.get("__Host-nk_session")
    assert token
    mutated = token[:-1] + ("A" if token[-1] != "A" else "B")
    a.api.client.cookies.set("__Host-nk_session", mutated)
    assert a.api.get("/v1/me").status_code == 401


@pytest.mark.parametrize(
    "table,column",
    [("memberships", "tenant_id"), ("sessions", "tenant_id"), ("audit_log", "tenant_id"), ("tenants", "id")],
)
def test_direct_sql_sees_only_own_rows(
    table: str,
    column: str,
    two_tenants: tuple[Tenant, Tenant],
    database: DatabaseInfo,
    admin_conn: psycopg.Connection,
) -> None:
    a, b = two_tenants
    total = admin_conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    own = admin_conn.execute(f"SELECT count(*) FROM {table} WHERE {column} = %s", (a.tenant_id,)).fetchone()
    assert total and own and total[0] > own[0] > 0  # B satırları gerçekten var

    with app_tx(database, a.tenant_id) as conn:
        seen = {str(r[0]) for r in conn.execute(f"SELECT {column} FROM {table}")}
        assert seen == {a.tenant_id}
        # Başka kiracıyı açıkça sorgulamak da boş döner
        assert conn.execute(
            f"SELECT count(*) FROM {table} WHERE {column} = %s", (b.tenant_id,)
        ).fetchone() == (0,)


def test_no_context_or_empty_context_sees_nothing(
    two_tenants: tuple[Tenant, Tenant], database: DatabaseInfo
) -> None:
    for tenant in (None, ""):
        with app_tx(database, tenant) as conn:
            for table in (*TENANT_TABLES, "tenants", "users"):
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table


def test_users_visible_only_for_self(two_tenants: tuple[Tenant, Tenant], database: DatabaseInfo) -> None:
    a, _ = two_tenants
    with app_tx(database, a.tenant_id, a.user_id) as conn:
        assert [str(r[0]) for r in conn.execute("SELECT id FROM users")] == [a.user_id]
    # Kiracı A bağlamı + B'nin kullanıcı kimliği: kendi kiracısı olmayan kullanıcı yine de
    # yalnız app.user_id ile eşleşeni görür; bu değeri istemci değil sunucu belirler.
    with app_tx(database, a.tenant_id) as conn:
        assert conn.execute("SELECT count(*) FROM users").fetchone() == (0,)


def test_cross_tenant_writes_are_blocked(
    two_tenants: tuple[Tenant, Tenant], database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    a, b = two_tenants
    with app_tx(database, a.tenant_id) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO audit_log (tenant_id, action) VALUES (%s, 'x')", (b.tenant_id,))
    with app_tx(database, a.tenant_id) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')",
                (a.user_id, b.tenant_id),
            )
    with app_tx(database, a.tenant_id) as conn:
        cur = conn.execute("UPDATE sessions SET revoked_at = now() WHERE tenant_id = %s", (b.tenant_id,))
        assert cur.rowcount == 0
        cur = conn.execute("UPDATE tenants SET name = 'ele geçirildi' WHERE id = %s", (b.tenant_id,))
        assert cur.rowcount == 0
        # Kendi satırını başka kiracıya taşıyamaz (WITH CHECK)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "UPDATE sessions SET tenant_id = %s WHERE tenant_id = %s", (b.tenant_id, a.tenant_id)
            )
    assert admin_conn.execute(
        "SELECT count(*) FROM sessions WHERE tenant_id = %s AND revoked_at IS NOT NULL", (b.tenant_id,)
    ).fetchone() == (0,)
    assert admin_conn.execute("SELECT name FROM tenants WHERE id = %s", (b.tenant_id,)).fetchone() == (
        "Mağaza B",
    )


def test_forced_rls_applies_even_to_table_owner(
    two_tenants: tuple[Tenant, Tenant], database: DatabaseInfo
) -> None:
    a, _ = two_tenants
    owner_dsn = database.owner_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with app_tx(database, a.tenant_id, dsn=owner_dsn) as conn:
        assert {str(r[0]) for r in conn.execute("SELECT tenant_id FROM sessions")} == {a.tenant_id}
    with app_tx(database, None, dsn=owner_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone() == (0,)


def test_app_role_is_least_privileged(two_tenants: tuple[Tenant, Tenant], database: DatabaseInfo) -> None:
    a, _ = two_tenants
    with app_tx(database, a.tenant_id, a.user_id) as conn:
        role = conn.execute(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        assert role == (False, False, False, False)
    forbidden = [
        "SELECT password_hash FROM users",
        "SELECT * FROM users",
        "SELECT * FROM password_reset_tokens",
        "INSERT INTO users (email, password_hash) VALUES ('x@example.com', 'h')",
        "UPDATE users SET password_hash = 'h'",
        "UPDATE users SET email = 'y@example.com'",
        "UPDATE audit_log SET action = 'silindi'",
        "DELETE FROM audit_log",
        "DELETE FROM sessions",
        "DROP TABLE sessions",
        "TRUNCATE sessions",
        "INSERT INTO tenants (name) VALUES ('sahte')",
    ]
    for statement in forbidden:
        with app_tx(database, a.tenant_id, a.user_id) as conn:
            with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.UndefinedTable)):
                conn.execute(statement)  # type: ignore[call-overload]


def test_every_tenant_table_has_forced_rls(admin_conn: psycopg.Connection) -> None:
    """Gelecekte eklenecek her tenant_id'li tablo da ENABLE + FORCE RLS taşımak zorundadır."""
    rows = admin_conn.execute(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
          AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                      AND a.attname = 'tenant_id' AND NOT a.attisdropped)
        """
    ).fetchall()
    names = {r[0] for r in rows}
    assert {"memberships", "sessions", "audit_log"} <= names
    for name, enabled, forced, policies in rows:
        assert enabled and forced and policies >= 1, name


def test_auth_gate_functions_are_security_definer_with_fixed_search_path(
    admin_conn: psycopg.Connection,
) -> None:
    rows = admin_conn.execute(
        """
        SELECT p.proname, p.prosecdef, r.rolname, p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        JOIN pg_roles r ON r.oid = p.proowner WHERE n.nspname = 'auth_gate'
        """
    ).fetchall()
    assert {r[0] for r in rows} == {
        "find_user_for_login",
        "get_session",
        "register_account",
        "create_password_reset",
        "consume_password_reset",
    }
    for name, secdef, owner, config in rows:
        assert secdef and owner == "netkar_auth", name
        assert config and any(c.startswith("search_path=") for c in config), name
    # PUBLIC'in çalıştırma yetkisi yok
    assert admin_conn.execute(
        "SELECT has_function_privilege('public', 'auth_gate.get_session(text)', 'EXECUTE')"
    ).fetchone() == (False,)
