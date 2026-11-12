"""Kâr raporu eşzamanlılık kapısı (denetim S4 Y-01, O-01).

Her rapor isteği motoru çalıştırır (CPU, yüzlerce MB bellek). Kapı iki sınırı BEKLEMEDEN uygular
(sıra tutmak istekleri ve bağlantıları şişirir): doluysa hemen problem+json ve `Retry-After` döner.
  1. Kiracı başına aynı anda en fazla `tenant_slots` rapor (kiracı dolarsa 429).
  2. Süreç başına aynı anda en fazla `process_slots` rapor (süreç dolarsa 503).
  3. Adalet (denetim S4 YO-01, 2026-11-12 OS-06): süreçteki SON boş yuva, GERÇEKTEN BEKLEYEN yuvasız bir
     kiracı için ayrılır. "Bekleyen" = yuvasızken süreç doluluğundan 503 alıp son `2 x Retry-After` içinde
     ve hâlâ yuvasızdır (kapı sıra tutmadığından bekleme, yeniden deneme penceresiyle izlenir). Böyle bir
     kiracı varken zaten yuva tutan başka kiracı son yuvayı alamaz (429); kimse beklemiyorsa kural işlemez:
     tek başına çalışan meşru kullanıcı 429 görmez, `process_slots <= tenant_slots` ayarında da kiracı
     yuvalarını kullanabilir. Bedel: bekleyen kiracının İLK denemesi 503 alabilir; ardından gelen yeniden
     deneme (Retry-After sonrası) ayrılmış yuvayı bulur. Dört ve üzeri farklı ağır kiracı yine tüm yuvaları
     doldurabilir; asıl çözüm önbellektir (`app.services.report_cache`: isabet yuva tutmaz).

Sayaçlar süreç içidir: çok süreçli dağıtımda sınırlar süreç sayısıyla çarpılır (`ImportGate` ile aynı not).
Kontrol ve artırma arasında `await` yoktur; tek olay döngüsünde bu bölüm bölünemez, kilit gerekmez.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.errors import ProblemError


class ReportGate:
    """Kiracı başına ve süreç başına beklemeyen rapor yuvaları."""

    def __init__(
        self,
        process_slots: int,
        tenant_slots: int,
        retry_after_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.process_slots = process_slots
        self.tenant_slots = tenant_slots
        self._retry_after = str(max(1, retry_after_seconds))
        self._starve_window = 2.0 * max(1, retry_after_seconds)
        self._clock = clock
        # Süreç doluluğundan 503 alan yuvasız kiracılar: kiracı -> son ret zamanı (YO-01 "gerçek bekleyen").
        self._starved: dict[UUID, float] = {}
        self._active = 0
        self._per_tenant: dict[UUID, int] = {}

    @property
    def active(self) -> int:
        return self._active

    @property
    def active_tenants(self) -> int:
        return len(self._per_tenant)

    def _other_tenant_waiting(self, tenant_id: UUID) -> bool:
        """Başka bir kiracı yuvasızken yakın zamanda 503 aldı mı (eski kayıtlar silinir)."""
        now = self._clock()
        for t in [
            t for t, at in self._starved.items() if now - at > self._starve_window or t in self._per_tenant
        ]:
            del self._starved[t]
        return any(t != tenant_id for t in self._starved)

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
            if self._per_tenant.get(tenant_id, 0) == 0:
                self._starved[tenant_id] = self._clock()  # yuvasız ve süreç dolu: bekleyen sayılır
            raise ProblemError(
                503,
                "Rapor servisi yoğun",
                "report-busy",
                "Şu an çok sayıda rapor hesaplanıyor. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        if (
            self._per_tenant.get(tenant_id, 0) >= 1
            and self._active + 1 >= self.process_slots
            and self._other_tenant_waiting(tenant_id)
        ):
            raise ProblemError(
                429,
                "Rapor hesaplanıyor",
                "report-in-progress",
                "Diğer mağazalara da yer bırakmak için bu mağazanın eşzamanlı rapor sayısı sınırlandı. "
                "Biri bitince tekrar deneyin.",
                headers={"Retry-After": self._retry_after},
            )
        self._starved.pop(tenant_id, None)
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
