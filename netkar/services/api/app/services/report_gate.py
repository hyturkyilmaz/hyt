"""Kâr raporu eşzamanlılık kapısı (denetim S4 Y-01, O-01).

Her rapor isteği motoru çalıştırır (CPU, yüzlerce MB bellek). Kapı iki sınırı BEKLEMEDEN uygular
(sıra tutmak istekleri ve bağlantıları şişirir): doluysa hemen problem+json ve `Retry-After` döner.
  1. Kiracı başına aynı anda en fazla `tenant_slots` rapor (kiracı dolarsa 429).
  2. Süreç başına aynı anda en fazla `process_slots` rapor (süreç dolarsa 503).

Sayaçlar süreç içidir: çok süreçli dağıtımda sınırlar süreç sayısıyla çarpılır (`ImportGate` ile aynı not).
Kontrol ve artırma arasında `await` yoktur; tek olay döngüsünde bu bölüm bölünemez, kilit gerekmez.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.errors import ProblemError


class ReportGate:
    """Kiracı başına ve süreç başına beklemeyen rapor yuvaları."""

    def __init__(self, process_slots: int, tenant_slots: int, retry_after_seconds: int) -> None:
        self.process_slots = process_slots
        self.tenant_slots = tenant_slots
        self._retry_after = str(max(1, retry_after_seconds))
        self._active = 0
        self._per_tenant: dict[UUID, int] = {}

    @property
    def active(self) -> int:
        return self._active

    @property
    def active_tenants(self) -> int:
        return len(self._per_tenant)

    @asynccontextmanager
    async def slot(self, tenant_id: UUID) -> AsyncIterator[None]:
        """Boş yuva varsa alır ve çıkışta (hata ve iptalde de) bırakır; yoksa beklemeden 429/503."""
        if self._per_tenant.get(tenant_id, 0) >= self.tenant_slots:
            raise ProblemError(
                429,
                "Rapor hesaplanıyor",
                "report-in-progress",
                "Bu mağaza için çok sayıda rapor aynı anda hesaplanıyor. Biri bitince tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        if self._active >= self.process_slots:
            raise ProblemError(
                503,
                "Rapor servisi yoğun",
                "report-busy",
                "Şu an çok sayıda rapor hesaplanıyor. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        self._active += 1
        self._per_tenant[tenant_id] = self._per_tenant.get(tenant_id, 0) + 1
        try:
            yield
        finally:
            self._active -= 1
            remaining = self._per_tenant[tenant_id] - 1
            if remaining:
                self._per_tenant[tenant_id] = remaining
            else:
                del self._per_tenant[tenant_id]
