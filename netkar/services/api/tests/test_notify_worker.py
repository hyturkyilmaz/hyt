"""Bildirim görevleri (ADR-0009 D5): procrastinate kaydı, zamanlama, uçtan uca iş ve yapılandırma varsayılanları.

Görevler AYRI `notify` kuyruğundadır (`make worker-notify`, eşzamanlılık 1). Dağıtıcı her dakika, özet kurucusu saat başı
dakika 13'te çalışır; ikisi de bekleyen tek iş olarak sıralanır (`queueing_lock`). Gerçek gönderim varsayılan KAPALIDIR.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import procrastinate
import psycopg
import pytest
from procrastinate import exceptions as procrastinate_exceptions
from procrastinate import testing

from app.core.config import Settings
from app.core.email import InMemoryOutbox
from app.services.notify import NotificationConfigError, NotificationDispatcher
from app.worker.runtime import WorkerRuntime
from app.worker.tasks import CRON_NOTIFY_DIGESTS, CRON_NOTIFY_DISPATCH, register_tasks
from tests.test_alert_evaluation import mark_synced
from tests.test_alert_schema import World, make_world
from tests.test_notify_dispatch import DIGEST_AT, NOW, event, seed, state, user_settings


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    """İki kiracı (A: owner, admin, viewer; B: owner); tüm kaynakların yedeklemesi tamam."""
    made = make_world(admin_conn)
    mark_synced(admin_conn, made.a)
    mark_synced(admin_conn, made.b)
    return made


@pytest.fixture
async def runtime(settings: Settings) -> AsyncIterator[WorkerRuntime]:
    rt = WorkerRuntime(settings, now=lambda: NOW)
    yield rt
    await rt.aclose()


def memory_app(rt: WorkerRuntime) -> tuple[procrastinate.App, testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    app = procrastinate.App(connector=connector)
    register_tasks(app, rt)
    app.periodic_registry.periodic_tasks.clear()  # periyodik işler açılışta kendiliğinden girer; testler açıkça ekler
    return app, connector


def jobs(connector: testing.InMemoryConnector, name: str) -> list[dict[str, Any]]:
    return [j for j in connector.jobs.values() if j["task_name"] == name]


def test_notify_tasks_are_registered_on_their_own_queue_with_their_schedules() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)
    for name in ("notify.dispatch", "notify.build_digests"):
        task = app.tasks[name]
        assert task.queue == "notify" and task.lock == "notify"
    assert app.tasks["notify.dispatch"].queueing_lock == "notify-dispatch"
    assert app.tasks["notify.build_digests"].queueing_lock == "notify-digests"
    crons = {name: task.cron for (name, _), task in app.periodic_registry.periodic_tasks.items()}
    assert crons["notify.dispatch"] == CRON_NOTIFY_DISPATCH == "* * * * *"
    assert crons["notify.build_digests"] == CRON_NOTIFY_DIGESTS == "13 * * * *"  # dakika 0/30 değil


async def test_a_second_dispatch_is_not_queued_while_one_is_pending(runtime: WorkerRuntime) -> None:
    app, connector = memory_app(runtime)
    async with app.open_async():
        await app.tasks["notify.dispatch"].defer_async(timestamp=1)
        with pytest.raises(procrastinate_exceptions.AlreadyEnqueued):
            await app.tasks["notify.dispatch"].defer_async(timestamp=2)
    assert len(jobs(connector, "notify.dispatch")) == 1


async def test_dispatch_job_runs_end_to_end_with_the_real_flag_off(
    runtime: WorkerRuntime,
    world: World,
    admin_conn: psycopg.Connection[Any],
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await app.tasks["notify.dispatch"].defer_async(timestamp=1)
        await app.run_worker_async(wait=False)
    (job,) = jobs(connector, "notify.dispatch")
    assert job["status"] == "succeeded"
    assert state(admin_conn, outbox_id)["status"] == "suppressed"  # bayrak kapalı: gerçek gönderim yok
    sender = runtime.notifier._dev_sender
    assert isinstance(sender, InMemoryOutbox) and len(sender.messages) == 1  # yerel arka uç
    assert runtime.notifier._sender is None  # gerçek gönderici hiç kurulmadı


async def test_digest_job_runs_end_to_end(
    settings: Settings,
    world: World,
    admin_conn: psycopg.Connection[Any],
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    event(admin_conn, a)
    # Worker GEÇ uyanmış (saat 15:00 İstanbul): özet saati, zamanlanmış tikin `timestamp`ından hesaplanır (O3).
    rt = WorkerRuntime(settings, now=lambda: NOW)
    try:
        app, connector = memory_app(rt)
        async with app.open_async():
            await app.tasks["notify.build_digests"].defer_async(timestamp=int(DIGEST_AT.timestamp()))
            await app.run_worker_async(wait=False)
        (job,) = jobs(connector, "notify.build_digests")
        assert job["status"] == "succeeded"
        found = admin_conn.execute(
            "SELECT status FROM notification_outbox WHERE kind = 'digest' AND tenant_id = %s", (a.tenant_id,)
        ).fetchall()
        assert found == [("pending",), ("pending",)]  # owner ve admin (üye alıcılar)
    finally:
        await rt.aclose()


async def test_runtime_builds_the_dispatcher_from_settings_and_resets_on_close(settings: Settings) -> None:
    rt = WorkerRuntime(settings)
    notifier = rt.notifier
    assert isinstance(notifier, NotificationDispatcher) and rt.notifier is notifier
    assert notifier._enabled is False and notifier._base == "https://app.test.invalid"
    assert notifier._sender is None and isinstance(notifier._dev_sender, InMemoryOutbox)  # canlı arka uç yok
    # Bayrak açık ama gerçek arka uç yok: kurucu reddeder (staging'de sahte `sent` olmaz).
    enabled = WorkerRuntime(settings.model_copy(update={"alert_notifications_enabled": True}))
    with pytest.raises(NotificationConfigError):
        enabled.notifier  # noqa: B018
    await rt.aclose()
    assert rt._notifier is None


def test_the_real_send_flag_is_off_by_default_and_read_from_the_environment(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert settings.alert_notifications_enabled is False
    assert Settings.model_fields["alert_notifications_enabled"].default is False
    monkeypatch.setenv("ALERT_NOTIFICATIONS_ENABLED", "true")
    fresh = Settings(
        database_url=settings.database_url,
        data_encryption_key=settings.data_encryption_key,
        environment="test",
    )
    assert fresh.alert_notifications_enabled is True
