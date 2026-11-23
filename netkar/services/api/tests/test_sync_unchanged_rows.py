"""Değişmeyen satır güncellenmez: senkron upsert'leri, veri sürüm sayacı ve uyarı ertelemesi.

Eskiden `ON CONFLICT DO UPDATE` her satırı güncelliyordu; satır tetikleyicisi her güncellemede çalıştığından
aynı veriyle ikinci senkron bile `report_data_revisions.revision` değerini artırıyor (rapor önbelleği boşuna
geçersizleşiyor) ve `upserted > 0` sayıldığı için uyarı değerlendirmesi gereksiz ertelenebiliyordu. Ayrıca
`sync_cursors` tetikleyicisi her imleç ilerlemesinde (`watermark`, `last_window_start`: her turda değişir)
sayacı artırıyordu (migrasyon 0028 bunu daraltır). Bu dosya: aynı veriyle ikinci senkron (sürüm, sayaç,
`updated_at`, uyarı ertelemesi), tek alan değişince tek artış, NULL geçişleri (`IS DISTINCT FROM`), 0 satır
etkileyen ifadenin sayacı artırmaması (satır tetikleyicisi) ve 0028 yükseltme/geri alma/yükseltme.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import procrastinate
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from procrastinate import testing
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import OrderLine
from app.services.sync import store
from app.services.sync.runner import SyncRunner
from app.worker.tasks import defer_alerts_after_sync, register_tasks
from tests.sync_fixtures import Env
from tests.sync_helpers import NOW, client_factory, envelope_for_tests

ACCOUNT_TABLES = (
    "products",
    "orders",
    "order_lines",
    "returns",
    "financial_transactions",
    "cargo_invoice_items",
)


def revision(conn: psycopg.Connection[Any], account_id: UUID) -> int:
    row = conn.execute(
        "SELECT revision FROM report_data_revisions WHERE marketplace_account_id = %s", (account_id,)
    ).fetchone()
    return 0 if row is None else int(row[0])


def stamps(conn: psycopg.Connection[Any]) -> dict[str, list[Any]]:
    """Her veri tablosunun `updated_at` değerleri (satır güncellendiyse değişir)."""
    return {t: conn.execute(f"SELECT updated_at FROM {t} ORDER BY id").fetchall() for t in ACCOUNT_TABLES}


def alert_app() -> procrastinate.App:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)
    app.periodic_registry.periodic_tasks.clear()
    return app


def alert_jobs(app: procrastinate.App) -> list[dict[str, Any]]:
    connector = app.connector
    assert isinstance(connector, testing.InMemoryConnector)
    return [j for j in connector.jobs.values() if j["task_name"] == "alerts.evaluate"]


@pytest.fixture
def sessions(worker_engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(worker_engine, expire_on_commit=False)


async def write_products(
    sessions: async_sessionmaker[AsyncSession], env: Env, rows: list[dict[str, Any]]
) -> int:
    async with sessions.begin() as session:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(env.seller.tenant_id)}
        )
        return await store.upsert_products(
            session, rows, tenant_id=env.seller.tenant_id, account_id=env.seller.account_id
        )


# ===================================================================== aynı veriyle ikinci senkron


async def test_second_sync_with_identical_data_changes_nothing_and_defers_no_alert(env: Env) -> None:
    account = env.seller.account_id
    app = alert_app()
    first = await env.runner.run(account, "backfill")
    assert all(s.upserted > 0 for s in first.sources if s.status == "succeeded")
    after_first = revision(env.conn, account)
    assert after_first >= 1
    before = stamps(env.conn)
    app_open = app.open_async()
    async with app_open:
        assert await defer_alerts_after_sync(app, first) is True  # ilk yazım: uyarı ertelenir
        assert len(alert_jobs(app)) == 1

        # Zorlanmış backfill: aynı veri baştan yazılır.
        forced = await env.runner.run(account, "backfill", force=True)
        assert [s.upserted for s in forced.sources] == [0] * len(forced.sources)
        assert revision(env.conn, account) == after_first
        assert stamps(env.conn) == before  # hiçbir satırın updated_at değeri değişmedi

        # Artımlı senkron: imleç ilerler (watermark, last_window_start) ama veri aynıdır.
        later = NOW + timedelta(minutes=15)
        runner = SyncRunner(
            env.runner._engine, client_factory(env.api), envelope_for_tests(), now=lambda: later
        )
        incremental = await runner.run(account, "incremental")
        assert incremental.status == "completed"
        assert [s.upserted for s in incremental.sources] == [0] * len(incremental.sources)
        assert revision(env.conn, account) == after_first  # imleç ilerlemesi sürümü artırmaz (0028)
        assert stamps(env.conn) == before
        mark = env.conn.execute("SELECT watermark FROM sync_cursors WHERE source = 'orders'").fetchone()
        assert mark == (later,)  # imleç gerçekten ilerledi

        # Uyarı ertelemesi: hiçbir kaynakta upserted > 0 yok, iş eklenmez.
        assert await defer_alerts_after_sync(app, forced) is False
        assert await defer_alerts_after_sync(app, incremental) is False
    assert len(alert_jobs(app)) == 1


async def test_one_changed_field_bumps_the_revision_exactly_once(env: Env) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill")
    before = revision(env.conn, account)
    stamps_before = stamps(env.conn)

    env.api.orders = [{**env.api.orders[0], "packageGrossAmount": 9999.5}]
    changed = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    (orders,) = changed.sources
    assert orders.upserted == 1  # yalnız paket satırı (iki satır kalemi değişmedi)
    assert revision(env.conn, account) == before + 1
    stamps_after = stamps(env.conn)
    assert stamps_after["orders"] != stamps_before["orders"]
    assert {t: v for t, v in stamps_after.items() if t != "orders"} == {
        t: v for t, v in stamps_before.items() if t != "orders"
    }
    # Aynı değerle yeniden: artık değişiklik yok.
    again = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert again.sources[0].upserted == 0
    assert revision(env.conn, account) == before + 1


async def test_a_changed_order_line_counts_once_and_unchanged_packages_still_resolve_their_lines(
    env: Env,
) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill", sources=["orders"])
    before = revision(env.conn, account)
    first = env.api.orders[0]
    lines = [{**first["lines"][0], "quantity": 3}, first["lines"][1]]
    env.api.orders = [{**first, "lines": lines}]
    outcome = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert outcome.sources[0].upserted == 1  # paket aynı, yalnız bir satır değişti
    assert revision(env.conn, account) == before + 1
    quantities = env.conn.execute("SELECT quantity FROM order_lines ORDER BY line_id").fetchall()
    assert quantities == [(3,), (1,)]


async def test_a_line_removed_from_the_payload_counts_as_a_change(env: Env) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill", sources=["orders"])
    before = revision(env.conn, account)
    first = env.api.orders[0]
    env.api.orders = [{**first, "lines": [first["lines"][0]]}]
    outcome = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert outcome.sources[0].upserted == 1  # kalkan satır `removed_at` ile işaretlendi
    assert revision(env.conn, account) == before + 1
    again = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert again.sources[0].upserted == 0  # işaretli satır yeniden saymaz
    assert revision(env.conn, account) == before + 1


async def test_a_revived_line_returns_to_active_and_counts_as_a_change(env: Env) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill", sources=["orders"])
    first = env.api.orders[0]
    env.api.orders = [{**first, "lines": [first["lines"][0]]}]
    await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert env.conn.execute("SELECT count(*) FROM order_lines WHERE removed_at IS NOT NULL").fetchone() == (
        1,
    )
    before = revision(env.conn, account)
    env.api.orders = [first]  # satır geri geldi
    revived = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert revived.sources[0].upserted == 1
    assert revision(env.conn, account) == before + 1
    assert env.conn.execute("SELECT count(*) FROM order_lines WHERE removed_at IS NOT NULL").fetchone() == (
        0,
    )


async def test_items_jsonb_content_change_bumps_but_key_order_alone_does_not(
    env: Env, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill", sources=["orders"])
    first_line = env.conn.execute("SELECT order_id, line_id FROM order_lines ORDER BY line_id").fetchone()
    assert first_line is not None
    order_id, line_id = first_line
    base = {
        "order_id": order_id,
        "line_id": line_id,
        "barcode": "8681000000011",
        "quantity": 1,
        "line_gross_amount": Decimal("299.90"),
        "removed_at": None,
    }

    async def write(items: list[dict[str, str]]) -> int:
        async with sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(env.seller.tenant_id)}
            )
            return await store.upsert_rows(
                session,
                OrderLine,
                [{**base, "items": items}],
                tenant_id=env.seller.tenant_id,
                account_id=account,
                conflict=("order_id", "line_id"),
            )

    assert await write([{"id": "1", "seller_discount": "0.00", "ty_discount": "0.00"}]) == 1
    before = revision(env.conn, account)
    # Yalnız anahtar sırası farklı: jsonb eşit sayılır.
    assert await write([{"ty_discount": "0.00", "seller_discount": "0.00", "id": "1"}]) == 0
    assert revision(env.conn, account) == before
    # İçerik değişti.
    assert await write([{"id": "1", "seller_discount": "5.00", "ty_discount": "0.00"}]) == 1
    assert revision(env.conn, account) == before + 1


# ============================================================================== NULL geçişleri


async def test_null_to_value_and_value_to_null_are_detected_and_equal_values_are_not(
    env: Env, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account = env.seller.account_id
    key = {"barcode": "8689999000001"}
    assert revision(env.conn, account) == 0
    assert await write_products(sessions, env, [{**key, "title": None, "vat_rate": None}]) == 1
    assert revision(env.conn, account) == 1
    # NULL -> NULL: değişiklik yok.
    assert await write_products(sessions, env, [{**key, "title": None, "vat_rate": None}]) == 0
    assert revision(env.conn, account) == 1
    # NULL -> değer.
    assert await write_products(sessions, env, [{**key, "title": "Tişört", "vat_rate": Decimal("20")}]) == 1
    assert revision(env.conn, account) == 2
    # değer -> aynı değer (sayısal olarak eşit: 20 ile 20.0).
    assert await write_products(sessions, env, [{**key, "title": "Tişört", "vat_rate": Decimal("20.0")}]) == 0
    assert revision(env.conn, account) == 2
    # değer -> NULL (yalnız bir sütun).
    assert await write_products(sessions, env, [{**key, "title": "Tişört", "vat_rate": None}]) == 1
    assert revision(env.conn, account) == 3
    assert await write_products(sessions, env, [{**key, "title": None, "vat_rate": None}]) == 1
    assert revision(env.conn, account) == 4
    row = env.conn.execute("SELECT title, vat_rate FROM products WHERE barcode = %s", (key["barcode"],))
    assert row.fetchone() == (None, None)


async def test_mixed_batch_counts_only_new_and_changed_rows_and_bumps_once(
    env: Env, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account = env.seller.account_id
    rows = [{"barcode": f"869000000{n}", "title": f"Ürün {n}"} for n in range(4)]
    assert await write_products(sessions, env, rows) == 4
    before = revision(env.conn, account)
    rows[1] = {**rows[1], "title": "Yeni ad"}
    rows.append({"barcode": "8690000099", "title": "Yeni ürün"})
    assert await write_products(sessions, env, rows) == 2  # bir değişen + bir yeni
    assert revision(env.conn, account) == before + 1  # tek işlemde tek artış


async def test_user_owned_columns_survive_and_do_not_count_as_changes(
    env: Env, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account = env.seller.account_id
    await env.runner.run(account, "backfill")
    env.conn.execute("UPDATE products SET unit_desi = 7.5")
    env.conn.execute("UPDATE returns SET returned_to_stock = false")
    before = revision(env.conn, account)
    forced = await env.runner.run(account, "backfill", force=True)
    assert [s.upserted for s in forced.sources] == [0] * len(forced.sources)
    assert revision(env.conn, account) == before
    assert env.conn.execute("SELECT DISTINCT unit_desi FROM products").fetchall() == [(Decimal("7.5"),)]
    assert env.conn.execute("SELECT DISTINCT returned_to_stock FROM returns").fetchall() == [(False,)]


# ======================================================== 0 satır etkileyen ifade sayacı artırmaz


async def test_statements_that_touch_zero_rows_never_bump_the_revision(
    env: Env,
) -> None:
    """Tetikleyici FOR EACH ROW'dur (STATEMENT değil): etkilenen satır yoksa hiç çalışmaz."""
    account = env.seller.account_id
    await env.runner.run(account, "backfill")
    before = revision(env.conn, account)
    for table in ACCOUNT_TABLES:
        done = env.conn.execute(f"UPDATE {table} SET updated_at = now() WHERE false")
        assert done.rowcount == 0
        assert env.conn.execute(f"DELETE FROM {table} WHERE false").rowcount == 0
    # Çakışan ama WHERE koşulu yanlış olan upsert: satır güncellenmez, tetikleyici çalışmaz.
    done = env.conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode) "
        "SELECT tenant_id, marketplace_account_id, barcode FROM products "
        "ON CONFLICT (marketplace_account_id, barcode) DO UPDATE SET updated_at = now() WHERE false"
    )
    assert done.rowcount == 0
    assert revision(env.conn, account) == before


