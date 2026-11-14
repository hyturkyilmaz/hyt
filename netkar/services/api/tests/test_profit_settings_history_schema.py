"""Migrasyon 0008 (ayar tarihçesi, ADR-0007 §4): şema, değişmezlik, RLS/yetki, taşıma ve geri alınabilirlik.

Değişmezlik iki katmanlıdır: uygulama rolünde YETKİ (DELETE yok, iş alanlarında UPDATE yok) ve sahip rolde dahil
TETİKLEYİCİ (kapanmış satır ve iş alanları güncellenemez). Günlük (`profit_settings_changes`) RLS altındadır ve
uygulama rolü onu yalnız okur ve ekler.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect

from app.models import (
    CargoTariffRecord,
    ProfitSettingsChange,
    ProfitSettingsRecord,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
)
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller
from tests.sync_helpers import make_seller as make_plain_seller
from tests.test_profit_settings_schema import BRACKETS, insert_all, role_tx

VERSIONED = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")
CLOSE = "revision_to = 2, ended_at = now(), ended_by = %s, end_reason = 'degistirildi'"
MODELS: tuple[type[Any], ...] = (
    ProfitSettingsRecord,
    CargoTariffRecord,
    ServiceFeeEstimateRecord,
    VariableExpenseRecord,
    ProfitSettingsChange,
)


def make_seller(conn: psycopg.Connection[Any], **kw: Any) -> Seller:
    """Kiracı + kullanıcı + hesap ve kullanıcının kiracı üyeliği (günlükte `changed_by` üye olmalıdır, 0009)."""
    seller = make_plain_seller(conn, **kw)
    conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')",
        (seller.user_id, seller.tenant_id),
    )
    return seller


def owner_dsn(database: DatabaseInfo) -> str:
    return database.owner_url.set(drivername="postgresql").render_as_string(hide_password=False)


def add_change(conn: psycopg.Connection[Any], seller: Seller, revision: int = 5, /, **over: Any) -> None:
    """Günlüğe bir kayıt (varsayılan: tarife ekleme); `over` sütun değerlerini değiştirir."""
    row: dict[str, Any] = {
        "tenant_id": seller.tenant_id,
        "marketplace_account_id": seller.account_id,
        "revision": revision,
        "changed_by": seller.user_id,
        "item": "cargo_tariff",
        "action": "ekle",
        "affects_past": False,
    }
    row.update(over)  # `revision` de ezilebilir
    conn.execute(
        f"INSERT INTO profit_settings_changes ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
        tuple(row.values()),
    )


# --------------------------------------------------------------------------- şema
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


def test_versioned_tables_have_revision_range_columns_and_indexes(
    admin_conn: psycopg.Connection[Any],
) -> None:
    for table in VERSIONED:
        columns = {
            r[0]: (r[1], r[2])
            for r in admin_conn.execute(
                "SELECT column_name, is_nullable, data_type FROM information_schema.columns WHERE table_name = %s",
                (table,),
            )
        }
        assert columns["revision_from"] == ("NO", "bigint"), table  # NOT NULL
        for nullable in ("revision_to", "ended_at", "ended_by", "end_reason", "replaces_id"):
            assert columns[nullable][0] == "YES", (table, nullable)
        indexes = {
            r[0]
            for r in admin_conn.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", (table,))
        }
        assert {f"ix_{table}_active", f"ix_{table}_revision", f"ix_{table}_tenant_account"} <= indexes, table
    unique = {
        r[0] for r in admin_conn.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
    }
    assert {"uq_cargo_tariffs_active_version", "uq_service_fee_estimates_active_version"} <= unique
    # eski tam tekillik kısıtları kalktı (kapanmış satırlar aynı anahtarı taşıyabilir)
    old = admin_conn.execute(
        "SELECT conname FROM pg_constraint WHERE conname IN ('uq_cargo_tariffs_version', "
        "'uq_service_fee_estimates_version')"
    ).fetchall()
    assert old == []


def test_journal_table_has_forced_rls_policy_index_and_least_privilege(
    admin_conn: psycopg.Connection[Any],
) -> None:
    row = admin_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity, "
        "(SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'tenant_isolation') "
        "FROM pg_class c WHERE relname = 'profit_settings_changes'"
    ).fetchone()
    assert row == (True, True, 1)
    index = admin_conn.execute(
        "SELECT 1 FROM pg_indexes WHERE indexname = 'ix_profit_settings_changes_tenant_account'"
    ).fetchone()
    assert index is not None

    def has(role: str, privilege: str) -> bool:
        got = admin_conn.execute(
            "SELECT has_table_privilege(%s, 'profit_settings_changes', %s)", (role, privilege)
        ).fetchone()
        assert got is not None
        return bool(got[0])

    assert has("netkar_app", "SELECT") and has("netkar_app", "INSERT")
    assert not has("netkar_app", "UPDATE") and not has("netkar_app", "DELETE")  # değişmez günlük
    assert not has("netkar_app", "TRUNCATE")
    assert has("netkar_worker", "SELECT")
    for privilege in ("INSERT", "UPDATE", "DELETE"):
        assert not has("netkar_worker", privilege), privilege
    assert not has("netkar_sync_gate", "SELECT") and not has("public", "SELECT")


def test_journal_check_constraints(admin_conn: psycopg.Connection[Any]) -> None:
    seller = make_seller(admin_conn)
    add_change(admin_conn, seller, 1)  # geçerli
    bad: list[dict[str, Any]] = [
        {"item": "bilinmeyen"},
        {"action": "sil"},
        {"revision": 0},
        {"item": "tasima", "action": "ekle"},  # tasima kalemi yalnız tasima eylemiyle
        {"action": "tasima"},  # tasima eylemi yalnız tasima kalemiyle
        {"changed_by": None},  # tasima dışında kullanıcı zorunlu
        {"default_desi_after": 3},  # desi alanları yalnız defaults ve tasima için
        {"action": "degistir"},  # degistir yerini aldığı satırı taşımak zorunda
        {"replaced_record_id": uuid4()},  # ekle, değiştirilen satır taşıyamaz
    ]
    for index, over in enumerate(bad):
        with pytest.raises(psycopg.errors.CheckViolation):
            add_change(admin_conn, seller, 10 + index, **over)
    # geçerli sınır durumları
    add_change(admin_conn, seller, 30, item="tasima", action="tasima", changed_by=None, default_desi_after=2)
    add_change(admin_conn, seller, 31, action="degistir", replaced_record_id=uuid4(), record_id=uuid4())
    add_change(
        admin_conn,
        seller,
        32,
        item="defaults",
        action="degistir",
        default_desi_before=1,
        default_desi_after=2,
    )
    with pytest.raises(psycopg.errors.UniqueViolation):  # sürüm başına tek kayıt
        add_change(admin_conn, seller, 31)


def test_closing_columns_are_all_or_nothing_and_after_the_opening_revision(
    admin_conn: psycopg.Connection[Any],
) -> None:
    seller = make_seller(admin_conn)
    ids = insert_all(admin_conn, seller)
    for table in VERSIONED:
        row = ids[table]
        for sql in (
            f"UPDATE {table} SET revision_to = 2 WHERE id = %s",  # kapanış sütunları eksik
            f"UPDATE {table} SET revision_to = 1, ended_at = now(), ended_by = '{seller.user_id}', "
            "end_reason = 'degistirildi' WHERE id = %s",  # revision_to <= revision_from
            f"UPDATE {table} SET revision_to = 2, ended_at = now(), ended_by = '{seller.user_id}', "
            "end_reason = 'baska' WHERE id = %s",  # bilinmeyen neden
            f"UPDATE {table} SET replaces_id = id WHERE id = %s",  # kendini değiştiremez
        ):
            with pytest.raises(psycopg.errors.CheckViolation):
                admin_conn.execute(sql, (row,))
        admin_conn.execute(
            f"UPDATE {table} SET revision_to = 2, ended_at = now(), ended_by = %s, "
            "end_reason = 'geri_cekildi' WHERE id = %s",
            (seller.user_id, row),
        )


def test_uniqueness_applies_to_active_rows_only(admin_conn: psycopg.Connection[Any]) -> None:
    seller = make_seller(admin_conn)
    ids = insert_all(admin_conn, seller)
    base = (seller.tenant_id, seller.account_id)
    tariff = (
        "INSERT INTO cargo_tariffs (revision_from, tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
        "price_includes_vat, brackets, entered_by) VALUES (2, %s, %s, 'trendyol', 'TE', '2026-01-01', true, %s, %s)"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):  # iki etkin satır aynı anahtar
        admin_conn.execute(tariff, (*base, BRACKETS, seller.user_id))
    admin_conn.execute(
        f"UPDATE cargo_tariffs SET {CLOSE} WHERE id = %s", (seller.user_id, ids["cargo_tariffs"])
    )  # eski satır kapandı: aynı anahtarlı yeni etkin satır eklenebilir
    admin_conn.execute(tariff, (*base, BRACKETS, seller.user_id))
    fee = (
        "INSERT INTO service_fee_estimates (revision_from, tenant_id, marketplace_account_id, valid_from, amount, "
        "amount_includes_vat, entered_by) VALUES (2, %s, %s, '2026-01-01', 1, true, %s)"
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin_conn.execute(fee, (*base, seller.user_id))
    admin_conn.execute(
        f"UPDATE service_fee_estimates SET {CLOSE} WHERE id = %s",
        (seller.user_id, ids["service_fee_estimates"]),
    )
    admin_conn.execute(fee, (*base, seller.user_id))


# --------------------------------------------------------------------------- yetki ve tetikleyici
def test_app_role_cannot_delete_or_change_work_fields_but_can_close_active_rows(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    # 0009/0010: uygulama rolü satırı yalnız ayar sayacındaki sürümle ve sayacı bu işlemde artırarak kapatır
    # (sayaç 1, `bump` ile 2; CLOSE `revision_to = 2`).
    denied = (
        "DELETE FROM cargo_tariffs",
        "DELETE FROM service_fee_estimates",
        "DELETE FROM variable_expenses",
        "UPDATE cargo_tariffs SET brackets = '[]'::jsonb",
        "UPDATE cargo_tariffs SET valid_from = '2026-02-02'",
        "UPDATE service_fee_estimates SET amount = 1",
        "UPDATE variable_expenses SET amount_excl_vat = 1",
        "UPDATE variable_expenses SET name = 'x'",
        "UPDATE cargo_tariffs SET replaces_id = id",
        "UPDATE profit_settings_changes SET item = 'defaults'",
        "DELETE FROM profit_settings_changes",
        "DELETE FROM profit_settings",
    )
    for sql in denied:
        with (
            role_tx(database.app_dsn(), seller.tenant_id) as conn,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            conn.execute(sql)
    with role_tx(database.app_dsn(), seller.tenant_id) as conn:  # kapanış sütunları serbest
        assert bump(conn, seller) == 2
        for table in VERSIONED:
            assert conn.execute(f"UPDATE {table} SET {CLOSE}", (seller.user_id,)).rowcount == 1, table


def test_owner_role_is_bound_by_the_version_guard_trigger(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Tetikleyici sahip rolü de bağlar: kapanmış satır ve iş alanları, yetkiden bağımsız, güncellenemez."""
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    work_updates = {
        "cargo_tariffs": "UPDATE cargo_tariffs SET brackets = '[]'::jsonb",
        "service_fee_estimates": "UPDATE service_fee_estimates SET amount = 1",
        "variable_expenses": "UPDATE variable_expenses SET amount_excl_vat = 1",
    }
    for table, sql in work_updates.items():  # etkin satırın iş alanı
        with (
            role_tx(owner_dsn(database), seller.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation, match="is alanlari"),
        ):
            conn.execute(sql)
        # kapanış sütunları ise sahip rolle de güncellenir ve ardından satır kilitlenir
        with role_tx(owner_dsn(database), seller.tenant_id) as conn:
            assert conn.execute(f"UPDATE {table} SET {CLOSE}", (seller.user_id,)).rowcount == 1
            with pytest.raises(psycopg.errors.CheckViolation, match="kapanmis"):
                conn.execute(f"UPDATE {table} SET revision_to = 3")
    with (
        role_tx(owner_dsn(database), seller.tenant_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="is alanlari"),
    ):
        conn.execute("UPDATE cargo_tariffs SET valid_from = '2026-03-03'")


