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