# ============================================================= kaynak düzelmesi ve uyarı ertelemesi


async def test_recovery_after_a_failed_run_defers_alerts_even_when_nothing_was_written(env: Env) -> None:
    account = env.seller.account_id
    app = alert_app()
    await env.runner.run(account, "backfill")
    env.api.fail_after["/orders/stream"] = (0, 500)
    failed = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert failed.sources[0].status == "failed" and failed.sources[0].recovered is False
    env.api.fail_after.clear()
    before = revision(env.conn, account)
    healed = await env.runner.run(account, "backfill", sources=["orders"], force=True)
    assert healed.sources[0].status == "succeeded" and healed.sources[0].upserted == 0
    assert healed.sources[0].recovered is True  # önceki çalışma failed
    assert revision(env.conn, account) == before  # veri sürümü değişmedi
    async with app.open_async():
        assert await defer_alerts_after_sync(app, healed) is True  # yine de değerlendirme ertelenir
        # Sipariş kesinti kuralının da bastırma kaynağıdır: düzelmede kapsam `all` olmalı (`fast` kesintiyi çalıştırmaz).
        (job,) = alert_jobs(app)
        assert job["args"]["scope"] == "all"
        # Düzelme tekrar etmez: sonraki başarılı tur ertelemez.
        again = await env.runner.run(account, "backfill", sources=["orders"], force=True)
        assert again.sources[0].recovered is False
        assert await defer_alerts_after_sync(app, again) is False


