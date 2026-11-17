"""Migrasyonlar: geri alınabilirlik ve şema doğrulaması."""

from __future__ import annotations

import psycopg
from alembic import command
from alembic.config import Config


def test_downgrade_then_upgrade_roundtrip(alembic_cfg: Config, admin_conn: psycopg.Connection) -> None:
    command.downgrade(alembic_cfg, "base")
    tables = {r[0] for r in admin_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert tables == set() or tables == {"alembic_version"}
    assert admin_conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='auth_gate'").fetchone() is None
    command.upgrade(alembic_cfg, "head")
    tables = {r[0] for r in admin_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    assert {
        "tenants",
        "users",
        "memberships",
        "sessions",
        "password_reset_tokens",
        "audit_log",
        "rate_limits",
        "procrastinate_jobs",
    } <= tables


def test_totp_state_migration_0003_is_reversible_and_least_privileged(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    new_columns = {"totp_last_step", "totp_failed_count", "totp_locked_until"}

    def user_columns() -> set[str]:
        rows = admin_conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"
        )
        return {r[0] for r in rows}

    command.downgrade(alembic_cfg, "0002")
    assert not (new_columns & user_columns())
    command.upgrade(alembic_cfg, "head")
    assert new_columns <= user_columns()
    for column in sorted(new_columns):
        privileges = admin_conn.execute(
            "SELECT has_column_privilege('netkar_app', 'users', %s, 'SELECT'),"
            " has_column_privilege('netkar_app', 'users', %s, 'UPDATE')",
            (column, column),
        ).fetchone()
        assert privileges == (True, True), column
    # Parola özeti hâlâ uygulama rolüne kapalı
    assert admin_conn.execute(
        "SELECT has_column_privilege('netkar_app', 'users', 'password_hash', 'SELECT')"
    ).fetchone() == (False,)


def test_migration_0015_demo_flag_and_marks_are_reversible(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    def has_column() -> bool:
        return (
            admin_conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'marketplace_accounts' "
                "AND column_name = 'is_demo'"
            ).fetchone()
            is not None
        )

    assert has_column()
    command.downgrade(alembic_cfg, "0014")
    assert not has_column()
    assert admin_conn.execute("SELECT to_regclass('public.deployment_marks')").fetchone() == (None,)
    assert admin_conn.execute("SELECT to_regprocedure('public.mark_demo_account(uuid)')").fetchone() == (
        None,
    )
    # Eski durum: INSERT tablo düzeyinde geri gelir.
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'marketplace_accounts', 'INSERT')"
    ).fetchone() == (True,)
    command.upgrade(alembic_cfg, "head")
    assert has_column()
    privileges = admin_conn.execute(
        "SELECT has_column_privilege('netkar_app', 'marketplace_accounts', 'is_demo', 'INSERT'),"
        " has_column_privilege('netkar_app', 'marketplace_accounts', 'is_demo', 'UPDATE'),"
        " has_table_privilege('netkar_app', 'deployment_marks', 'INSERT'),"
        " has_table_privilege('netkar_app', 'deployment_marks', 'SELECT'),"
        " has_function_privilege('netkar_app', 'public.mark_demo_account(uuid)', 'EXECUTE')"
    ).fetchone()
    assert privileges == (False, False, False, True, True)


def test_migration_0016_instance_id_and_strict_mark_function_are_reversible(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    def instance_id() -> str | None:
        row = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
        return None if row is None else str(row[0])

    def function_raises_when_nothing_updated() -> bool:
        source = admin_conn.execute(
            "SELECT prosrc FROM pg_proc WHERE oid = 'public.mark_demo_account(uuid)'::regprocedure"
        ).fetchone()
        assert source is not None
        return "IF NOT FOUND" in source[0]

    first = instance_id()
    assert first is not None and len(first) == 36 and function_raises_when_nothing_updated()
    command.downgrade(alembic_cfg, "0015")
    assert instance_id() is None and not function_raises_when_nothing_updated()
    command.upgrade(alembic_cfg, "head")
    second = instance_id()
    assert second is not None and len(second) == 36 and function_raises_when_nothing_updated()
    # Sahip ve yetkiler `CREATE OR REPLACE` ile korunur: uygulama çalıştırabilir, PUBLIC çalıştıramaz.
    row = admin_conn.execute(
        "SELECT pg_get_userbyid(proowner), has_function_privilege('netkar_app', oid, 'EXECUTE'), "
        "has_function_privilege('public', oid, 'EXECUTE') "
        "FROM pg_proc WHERE oid = 'public.mark_demo_account(uuid)'::regprocedure"
    ).fetchone()
    assert row == ("netkar_owner", True, False)
    # Uygulama ve işçi instance_id'yi okur ama yazamaz.
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'deployment_marks', 'SELECT'),"
        " has_table_privilege('netkar_worker', 'deployment_marks', 'SELECT'),"
        " has_table_privilege('netkar_app', 'deployment_marks', 'INSERT'),"
        " has_table_privilege('netkar_worker', 'deployment_marks', 'UPDATE')"
    ).fetchone() == (True, True, False, False)


def test_migration_0017_email_verification_is_reversible_and_least_privileged(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    def result_columns() -> list[str]:
        row = admin_conn.execute(
            "SELECT p.proargnames, p.proargmodes FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'auth_gate' AND p.proname = 'consume_password_reset'"
        ).fetchone()
        assert row is not None
        names, modes = row
        return [n for n, m in zip(names, modes, strict=True) if m == "t"]

    def functions() -> set[str]:
        rows = admin_conn.execute(
            "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = 'auth_gate'"
        )
        return {r[0] for r in rows}

    new_functions = {"create_email_verification", "consume_email_verification"}
    assert new_functions <= functions()
    assert result_columns() == ["reset_user_id", "reset_tenant_id", "reset_claimed_unverified"]
    assert admin_conn.execute("SELECT to_regclass('public.email_verification_tokens')").fetchone() != (None,)
    # Uygulama rolü token tablosuna erişemez; RLS zorlu
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'email_verification_tokens', 'SELECT'),"
        " has_table_privilege('netkar_app', 'email_verification_tokens', 'INSERT'),"
        " (SELECT relforcerowsecurity FROM pg_class WHERE relname = 'email_verification_tokens')"
    ).fetchone() == (False, False, True)

    command.downgrade(alembic_cfg, "0016")
    assert not (new_functions & functions())
    assert admin_conn.execute("SELECT to_regclass('public.email_verification_tokens')").fetchone() == (None,)
    # Eski gövde geri geldi (iki sütun) ve uygulama rolü hâlâ çalıştırabilir
    assert result_columns() == ["reset_user_id", "reset_tenant_id"]
    assert admin_conn.execute(
        "SELECT has_function_privilege('netkar_app', 'auth_gate.consume_password_reset(text, text)', 'EXECUTE')"
    ).fetchone() == (True,)
    # email_verified_at sütunu 0001'den gelir; geri alma onu silmez
    assert (
        admin_conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'email_verified_at'"
        ).fetchone()
        is not None
    )

    command.upgrade(alembic_cfg, "head")
    assert new_functions <= functions()
    assert result_columns() == ["reset_user_id", "reset_tenant_id", "reset_claimed_unverified"]
