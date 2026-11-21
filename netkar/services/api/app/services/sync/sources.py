"""Senkron kaynakları: ne çekilir, pencere kuralı, nasıl eşlenir ve yazılır (ADR-0005 §3).

Her kaynak `SourceSpec`'tir: `fetch` ağ çağrılarını yapar ve satırları BELLEKTE hazırlar (veritabanı
işlemi açık değildir), `write` hazır satırları tek işlemde yazar. Böylece ağ beklemesi sırasında
veritabanı işlemi tutulmaz ve bir pencere ya tamamen yazılır ya hiç yazılmaz.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.trendyol import TrendyolClient, TrendyolRequestError
from app.profit.constants import COMMISSION_SIGN
from app.services.sync import mappers, store

logger = logging.getLogger("netkar.sync")

# Kaynak adları sync_runs / sync_cursors CHECK kısıtıyla aynıdır. Sıra anlamlıdır: cargo_invoices,
# other_financials'tan gelen fatura seri numaralarına bağlıdır.
SOURCE_ORDER = ("orders", "claims", "products", "settlements", "other_financials", "cargo_invoices")

# Trendyol: orders/stream en çok 14 gün; claims için üst sınır dokümante değil, 14 gün seçildi;
# finans en çok 15 gün (istemci pencereyi 15 gün - 1 ms'ye böler).
STREAM_SPAN = timedelta(days=14)
CLAIMS_SPAN = timedelta(days=14)
FINANCE_SPAN = timedelta(days=15)

# `[CHE]` her istekte tek transactionType ister (docs/12 K05). Motorun bildiği, komisyon işareti
# tablosundaki tüm tipler çekilir; nakit hareketleri (PaymentOrder, WireTransfer, IncomingTransfer)
# gider olmadığı için çekilmez. Tip adlarının canlıda doğrulanması gerekir (K-N07).
SETTLEMENT_TYPES: tuple[str, ...] = tuple(sorted(COMMISSION_SIGN))

# (transactionType, transactionSubType). Platform hizmet bedeli ayrı alt tip isteğidir (K13).
# DeductionInvoices alt tipsiz istek de aynı satırları döndürebilir: yinelenen kimlik besleyicide
# alt tipli satır tercih edilerek tekilleştirilir (profit_feed).
OTHER_FINANCIAL_REQUESTS: tuple[tuple[str, str], ...] = (
    ("DeductionInvoices", ""),
    ("DeductionInvoices", "PlatformServiceFee"),
    ("Stoppage", ""),
    ("CashAdvance", ""),
    ("FinancialItem", ""),
)


@dataclass(frozen=True, slots=True)
class Batch:
    """Bir pencerenin çekilmiş ve eşlenmiş içeriği (veritabanına yazılmaya hazır)."""

    fetched: int
    skipped: int
    rows: Any


FetchFn = Callable[[TrendyolClient, datetime, datetime], Awaitable[Batch]]
WriteFn = Callable[[AsyncSession, UUID, UUID, Any], Awaitable[int]]


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """Bir senkron kaynağının tanımı. `span` None ise kaynak pencere kullanmaz (tam yenileme)."""

    name: str
    span: timedelta | None
    fetch: FetchFn
    write: WriteFn
    # Artımlı çekimde imleçten geriye bakma payı: geç değişen kayıtları yakalar.
    overlap: timedelta = timedelta(hours=1)


async def _fetch_orders(client: TrendyolClient, start: datetime, end: datetime) -> Batch:
    fetched = 0
    skipped = 0
    packages: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    async for package in client.iter_shipment_packages_stream(start, end):
        fetched += 1
        mapped = mappers.map_package(package)
        if mapped is None:
            skipped += 1
            continue
        skipped += mapped.skipped_lines
        packages.append((mapped.order, mapped.lines))
    return Batch(fetched, skipped, packages)


async def _write_orders(session: AsyncSession, tenant_id: UUID, account_id: UUID, rows: Any) -> int:
    orders, lines = await store.upsert_orders(session, rows, tenant_id=tenant_id, account_id=account_id)
    return orders + lines


async def _fetch_claims(client: TrendyolClient, start: datetime, end: datetime) -> Batch:
    fetched = 0
    skipped = 0
    rows: list[dict[str, Any]] = []
    async for claim in client.iter_claims(start, end):
        fetched += 1
        claim_rows, claim_skipped = mappers.map_claim(claim)
        rows.extend(claim_rows)
        skipped += claim_skipped
    return Batch(fetched, skipped, rows)


async def _write_claims(session: AsyncSession, tenant_id: UUID, account_id: UUID, rows: Any) -> int:
    return await store.upsert_returns(session, rows, tenant_id=tenant_id, account_id=account_id)


async def _fetch_products(client: TrendyolClient, start: datetime, end: datetime) -> Batch:
    fetched = 0
    skipped = 0
    rows: list[dict[str, Any]] = []
    async for product in client.iter_approved_products():
        fetched += 1
        product_rows, product_skipped = mappers.map_product(product)
        rows.extend(product_rows)
        skipped += product_skipped
    return Batch(fetched, skipped, rows)


async def _write_products(session: AsyncSession, tenant_id: UUID, account_id: UUID, rows: Any) -> int:
    return await store.upsert_products(session, rows, tenant_id=tenant_id, account_id=account_id)


async def _fetch_typed(
    client: TrendyolClient,
    source: str,
    requests: Sequence[tuple[str, str]],
    start: datetime,
    end: datetime,
) -> Batch:
    """Her (tip, alt tip) isteğini ayrı çeker. Trendyol bir tip adını reddederse (400) yalnız o istek atlanır.

    Tip adları canlıda doğrulanmamıştır (K-N07): tek yanlış ad tüm ekstre senkronunu durdurmasın. Reddedilen
    istek `skipped` sayacında ve uyarı logunda (tip adı, kişisel veri değil) görünür; diğer hatalar yayılır.
    """
    fetched = 0
    skipped = 0
    rows: list[dict[str, Any]] = []
    for request_type, sub_type in requests:
        try:
            if source == "settlements":
                stream = client.iter_settlements([request_type], start, end)
            else:
                stream = client.iter_other_financials([request_type], start, end, sub_type=sub_type or None)
            async for tx in stream:
                fetched += 1
                rows.append(
                    mappers.map_transaction(
                        tx, source=source, request_type=request_type, request_sub_type=sub_type
                    )
                )
        except TrendyolRequestError:
            skipped += 1
            logger.warning(
                "sync: istek tipi reddedildi", extra={"source": source, "request_type": request_type}
            )
    return Batch(fetched, skipped, rows)


async def _fetch_settlements(client: TrendyolClient, start: datetime, end: datetime) -> Batch:
    return await _fetch_typed(client, "settlements", [(t, "") for t in SETTLEMENT_TYPES], start, end)


async def _fetch_other_financials(client: TrendyolClient, start: datetime, end: datetime) -> Batch:
    return await _fetch_typed(client, "other_financials", OTHER_FINANCIAL_REQUESTS, start, end)


async def _write_transactions(session: AsyncSession, tenant_id: UUID, account_id: UUID, rows: Any) -> int:
    return await store.upsert_transactions(session, rows, tenant_id=tenant_id, account_id=account_id)


SOURCES: dict[str, SourceSpec] = {
    "orders": SourceSpec("orders", STREAM_SPAN, _fetch_orders, _write_orders, overlap=timedelta(hours=1)),
    "claims": SourceSpec("claims", CLAIMS_SPAN, _fetch_claims, _write_claims, overlap=timedelta(hours=2)),
    "products": SourceSpec("products", None, _fetch_products, _write_products),
    # Ekstre kayıtları teslimattan sonra, geriye dönük tarihli oluşabilir: geniş örtüşme (ADR-0005 §3).
    "settlements": SourceSpec(
        "settlements", FINANCE_SPAN, _fetch_settlements, _write_transactions, overlap=timedelta(days=7)
    ),
    "other_financials": SourceSpec(
        "other_financials",
        FINANCE_SPAN,
        _fetch_other_financials,
        _write_transactions,
        overlap=timedelta(days=7),
    ),
}
# Kargo faturaları pencereyle değil, ekstredeki fatura seri numaralarıyla çekilir: özel akış
# (`SyncRunner._run_cargo`), bu yüzden SOURCES içinde değildir.
CARGO_SOURCE = "cargo_invoices"