# --------------------------------------------------------------------------- RLS / IDOR (günlük)
def test_journal_is_tenant_isolated_for_read_and_write(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    a = make_seller(admin_conn)
    b = make_seller(admin_conn, seller_id="9999")
    add_change(admin_conn, a, 1)
    add_change(admin_conn, b, 1)
    for tenant in (a, b):  # uygulama rolünün günlük tetikleyicisi sayaçla karşılaştırır (0009)
        admin_conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
            "VALUES (%s, %s, %s, 1)",
            (tenant.tenant_id, tenant.account_id, tenant.user_id),
        )
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        assert {r[0] for r in conn.execute("SELECT tenant_id FROM profit_settings_changes")} == {a.tenant_id}
    with role_tx(database.app_dsn()) as conn:  # bağlamsız oturum hiçbir satır görmez
        assert conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (0,)
    with role_tx(database.worker_dsn(), a.tenant_id) as conn:  # worker yalnız okur
        assert conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (1,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("DELETE FROM profit_settings_changes")
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        with pytest.raises(
            psycopg.errors.InsufficientPrivilege
        ):  # B kiracısı adına kayıt RLS WITH CHECK ile reddedilir (sahip rolde tetikleyici devre dışıdır)
            add_change(conn, b, 2)
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):  # uygulama rolünde tetikleyici de reddeder
            add_change(conn, b, 2)
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        add_change(conn, a, bump(conn, a))  # kendi kiracısına ekleyebilir (sayaç 1 -> 2, bu işlemde)
    # hesap başka kiracıya ait bir kayda bağlanamaz (bileşik yabancı anahtar, RLS olmasa bile)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_change(admin_conn, a, 3, marketplace_account_id=b.account_id)
    # sahip rol de FORCE RLS altındadır: bağlamsız satır görmez
    with role_tx(owner_dsn(database)) as conn:
        assert conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (0,)


