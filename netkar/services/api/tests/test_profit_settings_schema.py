"""Migrasyon 0007 (kâr ayarları): şema, CHECK kısıtları, RLS/IDOR, rol yetkileri ve geri alınabilirlik (ADR-0006 §3.2)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect

from app.models import (
    CargoTariffRecord,
    ProfitSettingsRecord,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
)
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller, make_seller

TABLES = ("profit_settings", "cargo_tariffs", "service_fee_estimates", "variable_expenses")
DELETABLE = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")
MODELS: tuple[type[Any], ...] = (
    ProfitSettingsRecord,
    CargoTariffRecord,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
)
BRACKETS = '[{"max_desi": "2", "price": "45.00"}]'


@contextmanager
def role_tx(dsn: str, tenant_id: Any | None = None) -> Iterator[psycopg.Connection[Any]]:
    """Verilen rolle işlem açar (kiracı bağlamı işlem yerel kurulur); sonunda geri alır."""
    with psycopg.connect(dsn) as conn:
        if tenant_id is not None:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        try:
            yield conn
        finally:
            conn.rollback()


def insert_all(conn: psycopg.Connection[Any], seller: Seller) -> dict[str, Any]:
    """Dört tabloya birer satır (superuser bağlantısıyla) ve kimlikleri."""
    ids: dict[str, Any] = {}
    base = (seller.tenant_id, seller.account_id)
    row = conn.execute(
        "INSERT INTO profit_settings (tenant_id, marketplace_account_id, default_desi, updated_by) "
        "VALUES (%s, %s, 3, %s) RETURNING id",
        (*base, seller.user_id),
    ).fetchone()
    assert row is not None
    ids["profit_settings"] = row[0]
    row = conn.execute(
        "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
        "price_includes_vat, brackets, entered_by) VALUES (%s, %s, 'trendyol', 'TE', '2026-01-01', true, %s, %s) "
        "RETURNING id",
        (*base, BRACKETS, seller.user_id),
    ).fetchone()
    assert row is not None
    ids["cargo_tariffs"] = row[0]
    row = conn.execute(
        "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, valid_from, amount, "
        "amount_includes_vat, entered_by) VALUES (%s, %s, '2026-01-01', 12, true, %s) RETURNING id",
        (*base, seller.user_id),
    ).fetchone()
    assert row is not None
    ids["service_fee_estimates"] = row[0]
    row = conn.execute(
        "INSERT INTO variable_expenses (tenant_id, marketplace_account_id, name, kind, amount_excl_vat, "
        "vat_rate, valid_from, entered_by) VALUES (%s, %s, 'paket', 'siparis_basi', 6, 20, '2026-01-01', %s) "
        "RETURNING id",
        (*base, seller.user_id),
    ).fetchone()
    assert row is not None
    ids["variable_expenses"] = row[0]
    return ids


# --------------------------------------------------------------------------- şema
def test_tables_exist_with_forced_rls_and_account_scope(admin_conn: psycopg.Connection[Any]) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation'),
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND a.attname = 'tenant_id'),
               EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                       AND a.attname = 'marketplace_account_id'),
               EXISTS (SELECT 1 FROM pg_indexes i WHERE i.tablename = c.relname
                       AND i.indexname = 'ix_' || c.relname || '_tenant_account')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
        """,
        (list(TABLES),),
    ).fetchall()
    assert {r[0] for r in rows} == set(TABLES)
    for name, enabled, forced, policies, has_tenant, has_account, has_index in rows:
        assert enabled and forced and policies == 1 and has_tenant and has_account and has_index, name


def test_orm_models_match_database_columns(admin_conn: psycopg.Connection[Any]) -> None:
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


def test_money_and_rate_column_types(admin_conn: psycopg.Connection[Any]) -> None:
    rows = admin_conn.execute(
        "SELECT table_name, column_name, numeric_precision, numeric_scale FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY(%s) AND data_type = 'numeric'",
        (list(TABLES),),
    ).fetchall()
    types = {(t, c): (p, s) for t, c, p, s in rows}
    assert types == {
        ("profit_settings", "default_desi"): (9, 2),
        ("service_fee_estimates", "amount"): (18, 6),
        ("variable_expenses", "amount_excl_vat"): (18, 6),
        ("variable_expenses", "percent"): (9, 4),
        ("variable_expenses", "vat_rate"): (9, 4),
    }


