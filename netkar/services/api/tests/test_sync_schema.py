"""Migrasyon 0006: şema, RLS, rol yetkileri (D-05), sync_gate ve geri alınabilirlik (ADR-0005)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect

from app.models import (
    CargoInvoiceItem,
    FinancialTransaction,
    Order,
    OrderLine,
    Product,
    ProductCost,
    Return,
    SyncCursor,
    SyncRun,
)
from tests.conftest import DatabaseInfo
from tests.sync_helpers import make_seller

NEW_TABLES = (
    "products",
    "product_costs",
    "orders",
    "order_lines",
    "returns",
    "financial_transactions",
    "cargo_invoice_items",
    "sync_runs",
    "sync_cursors",
)
MODELS: tuple[type[Any], ...] = (
    Product,
    ProductCost,
    Order,
    OrderLine,
    Return,
    FinancialTransaction,
    CargoInvoiceItem,
    SyncRun,
    SyncCursor,
)
# Son müşteriye ait kişisel veri sütunu hiçbir tabloda olamaz (KVKK, EK-6).
FORBIDDEN_COLUMN_PARTS = (
    "first_name",
    "last_name",
    "full_name",
    "customer_name",
    "address",
    "phone",
    "email",
    "tckn",
    "identity",
    "tax_number",
    "tax_office",
    "latitude",
    "longitude",
    "note",
    "district",
    "neighborhood",
    "postal",
)


@contextmanager
def role_tx(dsn: str, tenant_id: Any | None = None) -> Iterator[psycopg.Connection[Any]]:
    """Verilen rolle işlem açar (kiracı bağlamı verilirse işlem yerel olarak kurulur); sonunda geri alır."""
    with psycopg.connect(dsn) as conn:
        if tenant_id is not None:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        try:
            yield conn
        finally:
            conn.rollback()


def test_all_new_tables_exist_with_forced_rls_and_account_scope(admin_conn: psycopg.Connection) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation'),
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'),
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                       AND a.attname = 'marketplace_account_id')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
        """,
        (list(NEW_TABLES),),
    ).fetchall()
    assert {r[0] for r in rows} == set(NEW_TABLES)
    for name, enabled, forced, policies, has_tenant, has_account in rows:
        assert enabled and forced and policies == 1 and has_tenant and has_account, name


def test_no_table_has_a_customer_pii_column(admin_conn: psycopg.Connection) -> None:
    columns = admin_conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s)",
        (list(NEW_TABLES),),
    ).fetchall()
    bad = [(t, c) for t, c in columns if any(part in c for part in FORBIDDEN_COLUMN_PARTS)]
    assert bad == []
    # il adı tutulabilir; müşteri anahtarı yalnız takma adlıdır
    names = {c for t, c in columns if t == "orders"}
    assert {"province", "province_code", "customer_key"} <= names


def test_orm_models_match_database_columns(admin_conn: psycopg.Connection) -> None:
    for model in MODELS:
        table = model.__tablename__
        db_columns = {
            r[0]
            for r in admin_conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
            )
        }
        mapper: Any = sa_inspect(model)
        assert {c.key for c in mapper.columns} == db_columns, table


def test_money_columns_are_lossless_numeric_and_rates_are_bounded(admin_conn: psycopg.Connection) -> None:
    rows = admin_conn.execute(
        "SELECT table_name, column_name, numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s) AND data_type = 'numeric'",
        (list(NEW_TABLES),),
    ).fetchall()
    for table, column, precision, scale in rows:
        if column.endswith("_rate"):
            assert (precision, scale) == (9, 4), (table, column)
        elif column.endswith("deci") or column == "unit_desi":
            assert (precision, scale) == (12, 4), (table, column)
        else:
            assert (precision, scale) == (18, 6), (table, column)  # kuruş altı hassasiyet (74,985)
    assert {c for _, c, _, _ in rows} >= {"commission_amount", "seller_revenue", "unit_cost_excl_vat"}


