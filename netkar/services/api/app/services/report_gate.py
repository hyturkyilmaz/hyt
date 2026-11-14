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

Terk edilen motor (DK-01): hesap üst süresi aşılınca istek 503 alır ama motor iş parçacığı Python'da
öldürülemez; yuva (`SlotHandle.defer`) iş parçacığı gerçekten bitene dek tutulur, böylece "süreçte en çok N
motor" sınırı zaman aşımında bozulmaz: terk edilen motor bitene dek yeni hesap kapıdan geçemez (429/503).

Sayaçlar süreç içidir: çok süreçli dağıtımda sınırlar süreç sayısıyla çarpılır (`ImportGate` ile aynı not).
Kontrol ve artırma arasında `await` yoktur; tek olay döngüsünde bu bölüm bölünemez, kilit gerekmez.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.errors import ProblemError


class SlotHandle:
    """Alınmış bir yuvanın tutamağı (DK-01): yuva, motor iş parçacığı GERÇEKTEN bitene dek tutulabilir.

    `defer()` sonrası `slot()` çıkışı yuvayı bırakmaz; bırakma `release()` ile (iş parçacığı görevinin
    bitiş geri çağrısında, olay döngüsünde) yapılır. `release()` tekrarlanabilir (idempotent).
    """

    __slots__ = ("_abandoned", "_deferred", "_gate", "_released", "_tenant_id")

    def __init__(self, gate: ReportGate, tenant_id: UUID) -> None:
        self._gate = gate
        self._tenant_id = tenant_id
        self._deferred = False
        self._released = False
        self._abandoned = False

    def defer(self) -> None:
        self._deferred = True

    def mark_abandoned(self) -> int:
        """İstek beklemeyi bıraktı ama motor iş parçacığı sürüyor (DK-10): terk edilmiş yuva sayısına eklenir.

        Idempotent; bırakma (`release`) sayıyı düşürür. Dönüş: güncel terk edilmiş yuva sayısı.
        """
        if not self._abandoned and not self._released:
            self._abandoned = True
            self._gate._abandoned += 1
        return self._gate._abandoned

    @property
    def deferred(self) -> bool:
        return self._deferred

    @property
    def process_slots(self) -> int:
        return self._gate.process_slots

    @property
    def abandoned(self) -> bool:
        return self._abandoned

    @property
    def gate_abandoned(self) -> int:
        """Kapıdaki güncel terk edilmiş yuva sayısı (log alanı)."""
        return self._gate.abandoned

    def release(self) -> None:
        if not self._released:
            self._released = True
            if self._abandoned:
                self._gate._abandoned -= 1
            self._gate._release(self._tenant_id)


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
        self._abandoned = 0  # istek tarafından terk edilmiş ama iş parçacığı sürerken tutulan yuvalar (DK-10)
        self._per_tenant: dict[UUID, int] = {}

    @property
    def active(self) -> int:
        return self._active

    @property
    def abandoned(self) -> int:
        """Terk edilmiş (isteği 503 almış) ama motoru hâlâ çalışan yuva sayısı; `process_slots`'a ulaşırsa
        bütün raporlar 503 olur (runbook: docs/operasyon/runbook_rapor_motoru.md)."""
        return self._abandoned

    @property
    def active_tenants(self) -> int:
        return len(self._per_tenant)

    def _sweep_starved(self) -> None:
        """Süresi dolmuş ya da artık yuva tutan kiracıların "bekleyen" kaydını siler (OK-11)."""
        now = self._clock()
        for t in [
            t for t, at in self._starved.items() if now - at > self._starve_window or t in self._per_tenant
        ]:
            del self._starved[t]

    def _other_tenant_waiting(self, tenant_id: UUID) -> bool:
        """Başka bir kiracı yuvasızken yakın zamanda 503 aldı mı (eski kayıtlar silinir)."""
        self._sweep_starved()
        return any(t != tenant_id for t in self._starved)

    @asynccontextmanager
    async def slot(self, tenant_id: UUID) -> AsyncIterator[SlotHandle]:
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
            self._sweep_starved()  # yeniden denemeyen kiracıların kayıtları bu dalda da temizlenir (OK-11)
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
        handle = SlotHandle(self, tenant_id)
        try:
            yield handle
        finally:
            if not handle.deferred:  # ertelendiyse bırakma, iş parçacığının bitişine devredilmiştir (DK-01)
                handle.release()

    def _release(self, tenant_id: UUID) -> None:
        self._active -= 1
        remaining = self._per_tenant[tenant_id] - 1
        if remaining:
            self._per_tenant[tenant_id] = remaining
        else:
            del self._per_tenant[tenant_id]
