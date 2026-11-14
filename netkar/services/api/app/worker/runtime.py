"""Worker çalışma zamanı: `netkar_worker` rolüyle motor, senkron yürütücü ve planlayıcı.

Motor ve yürütücü tembel kurulur (ilk görevde, olay döngüsü içinde): modül içe aktarılırken veya
görevler kaydedilirken veritabanına bağlanılmaz. Worker UYGULAMA ROLÜNE GERİ DÜŞMEZ: şifreli
sütunlar yalnız `netkar_worker` ile okunur (ADR-0005 §6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.envelope import EnvelopeCipher
from app.db.session import create_engine
from app.services.marketplace_accounts import TrendyolClientFactory, default_client_factory
from app.services.sync.runner import SyncPolicy, SyncRunner
from app.services.sync.sources import SOURCE_ORDER

logger = logging.getLogger("netkar.worker")


@dataclass(frozen=True, slots=True)
class PlannedAccount:
    """Planlayıcının gördüğü etkin hesap: kiracı, kimlik ve backfill'i tamamlanmış kaynaklar."""

    tenant_id: UUID
    account_id: UUID
    backfilled_sources: frozenset[str]

    @property
    def missing_backfill(self) -> bool:
        return not set(SOURCE_ORDER) <= self.backfilled_sources


class WorkerRuntime:
    """Worker bağımlılıkları. Testlerde sahte istemci fabrikası, saat ve motor verilebilir."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client_factory: TrendyolClientFactory | None = None,
        engine: AsyncEngine | None = None,
        now: Callable[[], datetime] | None = None,
        policy: SyncPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._engine = engine
        self._owns_engine = engine is None
        self._now = now or (lambda: datetime.now(UTC))
        self._policy = policy
        self._runner: SyncRunner | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    @property
    def engine(self) -> AsyncEngine:
        """`netkar_worker` rolüyle bağlanan motor (WORKER_DATABASE_URL yoksa hata)."""
        if self._engine is None:
            url = self.settings.worker_libpq_url.replace("postgresql://", "postgresql+psycopg://", 1)
            self._engine = create_engine(url)
        return self._engine

    @property
    def runner(self) -> SyncRunner:
        if self._runner is None:
            factory = self._client_factory or default_client_factory(self.settings)
            self._runner = SyncRunner(
                self.engine,
                factory,
                EnvelopeCipher(self.settings.key_ring),
                policy=self._policy,
                now=self._now,
            )
        return self._runner

    async def list_accounts(self) -> list[PlannedAccount]:
        """Etkin hesaplar (kiracı bağlamsız dar işlev). Yalnız kimlik, kiracı ve backfill durumu döner."""
        sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(self.engine, expire_on_commit=False)
        async with sessions() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT tenant_id, account_id, backfilled_sources FROM sync_gate.syncable_accounts()"
                    )
                )
            ).all()
            await session.rollback()
        return [PlannedAccount(UUID(str(r[0])), UUID(str(r[1])), frozenset(r[2])) for r in rows]

    async def aclose(self) -> None:
        """Kendi kurduğu motoru kapatır."""
        if self._engine is not None and self._owns_engine:
            await self._engine.dispose()
            self._engine = None
            self._runner = None


def sources_to_plan(account: PlannedAccount, wanted: Sequence[str]) -> list[str]:
    """Artımlı çekimde backfill'i tamamlanmış kaynaklar (diğerlerini backfill üstlenir)."""
    return [s for s in wanted if s in account.backfilled_sources]