def test_natural_keys_are_unique_and_account_tenant_pair_is_enforced(
    admin_conn: psycopg.Connection,
) -> None:
    seller = make_seller(admin_conn)
    other = make_seller(admin_conn, seller_id="9999")
    # hesap başka kiracıya ait bir satıra bağlanamaz (bileşik yabancı anahtar)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin_conn.execute(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B1')",
            (other.tenant_id, seller.account_id),
        )
    admin_conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B1')",
        (seller.tenant_id, seller.account_id),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin_conn.execute(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B1')",
            (seller.tenant_id, seller.account_id),
        )


def test_check_constraints_reject_bad_values(admin_conn: psycopg.Connection) -> None:
    seller = make_seller(admin_conn)
    base = (seller.tenant_id, seller.account_id)
    for sql, params in (
        (
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode, vat_rate) VALUES (%s, %s, 'B', 101)",
            base,
        ),
        ("INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, '')", base),
        (
            "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, "
            "unit_cost_excl_vat, vat_rate, entered_by) VALUES (%s, %s, 'B', '2026-01-01', -1, 20, %s)",
            (*base, seller.user_id),
        ),
        (
            "INSERT INTO sync_runs (tenant_id, marketplace_account_id, run_group_id, kind, source, status) "
            "VALUES (%s, %s, gen_random_uuid(), 'backfill', 'orders', 'failed')",
            base,
        ),
        (
            "INSERT INTO sync_runs (tenant_id, marketplace_account_id, run_group_id, kind, source, status) "
            "VALUES (%s, %s, gen_random_uuid(), 'backfill', 'sorular', 'running')",
            base,
        ),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(sql, params)  # type: ignore[call-overload]