# ================================================================================ imleç (0028)


def test_cursor_progress_does_not_bump_but_backfill_completion_insert_and_delete_do(
    env: Env,
) -> None:
    account = env.seller.account_id
    conn = env.conn
    conn.execute(
        "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark) "
        "VALUES (%s, %s, 'orders', %s)",
        (env.seller.tenant_id, account, NOW),
    )
    assert revision(conn, account) == 1  # ilk imleç satırı (ekleme) sayar
    conn.execute(
        "UPDATE sync_cursors SET watermark = %s, last_window_start = %s, updated_at = now() "
        "WHERE marketplace_account_id = %s",
        (NOW + timedelta(hours=1), NOW, account),
    )
    assert revision(conn, account) == 1  # yalnız ilerleme: sayaç artmaz
    conn.execute(
        "UPDATE sync_cursors SET backfill_completed_at = %s WHERE marketplace_account_id = %s", (NOW, account)
    )
    assert revision(conn, account) == 2  # backfill tamamlandı: sayar
    conn.execute(
        "UPDATE sync_cursors SET backfill_completed_at = %s WHERE marketplace_account_id = %s", (NOW, account)
    )
    assert revision(conn, account) == 2  # aynı değer: sayar değil
    conn.execute("DELETE FROM sync_cursors WHERE marketplace_account_id = %s", (account,))
    assert revision(conn, account) == 3


