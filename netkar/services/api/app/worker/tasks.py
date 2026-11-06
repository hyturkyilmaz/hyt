"""Görev tanımları. Görevler `register_tasks` ile verilen App'e bağlanır (test edilebilirlik)."""

from __future__ import annotations

import logging

import procrastinate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger("netkar.worker")

# Sabit pencere sayaçlarının saklama süresi (saat). Eski pencereler artık anlamsızdır.
RATE_LIMIT_RETENTION_HOURS = 24


async def heartbeat() -> str:
    """Worker'ın yaşadığını gösteren örnek periyodik görev."""
    logger.info("worker heartbeat")
    return "ok"


async def prune_rate_limits(engine: AsyncEngine) -> int:
    """Süresi geçmiş rate limit pencerelerini siler (operasyonel sayaç; kullanıcı verisi değil)."""
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM rate_limits WHERE window_start < now() - make_interval(hours => :h)"),
            {"h": RATE_LIMIT_RETENTION_HOURS},
        )
    return int(result.rowcount)


def register_tasks(app: procrastinate.App) -> None:
    """Görevleri ve periyodik zamanlamaları App'e kaydeder."""

    @app.periodic(cron="* * * * *")
    @app.task(name="netkar.heartbeat")
    async def _heartbeat(timestamp: int) -> str:
        return await heartbeat()

    @app.periodic(cron="17 * * * *")
    @app.task(name="netkar.prune_rate_limits")
    async def _prune(timestamp: int) -> int:
        engine = create_async_engine(get_settings().database_url)
        try:
            return await prune_rate_limits(engine)
        finally:
            await engine.dispose()
