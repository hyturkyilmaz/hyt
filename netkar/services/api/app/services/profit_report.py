"""Dönem ve ürün kâr özeti: besleyici + saf motor (ADR-0005 §7).

API uçları (`app/api/v1/profit.py`) bu işlevleri çağırır; bir istek motoru EN FAZLA BİR KEZ çalıştırır.
RLS bağlamı (`app.tenant_id`) çağıran tarafından kurulur. Kâr motoru dönemin TÜM satırlarıyla çalışır:
ortak giderler (kargo, hizmet bedeli, reklam) satırlara dağıtıldığı için tek ürünü tek başına
hesaplamak farklı sonuç verirdi; ürün özeti dönem sonucundan seçilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.profit import ProfitSettings, calculate_profit
from app.profit.results import LineResult, PeriodTotals, ProductTotals, ProfitResult
from app.services.profit_feed import FeedNotes, build_profit_input


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
    result = await run_in_threadpool(calculate_profit, feed.profit_input)
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
