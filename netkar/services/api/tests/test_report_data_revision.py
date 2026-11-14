"""Hesap başına rapor veri sürümü sayacı (denetim 2026-11-12 OS-03, OS-04; migrasyon 0012).

Sayaç `report_data_revisions.revision`: motor girdisini besleyen sekiz tabloya yazan HER işlem COMMIT edilirken
veritabanı tetikleyicisi onu işlem başına bir kez artırır. Bu dosya: şema ve yetkiler, her yazım yolunun
(senkron upsert, `removed_at`, imleç, maliyet içe aktarma ve PUT, ham SQL) sürümü değiştirdiği, işlem ve
eşzamanlılık özellikleri (geri alma, işlem başına tek artış, kayıpsız eşzamanlı artış), okuma maliyetinin
tablo taramasından bağımsızlığı ve geri alınabilir migrasyon. Takvime bağlı test yoktur.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import create_engine
from app.services.report_cache import report_data_version
from app.services.sync import store
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import B1, B2, Shop, csv_bytes, make_shop_factory, upload
from tests.report_helpers import seed_basic
from tests.sync_fixtures import Env
from tests.sync_helpers import NOW
from tests.test_rls_idor import app_tx

VERSIONED = {
    "orders",
    "order_lines",
    "returns",
    "financial_transactions",
    "cargo_invoice_items",
    "products",
    "product_costs",
    "sync_cursors",
}
# Motor girdisi OLMAYAN hesap bağlı tablolar: senkron çalışma günlüğü, sayacın kendisi ve kâr ayarı tabloları
# (ayarlar rapor anahtarında `settings_revision` ile, ayrı sayaçla izlenir).
NOT_ENGINE_INPUT = {
    "sync_runs",
    "report_data_revisions",
    "profit_settings",
    "profit_settings_changes",
    "cargo_tariffs",
    "service_fee_estimates",
    "variable_expenses",
}


def revision(conn: psycopg.Connection[Any], account_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM report_data_revisions WHERE marketplace_account_id = %s", (account_id,)
    ).fetchone()
    return 0 if row is None else int(row[0])


# ===================================================================================== şema ve yetki


def test_every_engine_input_table_has_the_deferred_counter_trigger_and_new_tables_must_decide(
    admin_conn: psycopg.Connection[Any],
) -> None:
    rows = admin_conn.execute(
        """
        SELECT c.relname, t.tgdeferrable, t.tginitdeferred, t.tgenabled, p.proname, p.prosecdef,
               (t.tgtype & 1) = 1 AS per_row, (t.tgtype & 4) = 4 AS on_insert,
               (t.tgtype & 8) = 8 AS on_delete, (t.tgtype & 16) = 16 AS on_update
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid
        WHERE t.tgname = 'trg_bump_report_data_revision' AND NOT t.tgisinternal OR t.tgconstraint <> 0
        """
    ).fetchall()
    bump = {r[0]: r for r in rows if r[4] == "bump_report_data_revision"}
    assert set(bump) == VERSIONED
    for name, deferrable, initially_deferred, enabled, _, secdef, per_row, ins, dele, upd in bump.values():
        assert deferrable and initially_deferred and enabled == "O" and secdef, name
        assert per_row and ins and dele and upd, name  # INSERT, UPDATE ve DELETE
    # Hesaba bağlı (tenant_id + marketplace_account_id) her yeni tablo ya sürümlü olmalı ya da bilinçle muaf.
    scoped = {
        r[0]
        for r in admin_conn.execute(
            """
            SELECT table_name FROM information_schema.columns
            WHERE table_schema = 'public' AND column_name IN ('tenant_id', 'marketplace_account_id')
            GROUP BY table_name HAVING count(*) = 2
            """
        )
    }
    assert scoped - NOT_ENGINE_INPUT == VERSIONED, (
        "yeni hesap bağlı tablo: sürüm tetikleyicisi ya da muafiyet"
    )


def test_counter_table_is_rls_forced_and_application_roles_cannot_write_or_rewind_it(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    tenant_a, tenant_b = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    account_a, account_b = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    admin_conn.execute(
        "INSERT INTO report_data_revisions (marketplace_account_id, tenant_id, revision) "
        "VALUES (%s, %s, 5), (%s, %s, 7)",
        (account_a, tenant_a, account_b, tenant_b),
    )
    assert admin_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'report_data_revisions'"
    ).fetchone() == (True, True)
    with app_tx(database, tenant_a) as conn:  # uygulama rolü yalnız kendi kiracısının satırını görür
        assert conn.execute("SELECT revision FROM report_data_revisions").fetchall() == [(5,)]
    with app_tx(database, None) as conn:  # bağlamsız: hiçbir satır
        assert conn.execute("SELECT count(*) FROM report_data_revisions").fetchone() == (0,)
    for statement in (
        f"UPDATE report_data_revisions SET revision = 1 WHERE marketplace_account_id = '{account_a}'",
        f"UPDATE report_data_revisions SET revision = revision + 1 WHERE marketplace_account_id = '{account_a}'",
        f"INSERT INTO report_data_revisions VALUES ('{account_a}', '{tenant_a}', 99)",
        "DELETE FROM report_data_revisions",
        "TRUNCATE report_data_revisions",
    ):
        with app_tx(database, tenant_a) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)  # type: ignore[call-overload]
    with app_tx(database, tenant_a, dsn=database.worker_dsn()) as conn:  # işçi sayacı okumaz da yazmaz da
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT revision FROM report_data_revisions")
    with app_tx(database, tenant_a, dsn=database.worker_dsn()) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE report_data_revisions SET revision = 0")
    # Tetikleyici işlevi doğrudan çağrılamaz ve sabit search_path ile tanımlıdır.
    func = admin_conn.execute(
        "SELECT prosecdef, proconfig, pg_get_userbyid(proowner) FROM pg_proc "
        "WHERE proname = 'bump_report_data_revision'"
    ).fetchone()
    assert func is not None and func[0] and any(c.startswith("search_path=") for c in func[1])
    assert func[2] == "netkar_owner"
    assert admin_conn.execute(
        "SELECT has_function_privilege('public', 'public.bump_report_data_revision()', 'EXECUTE')"
    ).fetchone() == (False,)


# ========================================================================= her yazım yolu sürümü değiştirir


async def test_every_sync_write_path_bumps_the_revision_removed_flag_and_cursor_included(
    env: Env, worker_engine: Any
) -> None:
    account = env.seller.account_id
    assert revision(env.conn, account) == 0
    await env.runner.run(account, "backfill")  # upsert_products/orders/returns/transactions/cargo + imleç
    after_backfill = revision(env.conn, account)
    assert after_backfill >= 1
    for table in (
        "products",
        "orders",
        "order_lines",
        "returns",
        "financial_transactions",
        "cargo_invoice_items",
    ):
        assert env.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] > 0, table  # type: ignore[index]

    # removed_at yolu: paket bölündü, ikinci satır payload'dan kalktı (store.upsert_orders işaretler).
    first = env.api.orders[0]
    env.api.orders = [{**first, "lines": [first["lines"][0]]}]
    await env.runner.run(account, "backfill", sources=["orders"], force=True)
    flagged = env.conn.execute("SELECT count(*) FROM order_lines WHERE removed_at IS NOT NULL").fetchone()
    assert flagged == (1,)
    after_removed = revision(env.conn, account)
    assert after_removed > after_backfill

    # Yalnız imleç yazımı (sync_cursors): başka hiçbir tabloya dokunmadan.
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with sessions.begin() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(env.seller.tenant_id)},
        )
        await store.advance_cursor(
            session,
            tenant_id=env.seller.tenant_id,
            account_id=account,
            source="orders",
            watermark=NOW,
            window_start=None,
        )
    assert revision(env.conn, account) == after_removed + 1


# product_costs: senkron yazmaz; maliyet içe aktarma ve PUT testi onu kapsar.
@pytest.mark.parametrize("table", sorted(VERSIONED - {"product_costs"}))
async def test_raw_update_insert_and_delete_on_each_engine_input_table_bump_the_revision(
    env: Env, table: str
) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill")
    before = revision(env.conn, account)
    updated = env.conn.execute(
        f"UPDATE {table} SET updated_at = now() WHERE marketplace_account_id = %s", (account,)
    ).rowcount
    assert updated > 0, table
    assert revision(env.conn, account) == before + 1, table
    # DELETE da (uygulama silmez ama sürüm yine değişmeli): bağımlılığı olmayan tablolarda dene.
    if table in {"cargo_invoice_items", "returns", "financial_transactions"}:
        env.conn.execute(f"DELETE FROM {table} WHERE marketplace_account_id = %s", (account,))
        assert revision(env.conn, account) == before + 2, table


def test_cost_import_put_and_direct_cost_insert_bump_the_revision(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    shop: Shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    base = revision(admin_conn, shop.account_id)
    assert base >= 1  # tohum yazımları (ürün, maliyet, sipariş) da saydı

    dry = upload(shop, csv_bytes(f"{B2};30,00;20;2026-01-01"), dry_run=True)
    assert (
        dry.status_code == 200 and revision(admin_conn, shop.account_id) == base
    )  # yazmayan istek: değişmez
    done = upload(shop, csv_bytes(f"{B2};30,00;20;2026-01-01"), dry_run=False)
    assert done.status_code == 200 and done.json()["committed"] is True
    after_import = revision(admin_conn, shop.account_id)
    assert after_import == base + 1  # içe aktarma tek işlem, tek artış

    put = shop.api.put(
        f"{shop.base}/products/{B1}/costs",
        {"valid_from": "2026-02-01", "unit_cost_excl_vat": "41.00", "vat_rate": 20},
    )
    assert put.status_code == 200
    assert revision(admin_conn, shop.account_id) == after_import + 1
    rejected = shop.api.put(f"{shop.base}/products/{B1}/costs", {"valid_from": "not-a-date"})
    assert rejected.status_code == 422 and revision(admin_conn, shop.account_id) == after_import + 1


# ================================================================================ işlem ve eşzamanlılık


def test_one_increment_per_transaction_per_account_rollback_and_other_accounts_are_isolated(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    start = revision(admin_conn, shop.account_id)
    with psycopg.connect(database.admin_dsn()) as tx:  # tek işlemde birçok satır ve tablo
        tx.execute(
            "UPDATE orders SET updated_at = now() WHERE marketplace_account_id = %s", (shop.account_id,)
        )
        tx.execute(
            "UPDATE products SET updated_at = now() WHERE marketplace_account_id = %s", (shop.account_id,)
        )
        tx.execute(
            "UPDATE order_lines SET updated_at = now() WHERE marketplace_account_id = %s", (shop.account_id,)
        )
        assert revision(admin_conn, shop.account_id) == start  # commit'ten ÖNCE artmaz (başka oturum görmez)
        tx.commit()
    assert revision(admin_conn, shop.account_id) == start + 1  # onlarca satır, bir artış
    with psycopg.connect(database.admin_dsn()) as tx:
        tx.execute(
            "UPDATE orders SET updated_at = now() WHERE marketplace_account_id = %s", (shop.account_id,)
        )
        tx.rollback()
    assert revision(admin_conn, shop.account_id) == start + 1  # geri alınan işlem sayacı değiştirmez
    row = admin_conn.execute(
        "SELECT count(*) FROM report_data_revisions WHERE marketplace_account_id <> %s", (shop.account_id,)
    ).fetchone()
    assert row == (0,)  # başka hesap için satır açılmadı


def test_ok01_session_level_guc_cannot_suppress_the_bump(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    """OK-01: 0012'deki özel GUC `netkar.rdr_<hesap>` oturum düzeyinde '1' yapılınca artış bastırılabiliyordu.
    Tekilleştirme artık satırdaki `last_xact` (xid8) ile yapılır: hiçbir oturum ayarı artışı engelleyemez."""
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    account = str(shop.account_id)
    hexed = account.replace("-", "")
    with psycopg.connect(database.admin_dsn(), autocommit=True) as session:
        # Eski anahtar ve olası başka adlar, oturum düzeyinde (is_local = false) ve işlem yerel.
        for name in (f"netkar.rdr_{hexed}", "netkar.rdr_x", "netkar.rdr"):
            session.execute("SELECT set_config(%s, '1', false)", (name,))
        before = revision(admin_conn, shop.account_id)
        for expected in (before + 1, before + 2):  # her işlem bir artış (ayar bunu bastıramaz)
            session.execute(
                "UPDATE orders SET updated_at = now() WHERE marketplace_account_id = %s", (account,)
            )
            assert revision(admin_conn, shop.account_id) == expected
    # Aynı işlemde birden çok yazım yine tek artış (xid8 işareti, GUC değil).
    with psycopg.connect(database.admin_dsn()) as tx:
        tx.execute("SELECT set_config(%s, '1', false)", (f"netkar.rdr_{hexed}",))
        for table in ("orders", "products", "order_lines"):
            tx.execute(
                f"UPDATE {table} SET updated_at = now() WHERE marketplace_account_id = %s",  # type: ignore[arg-type]
                (account,),
            )
        tx.commit()
    assert revision(admin_conn, shop.account_id) == before + 3
    marker = admin_conn.execute(
        "SELECT last_xact IS NOT NULL FROM report_data_revisions WHERE marketplace_account_id = %s",
        (shop.account_id,),
    ).fetchone()
    assert marker == (True,)


def test_ok01_marker_column_is_not_writable_by_application_roles(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    for dsn in (None, database.worker_dsn()):
        with app_tx(database, str(shop.tenant_id), dsn=dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("UPDATE report_data_revisions SET last_xact = NULL")


def test_concurrent_writers_never_lose_an_increment(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    start = revision(admin_conn, shop.account_id)
    writers, errors = 12, []
    gate = threading.Barrier(writers)

    def write(i: int) -> None:
        try:
            with psycopg.connect(database.admin_dsn()) as tx:
                tx.execute(  # her yazar kendi satırını ekler (satır kilidi çakışması yok); sayaç commit anında artar
                    "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title) "
                    "VALUES (%s, %s, %s, 'x')",
                    (shop.tenant_id, shop.account_id, f"CONC{i}"),
                )
                gate.wait(15)  # hepsi commit'e aynı anda yüklensin
                tx.commit()
        except Exception as exc:  # pragma: no cover - hata yoksa çalışmaz
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert revision(admin_conn, shop.account_id) == start + writers  # UPDATE x = x + 1: kayıp yok


def test_first_writers_racing_on_a_new_account_create_one_row_and_count_every_commit(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    writers, errors = 8, []
    gate = threading.Barrier(writers)

    def write(i: int) -> None:
        try:
            with psycopg.connect(database.admin_dsn()) as tx:
                tx.execute(
                    "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title) "
                    "VALUES (%s, %s, %s, 'x')",
                    (shop.tenant_id, shop.account_id, f"RACE{i}"),
                )
                gate.wait(15)
                tx.commit()
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert revision(admin_conn, shop.account_id) == writers
    assert admin_conn.execute("SELECT count(*) FROM report_data_revisions").fetchone() == (1,)


# ================================================================================== okuma maliyeti


async def test_version_read_is_one_statement_on_the_counter_table_and_never_scans_the_data_tables(
    database: DatabaseInfo, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    engine = create_engine(database.app_url.render_as_string(hide_password=False))
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def capture(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        statements.append(statement)

    try:
        async with async_sessionmaker(engine, expire_on_commit=False).begin() as session:
            session_typed: AsyncSession = session
            await session_typed.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(shop.tenant_id)},
            )
            statements.clear()
            version = await report_data_version(session_typed, shop.tenant_id, shop.account_id)
    finally:
        await engine.dispose()
    assert version == revision(admin_conn, shop.account_id) >= 1
    assert len(statements) == 1 and "report_data_revisions" in statements[0]
    for table in VERSIONED:  # veri tablolarına dokunmaz (geçmiş hacminden bağımsız)
        assert f"FROM {table}" not in statements[0] and f"JOIN {table}" not in statements[0]


# ===================================================================================== migrasyon


def test_migration_0012_downgrades_cleanly_and_upgrades_again(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any]
) -> None:
    def present() -> tuple[bool, int, bool]:
        table = admin_conn.execute("SELECT to_regclass('public.report_data_revisions')").fetchone()
        triggers = admin_conn.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_bump_report_data_revision'"
        ).fetchone()
        func = admin_conn.execute("SELECT to_regprocedure('public.bump_report_data_revision()')").fetchone()
        assert table is not None and triggers is not None and func is not None
        return table[0] is not None, int(triggers[0]), func[0] is not None

    assert present() == (True, 8, True)
    command.downgrade(alembic_cfg, "0011")
    assert present() == (False, 0, False)
    # Veri tabloları ve içerikleri 0012'den önceki hâliyle çalışır (tetikleyici yokken yazım hata vermez).
    assert admin_conn.execute("SELECT count(*) FROM orders").fetchone() is not None
    command.upgrade(alembic_cfg, "head")
    assert present() == (True, 8, True)
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)


def test_migration_0013_downgrade_restores_the_0012_state_without_losing_data_and_upgrades_again(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    shop = make_shop_factory(make_api, admin_conn)("a@example.com", "Mağaza A")
    seed_basic(admin_conn, shop)
    before = revision(admin_conn, shop.account_id)
    assert before >= 1

    def state() -> tuple[bool, bool, list[str], str]:
        column = admin_conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'report_data_revisions' AND column_name = 'last_xact'"
        ).fetchone()
        body = admin_conn.execute(
            "SELECT prosrc FROM pg_proc WHERE proname = 'bump_report_data_revision'"
        ).fetchone()
        policy = admin_conn.execute(
            "SELECT roles FROM pg_policies WHERE tablename = 'report_data_revisions' AND policyname = 'owner_counter'"
        ).fetchone()
        assert column is not None and body is not None and policy is not None
        return column[0] == 1, "netkar.rdr_" in body[0], sorted(policy[0]), body[0]

    has_column, uses_guc, roles, body_0013 = state()
    assert (has_column, uses_guc, roles) == (True, False, ["netkar_owner"])
    command.downgrade(alembic_cfg, "0012")
    has_column, uses_guc, roles, _ = state()
    assert (has_column, uses_guc, roles) == (False, True, ["netkar_owner"])  # 0012 durumu (GUC'li, sütunsuz)
    assert revision(admin_conn, shop.account_id) == before  # veri kaybı yok
    func = admin_conn.execute(
        "SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'bump_report_data_revision'"
    ).fetchone()
    assert func is not None and func[0] and any(c.startswith("search_path=") for c in func[1])
    admin_conn.execute(
        "UPDATE orders SET updated_at = now() WHERE marketplace_account_id = %s", (shop.account_id,)
    )
    assert revision(admin_conn, shop.account_id) == before + 1  # 0012 tetikleyicisi çalışıyor
    command.upgrade(alembic_cfg, "head")
    assert state() == (True, False, ["netkar_owner"], body_0013)
    assert revision(admin_conn, shop.account_id) == before + 1


# ===================================================================== DK-09: sahiplik doğrulaması (0014)


def _owners(conn: psycopg.Connection[Any]) -> tuple[str, str]:
    table = conn.execute(
        "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'report_data_revisions'"
    ).fetchone()
    func = conn.execute(
        "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname = 'bump_report_data_revision'"
    ).fetchone()
    assert table is not None and func is not None
    return table[0], func[0]


def test_dk09_table_and_trigger_function_are_owned_by_netkar_owner_after_upgrade(
    admin_conn: psycopg.Connection[Any],
) -> None:
    assert _owners(admin_conn) == ("netkar_owner", "netkar_owner")
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)


def test_dk09_migration_0014_aborts_with_a_clear_message_on_a_wrong_owner_and_downgrade_is_a_noop(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    superuser = database.admin_url.username
    assert superuser and superuser != "netkar_owner"
    try:
        command.downgrade(alembic_cfg, "0013")  # 0014 geri alma: no-op, sahiplik aynı kalır
        assert _owners(admin_conn) == ("netkar_owner", "netkar_owner")
        # 0012'nin süper kullanıcıyla çalıştırılması benzetimi: tablo sahibi süper kullanıcı olur.
        admin_conn.execute(f'ALTER TABLE report_data_revisions OWNER TO "{superuser}"')
        with pytest.raises(Exception, match="Sahiplik hatasi") as caught:
            command.upgrade(alembic_cfg, "head")
        assert "ALTER TABLE public.report_data_revisions OWNER TO netkar_owner" in str(caught.value)
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0013",)
        # Yanlış işlev sahibi de yakalanır (tablo düzeltilmiş olsa bile).
        admin_conn.execute("ALTER TABLE report_data_revisions OWNER TO netkar_owner")
        admin_conn.execute(f'ALTER FUNCTION public.bump_report_data_revision() OWNER TO "{superuser}"')
        with pytest.raises(Exception, match="Sahiplik hatasi"):
            command.upgrade(alembic_cfg, "head")
    finally:
        # Ara bir iddia düşse de paylaşılan test veritabanı sahipliği ve head sürümüyle geri döner (DK-14).
        admin_conn.execute("ALTER TABLE report_data_revisions OWNER TO netkar_owner")
        admin_conn.execute("ALTER FUNCTION public.bump_report_data_revision() OWNER TO netkar_owner")
        command.upgrade(alembic_cfg, "head")
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)
    assert _owners(admin_conn) == ("netkar_owner", "netkar_owner")


def test_dk12_migration_0013_stops_on_a_wrong_table_owner_before_touching_the_function_owner(
    alembic_cfg: Config, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    superuser = database.admin_url.username
    assert superuser and superuser != "netkar_owner"
    try:
        command.downgrade(alembic_cfg, "0012")
        # 0012'nin süper kullanıcıyla çalıştırılması: tablo ve işlev süper kullanıcınındır.
        admin_conn.execute(f'ALTER TABLE report_data_revisions OWNER TO "{superuser}"')
        admin_conn.execute(f'ALTER FUNCTION public.bump_report_data_revision() OWNER TO "{superuser}"')
        with pytest.raises(Exception, match="Sahiplik hatasi"):
            command.upgrade(alembic_cfg, "0013")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0012",)
        assert _owners(admin_conn) == (superuser, superuser)  # işlev sahibi değişmedi
        has_column = admin_conn.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'report_data_revisions' AND column_name = 'last_xact'"
        ).fetchone()
        assert has_column == (0,)  # şema değişmedi
    finally:
        admin_conn.execute("ALTER TABLE report_data_revisions OWNER TO netkar_owner")
        admin_conn.execute("ALTER FUNCTION public.bump_report_data_revision() OWNER TO netkar_owner")
        command.upgrade(alembic_cfg, "head")
    assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0014",)