# --------------------------------------------------------------------------- taşıma ve geri alma
def tables_state(conn: psycopg.Connection[Any]) -> dict[str, int]:
    return {
        t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0])  # type: ignore[index]
        for t in (*VERSIONED, "profit_settings", "profit_settings_changes")
    }


def test_upgrade_marks_existing_rows_with_the_current_revision_and_writes_a_move_record(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    empty = make_seller(admin_conn, seller_id="9999")  # ayar satırı olmayan hesap: taşıma kaydı yok
    try:
        command.downgrade(alembic_cfg, "0007")
        base = (seller.tenant_id, seller.account_id, seller.user_id)
        admin_conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, default_desi, revision) "
            "VALUES (%s, %s, %s, 3, 4)",
            base,
        )
        admin_conn.execute(
            "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, entered_by, agreement, carrier, "
            "valid_from, price_includes_vat, brackets) VALUES (%s, %s, %s, 'trendyol', 'TE', '2026-01-01', true, %s)",
            (*base, BRACKETS),
        )
        admin_conn.execute(
            "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
            "amount_includes_vat) VALUES (%s, %s, %s, '2026-01-01', 12, true)",
            base,
        )
        command.upgrade(alembic_cfg, "head")
        for table in ("cargo_tariffs", "service_fee_estimates"):
            row = admin_conn.execute(f"SELECT revision_from, revision_to FROM {table}").fetchone()
            assert row == (4, None), table  # mevcut satırlar o anki ayar sürümüyle işaretli, etkin
        moves = admin_conn.execute(
            "SELECT marketplace_account_id, revision, item, action, affects_past, past_change_confirmed, "
            "default_desi_after, changed_by FROM profit_settings_changes"
        ).fetchall()
        assert moves == [(seller.account_id, 4, "tasima", "tasima", False, False, 3, None)]
        assert empty.account_id not in {m[0] for m in moves}
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_then_upgrade_roundtrip_on_empty_tables_needs_no_flag(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_HISTORY_LOSS", raising=False)
    try:
        command.downgrade(alembic_cfg, "0007")
        assert admin_conn.execute("SELECT to_regclass('public.profit_settings_changes')").fetchone() == (
            None,
        )
        columns = {
            r[0]
            for r in admin_conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'cargo_tariffs'"
            )
        }
        assert (
            not {"revision_from", "revision_to", "ended_at", "ended_by", "end_reason", "replaces_id"}
            & columns
        )
        got = admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'cargo_tariffs', 'DELETE'), "
            "has_table_privilege('netkar_app', 'cargo_tariffs', 'UPDATE')"
        ).fetchone()
        assert got == (True, True)  # 0007 yetkileri geri geldi
        command.upgrade(alembic_cfg, "head")
        assert admin_conn.execute("SELECT to_regclass('public.profit_settings_changes')").fetchone() != (
            None,
        )
        forced = admin_conn.execute(
            "SELECT bool_and(relforcerowsecurity) FROM pg_class WHERE relname = ANY(%s)",
            ([*VERSIONED, "profit_settings", "profit_settings_changes"],),
        ).fetchone()
        assert forced == (True,)
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_with_only_move_records_needs_no_flag_and_keeps_active_rows(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_HISTORY_LOSS", raising=False)
    seller = make_seller(admin_conn)
    insert_all(admin_conn, seller)
    add_change(admin_conn, seller, 1, item="tasima", action="tasima", changed_by=None)
    try:
        command.downgrade(alembic_cfg, "0007")  # yalnız `tasima` kaydı: tarihçe sayılmaz
        assert admin_conn.execute("SELECT count(*) FROM cargo_tariffs").fetchone() == (1,)
    finally:
        command.upgrade(alembic_cfg, "head")


def seed_history(conn: psycopg.Connection[Any], seller: Seller) -> None:
    """Etkin satırlar + bir kapanmış tarife (aynı anahtar, yerini alan etkin satırla) + günlük kaydı."""
    ids = insert_all(conn, seller)
    conn.execute(
        "UPDATE cargo_tariffs SET revision_to = 2, ended_at = now(), ended_by = %s, end_reason = 'degistirildi' "
        "WHERE id = %s",
        (seller.user_id, ids["cargo_tariffs"]),
    )
    conn.execute(
        "INSERT INTO cargo_tariffs (revision_from, tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
        "price_includes_vat, brackets, entered_by, replaces_id) "
        "VALUES (2, %s, %s, 'trendyol', 'TE', '2026-01-01', true, %s, %s, %s)",
        (seller.tenant_id, seller.account_id, BRACKETS, seller.user_id, ids["cargo_tariffs"]),
    )
    add_change(conn, seller, 2, action="degistir", replaced_record_id=ids["cargo_tariffs"])


def test_downgrade_is_refused_while_history_exists_and_the_database_is_left_untouched(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NETKAR_ALLOW_SETTINGS_HISTORY_LOSS", raising=False)
    seller = make_seller(admin_conn)
    seed_history(admin_conn, seller)
    before = tables_state(admin_conn)
    try:
        with pytest.raises(RuntimeError) as caught:
            command.downgrade(alembic_cfg, "0007")
        message = str(caught.value)
        assert "0008" in message and "yedek" in message.lower()
        assert "NETKAR_ALLOW_SETTINGS_HISTORY_LOSS=1" in message
        assert "cargo_tariffs: 1 kapanmış satır" in message and "günlük: 1 kayıt" in message
        # Alembic her migrasyonu ayrı işlemde çalıştırır: 0009 (yalnız kısıt ve tetikleyici) geri alındı, 0008 durdu.
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0008",)
        assert tables_state(admin_conn) == before
        forced = admin_conn.execute(
            "SELECT bool_and(relforcerowsecurity) FROM pg_class WHERE relname = ANY(%s)",
            ([*VERSIONED, "profit_settings", "profit_settings_changes"],),
        ).fetchone()
        assert forced == (True,)  # FORCE RLS yerinde kaldı
    finally:
        command.upgrade(alembic_cfg, "head")


def test_downgrade_with_the_flag_drops_history_but_keeps_active_rows_and_restores_old_constraints(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seller = make_seller(admin_conn)
    seed_history(admin_conn, seller)
    monkeypatch.setenv("NETKAR_ALLOW_SETTINGS_HISTORY_LOSS", "1")
    try:
        command.downgrade(alembic_cfg, "0007")
        # kapanmış satır gitti, etkin satırlar ve değerleri korundu
        assert admin_conn.execute(
            "SELECT count(*), count(DISTINCT carrier) FROM cargo_tariffs"
        ).fetchone() == (1, 1)
        for table in ("service_fee_estimates", "variable_expenses", "profit_settings"):
            assert admin_conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,), table
        # eski tekillik kısıtı geri geldi
        with pytest.raises(psycopg.errors.UniqueViolation):
            admin_conn.execute(
                "INSERT INTO cargo_tariffs (tenant_id, marketplace_account_id, agreement, carrier, valid_from, "
                "price_includes_vat, brackets, entered_by) VALUES (%s, %s, 'trendyol', 'TE', '2026-01-01', true, %s, %s)",
                (seller.tenant_id, seller.account_id, BRACKETS, seller.user_id),
            )
        command.upgrade(alembic_cfg, "head")
        assert admin_conn.execute(
            "SELECT count(*) FROM cargo_tariffs WHERE revision_to IS NULL"
        ).fetchone() == (1,)
        assert admin_conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (
            1,
        )  # taşıma kaydı
    finally:
        command.upgrade(alembic_cfg, "head")


def test_flag_value_must_be_exactly_one(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    seller = make_seller(admin_conn)
    seed_history(admin_conn, seller)
    monkeypatch.setenv("NETKAR_ALLOW_SETTINGS_HISTORY_LOSS", "true")
    try:
        with pytest.raises(RuntimeError):
            command.downgrade(alembic_cfg, "0007")
    finally:
        command.upgrade(alembic_cfg, "head")


# --------------------------------------------------------------------------- 0008 Revizyon 1: başlıksız hesap (YT-03)
def test_upgrade_creates_the_head_for_accounts_with_rows_but_no_head_and_writes_the_move_record(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    """Denetim YT-03: ayar satırı olmayan ama satırı olan hesap, taşımada `revision = 1` başlık ve `tasima` alır."""
    headless = make_seller(admin_conn)
    empty = make_seller(admin_conn, seller_id="9999")  # hiç satırı yok: başlık da, taşıma kaydı da olmaz
    try:
        command.downgrade(alembic_cfg, "0007")
        base = (headless.tenant_id, headless.account_id, headless.user_id)
        admin_conn.execute(
            "INSERT INTO service_fee_estimates (tenant_id, marketplace_account_id, entered_by, valid_from, amount, "
            "amount_includes_vat) VALUES (%s, %s, %s, '2026-01-01', 12, true)",
            base,
        )
        admin_conn.execute(
            "INSERT INTO variable_expenses (tenant_id, marketplace_account_id, entered_by, name, kind, "
            "amount_excl_vat, vat_rate, valid_from) VALUES (%s, %s, %s, 'paket', 'siparis_basi', 6, 20, '2026-01-01')",
            base,
        )
        assert admin_conn.execute("SELECT count(*) FROM profit_settings").fetchone() == (0,)
        command.upgrade(alembic_cfg, "head")
        head = admin_conn.execute(
            "SELECT marketplace_account_id, revision, updated_by, default_desi FROM profit_settings"
        ).fetchall()
        assert head == [(headless.account_id, 1, headless.user_id, None)]  # başlık 1; boş hesapta yok
        for table in ("service_fee_estimates", "variable_expenses"):
            row = admin_conn.execute(f"SELECT revision_from, revision_to FROM {table}").fetchone()
            assert row == (1, None), table  # etkin satır, damga 0 DEĞİL
        moves = admin_conn.execute(
            "SELECT marketplace_account_id, revision, item, default_desi_after, changed_by "
            "FROM profit_settings_changes"
        ).fetchall()
        assert moves == [(headless.account_id, 1, "tasima", None, None)]
        assert empty.account_id not in {m[0] for m in moves}
    finally:
        command.upgrade(alembic_cfg, "head")


# --------------------------------------------------------------------------- 0009: YT-04 sahte kayıt denemeleri
def seed_forgery_target(conn: psycopg.Connection[Any]) -> tuple[Seller, Seller]:
    """A kiracısı (ayar sayacı 5, sürüm 1 etkin satırlar) ve başka bir kiracı B."""
    a = make_seller(conn)
    b = make_seller(conn, seller_id="9999")
    insert_all(conn, a)
    conn.execute("UPDATE profit_settings SET revision = 5 WHERE marketplace_account_id = %s", (a.account_id,))
    return a, b


TARIFF_INSERT = (
    "INSERT INTO cargo_tariffs (revision_from, revision_to, ended_at, ended_by, end_reason, tenant_id, "
    "marketplace_account_id, agreement, carrier, valid_from, price_includes_vat, brackets, entered_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, 'seller', 'FORGED', '2026-01-01', true, %s, %s)"
)


def forged_tariff(
    conn: psycopg.Connection[Any], seller: Seller, revision_from: int, closed_at: int | None
) -> None:
    ended = closed_at is not None
    conn.execute(
        TARIFF_INSERT,
        (
            revision_from,
            closed_at,
            "2026-11-10T10:00:00+00:00" if ended else None,
            seller.user_id if ended else None,
            "degistirildi" if ended else None,
            seller.tenant_id,
            seller.account_id,
            BRACKETS,
            seller.user_id,
        ),
    )


def bump(conn: psycopg.Connection[Any], seller: Seller, by: int = 1) -> int:
    """Dürüst akışın ilk adımı: ayar sayacını BU işlemde artırır (`finish_write`); yeni sayacı döndürür."""
    row = conn.execute(
        "UPDATE profit_settings SET revision = revision + %s WHERE marketplace_account_id = %s RETURNING revision",
        (by, seller.account_id),
    ).fetchone()
    assert row is not None
    return int(row[0])


def test_app_role_cannot_forge_history_rows_the_five_audit_attempts(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Denetim YT-04 PoC A.3: `netkar_app` ile beş sahte yazımın beşi de reddedilir."""
    a, b = seed_forgery_target(admin_conn)
    dsn = database.app_dsn()
    # 1. geçmiş `revision_from` (sayaç 5 iken 1)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="sayacina"):
        forged_tariff(conn, a, 1, None)
    # 2. baştan kapalı satır (doğru `revision_from`, `revision_to` dolu)
    with (
        role_tx(dsn, a.tenant_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="bastan kapali"),
    ):
        forged_tariff(conn, a, 5, 6)
    # 3. sahte `tasima` kaydı
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="tasima"):
        add_change(conn, a, 5, item="tasima", action="tasima", changed_by=None, default_desi_after=2)
    # 4. başka kiracının kullanıcısı `changed_by`
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        add_change(conn, a, bump(conn, a), changed_by=b.user_id)  # sayaç bu işlemde artırıldı: FK'ye ulaşır
    # 5. etkin satırı sayaçtan kopuk bir `revision_to` ile kapatmak
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="sayacindaki"):
        conn.execute(
            f"UPDATE cargo_tariffs SET {CLOSE.replace('revision_to = 2', 'revision_to = 1000000')}",
            (a.user_id,),
        )
    # ek: sayacın ilerisi ve geçmiş günlük sürümü
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="sayacina"):
        forged_tariff(conn, a, 6, None)
    for revision in (4, 6):
        with (
            role_tx(dsn, a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation, match="sayacina"),
        ):
            add_change(conn, a, revision)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        add_change(conn, b, 5)  # başka kiracı adına: sayaç bağlamda görünmez
    assert admin_conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (0,)
    assert admin_conn.execute("SELECT count(*) FROM cargo_tariffs").fetchone() == (1,)


def test_app_role_honest_write_sequence_still_passes_the_guards(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Yazım akışının dizisi geçer: sayaç +1 (bu işlemde), satır sayaca eşit sürümle, eski satır sayaçla kapanır, günlük."""
    a, _ = seed_forgery_target(admin_conn)
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        head = bump(conn, a)  # `finish_write`: sayaç 5 -> 6, aynı işlemde
        assert head == 6
        assert (
            conn.execute(
                f"UPDATE cargo_tariffs SET {CLOSE.replace('revision_to = 2', f'revision_to = {head}')}",
                (a.user_id,),
            ).rowcount
            == 1
        )
        forged_tariff(conn, a, head, None)
        # varsayılan desi yazımı: aynı işlemde ikinci başlık UPDATE'i sürümü değiştirmez, işlem bağı korunur
        conn.execute("UPDATE profit_settings SET default_desi = 3, updated_at = now()")
        add_change(conn, a, head, action="degistir", replaced_record_id=uuid4(), record_id=uuid4())
        for table in ("service_fee_estimates", "variable_expenses"):
            assert (
                conn.execute(
                    f"UPDATE {table} SET {CLOSE.replace('revision_to = 2', f'revision_to = {head}')}",
                    (a.user_id,),
                ).rowcount
                == 1
            )


def test_app_role_cannot_add_rows_to_a_published_revision_without_bumping_the_counter(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Denetim YK-01 PoC A: sayaç artırılmadan yayımlanmış sürüme satır, kapanış ve günlük eklenemez."""
    a, _ = seed_forgery_target(admin_conn)  # sayaç 5 başka bir işlemde yazıldı
    dsn = database.app_dsn()
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bu islemde"):
        forged_tariff(conn, a, 5, None)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bu islemde"):
        add_change(conn, a, 5)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bu islemde"):
        conn.execute(
            f"UPDATE cargo_tariffs SET {CLOSE.replace('revision_to = 2', 'revision_to = 5')}", (a.user_id,)
        )
    # başlık güncellemesi sürümü artırmıyorsa işlem bağı kurulmaz (aynı değerle UPDATE bağ vermez)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bu islemde"):
        conn.execute("UPDATE profit_settings SET revision = 5, default_desi = 2")
        forged_tariff(conn, a, 5, None)
    assert admin_conn.execute("SELECT count(*) FROM profit_settings_changes").fetchone() == (0,)
    assert admin_conn.execute("SELECT count(*) FROM cargo_tariffs").fetchone() == (1,)


def test_app_role_cannot_rewind_or_skip_the_counter(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Denetim YK-01 PoC B: sayaç geri sarılamaz, atlanamaz ve yeni hesapta 1 dışında başlayamaz."""
    a, _ = seed_forgery_target(admin_conn)
    dsn = database.app_dsn()
    for target in (2, 0, 4, 7, 1000000):  # geri sarma, sıfır, geri, atlama, uçurum
        with (
            role_tx(dsn, a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation, match=r"artabilir|baslar"),
        ):
            conn.execute("UPDATE profit_settings SET revision = %s", (target,))
    # PoC B'nin tamamı: geri sar, sahte satır ekle, sayacı eski değerine getir
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE profit_settings SET revision = 2")
    with role_tx(dsn, a.tenant_id) as conn:  # +1 serbest, aynı değer serbest
        assert bump(conn, a) == 6
        conn.execute("UPDATE profit_settings SET default_desi = 2")
    # başka bir hesap için sayaçla başlama (INSERT): yalnız 1
    other = make_seller(admin_conn, seller_id="5555")
    with role_tx(dsn, other.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="baslar"):
        conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
            "VALUES (%s, %s, %s, 9)",
            (other.tenant_id, other.account_id, other.user_id),
        )
    with role_tx(dsn, other.tenant_id) as conn:
        conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
            "VALUES (%s, %s, %s, 1)",
            (other.tenant_id, other.account_id, other.user_id),
        )
        forged_tariff(conn, other, 1, None)  # yeni hesap: satır aynı işlemde oluştu, bağ kurulu


def test_revision_xact_is_assigned_by_the_trigger_and_cannot_be_forged(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """`revision_xact` istemci değerini yok sayar; yalnız sayaç artınca bu işleme taşınır (her rol için)."""
    a, _ = seed_forgery_target(admin_conn)
    dsn = database.app_dsn()
    # 0011: uygulama rolünün `revision_xact` sütununda UPDATE yetkisi yoktur (sütun düzeyi yetki)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE profit_settings SET revision_xact = pg_current_xact_id()")
    # sahip rol sütunu yazabilir ama tetikleyici değeri yok sayar: sayaç artmadığı için eski değer korunur
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        conn.execute("UPDATE profit_settings SET revision_xact = pg_current_xact_id()")
        row = conn.execute("SELECT revision_xact = pg_current_xact_id() FROM profit_settings").fetchone()
        assert row == (False,)
    with role_tx(dsn, a.tenant_id) as conn:
        with pytest.raises(psycopg.errors.CheckViolation, match="bu islemde"):
            forged_tariff(conn, a, 5, None)
    with role_tx(dsn, a.tenant_id) as conn:
        head = bump(conn, a)
        row = conn.execute(
            "SELECT revision_xact = pg_current_xact_id() FROM profit_settings WHERE revision = %s", (head,)
        ).fetchone()
        assert row == (True,)
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        conn.execute("UPDATE profit_settings SET revision_xact = '1'::text::xid8")  # sahte değer yok sayılır
        row = conn.execute("SELECT revision_xact = pg_current_xact_id() FROM profit_settings").fetchone()
        assert row == (False,)
    # yönetici sayacı geri alabilir (muafiyet) ve `revision_xact` yine tetikleyiciyle atanır
    row = admin_conn.execute(
        "UPDATE profit_settings SET revision = 3 RETURNING revision_xact = pg_current_xact_id()"
    ).fetchone()
    assert row == (True,)


def test_sequence_guards_bind_only_the_app_role_but_immutability_binds_everyone(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Sıra kuralları `netkar_app`'e özgüdür (sahip rolün veri doldurması takılmaz); değişmezlik herkesi bağlar."""
    a, _ = seed_forgery_target(admin_conn)
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        forged_tariff(conn, a, 1, None)  # sahip rol: sayaçtan bağımsız eklenebilir (doldurma migrasyonu)
        add_change(conn, a, 1, item="tasima", action="tasima", changed_by=None)
    forged_tariff(admin_conn, a, 1, None)  # yönetici de
    with (
        role_tx(owner_dsn(database), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.CheckViolation, match="is alanlari"),
    ):
        conn.execute("UPDATE cargo_tariffs SET brackets = '[]'::jsonb")


def test_journal_changed_by_must_be_a_member_of_the_row_tenant_for_every_role(
    admin_conn: psycopg.Connection[Any],
) -> None:
    """Bileşik FK `(changed_by, tenant_id) -> memberships`: üye olmayan ya da başka kiracı kullanıcısı yazılamaz."""
    a, b = seed_forgery_target(admin_conn)
    stranger = uuid4()
    admin_conn.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (%s, 'yabanci@example.com', 'x')", (stranger,)
    )
    for who in (b.user_id, stranger):  # başka kiracının üyesi; hiçbir kiracının üyesi değil
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            add_change(admin_conn, a, 1, changed_by=who)
    add_change(admin_conn, a, 1)  # kendi kiracısının üyesi
    add_change(admin_conn, a, 2, item="tasima", action="tasima", changed_by=None)  # tasima: changed_by boş


def test_journal_defaults_rows_are_tight_ck_replace(admin_conn: psycopg.Connection[Any]) -> None:
    """Denetim YT-09: `defaults` kaydı satır kimliği taşımaz; `ekle` önceki, `geri_cek` sonraki desiyi taşımaz."""
    a, _ = seed_forgery_target(admin_conn)
    bad: list[dict[str, Any]] = [
        {"action": "ekle", "record_id": uuid4(), "default_desi_after": 2},
        {
            "action": "degistir",
            "replaced_record_id": uuid4(),
            "default_desi_before": 1,
            "default_desi_after": 2,
        },
        {"action": "ekle", "default_desi_before": 1, "default_desi_after": 2},  # ekle: önceki desi yok
        {
            "action": "geri_cek",
            "default_desi_before": 1,
            "default_desi_after": 2,
        },  # geri_cek: sonraki desi yok
    ]
    for index, over in enumerate(bad):
        with pytest.raises(psycopg.errors.CheckViolation):
            add_change(admin_conn, a, 10 + index, item="defaults", **over)
    add_change(admin_conn, a, 20, item="defaults", action="ekle", default_desi_after=2)
    add_change(
        admin_conn, a, 21, item="defaults", action="degistir", default_desi_before=2, default_desi_after=3
    )
    add_change(admin_conn, a, 22, item="defaults", action="geri_cek", default_desi_before=3)
    # diğer kalemlerde eski kural geçerli
    with pytest.raises(psycopg.errors.CheckViolation):
        add_change(admin_conn, a, 23, action="degistir")


def test_replaces_indexes_exist_and_are_partial(admin_conn: psycopg.Connection[Any]) -> None:
    """Denetim YT-02: halef zinciri indekslidir."""
    for table in VERSIONED:
        row = admin_conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", (f"ix_{table}_replaces",)
        ).fetchone()
        assert row is not None, table
        assert "(replaces_id, tenant_id, marketplace_account_id)" in row[0], table
        assert "replaces_id IS NOT NULL" in row[0], table


def test_0010_downgrade_upgrade_roundtrip_restores_0009_bodies_and_keeps_data(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """0010 geri alınabilir: sütun, tetikleyici ve işlev düşer, 0009 gövdeleri döner; yeniden upgrade tam kurar."""
    a, _ = seed_forgery_target(admin_conn)
    before = tables_state(admin_conn)

    def column_present() -> bool:
        return admin_conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'profit_settings' AND column_name = 'revision_xact'"
        ).fetchone() == (1,)

    def functions() -> dict[str, tuple[bool, list[str] | None]]:
        rows = admin_conn.execute(
            "SELECT proname, prosecdef, proconfig FROM pg_proc WHERE proname LIKE 'profit_settings%guard'"
        ).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    search_path = ["search_path=pg_catalog, public"]
    assert column_present()
    assert set(functions()) == {
        "profit_settings_version_guard",
        "profit_settings_insert_guard",
        "profit_settings_changes_guard",
        "profit_settings_head_guard",
    }
    # YK-05: dört işlev de INVOKER ve sabit search_path
    assert all(config == (False, search_path) for config in functions().values())
    try:
        command.downgrade(alembic_cfg, "0009")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0009",)
        assert not column_present()
        assert "profit_settings_head_guard" not in functions()
        assert all(config == (False, None) for config in functions().values())  # 0009 gövdeleri
        assert tables_state(admin_conn) == before  # veri kaybı yok
        # 0009 davranışı: sayaç serbestçe geri sarılabilir (bu yüzden 0010 vardır)
        with role_tx(database.app_dsn(), a.tenant_id) as conn:
            conn.execute("UPDATE profit_settings SET revision = 2")
    finally:
        command.upgrade(alembic_cfg, "head")
    assert column_present() and len(functions()) == 4
    assert all(config == (False, search_path) for config in functions().values())
    with role_tx(database.app_dsn(), a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE profit_settings SET revision = 2")


def test_0009_downgrade_removes_only_its_objects_and_roundtrips(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """0009 geri alınabilir: nesneler düşer, 0008 gövdesi ve kısıtı döner, veri korunur; yeniden upgrade tam kurar."""
    a, _ = seed_forgery_target(admin_conn)
    before = tables_state(admin_conn)

    def names(kind: str) -> set[str]:
        sql = {
            "trigger": "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE '%guard'",
            "index": "SELECT indexname FROM pg_indexes WHERE indexname LIKE 'ix_%_replaces'",
            "fk": "SELECT conname FROM pg_constraint WHERE conname = 'fk_profit_settings_changes_member'",
            "function": "SELECT proname FROM pg_proc WHERE proname IN "
            "('profit_settings_insert_guard', 'profit_settings_changes_guard')",
        }[kind]
        return {r[0] for r in admin_conn.execute(sql)}

    full_triggers = {f"trg_{t}_version_guard" for t in VERSIONED}
    new_triggers = {f"trg_{t}_insert_guard" for t in VERSIONED} | {
        "trg_profit_settings_changes_guard",
        "trg_profit_settings_head_guard",  # 0010
    }
    assert names("trigger") == full_triggers | new_triggers
    try:
        command.downgrade(alembic_cfg, "0008")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0008",)
        assert names("trigger") == full_triggers  # değişmezlik tetikleyicisi kalır
        assert names("index") == set() and names("fk") == set() and names("function") == set()
        assert tables_state(admin_conn) == before  # veri kaybı yok
        # 0008 gövdesi: uygulama rolü sayaçtan kopuk revision_to yazabilir (bu yüzden 0009 vardır)
        with role_tx(database.app_dsn(), a.tenant_id) as conn:
            assert (
                conn.execute(
                    f"UPDATE cargo_tariffs SET {CLOSE.replace('revision_to = 2', 'revision_to = 1000000')}",
                    (a.user_id,),
                ).rowcount
                == 1
            )
        # 0008 kısıtı: defaults kaydı satır kimliği taşıyabilir
        add_change(admin_conn, a, 40, item="defaults", action="ekle", record_id=uuid4(), default_desi_after=2)
        admin_conn.execute("DELETE FROM profit_settings_changes")
    finally:
        command.upgrade(alembic_cfg, "head")
    assert names("trigger") == full_triggers | new_triggers
    assert len(names("index")) == 3 and names("fk") != set() and len(names("function")) == 2
    assert tables_state(admin_conn) == {**before, "profit_settings_changes": 0}


# --------------------------------------------------------------------------- 0011: ZK-01 anahtar kilidi
def test_app_role_cannot_move_the_head_to_another_account_the_zk01_proof_of_concept(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Denetim ZK-01 PoC: başlığı aynı kiracıdaki ikinci hesaba taşıyıp yeni başlıkla sayacı 1'e indirme reddedilir."""
    a, _ = seed_forgery_target(admin_conn)  # A: sayaç 5, sürüm 1 satırları etkin
    a2 = uuid4()  # aynı kiracıda ikinci hesap (uygulama rolü de ekleyebilir; denetim PoC'unda iptal durumlu)
    admin_conn.execute(
        "INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, created_by, "
        "api_key_last4, revoked_at) VALUES (%s, %s, 'trendyol', '7777', 'revoked', %s, 'abcd', now())",
        (a2, a.tenant_id, a.user_id),
    )
    dsn = database.app_dsn()
    # adım 2: başlığın hesap anahtarını çevirmek sütun düzeyinde yetki dışıdır
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "UPDATE profit_settings SET marketplace_account_id = %s WHERE marketplace_account_id = %s",
            (a2, a.account_id),
        )
    # kimlik ve kiracı sütunları da aynı biçimde kapalı; silme hiç yoktur
    for column, value in (("id", uuid4()), ("tenant_id", a.tenant_id), ("created_at", "2000-01-01")):
        with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"UPDATE profit_settings SET {column} = %s", (value,))
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM profit_settings")
    # sonuç: başlıklar ve sayaç değişmedi
    rows = admin_conn.execute(
        "SELECT marketplace_account_id, revision FROM profit_settings ORDER BY revision"
    ).fetchall()
    assert rows == [(a.account_id, 5)]


def test_head_key_is_immutable_for_every_role_including_owner_and_superuser(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Derinlemesine savunma: tetikleyici `id`, `tenant_id`, `marketplace_account_id` değişimini her rolde reddeder."""
    a, b = seed_forgery_target(admin_conn)
    a2 = uuid4()
    admin_conn.execute(
        "INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, created_by, "
        "api_key_last4, revoked_at) VALUES (%s, %s, 'trendyol', '7777', 'revoked', %s, 'abcd', now())",
        (a2, a.tenant_id, a.user_id),
    )
    changes = (
        ("marketplace_account_id", a2),
        ("id", uuid4()),
        ("tenant_id", b.tenant_id),
    )
    for column, value in changes:  # yönetici (süper kullanıcı): RLS'yi aşar, tetikleyici yine reddeder
        with pytest.raises(psycopg.errors.CheckViolation, match="hesap anahtari"):
            admin_conn.execute(f"UPDATE profit_settings SET {column} = %s", (value,))
    for column, value in changes[:2]:  # sahip rol
        with (
            role_tx(owner_dsn(database), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation, match="hesap anahtari"),
        ):
            conn.execute(f"UPDATE profit_settings SET {column} = %s", (value,))
    # değişmeyen anahtarla (aynı değere) UPDATE geçer; sayaç düzeltmesi sahip rolde serbest kalır
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        conn.execute(
            "UPDATE profit_settings SET marketplace_account_id = marketplace_account_id, revision = 2"
        )


# --------------------------------------------------------------------------- 0011: ZK-02 işlem başına tek artış
def test_app_role_can_bump_the_counter_only_once_per_transaction(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """Denetim ZK-02 PoC: aynı işlemde ikinci artış (5 -> 55 döngüsü dahil) reddedilir; ayrı işlemlerde artış serbest."""
    a, _ = seed_forgery_target(admin_conn)
    dsn = database.app_dsn()
    with role_tx(dsn, a.tenant_id) as conn:
        assert bump(conn, a) == 6
        with pytest.raises(psycopg.errors.CheckViolation, match="bir islemde yalniz bir kez"):
            bump(conn, a)
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bir kez"):
        for _ in range(50):
            bump(conn, a)  # 50 ardışık artış: ilkinden sonra reddedilir
    with role_tx(dsn, a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation, match="bir kez"):
        bump(conn, a, by=1)
        conn.execute("UPDATE profit_settings SET revision = revision + 1 WHERE revision = 6")
    # yeni başlık oluşturulan işlemde sayaç ikinci kez artırılamaz (dürüst akış zaten artırmaz: `ticket.created`)
    other = make_seller(admin_conn, seller_id="5555")
    with role_tx(dsn, other.tenant_id) as conn:
        conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
            "VALUES (%s, %s, %s, 1)",
            (other.tenant_id, other.account_id, other.user_id),
        )
        with pytest.raises(psycopg.errors.CheckViolation, match="bir kez"):
            bump(conn, other)
    # ayrı işlemler: her biri +1 yapabilir
    for expected in (6, 7, 8):
        with role_tx(dsn, a.tenant_id) as conn:
            assert bump(conn, a) == expected
            conn.commit()
    assert admin_conn.execute("SELECT revision FROM profit_settings").fetchone() == (8,)
    # sahip rol (bakım) muaf kalır: aynı işlemde birden çok düzeltme
    with role_tx(owner_dsn(database), a.tenant_id) as conn:
        conn.execute("UPDATE profit_settings SET revision = revision + 1")
        conn.execute("UPDATE profit_settings SET revision = revision + 1")


def test_honest_write_flow_passes_the_new_rules_end_to_end(
    admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """`begin_write`/`finish_write` dizisi 0011 ile uyumlu: yeni hesapta artış yok, mevcutta tek artış, desi güncellemesi."""
    a, _ = seed_forgery_target(admin_conn)
    dsn = database.app_dsn()
    with role_tx(dsn, a.tenant_id) as conn:
        # `begin_write`: kilit (FOR UPDATE sütun yetkisiyle çalışır), `finish_write`: tek +1
        assert conn.execute(
            "SELECT revision FROM profit_settings WHERE tenant_id = %s FOR UPDATE", (a.tenant_id,)
        )
        assert bump(conn, a) == 6
        conn.execute(
            "UPDATE profit_settings SET default_desi = 4, updated_by = %s, updated_at = now()", (a.user_id,)
        )
        forged_tariff(conn, a, 6, None)
        add_change(conn, a, 6)
    other = make_seller(admin_conn, seller_id="5555")
    with role_tx(dsn, other.tenant_id) as conn:  # ilk yazım: başlık sayaç 1 ile eklenir, artırma yok
        conn.execute(
            "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, revision) "
            "VALUES (%s, %s, %s, 1) ON CONFLICT (marketplace_account_id) DO NOTHING",
            (other.tenant_id, other.account_id, other.user_id),
        )
        conn.execute("SELECT 1 FROM profit_settings FOR UPDATE")
        forged_tariff(conn, other, 1, None)
        add_change(conn, other, 1)


# --------------------------------------------------------------------------- 0011: ZK-03 yazma yetkili roller
WRITE_TABLES = ("profit_settings", *VERSIONED, "profit_settings_changes")


def write_capable_roles(conn: psycopg.Connection[Any]) -> set[str]:
    """Süper kullanıcı olmayan, `pg_` ön eksiz rollerden bu tablolarda (sütun düzeyi dahil) yazabilenler."""
    roles = [
        r[0] for r in conn.execute("SELECT rolname FROM pg_roles WHERE NOT rolsuper AND rolname !~ '^pg_'")
    ]
    found: set[str] = set()
    for role in roles:
        for table in WRITE_TABLES:
            for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                table_level = conn.execute(
                    "SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege)
                ).fetchone()
                assert table_level is not None
                if table_level[0]:
                    found.add(role)
            for privilege in ("INSERT", "UPDATE"):
                column_level = conn.execute(
                    "SELECT has_any_column_privilege(%s, %s, %s)", (role, table, privilege)
                ).fetchone()
                assert column_level is not None
                if column_level[0]:
                    found.add(role)
    return found


def test_only_the_app_and_owner_roles_can_write_the_settings_tables(
    admin_conn: psycopg.Connection[Any],
) -> None:
    """ZK-03: yazma yetkili rol kümesi tam olarak {netkar_app, netkar_owner}. Yeni bir rol yetki alırsa bu test kırılır
    ve geliştirici kural işlevlerindeki (`profit_settings_maintenance_role`) muafiyet kararını bilinçli verir."""
    assert write_capable_roles(admin_conn) == {"netkar_app", "netkar_owner"}
    assert not admin_conn.execute(
        "SELECT has_table_privilege('public', 'profit_settings', 'UPDATE')"
    ).fetchone()[0]  # type: ignore[index]


def test_maintenance_exemption_is_an_explicit_positive_list(admin_conn: psycopg.Connection[Any]) -> None:
    """ZK-03: muaf olanlar yalnız `netkar_owner` ve süper kullanıcılar; kümedeki başka her rol, `netkar_app` dahil, değil."""
    exempt: set[str] = set()
    roles = [r[0] for r in admin_conn.execute("SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_'")]
    for role in roles:
        with admin_conn.transaction(force_rollback=True):
            admin_conn.execute(f'SET LOCAL ROLE "{role}"')
            row = admin_conn.execute("SELECT public.profit_settings_maintenance_role()").fetchone()
            assert row is not None
            if row[0]:
                exempt.add(role)
    superusers = {r[0] for r in admin_conn.execute("SELECT rolname FROM pg_roles WHERE rolsuper")}
    assert exempt == {"netkar_owner"} | superusers
    assert "netkar_app" not in exempt and "netkar_worker" not in exempt


def test_a_future_role_granted_write_access_is_bound_by_the_sequence_rules(
    admin_conn: psycopg.Connection[Any],
) -> None:
    """ZK-03 asıl senaryo: ileride yazma yetkisi alan yeni rol sessizce muaf olmaz (varsayılan ret)."""
    a, _ = seed_forgery_target(admin_conn)
    role = "netkar_future_writer"
    admin_conn.execute(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS")
    try:
        admin_conn.execute(f"GRANT SELECT, INSERT ON profit_settings_changes TO {role}")
        admin_conn.execute(f"GRANT SELECT ON profit_settings TO {role}")
        admin_conn.execute(f"GRANT SELECT, INSERT ON cargo_tariffs TO {role}")
        for statement, match in (
            (lambda c: add_change(c, a, 5), "bu islemde"),  # sayaç bu işlemde artırılmadı
            (lambda c: add_change(c, a, 1), "sayacina"),  # geçmiş sürüm
            (lambda c: forged_tariff(c, a, 1, None), "sayacina"),
        ):
            with admin_conn.transaction(force_rollback=True):
                admin_conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a.tenant_id),))
                admin_conn.execute(f"SET LOCAL ROLE {role}")
                with pytest.raises(psycopg.errors.CheckViolation, match=match):
                    statement(admin_conn)
    finally:
        admin_conn.execute(f"DROP OWNED BY {role}")
        admin_conn.execute(f"DROP ROLE {role}")


# --------------------------------------------------------------------------- 0011: ZK-04 işlev gövdesi eşitliği
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
GUARD_FUNCTIONS = (
    "profit_settings_version_guard",
    "profit_settings_insert_guard",
    "profit_settings_changes_guard",
    "profit_settings_head_guard",
)


def load_migration(file_name: str) -> Any:
    """Test içinde bir migrasyon modülünü sabitleri için yükler (migrasyonların kendisi bu desene dayanmaz)."""
    spec = importlib.util.spec_from_file_location(f"_netkar_test_{file_name[:4]}", MIGRATIONS / file_name)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function_definitions(conn: psycopg.Connection[Any]) -> dict[str, str]:
    rows = conn.execute(
        "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = ANY(%s)",
        (list(GUARD_FUNCTIONS),),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def test_downgrade_restores_exact_function_bodies_of_0010_and_0009(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    """ZK-04: 0011 -> 0010 -> 0009 downgrade sonrası dört işlevin `pg_get_functiondef` çıktısı, ilgili migrasyonun
    kendi sabitleriyle üretilen tanıma eşit; head'de 0011 sabitleriyle eşit."""
    m9 = load_migration("0009_profit_settings_history_hardening.py")
    m10 = load_migration("0010_profit_settings_revision_xact.py")
    m11 = load_migration("0011_profit_settings_head_lockdown.py")

    def replace_form(statement: str) -> str:
        return statement.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)

    expected = {
        "0011": [m11.HEAD_GUARD_0011, m11.VERSION_GUARD_0011, m11.INSERT_GUARD_0011, m11.JOURNAL_GUARD_0011],
        "0010": [
            replace_form(m10.HEAD_GUARD_SQL),
            m10.VERSION_GUARD_0010,
            m10.INSERT_GUARD_0010,
            m10.JOURNAL_GUARD_0010,
        ],
        "0009": [
            m9.VERSION_GUARD_0009,
            replace_form(m9.INSERT_GUARD_SQL),
            replace_form(m9.JOURNAL_GUARD_SQL),
        ],
    }

    def matches(statements: list[str]) -> bool:
        before = function_definitions(admin_conn)
        with admin_conn.transaction(force_rollback=True):  # beklenen tanım uygulanır, sonra geri alınır
            for statement in statements:
                admin_conn.execute(statement)
            after = function_definitions(admin_conn)
        return before == after

    try:
        assert matches(expected["0011"]) and not matches(expected["0010"])  # head: 0011 gövdeleri
        command.downgrade(alembic_cfg, "0010")
        assert set(function_definitions(admin_conn)) == set(GUARD_FUNCTIONS)
        assert matches(expected["0010"]) and not matches(expected["0011"])
        command.downgrade(alembic_cfg, "0009")
        # 0009'da başlık işlevi yoktur; üç kural işlevi 0009 gövdesidir
        assert set(function_definitions(admin_conn)) == set(GUARD_FUNCTIONS) - {"profit_settings_head_guard"}
        assert matches(expected["0009"])
    finally:
        command.upgrade(alembic_cfg, "head")
    assert matches(expected["0011"])


def test_0011_downgrade_upgrade_roundtrip_restores_grants_helper_and_keeps_data(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    """0011 geri alınabilir: yardımcı işlev düşer, tablo düzeyi UPDATE döner, veri korunur; yeniden upgrade tam kurar."""
    a, _ = seed_forgery_target(admin_conn)
    before = tables_state(admin_conn)

    def helper_present() -> bool:
        return admin_conn.execute(
            "SELECT count(*) FROM pg_proc WHERE proname = 'profit_settings_maintenance_role'"
        ).fetchone() == (1,)

    def table_update() -> bool:
        row = admin_conn.execute(
            "SELECT has_table_privilege('netkar_app', 'profit_settings', 'UPDATE')"
        ).fetchone()
        assert row is not None
        return bool(row[0])

    assert helper_present() and not table_update()
    try:
        command.downgrade(alembic_cfg, "0010")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0010",)
        assert not helper_present() and table_update()
        assert tables_state(admin_conn) == before  # veri kaybı yok
        # 0010 davranışı: tablo düzeyi UPDATE vardı (bu yüzden 0011 vardır)
        with role_tx(database.app_dsn(), a.tenant_id) as conn:
            conn.execute("UPDATE profit_settings SET marketplace_account_id = marketplace_account_id")
    finally:
        command.upgrade(alembic_cfg, "head")
    assert helper_present() and not table_update()
    assert tables_state(admin_conn) == before
    with (
        role_tx(database.app_dsn(), a.tenant_id) as conn,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        conn.execute("UPDATE profit_settings SET marketplace_account_id = marketplace_account_id")