def test_natural_keys_are_unique_and_account_tenant_pair_is_enforced(
    admin_conn: psycopg.Connection[Any],
) -> None:
    seller = make_seller(admin_conn)
    other = make_seller(admin_conn, seller_id="9999")
    insert_all(admin_conn, seller)
    # hesap başka kiracıya ait bir satıra bağlanamaz (bileşik yabancı anahtar)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin_conn.execute(
            "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, valid_from, amount, "
            "amount_includes_vat, entered_by) VALUES (%s, %s, '2026-02-01', 1, true, %s)",
            (other.tenant_id, seller.account_id, other.user_id),
        )
    duplicates = {
        "profit_settings": (
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by) VALUES (%s, %s, %s)",
            (seller.user_id,),
        ),
        "cargo_tariffs": (
            "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
            "price_includes_vat, brackets, entered_by) VALUES (%s, %s, 'trendyol', 'TE', '2026-01-01', false, "
            f"'{BRACKETS}', %s)",
            (seller.user_id,),
        ),
        "service_fee_estimates": (
            "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, valid_from, amount, "
            "amount_includes_vat, entered_by) VALUES (%s, %s, '2026-01-01', 1, false, %s)",
            (seller.user_id,),
        ),
    }
    for sql, extra in duplicates.values():
        with pytest.raises(psycopg.errors.UniqueViolation):
            admin_conn.execute(sql, (seller.tenant_id, seller.account_id, *extra))
    # aynı anahtarın başka anlaşma ya da başka firması çakışmaz
    admin_conn.execute(
        "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
        "price_includes_vat, brackets, entered_by) VALUES (%s, %s, 'seller', 'TE', '2026-01-01', false, %s, %s)",
        (seller.tenant_id, seller.account_id, BRACKETS, seller.user_id),
    )


@pytest.mark.parametrize(
    ("table", "columns", "values"),
    [
        ("profit_settings", "default_desi", "0"),
        ("profit_settings", "default_desi", "1000.01"),
        ("profit_settings", "revision", "0"),
        (
            "cargo_tariffs",
            "agreement, carrier, valid_from, price_includes_vat, brackets",
            "'x', 'TE', '2026-01-01', true, '[{}]'",
        ),
        (
            "cargo_tariffs",
            "agreement, carrier, valid_from, price_includes_vat, brackets",
            "'trendyol', '', '2026-01-01', true, '[{}]'",
        ),
        (
            "cargo_tariffs",
            "agreement, carrier, valid_from, price_includes_vat, brackets",
            "'trendyol', ' TE', '2026-01-01', true, '[{}]'",
        ),
        (
            "cargo_tariffs",
            "agreement, carrier, valid_from, price_includes_vat, brackets",
            "'trendyol', 'TE', '2026-01-01', true, '[]'",
        ),
        (
            "cargo_tariffs",
            "agreement, carrier, valid_from, price_includes_vat, brackets",
            "'trendyol', 'TE', '2026-01-01', true, '{}'",
        ),
        ("service_fee_estimates", "valid_from, amount, amount_includes_vat", "'2026-01-01', -1, true"),
        ("service_fee_estimates", "valid_from, amount, amount_includes_vat", "'2026-01-01', 10000.01, true"),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'', 'siparis_basi', 1, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'x', 'haftalik', 1, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'x', 'siparis_basi', 1, 18, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'x', 'siparis_basi', NULL, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'x', 'siparis_basi', -1, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from",
            "'x', 'adet_basi', 100000.01, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, percent, vat_rate, valid_from",
            "'x', 'siparis_basi', 1, 5, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, percent, vat_rate, valid_from",
            "'x', 'satis_yuzdesi', 1, 5, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, percent, vat_rate, valid_from",
            "'x', 'satis_yuzdesi', 0, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, percent, vat_rate, valid_from",
            "'x', 'satis_yuzdesi', 100.01, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, percent, vat_rate, valid_from",
            "'x', 'satis_yuzdesi', NULL, 20, '2026-01-01'",
        ),
        (
            "variable_expenses",
            "name, kind, amount_excl_vat, vat_rate, valid_from, valid_to",
            "'x', 'siparis_basi', 1, 20, '2026-02-01', '2026-01-31'",
        ),
    ],
)
def test_check_constraints_reject_bad_values(
    admin_conn: psycopg.Connection[Any], table: str, columns: str, values: str
) -> None:
    seller = make_seller(admin_conn)
    extra_cols = "tenant_id, marketplace_account_id, " + (
        "updated_by" if table == "profit_settings" else "entered_by"
    )
    sql = f"INSERT INTO {table} ({extra_cols}, {columns}) VALUES (%s, %s, %s, {values})"
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute(sql, (seller.tenant_id, seller.account_id, seller.user_id))


