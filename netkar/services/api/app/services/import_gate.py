"""Maliyet içe aktarma eşzamanlılık kapısı (denetim S3 Y-01).

İki sınır, ikisi de BEKLEMEZ (sıra tutmak istekleri ve bağlantıları şişirir): doluysa hemen problem+json
ve `Retry-After` döner.
  1. Kiracı başına aynı anda en fazla 1 içe aktarma (kiracı kilidi; yazma aşamasını da kapsar).
  2. Süreç başına aynı anda en fazla `parallelism` ayrıştırma (bellek ve CPU tavanı).

Sayaçlar süreç içidir: çok süreçli dağıtımda sınırlar süreç sayısıyla çarpılır. Kesin tek-uçuş
gerekirse kiracı kilidi `pg_try_advisory_lock` ile veritabanına taşınmalıdır (ADR gerekir).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from uuid import UUID

from app.core.errors import ProblemError


class ImportGate:
    """Kiracı kilidi ve süreç geneli ayrıştırma yuvaları."""

    def __init__(self, parallelism: int, retry_after_seconds: int) -> None:
        self.parallelism = parallelism
        self._retry_after = str(max(1, retry_after_seconds))
        # Semafor yalnız "doluysa reddet" için kullanılır; kimse beklemez, bu yüzden olay döngüsüne bağlanmaz.
        self._slots = asyncio.Semaphore(parallelism)
        self._tenants: set[UUID] = set()

    @property
    def active_tenants(self) -> int:
        return len(self._tenants)

    @contextmanager
    def tenant(self, tenant_id: UUID) -> Iterator[None]:
        """Kiracının işleyen bir içe aktarması varsa 429; aksi halde kilidi alır ve çıkışta bırakır."""
        if tenant_id in self._tenants:
            raise ProblemError(
                429,
                "İçe aktarma sürüyor",
                "import-in-progress",
                "Bu mağaza için bir içe aktarma zaten sürüyor. Bitmesini bekleyip tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        self._tenants.add(tenant_id)
        try:
            yield
        finally:
            self._tenants.discard(tenant_id)

    @asynccontextmanager
    async def parse_slot(self) -> AsyncIterator[None]:
        """Boş ayrıştırma yuvası varsa alır; yoksa beklemeden 503."""
        if self._slots.locked():
            raise ProblemError(
                503,
                "İçe aktarma servisi yoğun",
                "import-busy",
                "Şu an çok sayıda dosya işleniyor. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        await self._slots.acquire()  # locked() yanlış olduğundan beklemeden döner
        try:
            yield
        finally:
            self._slots.release()
