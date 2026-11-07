"""procrastinate App iskeleti.

Çalıştırma: `procrastinate --app=app.worker.app.app worker` (bkz. Makefile `worker`).
Worker, API'den AYRI bir DB rolüyle (`netkar_worker`, WORKER_DATABASE_URL) bağlanır: pazaryeri
şifreli sütunlarını okuyabilen tek rol odur (ADR-0005 §6). Kiracı verisine dokunan işler RLS bağlamını
iş adımı başına kendileri kurar (app.db.rls.tenant_transaction); RLS worker için de geçerlidir.
"""

from __future__ import annotations

import procrastinate

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.worker.runtime import WorkerRuntime
from app.worker.tasks import register_tasks


def build_app(settings: Settings | None = None, runtime: WorkerRuntime | None = None) -> procrastinate.App:
    """Verilen ayarlarla procrastinate uygulaması kurar (bağlantı ilk kullanımda açılır)."""
    settings = settings or get_settings()
    # Worker logları da JSON + maskeleme filtresinden geçer (kişisel veri ve sır log'a girmez).
    configure_logging(settings.log_level)
    worker_app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=settings.worker_libpq_url),
    )
    register_tasks(worker_app, runtime or WorkerRuntime(settings))
    return worker_app


app = build_app()
