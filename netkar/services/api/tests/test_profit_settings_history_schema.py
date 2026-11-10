"""Migrasyon 0008 (ayar tarihçesi, ADR-0007 §4): şema, değişmezlik, RLS/yetki, taşıma ve geri alınabilirlik.

Değişmezlik iki katmanlıdır: uygulama rolünde YETKİ (DELETE yok, iş alanlarında UPDATE yok) ve sahip rolde dahil
TETİKLEYİCİ (kapanmış satır ve iş alanları güncellenemez). Günlük (`profit_settings_changes`) RLS altındadır ve
uygulama rolü onu yalnız okur ve ekler.
"""

from __future__ import annotations

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
    # 0009: uygulama rolü satırı yalnız ayar sayacındaki sürümle kapatır (CLOSE `revision_to = 2`).
    admin_conn.execute("UPDATE profit_settings SET revision = 2")
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
            "VALUES (%s, %s, %s, 2)",
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
        add_change(conn, a, 2)  # kendi kiracısına ekleyebilir
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
        add_change(conn, a, 5, changed_by=b.user_id)
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
    """Yazım akışının yaptığı dizi geçer: satır sayaca eşit sürümle eklenir, eski satır sayaçla kapanır, günlük sayaçla."""
    a, _ = seed_forgery_target(admin_conn)
    with role_tx(database.app_dsn(), a.tenant_id) as conn:
        assert (
            conn.execute(
                f"UPDATE cargo_tariffs SET {CLOSE.replace('revision_to = 2', 'revision_to = 5')}",
                (a.user_id,),
            ).rowcount
            == 1
        )
        forged_tariff(conn, a, 5, None)
        add_change(conn, a, 5, action="degistir", replaced_record_id=uuid4(), record_id=uuid4())
        for table in ("service_fee_estimates", "variable_expenses"):
            assert (
                conn.execute(
                    f"UPDATE {table} SET {CLOSE.replace('revision_to = 2', 'revision_to = 5')}", (a.user_id,)
                ).rowcount
                == 1
            )


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
    new_triggers = {f"trg_{t}_insert_guard" for t in VERSIONED} | {"trg_profit_settings_changes_guard"}
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
