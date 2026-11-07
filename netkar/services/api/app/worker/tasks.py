"""Görev tanımları. Görevler `register_tasks` ile verilen App'e bağlanır (test edilebilirlik).

Senkron görevleri (ADR-0005 §3-§4):

  - `sync.backfill(account_id, force=False)`: siparişler (son ~3 ay, stream), iadeler, ürünler,
    ekstre (15 günlük pencereler) ve kargo faturaları; ilerleme `sync_runs`/`sync_cursors`'a yazılır.
  - `sync.incremental(account_id, sources=None)`: imleçten (geniş örtüşmeyle) devam eder.
  - Periyodik planlayıcılar: sipariş ve iade 15 dakikada bir, ekstre günde 2, ürünler günde 1.
    Backfill'i eksik hesaba backfill, tamamlanmış kaynaklara artımlı iş eklenir.

Geçici hatada (429, 5xx, ağ) görev `SyncTransientError` ile yeniden denenir (üstel geri çekilme);
kalıcı hata `sync_runs`'a sınıfıyla yazılır, iş başarısız sayılmaz (yeniden denemek aynı sonucu verir).
"""

from __future__ import annotations

import logging
from uuid import UUID

import procrastinate
from procrastinate import RetryStrategy
from sqlalchemy import text

from app.services.sync.errors import SyncTransientError
from app.worker.queue import defer_backfill, defer_incremental
from app.worker.runtime import WorkerRuntime, sources_to_plan

logger = logging.getLogger("netkar.worker")

# Sabit pencere sayaçlarının saklama süresi (saat). Eski pencereler artık anlamsızdır.
RATE_LIMIT_RETENTION_HOURS = 24

# Üstel bekleme: 4, 16, 64, 256, 1024 sn; yalnız geçici hata yeniden denenir.
SYNC_RETRY = RetryStrategy(max_attempts=6, exponential_wait=4, retry_exceptions=[SyncTransientError])

ORDER_CLAIM_SOURCES = ("orders", "claims")
FINANCE_SOURCES = ("settlements", "other_financials", "cargo_invoices")
PRODUCT_SOURCES = ("products",)
# Her kaynak planlayıcılardan birinde yer almalıdır (tests/test_sync_worker.py denetler).
PLANNED_SOURCES = frozenset((*ORDER_CLAIM_SOURCES, *FINANCE_SOURCES, *PRODUCT_SOURCES))

# Planlayıcı zamanlamaları (UTC). Dakika 0/30'dan kaçınılır: yük dağılsın.
CRON_ORDERS_CLAIMS = "*/15 * * * *"
CRON_FINANCE = "7 3,15 * * *"
CRON_PRODUCTS = "23 1 * * *"


async def heartbeat() -> str:
    """Worker'ın yaşadığını gösteren örnek periyodik görev."""
    logger.info("worker heartbeat")
    return "ok"


async def prune_rate_limits(runtime: WorkerRuntime) -> int:
    """Süresi geçmiş rate limit pencerelerini siler (operasyonel sayaç; kullanıcı verisi değil)."""
    async with runtime.engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM rate_limits WHERE window_start < now() - make_interval(hours => :h)"),
            {"h": RATE_LIMIT_RETENTION_HOURS},
        )
    return int(result.rowcount)


async def plan_sync(
    app: procrastinate.App, runtime: WorkerRuntime, sources: tuple[str, ...]
) -> dict[str, int]:
    """Etkin hesaplar için iş ekler: eksik backfill varsa backfill, tamamlanmış kaynaklara artımlı."""
    backfills = 0
    incrementals = 0
    for account in await runtime.list_accounts():
        if account.missing_backfill and await defer_backfill(app, account.account_id):
            backfills += 1
        ready = sources_to_plan(account, sources)
        if ready and await defer_incremental(app, account.account_id, ready):
            incrementals += 1
    return {"backfill": backfills, "incremental": incrementals}


def register_tasks(app: procrastinate.App, runtime: WorkerRuntime | None = None) -> None:
    """Görevleri ve periyodik zamanlamaları App'e kaydeder.

    `runtime` verilmezse tembel kurulan varsayılan çalışma zamanı kullanılır (ilk görevde ortamdan
    ayar okunur ve `netkar_worker` rolüyle bağlanılır). Kayıt sırasında veritabanına bağlanılmaz.
    """
    rt = runtime or WorkerRuntime()

    @app.periodic(cron="* * * * *")
    @app.task(name="netkar.heartbeat")
    async def _heartbeat(timestamp: int) -> str:
        return await heartbeat()

    @app.periodic(cron="17 * * * *")
    @app.task(name="netkar.prune_rate_limits")
    async def _prune(timestamp: int) -> int:
        return await prune_rate_limits(rt)

    @app.task(name="sync.backfill", queue="sync", retry=SYNC_RETRY)
    async def _backfill(account_id: str, force: bool = False) -> dict[str, object]:
        outcome = await rt.runner.run(UUID(account_id), "backfill", force=force)
        if outcome.retryable:
            raise SyncTransientError("geçici hata: yeniden denenecek")
        return outcome.summary()

    @app.task(name="sync.incremental", queue="sync", retry=SYNC_RETRY)
    async def _incremental(account_id: str, sources: list[str] | None = None) -> dict[str, object]:
        outcome = await rt.runner.run(UUID(account_id), "incremental", sources=sources)
        if outcome.retryable:
            raise SyncTransientError("geçici hata: yeniden denenecek")
        return outcome.summary()

    @app.periodic(cron=CRON_ORDERS_CLAIMS)
    @app.task(name="sync.plan_orders_claims", queue="sync")
    async def _plan_orders_claims(timestamp: int) -> dict[str, int]:
        return await plan_sync(app, rt, ORDER_CLAIM_SOURCES)

    @app.periodic(cron=CRON_FINANCE)
    @app.task(name="sync.plan_finance", queue="sync")
    async def _plan_finance(timestamp: int) -> dict[str, int]:
        return await plan_sync(app, rt, FINANCE_SOURCES)

    @app.periodic(cron=CRON_PRODUCTS)
    @app.task(name="sync.plan_products", queue="sync")
    async def _plan_products(timestamp: int) -> dict[str, int]:
        return await plan_sync(app, rt, PRODUCT_SOURCES)
