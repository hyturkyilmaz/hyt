"""Dönem ve ürün kâr özeti: besleyici + saf motor (ADR-0005 §7).

API uçları (`app/api/v1/profit.py`) bu işlevleri çağırır; bir istek motoru EN FAZLA BİR KEZ çalıştırır.
RLS bağlamı (`app.tenant_id`) çağıran tarafından kurulur. Kâr motoru dönemin TÜM satırlarıyla çalışır:
ortak giderler (kargo, hizmet bedeli, reklam) satırlara dağıtıldığı için tek ürünü tek başına
hesaplamak farklı sonuç verirdi; ürün özeti dönem sonucundan seçilir.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date
from uuid import UUID

import anyio.to_thread
from sqlalchemy.ext.asyncio import AsyncSession

from app.profit import ProfitSettings, calculate_profit
from app.profit.results import LineResult, PeriodTotals, ProductTotals, ProfitResult
from app.services.profit_feed import FeedNotes, build_profit_input
from app.services.report_gate import SlotHandle

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PeriodReport:
    """Dönem sonucu: motor çıktısı ve motora verilmeyen kayıtların notları."""

    start: date
    end: date
    result: ProfitResult
    notes: FeedNotes

    @property
    def totals(self) -> PeriodTotals:
        return self.result.period


@dataclass(frozen=True, slots=True)
class ProductReport:
    """Tek ürünün (barkod) dönem özeti: ürün toplamı (satışı yoksa None) ve satırları."""

    barcode: str
    start: date
    end: date
    product: ProductTotals | None
    lines: tuple[LineResult, ...]
    period: PeriodTotals
    notes: FeedNotes


async def period_profit(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    start: date,
    end: date,
    settings: ProfitSettings | None = None,
    *,
    release_connection: bool = False,
    slot: SlotHandle | None = None,
) -> PeriodReport:
    """[start, end] (İstanbul günleri) için kâr motorunu veritabanı kayıtlarıyla çalıştırır.

    `release_connection`: besleyici okumaları bitince işlemi kapatıp bağlantıyı havuza iade eder; motor
    bağlantısız ve "idle in transaction" kalmadan çalışır (denetim S4 O-01). İşlem yerel RLS bağlamı
    commit ile sıfırlanır: bundan sonra veritabanına dokunacak çağıran `set_rls_context`'i yeniden kurmalıdır.
    """
    feed = await build_profit_input(db, tenant_id, account_id, start, end, settings)
    if release_connection:
        await db.commit()
    # Motor saf ve CPU işidir (binlerce satırda yüzlerce ms): olay döngüsünü bloklamamak için iş parçacığında.
    if slot is None:
        result = await anyio.to_thread.run_sync(calculate_profit, feed.profit_input)
        return PeriodReport(start, end, result, feed.notes)
    # Kapı yuvası verildiyse (OK-05, DK-01): iş parçacığı görevi kalkana kadar ayrı bir görevde yürür ve
    # `shield` ile beklenir. Üst süre aşımı beklemeyi hemen keser (istek zamanında 503 alır) ama Python iş
    # parçacığını öldüremez; yuva görev bitene dek tutulur (geri çağrı olay döngüsünde bırakır), böylece
    # terk edilen motorlar kapının "süreçte en çok N motor" sınırını aşamaz.
    task = asyncio.ensure_future(anyio.to_thread.run_sync(calculate_profit, feed.profit_input))
    slot.defer()  # görev oluşturma ile ertelemenin arasında `await` yok: yuva sızmaz

    def _finished(done: asyncio.Future[ProfitResult]) -> None:
        if not done.cancelled():
            done.exception()  # sonuç/hata terk edilmişse "never retrieved" uyarısı çıkmasın
        was_abandoned = slot.abandoned
        slot.release()
        if was_abandoned:
            log.warning(
                "profit_engine_abandoned_finished pid=%d account=%s abandoned=%d",
                os.getpid(),
                account_id,
                slot.gate_abandoned,
            )

    task.add_done_callback(_finished)
    try:
        result = await asyncio.shield(task)
    except asyncio.CancelledError:
        if not task.done():
            # Yapılandırılmış alanlar (DK-10): terk edilmiş yuva sayısı süreç sınırına ulaşırsa bütün raporlar
            # 503 olur; log'dan izlenir. Kiracı/ayrıntı yazılmaz, yalnız hesap kimliği ve sayaçlar.
            abandoned = slot.mark_abandoned()
            log.warning(
                "profit_engine_abandoned pid=%d account=%s abandoned=%d process_slots=%d",
                os.getpid(),
                account_id,
                abandoned,
                slot.process_slots,
            )
        raise
    return PeriodReport(start, end, result, feed.notes)


async def product_profit(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    barcode: str,
    start: date,
    end: date,
    settings: ProfitSettings | None = None,
) -> ProductReport:
    """Bir barkodun dönem kârı: dönem hesaplanır, barkodun toplamı ve satırları seçilir."""
    report = await period_profit(db, tenant_id, account_id, start, end, settings)
    product = next((p for p in report.result.products if p.barcode == barcode), None)
    lines = tuple(line for line in report.result.lines if line.barcode == barcode)
    return ProductReport(barcode, start, end, product, lines, report.result.period, report.notes)
