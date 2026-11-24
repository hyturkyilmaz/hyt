"""Alembic ortamı. Migrasyonlar ayrı (tablo sahibi) rolle, senkron psycopg ile çalışır."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_MIGRATION_URL")
    if not url:
        raise RuntimeError("DATABASE_MIGRATION_URL tanımlı değil")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Çevrimdışı mod desteklenmiyor")
run_migrations_online()
