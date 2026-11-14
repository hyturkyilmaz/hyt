"""Dönem sonucu önbelleği (denetim S4 O-01, SU-01, YO-01).

Kâr motoru her rapor isteğinde dönemin TÜM satırlarıyla çalışır (CPU, yüzlerce MB). Ürün, sipariş, özet ve
uyarı görünümleri aynı dönem sonucundan seçildiği için sonuç şu anahtarla paylaşılır:

    (kiracı, hesap, dönem başı, dönem sonu, ayar sürümü `settings_revision`, hesabın veri sürümü)

- Kiracı ve hesap anahtarın İÇİNDEDİR: başka kiracının girdisine ulaşmak yapısal olarak imkansızdır
  (anahtar eşitliği; üstüne kiracı başına girdi ve satır tavanı).
- Ayar sürümü (K44) her ayar yazımında artar. Veri sürümü (`report_data_version`) hesap başına tek sayaçtır
  ve motor girdisine yazan HER işlemde veritabanı tetikleyicisiyle artar (senkron, maliyet içe aktarma ve PUT,
  elle SQL; migrasyon 0012): eski sonuç dönmez, eski anahtarlı girdiler TTL/LRU ile gider.
- Yalnız motor sonucu (`PeriodReport`: sipariş no, barkod, tutarlar) tutulur; son müşteriye ait veri motor
  girdisine hiç girmediği için önbellekte de yoktur.
- Süreç içidir (çok süreçli dağıtımda her süreç kendi önbelleğini tutar) ve TTL'lidir. Dört tavan vardır:
  toplam girdi, toplam satır (bellek tavanı), kiracı başına girdi ve kiracı başına satır. Yer açmak gerekince
  kiracı önce KENDİ en eski girdilerini düşürür; genel tavan dolarsa en çok satır tutan kiracının girdisi
  düşer (az yer kaplayan korunur). Kiracı satır tavanını aşan tek sonuç saklanmaz. Bellek: ölçülen yaklaşık
  4 KB/satır, süreç başına; işçi sayısıyla çarpılır (bkz. `core/config.py`).
- Tek uçuş (single-flight): aynı anahtar için eşzamanlı istekler tek motor çalıştırması paylaşır (panel
  açılışında özet, ürünler ve uyarılar aynı anda gelir); sonuç saklanmasa bile bekleyenlere doğrudan verilir;
  bekleyenler kapı yuvası TUTMAZ ve en çok `wait_seconds` bekler (aşımda 503); hesaplayan da
  `compute_timeout_seconds` ile sınırlıdır (aşımda iptal, uçuş kaydı silinir, 503; kapı yuvası motor iş
  parçacığı gerçekten bitene dek tutulur, DK-01; OK-05).
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from typing import NamedTuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.models import ReportDataRevision
from app.services.profit_report import PeriodReport

# Veri sürümü: hesabın motor girdisine yazan her işlemde artan tek sayaç (migrasyon 0012).
DataVersion = int


async def report_data_version(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> DataVersion:
    """Hesabın motor girdisinin veri sürümü: `report_data_revisions.revision` (satır yoksa 0).

    Sayacı uygulama kodu değil VERİTABANI artırır (denetim 2026-11-12 OS-03, OS-04): motor girdisini besleyen
    sekiz tablonun (orders, order_lines, returns, financial_transactions, cargo_invoice_items, products,
    product_costs, sync_cursors) her satır yazımında, işlem COMMIT edilirken, "ertelenmiş kısıt tetikleyicisi"
    hesabın sayacını işlem başına bir kez `revision + 1` yapar (migrasyon 0012). Sonuçlar:

    - Yazım yolu unutulamaz: yeni bir yazan kod da, elle SQL de sayacı artırır.
    - Okuma hesabın tek satırıdır (tablo taraması yok): isabet maliyeti geçmiş veri hacminden bağımsızdır.
    - Artırma ile veri aynı işlemde commit olur ve satır kilidi commit sırasını düzenler: `now()` işlem
      başlangıcı penceresi (OS-04) yoktur; eşzamanlı yazarlarda sayaç kaybı olmaz (`UPDATE x = x + 1`).
    - Sürüm, motor girdisi okunmadan ÖNCE okunmalıdır: veri okuma sırasında değişirse sonuç eski sürümle
      saklanır ve sonraki istek yeni sürümü görüp yeniden hesaplar (güvenli yön).
    """
    revision = (
        await db.execute(
            select(ReportDataRevision.revision).where(
                ReportDataRevision.tenant_id == tenant_id,
                ReportDataRevision.marketplace_account_id == account_id,
            )
        )
    ).scalar_one_or_none()
    return 0 if revision is None else int(revision)


class ReportKey(NamedTuple):
    """Önbellek anahtarı; kiracı ve hesap kimliği anahtarın parçasıdır."""

    tenant_id: UUID
    account_id: UUID
    start: date
    end: date
    settings_revision: int
    data_version: DataVersion


@dataclass(slots=True)
class _Entry:
    report: PeriodReport
    weight: int
    expires_at: float


class ReportCache:
    """Sınırlı LRU + TTL dönem sonucu önbelleği (tek olay döngüsünde bölünemez bölümler, kilit yok).

    Tavanlar: toplam girdi (`max_entries`), toplam satır (`max_lines`, bellek tavanı), kiracı başına girdi
    (`tenant_entries`) ve kiracı başına satır (`tenant_lines`). Ağırlık = sonuç satır sayısı + 1.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_entries: int,
        max_lines: int,
        tenant_entries: int,
        tenant_lines: int | None = None,
        wait_seconds: float = 25.0,
        compute_timeout_seconds: float | None = None,
        retry_after_seconds: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_lines = max_lines
        self.tenant_entries = tenant_entries
        # Etkin kiracı satır tavanı HER ZAMAN toplam tavanın dörtte birini aşamaz (OK-03): operatör
        # `max_lines` değerini düşürse ve `tenant_lines` sabit kalsa da tek kiracı önbelleği dolduramaz.
        # Varsayılan 40.000 / 10.000 davranışı aynıdır (min(10.000, 40.000 // 4)).
        fair_share = max(1, max_lines // 4)
        self.tenant_lines = min(tenant_lines if tenant_lines is not None else fair_share, fair_share)
        self.wait_seconds = wait_seconds
        # Hesaplayanın üst süre sınırı (OK-05); None = sınırsız (yalnız birim testleri).
        self.compute_timeout_seconds = compute_timeout_seconds
        self.retry_after = str(max(1, retry_after_seconds))
        self._clock = clock
        self._entries: OrderedDict[ReportKey, _Entry] = OrderedDict()
        # Tek uçuş: sonuç `Future` ile paylaşılır; None = hesaplayan başarısız oldu (hata paylaşılmaz).
        self._inflight: dict[ReportKey, asyncio.Future[PeriodReport | None]] = {}
        self._weight = 0
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        return self.ttl_seconds > 0

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def total_lines(self) -> int:
        return self._weight

    def tenant_weight(self, tenant_id: UUID) -> int:
        return sum(e.weight for k, e in self._entries.items() if k.tenant_id == tenant_id)

    def get(self, key: ReportKey) -> PeriodReport | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._clock():
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        return entry.report

    def put(self, key: ReportKey, report: PeriodReport) -> None:
        """Saklar; yer gerekirse ADİL düşürür (denetim OS-02).

        1. Tek girdinin ağırlığı kiracı satır tavanını (`tenant_lines`) aşarsa saklanmaz.
        2. Kiracının kendi tavanları (girdi sayısı, satır) aşılacaksa YALNIZ kendi en eski girdileri düşer;
           başka kiracının girdisine bu aşamada dokunulmaz.
        3. Genel tavan (girdi, satır) hâlâ aşılacaksa en çok satır tutan kiracının en eski girdisi düşer
           (yeni girdinin sahibi de bu hesaba katılır): az yer kaplayan kiracı korunur; tek kiracı kiracı
           tavanı kadar yer tutabildiğinden onu aşarak başkasını dışarı itemez.
        Süresi dolmuş girdiler önce süpürülür (OS-05): ölü girdi yer tutup canlıyı düşürmez.
        """
        weight = len(report.result.lines) + 1
        if not self.enabled or weight > self.tenant_lines:
            return
        self._sweep_expired()
        if key in self._entries:
            self._drop(key)
        mine = [k for k in self._entries if k.tenant_id == key.tenant_id]  # LRU sırası: en eskiden yeniye
        mine_weight = sum(self._entries[k].weight for k in mine)
        while mine and (len(mine) >= self.tenant_entries or mine_weight + weight > self.tenant_lines):
            oldest = mine.pop(0)
            mine_weight -= self._entries[oldest].weight
            self._drop(oldest)
        while len(self._entries) + 1 > self.max_entries or self._weight + weight > self.max_lines:
            victim = self._pick_victim(key.tenant_id, weight)
            if victim is None:
                return  # düşürülecek girdi yok (tek girdi toplam tavana sığmıyor): saklanmaz
            self._drop(victim)
        self._entries[key] = _Entry(report, weight, self._clock() + self.ttl_seconds)
        self._weight += weight

    def _pick_victim(self, inserting: UUID, new_weight: int) -> ReportKey | None:
        """En çok satır tutan kiracının en eski girdisi (yeni girdi sahibine `new_weight` eklenir)."""
        per_tenant: dict[UUID, int] = {}
        for k, e in self._entries.items():
            per_tenant[k.tenant_id] = per_tenant.get(k.tenant_id, 0) + e.weight
        if not per_tenant:
            return None
        per_tenant[inserting] = per_tenant.get(inserting, 0) + new_weight
        # Eşitlikte sözlük sırası (ilk girdisi en eski olan kiracı) korunur: max ilk en büyüğü döndürür.
        holders = {k.tenant_id for k in self._entries}
        heaviest = max((t for t in per_tenant if t in holders), key=lambda t: per_tenant[t])
        return next(k for k in self._entries if k.tenant_id == heaviest)

    def _sweep_expired(self) -> None:
        now = self._clock()
        for k in [k for k, e in self._entries.items() if e.expires_at <= now]:
            self._drop(k)

    def _drop(self, key: ReportKey) -> None:
        entry = self._entries.pop(key)
        self._weight -= entry.weight

    def clear(self) -> None:
        self._entries.clear()
        self._weight = 0

    async def _run(self, compute: Callable[[], Awaitable[PeriodReport]]) -> PeriodReport:
        """Hesabı `compute_timeout_seconds` ile sınırlar (OK-05).

        Süre aşılırsa hesap iptal edilir ve çağıran (`get_or_compute`) tek uçuş kaydını `finally` ile
        siler; istek 503 + `Retry-After` alır. Kapı yuvası burada BIRAKILMAZ: motor iş parçacığı
        Python'da öldürülemediğinden yuva `SlotHandle.defer()` ile iş parçacığının gerçek bitişine
        devredilmiştir (DK-01, bkz. `profit_report.period_profit`); takılan motor yuvayı süreç yeniden
        başlayana dek tutabilir (DK-10, runbook: docs/operasyon/runbook_rapor_motoru.md).

        Yalnız KENDİ zaman aşımımız çevrilir (`expired()`): hesabın içinden gelen başka `TimeoutError` olduğu
        gibi yayılır. Yalnız bekleme kesilir; motor iş parçacığı sürer (`asyncio.shield`).
        """
        if self.compute_timeout_seconds is None:
            return await compute()
        try:
            async with asyncio.timeout(self.compute_timeout_seconds) as scope:
                return await compute()
        except TimeoutError:
            if not scope.expired():
                raise
            raise ProblemError(
                503,
                "Rapor hesaplanamadı",
                "report-compute-timeout",
                "Rapor belirlenen sürede hazırlanamadı. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": self.retry_after},
            ) from None

    async def get_or_compute(
        self,
        key: ReportKey,
        compute: Callable[[], Awaitable[PeriodReport]],
        release: Callable[[], Awaitable[None]],
    ) -> tuple[PeriodReport, bool]:
        """(rapor, önbellekten ya da başka isteğin hesabından mı).

        Aynı anahtarın hesaplaması sürerken bekler; bekleme öncesi `release` veritabanı bağlantısını
        havuza iade eder (beklerken "idle in transaction" kalınmaz). Sonuç bekleyenlere `Future` ile doğrudan
        verilir: sonucun SAKLANIP SAKLANMAMASI (tavan aşımı, kiracı satır tavanı) paylaşımı etkilemez (OS-01);
        motor tek uçuşta bir kez çalışır.

        Hata paylaşılmaz: hesaplayan başarısız olursa (429/503 kapı reddi, 500, iptal) bekleyenler BUNDAN
        etkilenmez, döngüye girip kendi denemesini yapar (kendi kapı yuvasını ister, kendi hatasını alır).
        Gerekçe: kapı reddi hesaplayanın kiracı ya da süreç yuvasına aittir, bekleyen için geçerli olmaz.

        Bekleme süresi `wait_seconds` ile sınırlıdır (OS-10): hesaplayan bu sürede bitmezse bekleyen 503 +
        `Retry-After` alır. Gerekçe: takılmış ya da çok yavaş bir hesaplayanın ardından bekleyenin kendi
        hesabını başlatması aynı pahalı işi çoğaltır ve kapının CPU korumasını zorlar; 503 istemcinin
        yeniden denemesini ister (o zaman sonuç büyük olasılıkla önbelleğe girmiştir). Süre, ters vekilin
        istek zaman aşımından kısa tutulur ki istemci bağlantı kopmadan problem+json görsün.
        """
        if not self.enabled:  # kapalıyken tek uçuş da yok: her istek kendi hesabını yapar
            return await self._run(compute), False
        released = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.wait_seconds  # gerçek olay döngüsü saati (TTL saati sahte olabilir)
        while True:
            cached = self.get(key)
            if cached is not None:
                self.hits += 1
                return cached, True
            pending = self._inflight.get(key)
            if pending is None:
                break
            if not released:
                await release()
                released = True
            remaining = deadline - loop.time()
            if remaining > 0:
                # `wait` (wait_for değil): zaman aşımı ya da bekleyenin iptali ortak Future'ı iptal etmez.
                await asyncio.wait({pending}, timeout=remaining)
            if not pending.done():
                raise ProblemError(
                    503,
                    "Rapor hazırlanıyor",
                    "report-wait-timeout",
                    "Aynı rapor uzun süredir hesaplanıyor. Kısa süre sonra tekrar deneyin.",
                    headers={"Retry-After": self.retry_after},
                )
            shared = pending.result()
            if shared is not None:
                self.hits += 1
                return shared, True
            # hesaplayan başarısız oldu: döngü başına dön (önbellek, yeni hesaplayan ya da kendi hesabım)
        self.misses += 1
        flight: asyncio.Future[PeriodReport | None] = loop.create_future()
        self._inflight[key] = flight
        report: PeriodReport | None = None
        try:
            report = await self._run(compute)
            self.put(key, report)
            return report, False
        finally:
            del self._inflight[key]
            flight.set_result(report)  # başarıda sonuç, hata ve iptalde None (paylaşılmaz)
