"""Dönem sonucu önbelleği (denetim S4 O-01, SU-01, YO-01).

Kâr motoru her rapor isteğinde dönemin TÜM satırlarıyla çalışır (CPU, yüzlerce MB). Ürün, sipariş, özet ve
uyarı görünümleri aynı dönem sonucundan seçildiği için sonuç şu anahtarla paylaşılır:

    (kiracı, hesap, dönem başı, dönem sonu, ayar sürümü `settings_revision`, hesabın veri sürümü)

- Kiracı ve hesap anahtarın İÇİNDEDİR: başka kiracının girdisine ulaşmak yapısal olarak imkansızdır
  (anahtar eşitliği; üstüne kiracı başına girdi tavanı).
- Ayar sürümü (K44) her ayar yazımında artar, veri sürümü (`report_data_version`) senkron, maliyet içe
  aktarma ve maliyet yazımı sonrası değişir: eski sonuç dönmez, eski anahtarlı girdiler TTL/LRU ile gider.
- Yalnız motor sonucu (`PeriodReport`: sipariş no, barkod, tutarlar) tutulur; son müşteriye ait veri motor
  girdisine hiç girmediği için önbellekte de yoktur.
- Süreç içidir (çok süreçli dağıtımda her süreç kendi önbelleğini tutar), TTL'li ve iki yönden sınırlıdır:
  girdi sayısı ve toplam satır sayısı (bellek tavanı); tek girdi tavanı aşarsa saklanmaz.
- Tek uçuş (single-flight): aynı anahtar için eşzamanlı istekler tek motor çalıştırması paylaşır (panel
  açılışında özet, ürünler ve uyarılar aynı anda gelir); bekleyenler kapı yuvası TUTMAZ.
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

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CargoInvoiceItem,
    FinancialTransaction,
    Order,
    OrderLine,
    Product,
    ProductCost,
    Return,
    SyncCursor,
)
from app.services.profit_report import PeriodReport

# Motor girdisini besleyen tablolar (profit_feed.build_profit_input) ve son senkron işareti (sync_cursors).
_VERSIONED_TABLES: tuple[tuple[str, type], ...] = (
    ("orders", Order),
    ("order_lines", OrderLine),
    ("returns", Return),
    ("financial_transactions", FinancialTransaction),
    ("cargo_invoice_items", CargoInvoiceItem),
    ("products", Product),
    ("product_costs", ProductCost),
    ("sync_cursors", SyncCursor),
)

DataVersion = tuple[tuple[str, str, int], ...]


async def report_data_version(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> DataVersion:
    """Hesabın motor girdisinin veri sürümü: tablo başına (en son `updated_at`, satır sayısı).

    Tüm yazım yolları (senkron upsert, `removed_at` işareti, maliyet içe aktarma ve PUT) `updated_at`'i
    `now()` yapar; satır sayısı yeni satırı ve (olursa) silinmeyi yakalar. Tek gidiş, açık kiracı ve hesap
    süzgeci. Kalan sınır: iki işlemin `now()` sırası ile commit sırası ters düşerse (aynı hesaba eşzamanlı iki
    yazar) bir güncelleme sayıyı ve en büyük zamanı değiştirmeyebilir; TTL bu pencereyi sınırlar. Sürüm,
    motor girdisi okunmadan ÖNCE okunmalıdır: veri okuma sırasında değişirse sonuç eski sürümle saklanır ve
    sonraki istek yeni sürümü görüp yeniden hesaplar (güvenli yön).
    """
    parts = [
        select(
            literal(name).label("t"),
            func.max(model.updated_at).label("m"),  # type: ignore[attr-defined]
            func.count().label("n"),
        ).where(
            model.tenant_id == tenant_id,  # type: ignore[attr-defined]
            model.marketplace_account_id == account_id,  # type: ignore[attr-defined]
        )
        for name, model in _VERSIONED_TABLES
    ]
    rows = (await db.execute(union_all(*parts))).all()
    return tuple(
        sorted((str(name), "" if latest is None else latest.isoformat(), int(n)) for name, latest, n in rows)
    )


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
    """Sınırlı LRU + TTL dönem sonucu önbelleği (tek olay döngüsünde bölünemez bölümler, kilit yok)."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        max_entries: int,
        max_lines: int,
        tenant_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self.max_lines = max_lines
        self.tenant_entries = tenant_entries
        self._clock = clock
        self._entries: OrderedDict[ReportKey, _Entry] = OrderedDict()
        self._inflight: dict[ReportKey, asyncio.Event] = {}
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
        weight = len(report.result.lines) + 1
        if not self.enabled or weight > self.max_lines:
            return
        if key in self._entries:
            self._drop(key)
        # Kiracı başına tavan: tek kiracı (çok dönem gezerek) başkalarının girdisini dışarı itemez.
        mine = [k for k in self._entries if k.tenant_id == key.tenant_id]
        while len(mine) >= self.tenant_entries:
            self._drop(mine.pop(0))
        self._entries[key] = _Entry(report, weight, self._clock() + self.ttl_seconds)
        self._weight += weight
        while self._entries and (len(self._entries) > self.max_entries or self._weight > self.max_lines):
            self._drop(next(iter(self._entries)))

    def _drop(self, key: ReportKey) -> None:
        entry = self._entries.pop(key)
        self._weight -= entry.weight

    def clear(self) -> None:
        self._entries.clear()
        self._weight = 0

    async def get_or_compute(
        self,
        key: ReportKey,
        compute: Callable[[], Awaitable[PeriodReport]],
        release: Callable[[], Awaitable[None]],
    ) -> tuple[PeriodReport, bool]:
        """(rapor, önbellekten mi). Aynı anahtarın hesaplaması sürerken bekler; bekleme öncesi `release`
        veritabanı bağlantısını havuza iade eder (beklerken "idle in transaction" kalınmaz).

        Hesaplayan başarısız olursa bekleyenler sırayla kendi denemesini yapar (hata paylaşılmaz)."""
        if not self.enabled:  # kapalıyken tek uçuş da yok: her istek kendi hesabını yapar
            return await compute(), False
        released = False
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
            await pending.wait()
        self.misses += 1
        done = asyncio.Event()
        self._inflight[key] = done
        try:
            report = await compute()
            self.put(key, report)
            return report, False
        finally:
            del self._inflight[key]
            done.set()
