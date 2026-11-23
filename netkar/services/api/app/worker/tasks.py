"""Görev tanımları. Görevler `register_tasks` ile verilen App'e bağlanır (test edilebilirlik).

Senkron görevleri (ADR-0005 §3-§4):

  - `sync.backfill(account_id, force=False)`: siparişler (son ~3 ay, stream), iadeler, ürünler,
    ekstre (15 günlük pencereler) ve kargo faturaları; ilerleme `sync_runs`/`sync_cursors`'a yazılır.
  - `sync.incremental(account_id, sources=None)`: imleçten (geniş örtüşmeyle) devam eder.
  - Periyodik planlayıcılar: sipariş ve iade 15 dakikada bir, ekstre günde 2, ürünler günde 1.
    Backfill'i eksik hesaba backfill, tamamlanmış kaynaklara artımlı iş eklenir.

Uyarı görevleri (ADR-0009 D4, `alerts` kuyruğu):

  - `alerts.evaluate(account_id)`: hesap başına idempotent değerlendirme (`app.services.alert_evaluation`).
    Senkron görevi yeni kayıt yazınca, API kâr ayarı ya da maliyet yazımından sonra ve günlük planlayıcıdan
    eklenir.
  - `alerts.plan_daily`: günde bir, etkin her hesap için değerlendirme ekler (worker içi periyodik iş).
  - `alerts.recover_stalled`: 10 dakikada bir, worker'ı ölmüş takılı değerlendirme işlerini kuyruğa alır.
  Senkron sonrası değerlendirme 10 dakika ertelenir ve hesap başına tek bekleyen iş olur; kapsam `fast`
  (7 günlük kurallar) ya da finans yazımında `all`. Geçici veritabanı hatası en çok 3 kez, üstel beklemeyle
  yeniden denenir.

Bildirim görevleri (ADR-0009 D5, AYRI `notify` kuyruğu ve ayrı süreç, eşzamanlılık 1; `make worker-notify`):

  - `notify.dispatch`: her dakika; zamanı gelen outbox satırlarını işler (`app.services.notify`). CPU ağır
    uyarı değerlendirmeleri
    (`alerts` kuyruğu) dağıtımı geciktirmesin diye ayrı süreçtedir. Gerçek
    gönderim `ALERT_NOTIFICATIONS_ENABLED` ile KAPALIDIR: kapalıyken satırlar `suppressed` olur, ileti yalnız
    yerel arka uca (`file`/`memory`) yazılır. Bekleyen tek iş vardır (`queueing_lock`): iş gecikirse
    dakikalık tikler birikmez.
  - `notify.build_digests`: saat başı (dakika 13); İstanbul saatine göre özet saati gelen kullanıcılar için
    özet satırı. Saat, periyodik görevin ZAMANLANMIŞ tik zamanından (`timestamp`) hesaplanır: worker geç
    çalışsa bile o saatin kullanıcıları kaybolmaz.

Geçici hatada (429, 5xx, ağ) görev `SyncTransientError` ile yeniden denenir (üstel geri çekilme);
kalıcı hata `sync_runs`'a sınıfıyla yazılır, iş başarısız sayılmaz (yeniden denemek aynı sonucu verir).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import procrastinate
from procrastinate import RetryStrategy
from sqlalchemy import text

from app.services.alert_evaluation import SCOPE_ALL, SCOPE_FAST, AlertEvaluationTransient
from app.services.sync.errors import SyncTransientError
from app.services.sync.runner import SyncOutcome
from app.worker.queue import defer_alert_evaluation, defer_backfill, defer_incremental
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
# Günlük uyarı değerlendirmesi: 06:47 İstanbul (03:47 UTC). Pencere günü kaydığı için veri değişmese de
# gerekir.
CRON_ALERTS_DAILY = "47 3 * * *"
# Senkron sonrası erteleme için "başarılı" sayılan durumlar (invalid, credentials_error, inactive, locked
# değil).
ALERT_TRIGGER_STATUSES = frozenset(("completed", "partial"))
# Senkron sonrası erteleme penceresi: aynı hesap için pencerede tek değerlendirme (`queueing_lock`).
ALERT_SYNC_DELAY_MINUTES = 10
# Bildirim dağıtıcısı her dakika; günlük özet kurucusu saat başı, dakika 13 (ADR-0009 §7.1, §7.3).
# Bildirim görevleri AYRI kuyruk ve süreçte çalışır (uyarı değerlendirmesi dağıtımı geciktirmesin).
NOTIFY_QUEUE = "notify"
CRON_NOTIFY_DISPATCH = "* * * * *"
CRON_NOTIFY_DIGESTS = "13 * * * *"
# Takılmış (worker'ı ölmüş) değerlendirme işlerini kurtaran periyodik iş; dakika 0/30 değil.
CRON_ALERTS_RECOVER = "5-55/10 * * * *"
# Yalnız geçici veritabanı hataları yeniden denenir (en çok 3 deneme, üstel bekleme).
ALERT_RETRY = RetryStrategy(max_attempts=3, exponential_wait=4, retry_exceptions=[AlertEvaluationTransient])


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


async def plan_alert_evaluations(app: procrastinate.App, runtime: WorkerRuntime) -> dict[str, int]:
    """Etkin her hesap için günlük uyarı değerlendirmesi ekler (bekleyen iş varsa eklenmez)."""
    deferred = 0
    for account in await runtime.list_accounts():
        if await defer_alert_evaluation(app, account.account_id):
            deferred += 1
    return {"deferred": deferred}


async def defer_alerts_after_sync(app: procrastinate.App, outcome: SyncOutcome) -> bool:
    """Senkron yeni kayıt yazdıysa ya da bir kaynak hatadan düzeldiyse ERTELENMİŞ uyarı değerlendirmesi ekler.

    En iyi çaba: hata senkronu bozmaz. Durum `invalid`, `credentials_error`, `inactive` ya da `locked` ise ya
    da hiçbir kaynakta `upserted > 0` ve hiçbir kaynakta "düzelme" (önceki çalışma `failed`, bu tur
    `succeeded`) yoksa eklenmez. Düzelme veri sürümünü değiştirmez ama bildirim bastırma girdisini
    (`failed_sources`) değiştirir ve değerlendirme anahtarı bunu içerir: ertelenmezse bastırılmış bildirim
    ertesi güne kadar gecikirdi.
    Kapsam: finans kaynağı (ekstre, diğer finansal, kargo faturası) yazdıysa ya da HERHANGİ bir
    kaynak düzeldiyse `all` (92 günlük kesinti kuralı dahil); yalnız sipariş, iade ya da ürün yazdıysa
    `fast` (7 günlük kurallar). Düzelmede `all` seçilir: düzelen kaynak (ör. sipariş) kesinti kuralının
    da bastırma kaynağı olabilir (`RULE_SOURCES`); `fast` kapsam o kuralı çalıştırmaz ve bildirimi
    günlük işe kadar geciktirirdi. Düzelme seyrek olduğundan maliyet önemsizdir.
    """
    recovered = {s.source for s in outcome.sources if s.recovered and s.status == "succeeded"}
    written = {s.source for s in outcome.sources if s.upserted > 0} | recovered
    if outcome.status not in ALERT_TRIGGER_STATUSES or not written:
        return False
    scope = SCOPE_ALL if (written & set(FINANCE_SOURCES)) or recovered else SCOPE_FAST
    try:
        return await defer_alert_evaluation(
            app, outcome.account_id, scope=scope, delay_minutes=ALERT_SYNC_DELAY_MINUTES
        )
    except Exception as exc:
        logger.warning(
            "uyarı değerlendirmesi ertelenemedi",
            extra={"account_id": str(outcome.account_id), "error_class": type(exc).__name__},
        )
        return False


async def recover_stalled_alerts(app: procrastinate.App) -> int:
    """Worker'ı ölmüş (heartbeat'i kesilmiş) `alerts.evaluate` işlerini yeniden kuyruğa alır; sayıyı verir.

    Yazma aşaması hesap başına danışma kilidiyle ve tek işlemle yapıldığı için kurtarılan işin eski kopyasıyla
    çakışması güvenlidir.
    """
    recovered = 0
    for job in await app.job_manager.get_stalled_jobs(queue="alerts", task_name="alerts.evaluate"):
        await app.job_manager.retry_job(job)
        recovered += 1
    return recovered


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
        await defer_alerts_after_sync(app, outcome)
        if outcome.retryable:
            raise SyncTransientError("geçici hata: yeniden denenecek")
        return outcome.summary()

    @app.task(name="sync.incremental", queue="sync", retry=SYNC_RETRY)
    async def _incremental(account_id: str, sources: list[str] | None = None) -> dict[str, object]:
        outcome = await rt.runner.run(UUID(account_id), "incremental", sources=sources)
        await defer_alerts_after_sync(app, outcome)
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

    @app.task(name="alerts.evaluate", queue="alerts", retry=ALERT_RETRY)
    async def _evaluate_alerts(account_id: str, scope: str = SCOPE_ALL) -> dict[str, object]:
        outcome = await rt.alert_evaluator.evaluate(UUID(account_id), scope)
        return outcome.summary()

    @app.periodic(cron=CRON_ALERTS_DAILY)
    @app.task(name="alerts.plan_daily", queue="alerts")
    async def _plan_alerts_daily(timestamp: int) -> dict[str, int]:
        return await plan_alert_evaluations(app, rt)

    @app.periodic(cron=CRON_ALERTS_RECOVER)
    @app.task(name="alerts.recover_stalled", queue="alerts")
    async def _recover_stalled_alerts(timestamp: int) -> int:
        return await recover_stalled_alerts(app)

    @app.periodic(cron=CRON_NOTIFY_DISPATCH)
    @app.task(name="notify.dispatch", queue=NOTIFY_QUEUE, queueing_lock="notify-dispatch", lock="notify")
    async def _notify_dispatch(timestamp: int) -> dict[str, object]:
        return (await rt.notifier.dispatch()).summary()

    @app.periodic(cron=CRON_NOTIFY_DIGESTS)
    @app.task(name="notify.build_digests", queue=NOTIFY_QUEUE, queueing_lock="notify-digests", lock="notify")
    async def _notify_build_digests(timestamp: int) -> dict[str, object]:
        return (await rt.notifier.build_digests(at=datetime.fromtimestamp(timestamp, UTC))).summary()
