"""procrastinate App iskeleti.

Çalıştırma: `procrastinate --app=app.worker.app.app worker` (bkz. Makefile `worker`).
Worker, API ile aynı uygulama rolüyle bağlanır; kiracı verisine dokunan görevler
`app.tenant_id` bağlamını kendileri kurmalıdır (app.db.rls.set_rls_context).
"""

from __future__ import annotations

import procrastinate

from app.core.config import Settings, get_settings
from app.worker.tasks import register_tasks


def build_app(settings: Settings | None = None) -> procrastinate.App:
    """Verilen ayarlarla procrastinate uygulaması kurar (bağlantı ilk kullanımda açılır)."""
    settings = settings or get_settings()
    worker_app = procrastinate.App(
        connector=procrastinate.PsycopgConnector(conninfo=settings.libpq_url),
    )
    register_tasks(worker_app)
    return worker_app


app = build_app()
