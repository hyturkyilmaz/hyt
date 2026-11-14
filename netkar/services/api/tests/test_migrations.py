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
