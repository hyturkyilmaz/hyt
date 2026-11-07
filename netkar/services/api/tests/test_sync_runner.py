"""Senkron yürütücü: backfill, artımlı çekim, idempotentlik, yeniden başlama, kilit, 401/403, hata sınıfları.

Gerçek PostgreSQL (worker rolü, RLS) ve sahte Trendyol taşıması; gerçek ağ yok (ADR-0005).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import psycopg
import pytest

from app.core.envelope import EnvelopeCipher, KeyRing
from app.services.sync.runner import SyncPolicy, SyncRunner, account_lock
from app.services.sync.sources import SOURCE_ORDER
from tests.conftest import DatabaseInfo
from tests.sync_fixtures import Env, full_api
from tests.sync_helpers import (
    NOW,
    client_factory,
    count,
    envelope_for_tests,
    make_seller,
    ms,
    order_line,
    package,
    settlement_row,
    status_response,
)


def table_counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    tables = ("products", "orders", "order_lines", "returns", "financial_transactions", "cargo_invoice_items")
    return {t: count(conn, t) for t in tables}


# --- backfill ---------------------------------------------------------------------------------------


async def test_backfill_writes_every_source_and_marks_progress(env: Env) -> None:
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "completed" and not outcome.retryable
    assert [s.source for s in outcome.sources] == list(SOURCE_ORDER)
    assert all(s.status == "succeeded" for s in outcome.sources)

    counts = table_counts(env.conn)
    assert counts["products"] == 2 and counts["orders"] == 1 and counts["order_lines"] == 2
    assert counts["returns"] == 1 and counts["cargo_invoice_items"] == 1
    assert counts["financial_transactions"] == 3  # Sale, Kargo Faturası, Stopaj

    runs = env.conn.execute(
        "SELECT source, status, windows_total, windows_done, error_class, kind FROM sync_runs ORDER BY started_at"
    ).fetchall()
    assert [r[0] for r in runs] == list(SOURCE_ORDER)
    assert all(r[1] == "succeeded" and r[2] == r[3] and r[4] is None and r[5] == "backfill" for r in runs)
    by_source = {r[0]: r for r in runs}
    assert by_source["orders"][2] == 7 and by_source["settlements"][2] == 6  # 14 ve 15 günlük pencereler
    assert by_source["products"][2] == 1

    cursors = env.conn.execute(
        "SELECT source, watermark, backfill_completed_at FROM sync_cursors ORDER BY source"
    ).fetchall()
    assert {c[0] for c in cursors} == set(SOURCE_ORDER)
    assert all(c[1] == NOW and c[2] == NOW for c in cursors)

    # sahte API'ye gelen istekler: finans her tipte tek istek (K05: 1 istekte 1 tip)
    for query in env.api.calls_to("/settlements"):
        assert "," not in query["transactionTypes"]
    assert {q["transactionTypes"] for q in env.api.calls_to("/otherfinancials")} == {
        "DeductionInvoices",
        "Stoppage",
        "CashAdvance",
        "FinancialItem",
    }
    assert {"PlatformServiceFee"} == {
        q["transactionSubType"] for q in env.api.calls_to("/otherfinancials") if "transactionSubType" in q
    }


async def test_backfill_stores_expected_values_and_no_customer_data(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill")
    order = env.conn.execute(
        "SELECT order_number, shipment_package_id, ordered_at, status, carrier, province, province_code, "
        "customer_key, who_pays, cargo_deci FROM orders"
    ).fetchone()
    assert order is not None
    assert (
        order[0] == "1001" and order[1] == 3001 and order[3] == "Delivered" and order[4] == "Trendyol Express"
    )
    assert order[5] == "İstanbul" and order[6] == 34 and order[7] is None and order[9] == Decimal("2")
    line = env.conn.execute(
        "SELECT line_gross_amount, quantity, vat_rate, commission_rate, items FROM order_lines "
        "WHERE line_id = 30010"
    ).fetchone()
    assert line is not None
    assert (
        line[0] == Decimal("299.900000")
        and line[1] == 1
        and line[2] == Decimal("20")
        and line[3] == Decimal("15")
    )
    assert line[4] == [{"id": "300100", "seller_discount": "0.00", "ty_discount": "0.00"}]
    sale = env.conn.execute(
        "SELECT commission_amount, seller_revenue, request_type, request_sub_type FROM financial_transactions "
        "WHERE transaction_id = 'S1'"
    ).fetchone()
    assert sale == (Decimal("44.985000"), Decimal("254.915000"), "Sale", "")
    ret = env.conn.execute(
        "SELECT claim_id, claim_item_id, order_line_item_id, returned_to_stock FROM returns"
    ).fetchone()
    assert ret == ("C-1", "I-1", "300100", True)


async def test_second_backfill_skips_completed_sources_and_force_is_idempotent(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill")
    before = table_counts(env.conn)
    calls = len(env.api.calls)
    again = await env.runner.run(env.seller.account_id, "backfill")
    assert again.status == "completed"
    assert all(s.status == "skipped" and s.reason == "already_backfilled" for s in again.sources)
    assert len(env.api.calls) == calls  # hiç istek yok
    forced = await env.runner.run(env.seller.account_id, "backfill", force=True)
    assert forced.status == "completed" and len(env.api.calls) > calls
    assert table_counts(env.conn) == before  # yeniden yazım hiçbir şeyi çoğaltmaz
    assert count(env.conn, "financial_transactions") == 3


async def test_backfill_resumes_from_the_cursor_after_a_transient_failure(env: Env) -> None:
    env.api.fail_after["/orders/stream"] = (2, 500)  # 3. pencerede sunucu hatası
    first = await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    assert first.status == "partial" and first.retryable
    (source,) = first.sources
    assert source.status == "failed" and source.error_class == "server_error" and source.windows_done == 2

    run = env.conn.execute(
        "SELECT status, windows_total, windows_done, error_class FROM sync_runs WHERE source = 'orders'"
    ).fetchone()
    assert run == ("failed", 7, 2, "server_error")
    cursor = env.conn.execute(
        "SELECT watermark, backfill_completed_at FROM sync_cursors WHERE source = 'orders'"
    ).fetchone()
    assert cursor is not None and cursor[1] is None  # backfill tamamlanmış sayılmaz
    second_window_end = cursor[0]
    assert second_window_end == NOW - timedelta(days=89) + 2 * (
        timedelta(days=14) - timedelta(milliseconds=1)
    )

    # Sunucu düzelince devam eder: yalnız kalan 5 pencere istenir, ilk pencereler tekrar çekilmez
    env.api.fail_after.clear()
    env.api.calls.clear()
    second = await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    assert second.status == "completed"
    assert len(env.api.calls_to("/orders/stream")) == 5
    assert min(int(q["lastModifiedStartDate"]) for q in env.api.calls_to("/orders/stream")) == ms(
        second_window_end
    )
    assert count(env.conn, "orders") == 1
    done = env.conn.execute(
        "SELECT backfill_completed_at FROM sync_cursors WHERE source = 'orders'"
    ).fetchone()
    assert done == (NOW,)


# --- artımlı çekim ---------------------------------------------------------------------------------


async def test_incremental_before_backfill_does_nothing(env: Env) -> None:
    outcome = await env.runner.run(env.seller.account_id, "incremental")
    assert outcome.status == "completed"
    assert all(s.status == "skipped" and s.reason == "needs_backfill" for s in outcome.sources)
    assert env.api.calls == []
    assert count(env.conn, "sync_runs") == 0


async def test_incremental_starts_at_the_cursor_with_overlap_and_upserts_changes(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill")
    env.api.calls.clear()
    # yeni sipariş + mevcut siparişin durum değişikliği + yeni ekstre satırı
    env.api.orders = [
        package("1001", 3001, ordered=NOW - timedelta(days=20), status="Returned"),
        package("1002", 3002, ordered=NOW - timedelta(hours=3)),
    ]
    env.api.orders[0]["lastModifiedDate"] = ms(NOW - timedelta(minutes=30))
    env.api.orders[1]["lastModifiedDate"] = ms(NOW - timedelta(minutes=10))
    env.api.settlements["Sale"].append(
        settlement_row("S2", "1002", when=NOW - timedelta(hours=2), credit="100")
    )

    later = NOW + timedelta(minutes=15)
    runner = SyncRunner(env.runner._engine, client_factory(env.api), envelope_for_tests(), now=lambda: later)
    outcome = await runner.run(env.seller.account_id, "incremental")
    assert outcome.status == "completed" and all(s.status == "succeeded" for s in outcome.sources)

    # sipariş: imleç (NOW) - 1 saat örtüşme ile başlar, tek pencere
    (query,) = env.api.calls_to("/orders/stream")
    assert int(query["lastModifiedStartDate"]) == ms(NOW - timedelta(hours=1))
    assert int(query["lastModifiedEndDate"]) == ms(later)
    # ekstre: 7 gün örtüşme, tek pencere
    assert {int(q["startDate"]) for q in env.api.calls_to("/settlements")} == {ms(NOW - timedelta(days=7))}

    assert count(env.conn, "orders") == 2
    assert env.conn.execute("SELECT status FROM orders WHERE order_number = '1001'").fetchone() == (
        "Returned",
    )
    assert count(env.conn, "financial_transactions", "transaction_id IN ('S1', 'S2')") == 2
    runs = env.conn.execute(
        "SELECT count(*) FROM sync_runs WHERE kind = 'incremental' AND status = 'succeeded'"
    ).fetchone()
    assert runs == (6,)
    mark = env.conn.execute("SELECT watermark FROM sync_cursors WHERE source = 'orders'").fetchone()
    assert mark == (later,)


async def test_incremental_respects_requested_sources(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill")
    env.api.calls.clear()
    outcome = await env.runner.run(env.seller.account_id, "incremental", sources=["claims", "orders"])
    assert [s.source for s in outcome.sources] == ["orders", "claims"]  # kaynak sırası sabit
    assert not env.api.calls_to("/settlements") and not env.api.calls_to("/products")


async def test_lookback_is_clamped_to_the_policy_horizon(env: Env, worker_engine: Any) -> None:
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    env.conn.execute("UPDATE sync_cursors SET watermark = %s", (NOW - timedelta(days=200),))
    env.api.calls.clear()
    runner = SyncRunner(
        worker_engine,
        client_factory(env.api),
        envelope_for_tests(),
        now=lambda: NOW,
        policy=SyncPolicy(lookback_days=30),
    )
    await runner.run(env.seller.account_id, "incremental", sources=["orders"])
    starts = sorted(int(q["lastModifiedStartDate"]) for q in env.api.calls_to("/orders/stream"))
    assert starts[0] == ms(NOW - timedelta(days=30)) and len(starts) == 3  # 30 gün -> 3 pencere


# --- idempotentlik ve kullanıcı verisi --------------------------------------------------------------


async def test_removed_lines_are_flagged_not_deleted_and_revived(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    first = env.api.orders[0]
    kept = first["lines"][0]
    env.api.orders = [{**first, "lines": [kept]}]  # ikinci satır kalktı (paket bölündü)
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"], force=True)
    rows = dict(env.conn.execute("SELECT line_id, removed_at IS NOT NULL FROM order_lines").fetchall())
    assert rows == {30_010: False, 30_011: True}  # silinmedi, işaretlendi
    env.api.orders = [first]  # geri geldi
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"], force=True)
    rows = dict(env.conn.execute("SELECT line_id, removed_at IS NOT NULL FROM order_lines").fetchall())
    assert rows == {30_010: False, 30_011: False}


async def test_sync_never_overwrites_user_owned_columns(env: Env) -> None:
    await env.runner.run(env.seller.account_id, "backfill")
    env.conn.execute("UPDATE returns SET returned_to_stock = false")
    env.conn.execute("UPDATE products SET unit_desi = 3.5")
    env.conn.execute("UPDATE orders SET customer_key = 'abc'")
    await env.runner.run(env.seller.account_id, "backfill", force=True)
    assert env.conn.execute("SELECT returned_to_stock FROM returns").fetchone() == (False,)
    assert env.conn.execute("SELECT DISTINCT unit_desi FROM products").fetchall() == [(Decimal("3.5"),)]
    assert env.conn.execute("SELECT customer_key FROM orders").fetchone() == ("abc",)


async def test_duplicate_records_in_one_window_do_not_break_the_upsert(env: Env) -> None:
    env.api.orders = [env.api.orders[0], env.api.orders[0]]  # sayfa örtüşmesi
    env.api.settlements["Sale"] = [settlement_row("S1"), settlement_row("S1")]
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "completed"
    assert (
        count(env.conn, "orders") == 1
        and count(env.conn, "financial_transactions", "transaction_id = 'S1'") == 1
    )


async def test_bad_records_are_skipped_and_counted_not_fatal(env: Env) -> None:
    broken = package("1003", 3003)
    del broken["orderDate"]
    env.api.orders.append(broken)
    env.api.orders[0]["lines"].append({**order_line(30_012), "barcode": None})
    outcome = await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    assert outcome.status == "completed"
    run = env.conn.execute(
        "SELECT fetched_count, skipped_count FROM sync_runs WHERE source = 'orders'"
    ).fetchone()
    assert run is not None and run[0] > 0 and run[1] > 0  # her pencere iki paket döndürür; bozuklar atlanır
    assert count(env.conn, "orders") == 1 and count(env.conn, "order_lines") == 2


# --- hata sınıfları ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "error_class", "transient"),
    [(429, "rate_limited", True), (503, "server_error", True), (400, "request_rejected", False)],
)
async def test_failure_classes_and_other_sources_still_run(
    env: Env, status: int, error_class: str, transient: bool
) -> None:
    env.api.overrides["/orders/stream"] = status_response(status)
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "partial" and outcome.retryable is transient
    by = {s.source: s for s in outcome.sources}
    assert by["orders"].status == "failed" and by["orders"].error_class == error_class
    assert all(by[s].status == "succeeded" for s in SOURCE_ORDER if s != "orders")
    row = env.conn.execute("SELECT status, error_class FROM sync_runs WHERE source = 'orders'").fetchone()
    assert row == ("failed", error_class)
    assert count(env.conn, "products") == 2  # diğer kaynaklar yazıldı
    assert env.conn.execute("SELECT status FROM marketplace_accounts").fetchone() == ("active",)


async def test_network_error_is_transient_and_protocol_error_is_not(env: Env) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("bağlantı kurulamadı")

    env.api.overrides["/claims"] = boom
    env.api.overrides["/products/approved"] = lambda r: httpx.Response(200, content=b"bu json degil")
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    by = {s.source: s for s in outcome.sources}
    assert (by["claims"].error_class, by["claims"].transient) == ("network", True)
    assert (by["products"].error_class, by["products"].transient) == ("protocol", False)
    assert outcome.retryable


async def test_failure_records_hold_only_a_class_never_a_message(env: Env) -> None:
    env.api.overrides["/orders/stream"] = lambda r: httpx.Response(200, content=b'{"hasMore": "SahteAd"}')
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    row = env.conn.execute("SELECT error_class FROM sync_runs").fetchone()
    assert row is not None and row[0] in {"protocol", "validation"} and "SahteAd" not in str(row)
    columns = {
        r[0]
        for r in env.conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'sync_runs'"
        )
    }
    assert not {"message", "error", "body", "detail", "payload", "traceback"} & columns


@pytest.mark.parametrize(("status", "reason"), [(401, "unauthorized"), (403, "forbidden")])
async def test_auth_failure_invalidates_the_account_audits_and_stops(
    env: Env, status: int, reason: str
) -> None:
    env.api.overrides["/orders/stream"] = status_response(status)
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "invalid" and not outcome.retryable
    assert [s.source for s in outcome.sources] == ["orders"]  # senkron durdu: sonraki kaynaklara geçilmedi
    assert env.api.paths() == [env.api.paths()[0]] * len(env.api.paths())  # yalnız sipariş uç noktası
    assert env.conn.execute("SELECT status FROM marketplace_accounts").fetchone() == ("invalid",)
    audit = env.conn.execute(
        "SELECT action, target, meta, user_id FROM audit_log WHERE action LIKE 'marketplace_account.%'"
    ).fetchall()
    assert audit == [
        (
            "marketplace_account.sync_invalidated",
            str(env.seller.account_id),
            {"reason": reason, "source": "orders"},
            None,
        )
    ]
    run = env.conn.execute("SELECT status, error_class FROM sync_runs").fetchone()
    assert run == ("failed", reason)
    # geçersiz hesapta sonraki çalıştırmalar hiçbir şey yapmaz
    env.api.calls.clear()
    again = await env.runner.run(env.seller.account_id, "incremental")
    assert again.status == "inactive" and env.api.calls == []


async def test_auth_failure_mid_backfill_keeps_progress_already_written(env: Env) -> None:
    env.api.fail_after["/settlements"] = (0, 401)
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "invalid"
    assert [s.source for s in outcome.sources] == ["orders", "claims", "products", "settlements"]
    assert count(env.conn, "orders") == 1 and count(env.conn, "products") == 2  # yazılanlar silinmez


async def test_inactive_accounts_are_not_synced(make_env: Any) -> None:
    for status in ("invalid", "revoked"):
        e = make_env(status=status, seller_id="5555" if status == "invalid" else "6666")
        outcome = await e.runner.run(e.seller.account_id, "backfill")
        assert outcome.status == "inactive" and e.api.calls == []
    unknown = await e.runner.run(uuid4(), "backfill")
    assert unknown.status == "inactive"


async def test_undecryptable_credentials_are_reported_without_any_call(make_env: Any) -> None:
    wrong = EnvelopeCipher(KeyRing({"baska": bytes(range(32))}, "baska"))
    e = make_env(envelope=envelope_for_tests())
    broken = SyncRunner(e.runner._engine, client_factory(e.api), wrong, now=lambda: NOW)
    outcome = await broken.run(e.seller.account_id, "backfill")
    assert outcome.status == "credentials_error" and e.api.calls == []
    assert count(e.conn, "sync_runs") == 0 and e.conn.execute(
        "SELECT status FROM marketplace_accounts"
    ).fetchone() == ("active",)


# --- kilit ve izolasyon -----------------------------------------------------------------------------


async def test_concurrent_runs_for_the_same_account_do_not_overlap(env: Env) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def gate(request: httpx.Request) -> None:
        entered.set()
        await release.wait()

    env.api.gate = gate
    first = asyncio.create_task(env.runner.run(env.seller.account_id, "backfill"))
    await asyncio.wait_for(entered.wait(), 10)
    second = await env.runner.run(env.seller.account_id, "backfill")  # kilit tutuluyor
    assert second.status == "locked" and second.sources == []
    release.set()
    done = await asyncio.wait_for(first, 30)
    assert done.status == "completed"
    # kilit bırakıldı: yeni iş çalışabilir
    env.api.gate = None
    third = await env.runner.run(env.seller.account_id, "incremental")
    assert third.status == "completed"


async def test_lock_held_by_another_session_blocks_and_releases_on_disconnect(
    env: Env, database: DatabaseInfo
) -> None:
    key = f"netkar:sync:{env.seller.account_id}"
    holder = psycopg.connect(database.worker_dsn(), autocommit=True)
    holder.execute("SELECT pg_advisory_lock(hashtextextended(%s, 0))", (key,))
    try:
        blocked = await env.runner.run(env.seller.account_id, "backfill")
        assert blocked.status == "locked" and env.api.calls == []
    finally:
        holder.close()  # çöken süreç: bağlantı kopar, kilit kendiliğinden düşer
    # Sunucu, kopan oturumun kilidini birkaç ms içinde bırakır: kısa süre bekleyerek dene.
    for _ in range(50):
        free = await env.runner.run(env.seller.account_id, "backfill")
        if free.status != "locked":
            break
        await asyncio.sleep(0.1)
    assert free.status == "completed"


async def test_locks_of_different_accounts_are_independent(
    worker_engine: Any, admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = make_seller(admin_conn, seller_id="1111"), make_seller(admin_conn, seller_id="2222")
    async with (
        account_lock(worker_engine, a.account_id) as got_a,
        account_lock(worker_engine, b.account_id) as got_b,
    ):
        assert got_a and got_b
        async with account_lock(worker_engine, a.account_id) as again:
            assert again is False


async def test_rows_are_written_only_into_the_accounts_own_tenant(
    make_env: Any, admin_conn: psycopg.Connection[Any]
) -> None:
    a = make_env(seller_id="1111")
    b = make_env(full_api(), seller_id="2222")
    await a.runner.run(a.seller.account_id, "backfill")
    assert count(admin_conn, "orders", f"tenant_id = '{a.seller.tenant_id}'") == 1
    assert count(admin_conn, "orders", f"tenant_id = '{b.seller.tenant_id}'") == 0
    await b.runner.run(b.seller.account_id, "backfill")
    for table in ("orders", "order_lines", "products", "financial_transactions", "returns", "sync_runs"):
        wrong = admin_conn.execute(
            f"SELECT count(*) FROM {table} t JOIN marketplace_accounts m ON m.id = t.marketplace_account_id "
            "WHERE m.tenant_id <> t.tenant_id"
        ).fetchone()
        assert wrong == (0,), table


async def test_cargo_invoices_are_fetched_once_and_bad_serials_are_skipped(env: Env) -> None:
    env.api.other[("DeductionInvoices", "")].append(
        {
            "id": "../etc",
            "transactionDate": ms(NOW - timedelta(days=10)),
            "transactionType": "Kargo Faturası",
            "debt": "1",
            "credit": "0",
            "paymentOrderId": 1,
        }
    )
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    cargo = next(s for s in outcome.sources if s.source == "cargo_invoices")
    assert cargo.status == "succeeded" and cargo.skipped == 1 and cargo.upserted == 1
    assert [q for q in env.api.paths() if "cargo-invoice" in q] == [
        "/integration/finance/che/sellers/2738/cargo-invoice/KRG1/items"
    ]
    env.api.calls.clear()
    await env.runner.run(env.seller.account_id, "backfill", sources=["cargo_invoices"], force=True)
    # KRG1'in kalemleri var: yeniden çekilmez; yalnız kalemi olmayan geçersiz seri denenir ve atlanır
    assert not [q for q in env.api.paths() if "KRG1" in q]
    assert count(env.conn, "cargo_invoice_items") == 1


async def test_cargo_failure_is_classified_and_leaves_rest_for_next_run(env: Env) -> None:
    env.api.overrides["/cargo-invoice/"] = status_response(502)
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    cargo = next(s for s in outcome.sources if s.source == "cargo_invoices")
    assert (cargo.status, cargo.error_class, cargo.transient) == ("failed", "server_error", True)
    env.api.overrides.clear()
    retry = await env.runner.run(env.seller.account_id, "backfill", sources=["cargo_invoices"])
    assert retry.status == "completed" and count(env.conn, "cargo_invoice_items") == 1
    assert env.conn.execute(
        "SELECT backfill_completed_at FROM sync_cursors WHERE source = 'cargo_invoices'"
    ).fetchone() == (NOW,)


def test_outcome_summary_is_numeric_and_free_of_free_text() -> None:
    from app.services.sync.runner import SourceOutcome, SyncOutcome

    outcome = SyncOutcome(
        uuid4(),
        "backfill",
        "partial",
        [SourceOutcome("orders", "failed", error_class="network", transient=True)],
    )
    summary = outcome.summary()
    assert summary["status"] == "partial" and outcome.retryable
    assert summary["sources"] == {"orders": {"status": "failed", "error_class": "network", "upserted": 0}}


async def test_a_rejected_request_type_skips_only_that_request(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    """Doğrulanmamış tek tip adı (400) tüm ekstre senkronunu durdurmaz; yalnız o istek atlanır ve sayılır."""

    def reject_delivery_fee(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("transactionTypes") == "DeliveryFee":
            return httpx.Response(400, content=b"{}")
        return httpx.Response(200, content=b'{"page": 0, "totalPages": 1, "totalElements": 0, "content": []}')

    env.api.settlements["Sale"] = []  # Sale satırı yok; yanıtı geçersiz kılıcı verir
    env.api.overrides["/settlements"] = reject_delivery_fee
    with caplog.at_level("WARNING", logger="netkar.sync"):
        outcome = await env.runner.run(env.seller.account_id, "backfill", sources=["settlements"])
    assert outcome.status == "completed"
    (source,) = outcome.sources
    assert source.status == "succeeded" and source.skipped == 6  # 6 pencerede 1 reddedilen istek
    row = env.conn.execute("SELECT status, skipped_count, error_class FROM sync_runs").fetchone()
    assert row == ("succeeded", 6, None)
    assert {r.request_type for r in caplog.records if r.getMessage() == "sync: istek tipi reddedildi"} == {  # type: ignore[attr-defined]
        "DeliveryFee"
    }
