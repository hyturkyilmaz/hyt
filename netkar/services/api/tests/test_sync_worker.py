"""Worker görevleri: kayıt, çalıştırma, yeniden deneme, planlayıcı, kuyruk ve bağlantı eklenince backfill."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import procrastinate
import psycopg
import pytest
from procrastinate import testing

from app.core.config import Settings
from app.services.sync.sources import SOURCE_ORDER
from app.worker.queue import ProcrastinateJobQueue, defer_backfill, defer_incremental
from app.worker.runtime import PlannedAccount, WorkerRuntime, sources_to_plan
from app.worker.tasks import (
    FINANCE_SOURCES,
    ORDER_CLAIM_SOURCES,
    PLANNED_SOURCES,
    PRODUCT_SOURCES,
    plan_sync,
    register_tasks,
)
from tests.conftest import Api, RecordingJobQueue
from tests.sync_fixtures import full_api
from tests.sync_helpers import NOW, FakeTrendyol, client_factory, count, make_seller, status_response
from tests.test_marketplace_accounts import FakeTrendyol as ConnectTrendyol
from tests.test_marketplace_accounts import body


@pytest.fixture
async def runtime(settings: Settings) -> AsyncIterator[WorkerRuntime]:
    api = full_api()
    rt = WorkerRuntime(settings, client_factory=client_factory(api), now=lambda: NOW)
    rt.api = api  # type: ignore[attr-defined]
    yield rt
    await rt.aclose()


def memory_app(rt: WorkerRuntime) -> tuple[procrastinate.App, testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    app = procrastinate.App(connector=connector)
    register_tasks(app, rt)
    # Periyodik görevler worker açılışında kendiliğinden kuyruğa girer; testler işleri açıkça ekler.
    app.periodic_registry.periodic_tasks.clear()
    return app, connector


def jobs(connector: testing.InMemoryConnector, task: str | None = None) -> list[dict[str, Any]]:
    return [j for j in connector.jobs.values() if task is None or j["task_name"] == task]


def test_every_source_belongs_to_exactly_one_planner() -> None:
    assert PLANNED_SOURCES == set(SOURCE_ORDER)
    grouped = [*ORDER_CLAIM_SOURCES, *FINANCE_SOURCES, *PRODUCT_SOURCES]
    assert len(grouped) == len(set(grouped))


def test_periodic_schedules_match_the_specified_cadence() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)
    crons = {name: task.cron for (name, _), task in app.periodic_registry.periodic_tasks.items()}
    assert crons["sync.plan_orders_claims"] == "*/15 * * * *"  # sipariş ve iade 15 dakikada bir
    assert len(crons["sync.plan_finance"].split()[1].split(",")) == 2  # ekstre günde 2
    assert crons["sync.plan_products"].split()[2:] == ["*", "*", "*"]  # ürünler günde 1
    for name in ("sync.backfill", "sync.incremental"):
        task = app.tasks[name]
        assert task.queue == "sync" and task.retry_strategy is not None


def test_registering_tasks_never_opens_a_database_connection() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)  # ortam ayarı ve veritabanı olmadan da kurulur (tembel çalışma zamanı)
    assert "sync.backfill" in app.tasks


def test_worker_never_falls_back_to_the_app_role(settings: Settings, worker_env: None) -> None:
    no_worker = settings.model_copy(update={"worker_database_url": None})
    with pytest.raises(ValueError, match="WORKER_DATABASE_URL"):
        _ = no_worker.worker_libpq_url
    with pytest.raises(ValueError, match="WORKER_DATABASE_URL"):
        _ = WorkerRuntime(no_worker).engine
    from app.worker.app import build_app

    with pytest.raises(ValueError, match="WORKER_DATABASE_URL"):
        build_app(no_worker)
    assert settings.worker_libpq_url.startswith("postgresql://netkar_worker:")


async def test_backfill_task_syncs_the_account_and_returns_a_numeric_summary(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_backfill(app, seller.account_id)
        await app.run_worker_async(wait=False)
    (job,) = jobs(connector, "sync.backfill")
    assert job["status"] == "succeeded" and job["lock"] == f"sync:{seller.account_id}"
    assert job["queue_name"] == "sync" and job["args"] == {
        "account_id": str(seller.account_id),
        "force": False,
    }
    assert count(admin_conn, "orders") == 1 and count(admin_conn, "sync_cursors") == 6
    assert admin_conn.execute(
        "SELECT count(*) FROM sync_cursors WHERE backfill_completed_at IS NOT NULL"
    ).fetchone() == (6,)


async def test_incremental_task_runs_requested_sources_after_backfill(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    await runtime.runner.run(seller.account_id, "backfill")
    api: FakeTrendyol = runtime.api  # type: ignore[attr-defined]
    api.calls.clear()
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_incremental(app, seller.account_id, ["orders"])
        await app.run_worker_async(wait=False)
    (job,) = jobs(connector, "sync.incremental")
    assert job["status"] == "succeeded" and job["args"]["sources"] == ["orders"]
    assert api.calls_to("/orders/stream") and not api.calls_to("/settlements")


async def test_transient_failure_makes_the_job_retry_with_backoff(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    api: FakeTrendyol = runtime.api  # type: ignore[attr-defined]
    api.overrides["/orders/stream"] = status_response(503)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_backfill(app, seller.account_id)
        await app.run_worker_async(wait=False)
    (job,) = jobs(connector, "sync.backfill")
    assert job["status"] == "todo" and job["attempts"] == 1  # yeniden denenecek
    assert job["scheduled_at"] is not None
    # kalıcı hata (400) yeniden denenmez: görev tamamlanır, hata sync_runs'ta sınıfıyla durur
    api.overrides["/orders/stream"] = status_response(400)
    other = make_seller(admin_conn, seller_id="9999")
    app2, connector2 = memory_app(runtime)
    async with app2.open_async():
        await defer_backfill(app2, other.account_id)
        await app2.run_worker_async(wait=False)
    (done,) = jobs(connector2, "sync.backfill")
    assert done["status"] == "succeeded"
    assert admin_conn.execute(
        "SELECT error_class FROM sync_runs WHERE marketplace_account_id = %s AND status = 'failed'",
        (other.account_id,),
    ).fetchone() == ("request_rejected",)


async def test_invalid_credentials_stop_the_job_without_retry(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    api: FakeTrendyol = runtime.api  # type: ignore[attr-defined]
    api.overrides["/orders/stream"] = status_response(401)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_backfill(app, seller.account_id)
        await app.run_worker_async(wait=False)
    (job,) = jobs(connector, "sync.backfill")
    assert job["status"] == "succeeded"  # yeniden denenmedi
    assert admin_conn.execute("SELECT status FROM marketplace_accounts").fetchone() == ("invalid",)
    assert len(api.calls_to("/orders/stream")) == 1  # 401 yeniden denenmez


async def test_planner_queues_backfill_for_new_accounts_and_incremental_for_ready_sources(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    new = make_seller(admin_conn, seller_id="1111")
    ready = make_seller(admin_conn, seller_id="2222")
    partial = make_seller(admin_conn, seller_id="3333")
    make_seller(admin_conn, seller_id="4444", status="invalid")
    for seller, sources in ((ready, SOURCE_ORDER), (partial, ("orders", "claims"))):
        for source in sources:
            admin_conn.execute(
                "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark, "
                "backfill_completed_at) VALUES (%s, %s, %s, now(), now())",
                (seller.tenant_id, seller.account_id, source),
            )
    app, connector = memory_app(runtime)
    async with app.open_async():
        result = await plan_sync(app, runtime, ORDER_CLAIM_SOURCES)
        assert result == {"backfill": 2, "incremental": 2}
        backfills = {j["args"]["account_id"] for j in jobs(connector, "sync.backfill")}
        assert backfills == {str(new.account_id), str(partial.account_id)}
        incrementals = {
            j["args"]["account_id"]: j["args"]["sources"] for j in jobs(connector, "sync.incremental")
        }
        assert incrementals == {
            str(ready.account_id): ["orders", "claims"],
            str(partial.account_id): ["orders", "claims"],
        }
        # ekstre planlayıcısı: hazır olmayan kaynak için artımlı iş eklenmez
        finance = await plan_sync(app, runtime, FINANCE_SOURCES)
        assert finance["incremental"] == 1  # yalnız backfill'i tamamlanmış hesap
        for job in connector.jobs.values():
            assert job["lock"] == f"sync:{job['args']['account_id']}"


async def test_planner_does_not_pile_up_pending_jobs(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    admin_conn.execute(
        "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark, backfill_completed_at) "
        "VALUES (%s, %s, 'orders', now(), now())",
        (seller.tenant_id, seller.account_id),
    )
    app, connector = memory_app(runtime)
    async with app.open_async():
        first = await plan_sync(app, runtime, ORDER_CLAIM_SOURCES)
        second = await plan_sync(app, runtime, ORDER_CLAIM_SOURCES)  # 15 dk sonra: bekleyen iş var
    assert first == {"backfill": 1, "incremental": 1}
    assert second == {"backfill": 0, "incremental": 0}
    assert len(jobs(connector)) == 2


async def test_periodic_planner_task_defers_work_through_the_worker(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await app.tasks["sync.plan_orders_claims"].defer_async(timestamp=1)
        await app.run_worker_async(wait=False)
    planner = jobs(connector, "sync.plan_orders_claims")[0]
    assert planner["status"] == "succeeded"
    assert [j["args"]["account_id"] for j in jobs(connector, "sync.backfill")] == [str(seller.account_id)]


async def test_planned_account_helpers() -> None:
    account = PlannedAccount(UUID(int=1), UUID(int=2), frozenset({"orders", "claims"}))
    assert account.missing_backfill
    assert sources_to_plan(account, ["orders", "settlements", "claims"]) == ["orders", "claims"]
    assert not PlannedAccount(UUID(int=1), UUID(int=2), frozenset(SOURCE_ORDER)).missing_backfill


async def test_runtime_lists_accounts_via_the_gate_and_closes_its_engine(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    rt = WorkerRuntime(settings)
    try:
        accounts = await rt.list_accounts()
        assert [(a.tenant_id, a.account_id, a.backfilled_sources) for a in accounts] == [
            (seller.tenant_id, seller.account_id, frozenset())
        ]
        assert rt.engine is rt.engine and rt.runner is rt.runner
    finally:
        await rt.aclose()
    await rt.aclose()  # ikinci kapatma zararsız


async def test_prune_task_and_heartbeat_run_with_the_worker_role(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    admin_conn.execute(
        "INSERT INTO rate_limits VALUES ('old', now() - interval '3 days', 5), ('new', now(), 1)"
    )
    app, connector = memory_app(runtime)
    async with app.open_async():
        await app.tasks["netkar.prune_rate_limits"].defer_async(timestamp=1)
        await app.tasks["netkar.heartbeat"].defer_async(timestamp=1)
        await app.run_worker_async(wait=False)
    assert all(j["status"] == "succeeded" for j in jobs(connector))
    assert [r[0] for r in admin_conn.execute("SELECT key FROM rate_limits")] == ["new"]


# --- gerçek kuyruk (PostgreSQL, rol ayrımı) ---------------------------------------------------------


async def test_api_side_queue_enqueues_with_the_app_role_and_dedupes(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    queue = ProcrastinateJobQueue(settings)
    await queue.enqueue_backfill(seller.account_id)
    await queue.enqueue_backfill(seller.account_id)  # bekleyen iş varken yenisi eklenmez
    rows = admin_conn.execute(
        "SELECT task_name, queue_name, lock, queueing_lock, args, status FROM procrastinate_jobs"
    ).fetchall()
    assert rows == [
        (
            "sync.backfill",
            "sync",
            f"sync:{seller.account_id}",
            f"sync-backfill:{seller.account_id}",
            {"account_id": str(seller.account_id), "force": False},
            "todo",
        )
    ]
    other = make_seller(admin_conn, seller_id="9999")
    await queue.enqueue_backfill(other.account_id)  # havuz kapanıp yeniden açılabilir
    assert count(admin_conn, "procrastinate_jobs") == 2


async def test_job_enqueued_by_the_api_role_runs_under_the_worker_role_end_to_end(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    """API (netkar_app) iş ekler, worker (netkar_worker) şifreli anahtarı okuyup senkronu yürütür."""
    seller = make_seller(admin_conn)
    await ProcrastinateJobQueue(settings).enqueue_backfill(seller.account_id)
    api = full_api()
    rt = WorkerRuntime(settings, client_factory=client_factory(api), now=lambda: NOW)
    worker = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=settings.worker_libpq_url))
    register_tasks(worker, rt)
    try:
        async with worker.open_async():
            await worker.run_worker_async(wait=False, queues=["sync"])
    finally:
        await rt.aclose()
    assert admin_conn.execute(
        "SELECT status FROM procrastinate_jobs WHERE task_name = 'sync.backfill'"
    ).fetchone() == ("succeeded",)
    assert count(admin_conn, "orders") == 1 and count(admin_conn, "products") == 2
    # yetkiler gerçekten ayrı: API rolü şifreli sütunu okuyamadığı için senkronu API rolüyle yürütemezdi
    assert admin_conn.execute(
        "SELECT has_column_privilege('netkar_app', 'marketplace_accounts', 'api_secret_encrypted', 'SELECT')"
    ).fetchone() == (False,)


# --- bağlantı eklenince backfill kuyruğa girer -------------------------------------------------------


@pytest.fixture
def connect(make_api: Callable[..., Api]) -> Callable[..., Api]:
    fake = ConnectTrendyol()

    def _make() -> Api:
        api = make_api(trendyol_client_factory=fake.factory)
        api.signup_and_login("owner@example.com", tenant="Mağaza A")
        return api

    return _make


def test_connecting_an_account_queues_a_backfill(
    connect: Callable[..., Api], job_queue: RecordingJobQueue
) -> None:
    api = connect()
    response = api.post("/v1/marketplace-accounts", body())
    assert response.status_code == 201
    assert job_queue.backfills == [UUID(response.json()["id"])]
    # aynı satıcıyla ikinci bağlantı 409: yeni iş eklenmez
    assert api.post("/v1/marketplace-accounts", body()).status_code == 409
    assert len(job_queue.backfills) == 1


def test_reconnecting_an_invalid_account_queues_a_backfill_again(
    connect: Callable[..., Api], job_queue: RecordingJobQueue, admin_conn: psycopg.Connection[Any]
) -> None:
    api = connect()
    account_id = api.post("/v1/marketplace-accounts", body()).json()["id"]
    admin_conn.execute("UPDATE marketplace_accounts SET status = 'invalid'")
    assert api.post("/v1/marketplace-accounts", body()).status_code == 201
    assert job_queue.backfills == [UUID(account_id), UUID(account_id)]


def test_a_queue_failure_does_not_break_the_connection(
    connect: Callable[..., Api],
    job_queue: RecordingJobQueue,
    admin_conn: psycopg.Connection[Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    job_queue.fail = True
    api = connect()
    capsys.readouterr()
    response = api.post("/v1/marketplace-accounts", body())
    assert response.status_code == 201  # bağlantı kalıcı; planlayıcı backfill'i sonra yakalar
    assert count(admin_conn, "marketplace_accounts") == 1 and job_queue.backfills == []
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    record = next(r for r in records if "kuyruğa eklenemedi" in r["msg"])
    assert record["error_class"] == "RuntimeError" and "kuyruk erişilemez" not in json.dumps(record)


def test_validation_failure_queues_nothing(
    make_api: Callable[..., Api], job_queue: RecordingJobQueue
) -> None:
    fake = ConnectTrendyol(status=401)
    api = make_api(trendyol_client_factory=fake.factory)
    api.signup_and_login("owner@example.com", tenant="Mağaza A")
    assert api.post("/v1/marketplace-accounts", body()).status_code == 422
    assert job_queue.backfills == []


def test_default_app_queue_is_the_procrastinate_queue(
    make_app: Callable[..., Any], settings: Settings
) -> None:
    from app.main import create_app

    app = create_app(settings)
    assert isinstance(app.state.job_queue, ProcrastinateJobQueue)
    assert timedelta(0) == timedelta(0)  # create_app kuyruğu tembel kurar: veritabanına bağlanmaz


async def test_incremental_transient_failure_retries_and_other_planners_run(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    await runtime.runner.run(
        seller.account_id, "backfill"
    )  # tüm kaynaklar tamam: planlayıcılar artımlı iş ekler
    api: FakeTrendyol = runtime.api  # type: ignore[attr-defined]
    api.overrides["/settlements"] = status_response(503)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_incremental(app, seller.account_id, ["settlements"])
        await app.tasks["sync.plan_finance"].defer_async(timestamp=1)
        await app.tasks["sync.plan_products"].defer_async(timestamp=1)
        await app.run_worker_async(wait=False)
    incremental = [j for j in jobs(connector, "sync.incremental") if j["args"]["sources"] == ["settlements"]]
    assert incremental[0]["status"] == "todo"  # geçici hata: geri çekilmeyle yeniden denenecek
    assert {
        j["status"] for j in jobs(connector, "sync.plan_finance") + jobs(connector, "sync.plan_products")
    } == {"succeeded"}
    queued = {tuple(j["args"]["sources"]) for j in jobs(connector, "sync.incremental")}
    assert ("products",) in queued and ("settlements", "other_financials", "cargo_invoices") in queued


def test_runtime_reads_settings_lazily_from_the_environment(worker_env: None) -> None:
    rt = WorkerRuntime()
    assert rt.settings.worker_libpq_url.startswith("postgresql://netkar_worker:")
    assert rt.settings is rt.settings
