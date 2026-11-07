"""Veritabanı rollerinin kurulumu (migrasyon öncesi, yönetici bağlantısıyla).

Üretimde aynı işi `infra/postgres/init/01-roles.sh` yapar; testler ve yerel geliştirme bu
işlevi kullanır. Roller kümeye özgüdür (veritabanına değil), bu yüzden idempotent yazılmıştır.
"""

from __future__ import annotations

import psycopg
from psycopg import sql


def provision_roles(
    admin_conn: psycopg.Connection,
    database: str,
    owner_password: str,
    app_password: str,
    worker_password: str,
) -> None:
    """Rolleri kurar ve veritabanını owner'a devreder (ADR-0005 §6).

    netkar_owner (migrasyon), netkar_app (API), netkar_worker (senkron işçisi: şifreli sütunları
    okuyabilen TEK rol), netkar_auth (auth_gate işlev sahibi), netkar_sync_gate (sync_gate işlev sahibi).
    """
    admin_conn.autocommit = True
    for role, login, password in (
        ("netkar_owner", True, owner_password),
        ("netkar_app", True, app_password),
        ("netkar_worker", True, worker_password),
        ("netkar_auth", False, None),
        ("netkar_sync_gate", False, None),
    ):
        exists = admin_conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        verb = "ALTER" if exists else "CREATE"
        options = "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS " + ("LOGIN" if login else "NOLOGIN")
        stmt = sql.SQL("{verb} ROLE {role} {opts}").format(
            verb=sql.SQL(verb), role=sql.Identifier(role), opts=sql.SQL(options)
        )
        if password is not None:
            stmt = stmt + sql.SQL(" PASSWORD {pw}").format(pw=sql.Literal(password))
        admin_conn.execute(stmt)
    # INHERIT FALSE: owner yalnız SET ROLE ile (migrasyonda) netkar_auth olabilir; politikaları devralmaz.
    # Aksi halde netkar_auth'a özel "auth_path" politikası owner için de geçerli olur ve FORCE RLS boşa düşer.
    admin_conn.execute("GRANT netkar_auth TO netkar_owner WITH INHERIT FALSE, SET TRUE")
    # Aynı kural sync_gate için: işlev sahibi rolün politikaları owner'a geçmez.
    admin_conn.execute("GRANT netkar_sync_gate TO netkar_owner WITH INHERIT FALSE, SET TRUE")
    db = sql.Identifier(database)
    admin_conn.execute(sql.SQL("ALTER DATABASE {db} OWNER TO netkar_owner").format(db=db))
    admin_conn.execute(sql.SQL("REVOKE ALL ON DATABASE {db} FROM PUBLIC").format(db=db))
    admin_conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {db} TO netkar_app").format(db=db))
    admin_conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {db} TO netkar_worker").format(db=db))