# ==================================================================================== migrasyon


CURSOR_TRIGGERS = (
    "SELECT t.tgname, (t.tgtype & 1) = 1, t.tgdeferrable AND t.tginitdeferred, t.tgqual IS NOT NULL "
    "FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
    "WHERE c.relname = 'sync_cursors' AND NOT t.tgisinternal ORDER BY t.tgname"
)


def test_migration_0028_upgrade_downgrade_upgrade_keeps_data_and_restores_each_state(
    alembic_cfg: Config, env: Env
) -> None:
    conn = env.conn
    account = env.seller.account_id
    conn.execute(
        "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark) "
        "VALUES (%s, %s, 'orders', %s)",
        (env.seller.tenant_id, account, NOW),
    )
    revision_before = revision(conn, account)

    def progress_bumps() -> bool:
        before = revision(conn, account)
        conn.execute("UPDATE sync_cursors SET watermark = watermark + interval '1 minute'")
        return revision(conn, account) == before + 1

    upgraded = conn.execute(CURSOR_TRIGGERS).fetchall()
    assert upgraded == [
        ("bump_rdr_cursor_insert_delete", True, True, False),
        ("bump_rdr_cursor_update", True, True, True),
    ]
    assert not any(name.startswith("trg_") for name, *_ in upgraded)  # `trg_` öneki bu migrasyona ait değil
    assert progress_bumps() is False

    command.downgrade(alembic_cfg, "0027")
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0027",)
    assert conn.execute(CURSOR_TRIGGERS).fetchall() == [("trg_bump_report_data_revision", True, True, False)]
    assert conn.execute("SELECT count(*) FROM sync_cursors").fetchone() == (1,)  # veri kaybı yok
    assert revision(conn, account) >= revision_before
    assert progress_bumps() is True  # 0027 davranışı: her ilerleme sayar

    command.upgrade(alembic_cfg, "head")
    assert conn.execute(CURSOR_TRIGGERS).fetchall() == upgraded
    assert conn.execute("SELECT count(*) FROM sync_cursors").fetchone() == (1,)
    assert progress_bumps() is False
    # Diğer yedi tablonun tetikleyicisine dokunulmadı.
    others = conn.execute(
        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
        "WHERE t.tgname = 'trg_bump_report_data_revision' AND c.relname <> 'sync_cursors'"
    ).fetchone()
    assert others == (7,)