def test_app_role_cannot_select_encrypted_columns_but_can_write_them(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    """D-05: şifreli sütunlar yalnız worker'a okunur; bağlantı ekleme yolu (INSERT/UPDATE) çalışır."""
    seller = make_seller(admin_conn)
    for column in ("api_key_encrypted", "api_secret_encrypted"):
        with (
            role_tx(database.app_dsn(), seller.tenant_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(f"SELECT {column} FROM marketplace_accounts")
    with (
        role_tx(database.app_dsn(), seller.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("SELECT * FROM marketplace_accounts")
    with role_tx(database.app_dsn(), seller.tenant_id) as conn:
        row = conn.execute("SELECT id, seller_id, status, api_key_last4 FROM marketplace_accounts").fetchone()
        assert row is not None and row[1] == seller.seller_id
        # yeniden bağlama yolu: şifreli sütunları yazabilir
        updated = conn.execute(
            "UPDATE marketplace_accounts SET api_key_encrypted = 'v2:x', status = 'active', updated_at = now() "
            "WHERE id = %s",
            (seller.account_id,),
        ).rowcount
        assert updated == 1
    priv = admin_conn.execute(
        "SELECT has_column_privilege('netkar_app', 'marketplace_accounts', 'api_key_encrypted', 'INSERT'),"
        " has_column_privilege('netkar_app', 'marketplace_accounts', 'api_secret_encrypted', 'UPDATE')"
    ).fetchone()
    assert priv == (True, True)


def test_worker_role_reads_encrypted_columns_only_inside_its_tenant(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    a = make_seller(admin_conn, seller_id="1111")
    b = make_seller(admin_conn, seller_id="2222")
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        rows = conn.execute("SELECT seller_id, api_key_encrypted FROM marketplace_accounts").fetchall()
        assert [r[0] for r in rows] == ["1111"] and rows[0][1].startswith("v2:")
        assert conn.execute(
            "SELECT count(*) FROM marketplace_accounts WHERE id = %s", (b.account_id,)
        ).fetchone() == (0,)
    with role_tx(database.worker_dsn()) as conn:  # kiracı bağlamı yok: RLS her şeyi gizler
        assert conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM orders").fetchone() == (0,)


def test_worker_role_is_not_privileged_and_cannot_delete_or_touch_identity(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    row = admin_conn.execute(
        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, rolcanlogin FROM pg_roles "
        "WHERE rolname = 'netkar_worker'"
    ).fetchone()
    assert row == (False, False, False, False, True)
    gate = admin_conn.execute(
        "SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'netkar_sync_gate'"
    ).fetchone()
    assert gate == (False, False, False)
    # worker hiçbir tabloda DELETE yapamaz (rate_limits hariç: operasyonel sayaç)
    deletable = {
        r[0]
        for r in admin_conn.execute(
            "SELECT table_name FROM information_schema.role_table_grants "
            "WHERE grantee = 'netkar_worker' AND privilege_type = 'DELETE' AND table_schema = 'public'"
        )
    }
    assert {t for t in deletable if not t.startswith("procrastinate_")} == {"rate_limits"}
    # hesap kimlik sütunları worker için de değişmezdir; yalnız status ve updated_at güncellenir
    updatable = {
        r[0]
        for r in admin_conn.execute(
            "SELECT column_name FROM information_schema.column_privileges "
            "WHERE grantee = 'netkar_worker' AND table_name = 'marketplace_accounts' "
            "AND privilege_type = 'UPDATE'"
        )
    }
    assert updatable == {"status", "updated_at"}
    # kullanıcı verisi: maliyeti worker yazamaz
    assert admin_conn.execute(
        "SELECT has_table_privilege('netkar_worker', 'product_costs', 'INSERT'),"
        " has_table_privilege('netkar_worker', 'product_costs', 'UPDATE'),"
        " has_table_privilege('netkar_worker', 'product_costs', 'SELECT')"
    ).fetchone() == (False, False, True)
    # tablolar: netkar_app'te DELETE hiçbirinde yok; kullanıcı verisi dışında yalnız SELECT
    app_priv = {
        (r[0], r[1])
        for r in admin_conn.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = 'netkar_app' AND table_name = ANY(%s)",
            (list(NEW_TABLES),),
        )
    }
    assert {t for t, p in app_priv if p == "DELETE"} == set()
    assert {t for t, p in app_priv if p in ("INSERT", "UPDATE")} == {"product_costs"}


def test_app_role_may_only_flip_returned_to_stock(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    seller = make_seller(admin_conn)
    admin_conn.execute(
        "INSERT INTO returns (tenant_id, marketplace_account_id, claim_id, claim_item_id, order_number) "
        "VALUES (%s, %s, 'C1', 'I1', '1001')",
        (seller.tenant_id, seller.account_id),
    )
    with role_tx(database.app_dsn(), seller.tenant_id) as conn:
        assert conn.execute("UPDATE returns SET returned_to_stock = false, updated_at = now()").rowcount == 1
    with (
        role_tx(database.app_dsn(), seller.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE returns SET status = 'Accepted'")


def test_app_role_cannot_write_synced_data_and_isolation_holds_for_both_roles(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    a = make_seller(admin_conn, seller_id="1111")
    b = make_seller(admin_conn, seller_id="2222")
    for seller in (a, b):
        admin_conn.execute(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B1')",
            (seller.tenant_id, seller.account_id),
        )
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        assert conn.execute("SELECT marketplace_account_id FROM products").fetchall() == [(a.account_id,)]
    with (
        role_tx(database.app_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "INSERT INTO orders (tenant_id, marketplace_account_id, order_number, shipment_package_id, ordered_at) "
            "VALUES (%s, %s, '1', 1, now())",
            (a.tenant_id, a.account_id),
        )
    # worker bile başka kiracının satırını yazamaz (WITH CHECK)
    with (
        role_tx(database.worker_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B2')",
            (b.tenant_id, b.account_id),
        )
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:
        conn.execute(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode) VALUES (%s, %s, 'B2')",
            (a.tenant_id, a.account_id),
        )
        assert conn.execute("SELECT count(*) FROM products").fetchone() == (2,)


def test_sync_gate_returns_only_active_accounts_without_secrets(
    database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    active = make_seller(admin_conn, seller_id="1111")
    make_seller(admin_conn, seller_id="2222", status="invalid")
    make_seller(admin_conn, seller_id="3333", status="revoked")
    admin_conn.execute(
        "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark, backfill_completed_at) "
        "VALUES (%s, %s, 'orders', now(), now()), (%s, %s, 'claims', now(), NULL)",
        (active.tenant_id, active.account_id, active.tenant_id, active.account_id),
    )
    with role_tx(database.worker_dsn()) as conn:  # kiracı bağlamı olmadan
        rows = conn.execute("SELECT * FROM sync_gate.syncable_accounts()").fetchall()
        assert rows == [(active.tenant_id, active.account_id, ["orders"])]
        one = conn.execute(
            "SELECT tenant_id FROM sync_gate.syncable_accounts(%s)", (active.account_id,)
        ).fetchall()
        assert one == [(active.tenant_id,)]
        assert conn.execute("SELECT * FROM sync_gate.syncable_accounts(%s)", (uuid4(),)).fetchall() == []
        # işlev tabloyu açmaz: worker kiracı bağlamsız tabloyu hâlâ göremez
        assert conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
    result_columns = admin_conn.execute(
        "SELECT pg_get_function_result(p.oid), p.prosecdef, p.proconfig, r.rolname FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace JOIN pg_roles r ON r.oid = p.proowner "
        "WHERE n.nspname = 'sync_gate'"
    ).fetchall()
    assert len(result_columns) == 1
    result, secdef, config, owner = result_columns[0]
    assert secdef and owner == "netkar_sync_gate" and any("search_path" in c for c in config)
    assert "encrypted" not in result and "secret" not in result


def test_sync_gate_is_closed_to_the_app_role(database: DatabaseInfo) -> None:
    with role_tx(database.app_dsn()) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM sync_gate.syncable_accounts()")


def test_migration_0006_is_reversible_and_restores_previous_grants(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    def tables() -> set[str]:
        return {
            r[0] for r in admin_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }

    assert set(NEW_TABLES) <= tables()
    try:
        command.downgrade(alembic_cfg, "0005")
        assert not (set(NEW_TABLES) & tables())
        assert admin_conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = 'sync_gate'").fetchone() is None
        # 0005 durumu: netkar_app tablo düzeyinde SELECT'e (şifreli sütunlar dahil) geri döner
        assert admin_conn.execute(
            "SELECT has_column_privilege('netkar_app', 'marketplace_accounts', 'api_key_encrypted', 'SELECT')"
        ).fetchone() == (True,)
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_worker', 'marketplace_accounts', 'SELECT')"
        ).fetchone() == (False,)
        command.upgrade(alembic_cfg, "head")
        assert set(NEW_TABLES) <= tables()
        assert admin_conn.execute(
            "SELECT has_column_privilege('netkar_app', 'marketplace_accounts', 'api_key_encrypted', 'SELECT')"
        ).fetchone() == (False,)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_migration_fails_with_clear_message_when_roles_are_missing(
    alembic_cfg: Config, admin_conn: psycopg.Connection
) -> None:
    """Roller migrasyondan önce kurulmalıdır (netkar_owner CREATEROLE değildir)."""
    try:
        command.downgrade(alembic_cfg, "0005")
        admin_conn.execute("ALTER ROLE netkar_worker RENAME TO netkar_worker_gecici")
        with pytest.raises(Exception, match="provision_roles"):
            command.upgrade(alembic_cfg, "head")
    finally:
        admin_conn.execute("ALTER ROLE netkar_worker_gecici RENAME TO netkar_worker")
        command.upgrade(alembic_cfg, "head")
