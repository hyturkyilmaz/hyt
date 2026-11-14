"""Senkron kenar durumları: hata sınıflandırma tablosu, kilit serbest bırakma, yarışlar, boş pencere."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import httpx
import psycopg
import pytest

from app.integrations.trendyol import (
    TrendyolAuthError,
    TrendyolConfigError,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolRequestError,
    TrendyolServerError,
    TrendyolValidationError,
    TrendyolWaitBudgetError,
    TrendyolWindowTooLargeError,
)
from app.services.sync.errors import ErrorInfo, classify_error
from app.services.sync.runner import SyncRunner, account_lock
from tests.sync_fixtures import Env, full_api
from tests.sync_helpers import NOW, client_factory, count, envelope_for_tests, make_seller


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TrendyolAuthError("x", status=401), ErrorInfo("unauthorized", auth=True)),
        (TrendyolForbiddenError("x", status=403), ErrorInfo("forbidden", auth=True)),
        (TrendyolRateLimitedError("x"), ErrorInfo("rate_limited", transient=True)),
        (TrendyolWaitBudgetError("x"), ErrorInfo("rate_limited", transient=True)),
        (TrendyolServerError("x"), ErrorInfo("server_error", transient=True)),
        (TrendyolNetworkError("x"), ErrorInfo("network", transient=True)),
        (TrendyolWindowTooLargeError(20_000), ErrorInfo("window_too_large")),
        (TrendyolProtocolError("x"), ErrorInfo("protocol")),
        (TrendyolRequestError("x"), ErrorInfo("request_rejected")),
        (TrendyolValidationError("x"), ErrorInfo("validation")),
        (TrendyolConfigError("x"), ErrorInfo("trendyol")),
        (TrendyolError("x"), ErrorInfo("trendyol")),
        (RuntimeError("beklenmeyen"), ErrorInfo("internal")),
        (ValueError("x"), ErrorInfo("internal")),
    ],
)
def test_error_classification_table(exc: BaseException, expected: ErrorInfo) -> None:
    assert classify_error(exc) == expected


async def test_lock_connection_is_discarded_when_unlock_fails(
    worker_engine: Any,
    admin_conn: psycopg.Connection[Any],
) -> None:
    seller = make_seller(admin_conn)
    async with account_lock(worker_engine, seller.account_id) as acquired:
        assert acquired
        # kilidi tutan oturum öldürülür (ağ kopması): bırakma başarısız olur, bağlantı havuza dönmez
        admin_conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype = 'advisory' AND granted "
            "AND pid <> pg_backend_pid()"
        )
        await asyncio.sleep(0.2)
    async with account_lock(worker_engine, seller.account_id) as again:
        assert again  # kilit oturumla birlikte düştü; yeni oturum alabilir


async def test_account_revoked_between_lookup_and_credential_read_is_reported(
    make_env: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env: Env = make_env()
    env.conn.execute("UPDATE marketplace_accounts SET status = 'invalid'")
    original = env.runner._resolve

    async def stale(account_id: Any) -> Any:  # arama anında hesap hâlâ etkindi (yarış)
        return env.seller.tenant_id

    monkeypatch.setattr(env.runner, "_resolve", stale)
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "credentials_error" and env.api.calls == []
    assert original is not None


async def test_auth_failure_after_the_account_was_already_invalidated_writes_no_second_audit(
    make_env: Any,
) -> None:
    env: Env = make_env()
    env.api.overrides["/orders/stream"] = lambda r: httpx.Response(401, content=b"{}")

    async def invalidate_first(request: httpx.Request) -> None:
        env.conn.execute("UPDATE marketplace_accounts SET status = 'invalid'")  # başka süreç önce davrandı

    env.api.gate = invalidate_first
    outcome = await env.runner.run(env.seller.account_id, "backfill")
    assert outcome.status == "invalid"
    assert count(env.conn, "audit_log", "action = 'marketplace_account.sync_invalidated'") == 0


async def test_incremental_with_a_cursor_in_the_future_has_nothing_to_fetch(
    make_env: Any,
) -> None:
    env: Env = make_env()
    await env.runner.run(env.seller.account_id, "backfill", sources=["orders"])
    env.conn.execute("UPDATE sync_cursors SET watermark = %s", (NOW + timedelta(days=30),))
    env.api.calls.clear()
    outcome = await env.runner.run(env.seller.account_id, "incremental", sources=["orders"])
    assert outcome.status == "completed" and env.api.calls == []
    run = env.conn.execute(
        "SELECT status, windows_total, windows_done FROM sync_runs WHERE kind = 'incremental'"
    ).fetchone()
    assert run == ("succeeded", 0, 0)


async def test_runner_defaults_to_the_real_clock(
    worker_engine: Any,
    admin_conn: psycopg.Connection[Any],
) -> None:
    seller = make_seller(admin_conn)
    runner = SyncRunner(worker_engine, client_factory(full_api()), envelope_for_tests())
    outcome = await runner.run(seller.account_id, "backfill", sources=["products"])  # tarihsiz kaynak
    assert outcome.status == "completed" and count(admin_conn, "products") == 2
    stamp = admin_conn.execute("SELECT backfill_completed_at FROM sync_cursors").fetchone()
    assert stamp is not None and abs((stamp[0] - NOW).days) > 0  # gerçek saat, test saati değil
