"""Worker iskeleti: görev kaydı ve heartbeat çalıştırma."""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import procrastinate
import psycopg
import pytest
from procrastinate import testing

from app.core.config import Settings, get_settings
from app.worker.tasks import heartbeat, register_tasks


async def test_heartbeat_task_runs() -> None:
    assert await heartbeat() == "ok"


async def test_tasks_are_registered_and_heartbeat_can_be_deferred() -> None:
    connector = testing.InMemoryConnector()
    app = procrastinate.App(connector=connector)
    register_tasks(app)
    assert {"netkar.heartbeat", "netkar.prune_rate_limits"} <= set(app.tasks)

    async with app.open_async():
        await app.tasks["netkar.heartbeat"].defer_async(timestamp=1)
        assert len(connector.jobs) == 1
        await app.run_worker_async(wait=False)
        job = next(iter(connector.jobs.values()))
        assert job["status"] == "succeeded"


@pytest.fixture
def worker_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """app.worker.app içe aktarılırken ortamdan ayar okunur."""
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", settings.data_encryption_key.get_secret_value())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_build_app_uses_settings_connector(settings: Settings, worker_env: None) -> None:
    from app.worker.app import build_app

    worker = build_app(settings)
    assert isinstance(worker.connector, procrastinate.PsycopgConnector)
    assert "netkar.heartbeat" in worker.tasks


def test_module_level_app_is_built_from_environment(worker_env: None) -> None:
    module = importlib.reload(importlib.import_module("app.worker.app"))
    assert isinstance(module.app, procrastinate.App)


async def test_worker_runs_job_on_real_database_with_app_role(
    settings: Settings, admin_conn: psycopg.Connection, worker_env: None
) -> None:
    """Gerçek PostgreSQL: procrastinate şeması ve netkar_app yetkileri iş çalıştırmaya yeter.

    Periyodik görevler (ör. saatlik prune) worker başlarken saate bağlı olarak kuyruğa
    girebilir; bu yüzden ayarlar ortamdan da okunabilir olmalı (worker_env) ve prune
    görevi saatten bağımsız, açıkça çalıştırılıp doğrulanır.
    """
    worker = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=settings.libpq_url))
    register_tasks(worker)
    try:
        async with worker.open_async():
            await worker.tasks["netkar.heartbeat"].defer_async(timestamp=1)
            await worker.tasks["netkar.prune_rate_limits"].defer_async(timestamp=1)
            await worker.run_worker_async(wait=False)
        rows = admin_conn.execute("SELECT task_name, status FROM procrastinate_jobs").fetchall()
        assert ("netkar.heartbeat", "succeeded") in rows
        assert ("netkar.prune_rate_limits", "succeeded") in rows
        assert all(status != "failed" for _, status in rows)
    finally:
        admin_conn.execute("TRUNCATE procrastinate_jobs CASCADE")