def test_check_constraints_accept_boundary_values(admin_conn: psycopg.Connection[Any]) -> None:
    seller = make_seller(admin_conn)
    base = (seller.tenant_id, seller.account_id, seller.user_id)
    admin_conn.execute(
        "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, default_desi) VALUES (%s, %s, %s, 1000)",
        base,
    )
    admin_conn.execute(
        "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
        "amount_includes_vat) VALUES (%s, %s, %s, '2026-01-01', 0, false)",
        base,
    )
    for kind, amount, percent in (
        ("siparis_basi", "0", None),
        ("adet_basi", "100000", None),
        ("satis_yuzdesi", None, "100"),
    ):
        admin_conn.execute(
            "INSERT INTO variable_expenses (tenant_id, marketplace_account_id, entered_by, name, kind, "
            "amount_excl_vat, percent, vat_rate, valid_from, valid_to) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 0, '2026-01-01', '2026-01-01')",
            (*base, f"g-{kind}", kind, amount, percent),
        )


# --------------------------------------------------------------------------- RLS / IDOR
def test_tenants_see_only_their_own_rows_and_cannot_write_across(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    a = make_seller(admin_conn)
    b = make_seller(admin_conn, seller_id="9999")
    insert_all(admin_conn, a)
    insert_all(admin_conn, b)
    for table in TABLES:
        with role_tx(database.app_dsn(), a.tenant_id) as conn:
            rows = conn.execute(f"SELECT tenant_id FROM {table}").fetchall()
            assert {r[0] for r in rows} == {a.tenant_id}, table
            # bağlamsız (kiracısız) oturum hiçbir satır görmez
        with role_tx(database.app_dsn()) as conn:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        # B'nin satırlarını güncelleme/silme: 0 satır etkilenir (RLS görünürlüğü)
        assert (
            conn.execute(
                "UPDATE profit_settings SET default_desi = 9 WHERE tenant_id = %s", (b.tenant_id,)
            ).rowcount
            == 0
        )
        for table in DELETABLE:
            assert conn.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (b.tenant_id,)).rowcount == 0
        # B kiracısı adına satır eklemek WITH CHECK ile reddedilir
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, valid_from, amount, "
                "amount_includes_vat, entered_by) VALUES (%s, %s, '2026-02-01', 1, true, %s)",
                (b.tenant_id, b.account_id, b.user_id),
            )
    with (
        role_tx(database.app_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by) VALUES (%s, %s, %s)",
            (b.tenant_id, b.account_id, b.user_id),
        )
    # B'nin hesabına A kiracısı satırı bağlanamaz (bileşik yabancı anahtar), RLS olmasa bile
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        admin_conn.execute(
            "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
            "price_includes_vat, brackets, entered_by) VALUES (%s, %s, 'trendyol', 'X', '2026-01-01', true, %s, %s)",
            (a.tenant_id, b.account_id, BRACKETS, a.user_id),
        )


