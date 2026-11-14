"""İş kuyruğuna ekleme: bağlantı eklenince backfill, planlayıcıdan artımlı çekim.

Aynı hesabın işleri iki katmanla çakışmaz: (1) procrastinate `lock` (aynı kilitli işler sırayla
çalışır), (2) yürütücüdeki PostgreSQL danışma kilidi. `queueing_lock` bekleyen yinelenen işi
engeller (planlayıcı 15 dakikada bir çalışsa da kuyrukta tek iş bekler).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

import procrastinate
from procrastinate import exceptions as procrastinate_exceptions

from app.core.config import Settings

logger = logging.getLogger("netkar.worker")

BACKFILL_TASK = "sync.backfill"
INCREMENTAL_TASK = "sync.incremental"


def account_lock_name(account_id: UUID | str) -> str:
    """Aynı hesabın senkron işlerini sıraya sokan procrastinate kilit adı."""
    return f"sync:{account_id}"


async def defer_backfill(app: procrastinate.App, account_id: UUID | str, *, force: bool = False) -> bool:
    """Backfill işini kuyruğa ekler. Aynı hesap için bekleyen iş varsa eklemez (False döner)."""
    task = app.tasks[BACKFILL_TASK].configure(
        lock=account_lock_name(account_id), queueing_lock=f"sync-backfill:{account_id}"
    )
    try:
        await task.defer_async(account_id=str(account_id), force=force)
    except procrastinate_exceptions.AlreadyEnqueued:
        return False
    return True


async def defer_incremental(
    app: procrastinate.App, account_id: UUID | str, sources: Sequence[str] | None = None
) -> bool:
    """Artımlı çekimi kuyruğa ekler (kaynak kümesi başına bir bekleyen iş)."""
    suffix = "+".join(sources) if sources else "all"
    task = app.tasks[INCREMENTAL_TASK].configure(
        lock=account_lock_name(account_id), queueing_lock=f"sync-incr:{account_id}:{suffix}"
    )
    try:
        await task.defer_async(account_id=str(account_id), sources=list(sources) if sources else None)
    except procrastinate_exceptions.AlreadyEnqueued:
        return False
    return True


class JobQueue(Protocol):
    """API tarafının iş ekleme arayüzü (testlerde sahte uygulama verilir)."""

    async def enqueue_backfill(self, account_id: UUID) -> None: ...


class ProcrastinateJobQueue:
    """Gerçek kuyruk: `netkar_app` rolüyle `procrastinate_jobs` tablosuna iş ekler.

    İş başına bağlantı havuzu açılır ve kapanır; bağlantı ekleme nadir ve oran sınırlıdır, bu yüzden
    API sürecinde kalıcı havuz tutulmaz.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app: procrastinate.App | None = None

    def _build(self) -> procrastinate.App:
        # Döngüsel içe aktarmayı önlemek için tembel: görev kaydı worker modüllerini içe aktarır.
        from app.worker.tasks import register_tasks

        app = procrastinate.App(connector=procrastinate.PsycopgConnector(conninfo=self._settings.libpq_url))
        register_tasks(app)
        return app

    async def enqueue_backfill(self, account_id: UUID) -> None:
        if self._app is None:
            self._app = self._build()
        async with self._app.open_async():
            await defer_backfill(self._app, account_id)