def test_table_owner_is_also_bound_by_row_level_security(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """FORCE RLS: tabloların sahibi (netkar_owner) bile bağlamsız satır görmez."""
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    dsn = database.owner_url.set(drivername="postgresql").render_as_string(hide_password=False)
    for table in TABLES:
        with role_tx(dsn) as conn:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table


def test_app_role_privileges_are_least_privilege(admin_conn: psycopg.Connection[Any]) -> None:
    def has(role: str, table: str, privilege: str) -> bool:
        row = admin_conn.execute(
            "SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege)
        ).fetchone()
        assert row is not None
        return bool(row[0])

    for table in TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE"):
            assert has("netkar_app", table, privilege), (table, privilege)
        assert not has("netkar_app", table, "TRUNCATE") and not has("netkar_app", table, "REFERENCES")
        assert has("netkar_app", table, "DELETE") is (table in DELETABLE), table
    # worker yalnız okur; sync_gate ve PUBLIC erişemez
    for table in TABLES:
        assert has("netkar_worker", table, "SELECT"), table
        for privilege in ("INSERT", "UPDATE", "DELETE"):
            assert not has("netkar_worker", table, privilege), (table, privilege)
        assert not has("netkar_sync_gate", table, "SELECT"), table
        assert not has("public", table, "SELECT"), table


def test_worker_can_read_but_not_write(admin_conn: psycopg.Connection[Any], database: DatabaseInfo) -> None:
    seller = make_seller(admin_conn)
    ids = insert_all(admin_conn, seller)
    with role_tx(database.worker_dsn(), seller.tenant_id) as conn:
        for table in TABLES:
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,), table
    for table, sql in (
        ("profit_settings", "UPDATE profit_settings SET default_desi = 5 WHERE id = %s"),
        ("cargo_tariffs", "DELETE FROM cargo_tariffs WHERE id = %s"),
        ("service_fee_estimates", "UPDATE service_fee_estimates SET amount = 1 WHERE id = %s"),
        ("variable_expenses", "DELETE FROM variable_expenses WHERE id = %s"),
    ):
        with (
            role_tx(database.worker_dsn(), seller.tenant_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(sql, (ids[table],))


def test_app_role_cannot_delete_the_settings_row(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    with (
        role_tx(database.app_dsn(), seller.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("DELETE FROM profit_settings")
    with role_tx(database.app_dsn(), seller.tenant_id) as conn:
        assert conn.execute("DELETE FROM cargo_tariffs").rowcount == 1  # sürümler silinebilir


# --------------------------------------------------------------------------- geri alınabilirlik
def test_migration_0007_is_reversible_and_leaves_earlier_tables_intact(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Veri varken downgrade AD-03 koruması nedeniyle açık onay ister (reddi ayrıca
    # tests/test_profit_settings_api_denetim.py doğrular); bu test geri alınabilirliği onayla sınar.
    monkeypatch.setenv("NETKAR_ALLOW_SETTINGS_DATA_LOSS", "1")

    def tables() -> set[str]:
        return {
            r[0] for r in admin_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        }

    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    assert set(TABLES) <= tables()
    try:
        command.downgrade(alembic_cfg, "0006")
        assert not (set(TABLES) & tables())
        assert {"products", "product_costs", "orders", "sync_runs"} <= tables()  # 0006 etkilenmedi
        command.upgrade(alembic_cfg, "head")
        assert set(TABLES) <= tables()
        # tekrar yükseltme boş tablolar üretir ve yetkiler yeniden verilir
        assert admin_conn.execute("SELECT count(*) FROM cargo_tariffs").fetchone() == (0,)
        assert admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'cargo_tariffs', 'DELETE'),"
            " has_table_privilege('netkar_worker', 'cargo_tariffs', 'INSERT')"
        ).fetchone() == (True, False)
        row = admin_conn.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'variable_expenses'"
        ).fetchone()
        assert row == (True,)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_below_0007_revokes_privileges_before_dropping(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    try:
        command.downgrade(alembic_cfg, "0006")
        assert admin_conn.execute("SELECT to_regclass('public.profit_settings')").fetchone() == (None,)
        command.downgrade(alembic_cfg, "base")
        command.upgrade(alembic_cfg, "head")  # tüm zincir yeniden kurulur
        assert admin_conn.execute("SELECT to_regclass('public.profit_settings')").fetchone() != (None,)
    finally:
        command.upgrade(alembic_cfg, "head")
