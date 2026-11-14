"""Senkron yazım katmanı: idempotent upsert'ler, imleç ve çalışma kaydı.

Her işlev çağıranın açtığı bir işlem içinde (kiracı bağlamı `app.tenant_id` ayarlı) çalışır; RLS
`WITH CHECK` kiracı tutarlılığını ayrıca zorlar. Upsert'ler doğal anahtarla `ON CONFLICT DO UPDATE`
yapar: aynı veri tekrar yazılırsa sonuç değişmez (yeniden deneme ve pencere örtüşmesi güvenlidir).
Kullanıcıya ait sütunlar (`returns.returned_to_stock`, `products.unit_desi`, `orders.customer_key`)
güncelleme kümesine girmez: senkron onların üzerine yazmaz.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import Table, func, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CargoInvoiceItem,
    FinancialTransaction,
    Order,
    OrderLine,
    Product,
    Return,
    SyncCursor,
    SyncRun,
)

# Bir INSERT'teki en fazla bağlı parametre (PostgreSQL sınırı 65535; güvenli pay bırakılır).
_MAX_PARAMS = 30_000


def dedupe(rows: Iterable[dict[str, Any]], key_columns: Sequence[str]) -> list[dict[str, Any]]:
    """Aynı doğal anahtarlı satırlardan SONUNCUSUNU tutar.

    Pencere sınırında ve sayfa örtüşmesinde yinelenen kayıt gelir; aynı INSERT içinde iki kez geçen
    anahtar `ON CONFLICT DO UPDATE` için hatadır ("cannot affect row a second time").
    """
    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        unique[tuple(row[c] for c in key_columns)] = row
    return list(unique.values())


def _chunks(rows: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
    if not rows:
        return
    width = max(len(rows[0]), 1) + 4
    size = max(1, _MAX_PARAMS // width)
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


async def upsert_rows(
    session: AsyncSession,
    model: type[Any],
    rows: list[dict[str, Any]],
    *,
    tenant_id: UUID,
    account_id: UUID,
    conflict: Sequence[str],
    exclude_from_update: Sequence[str] = (),
) -> int:
    """Satırları doğal anahtarla upsert eder; etkilenen (eklenen + güncellenen) satır sayısını döndürür."""
    table = cast(Table, model.__table__)
    keyed = dedupe(rows, [c for c in conflict if c not in ("marketplace_account_id",)])
    affected = 0
    for chunk in _chunks(keyed):
        values = [{**row, "tenant_id": tenant_id, "marketplace_account_id": account_id} for row in chunk]
        stmt = pg_insert(table).values(values)
        skip = {*conflict, *exclude_from_update, "tenant_id", "marketplace_account_id"}
        update_columns: dict[str, Any] = {c: stmt.excluded[c] for c in chunk[0] if c not in skip}
        update_columns["updated_at"] = func.now()
        stmt = stmt.on_conflict_do_update(index_elements=list(conflict), set_=update_columns)
        await session.execute(stmt)
        # ON CONFLICT DO UPDATE her satırı tam bir kez etkiler (ekler veya günceller); rowcount çok satırlı
        # INSERT'te güvenilir değildir (-1), bu yüzden etkilenen sayı gönderilen satır sayısıdır.
        affected += len(chunk)
    return affected


async def upsert_products(
    session: AsyncSession, rows: list[dict[str, Any]], *, tenant_id: UUID, account_id: UUID
) -> int:
    """Katalog: `unit_desi` kullanıcı verisidir, güncelleme kümesinde değildir (satırda zaten yok)."""
    return await upsert_rows(
        session,
        Product,
        rows,
        tenant_id=tenant_id,
        account_id=account_id,
        conflict=("marketplace_account_id", "barcode"),
    )


async def upsert_orders(
    session: AsyncSession,
    packages: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    tenant_id: UUID,
    account_id: UUID,
) -> tuple[int, int]:
    """Paketleri ve satırlarını yazar; payload'da artık olmayan satırları `removed_at` ile işaretler.

    Döner: (yazılan paket sayısı, yazılan satır sayısı). `customer_key` güncelleme kümesinde yoktur.
    """
    unique_packages = {int(order["shipment_package_id"]): (order, lines) for order, lines in packages}
    if not unique_packages:
        return 0, 0
    order_rows = [order for order, _ in unique_packages.values()]
    table = cast(Table, Order.__table__)
    ids: dict[int, UUID] = {}
    for chunk in _chunks(order_rows):
        values = [{**row, "tenant_id": tenant_id, "marketplace_account_id": account_id} for row in chunk]
        insert_stmt = pg_insert(table).values(values)
        skip = {"marketplace_account_id", "shipment_package_id", "tenant_id"}
        set_: dict[str, Any] = {c: insert_stmt.excluded[c] for c in chunk[0] if c not in skip}
        set_["updated_at"] = func.now()
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=["marketplace_account_id", "shipment_package_id"], set_=set_
        ).returning(table.c.id, table.c.shipment_package_id)
        for row_id, package_id in (await session.execute(upsert_stmt)).all():
            ids[int(package_id)] = row_id

    line_rows: list[dict[str, Any]] = []
    for package_id, (_, lines) in unique_packages.items():
        line_rows.extend({**line, "order_id": ids[package_id]} for line in lines)
    written_lines = await upsert_rows(
        session,
        OrderLine,
        line_rows,
        tenant_id=tenant_id,
        account_id=account_id,
        conflict=("order_id", "line_id"),
    )
    # Payload'da olmayan etkin satırları işaretle (silme yok): paket bölündüyse veya satır kalktıysa.
    keys = dedupe(line_rows, ("order_id", "line_id"))
    await session.execute(
        text(
            "UPDATE order_lines l SET removed_at = now(), updated_at = now() "
            "WHERE l.order_id = ANY(:order_ids) AND l.removed_at IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM unnest(CAST(:pair_orders AS uuid[]), CAST(:pair_lines AS bigint[])) "
            "AS p(oid, lid) "
            "WHERE p.oid = l.order_id AND p.lid = l.line_id)"
        ),
        {
            "order_ids": list(ids.values()),
            "pair_orders": [k["order_id"] for k in keys],
            "pair_lines": [k["line_id"] for k in keys],
        },
    )
    return len(ids), written_lines


async def upsert_returns(
    session: AsyncSession, rows: list[dict[str, Any]], *, tenant_id: UUID, account_id: UUID
) -> int:
    """İade kalemleri; `returned_to_stock` kullanıcı işaretidir ve ezilmez."""
    return await upsert_rows(
        session,
        Return,
        rows,
        tenant_id=tenant_id,
        account_id=account_id,
        conflict=("marketplace_account_id", "claim_id", "claim_item_id"),
        exclude_from_update=("returned_to_stock",),
    )


async def upsert_transactions(
    session: AsyncSession, rows: list[dict[str, Any]], *, tenant_id: UUID, account_id: UUID
) -> int:
    """Ekstre satırları: doğal anahtar (hesap, kaynak, istek tipi, alt tip, işlem kimliği)."""
    return await upsert_rows(
        session,
        FinancialTransaction,
        rows,
        tenant_id=tenant_id,
        account_id=account_id,
        conflict=("marketplace_account_id", "source", "request_type", "request_sub_type", "transaction_id"),
    )


async def upsert_cargo_items(
    session: AsyncSession, rows: list[dict[str, Any]], *, tenant_id: UUID, account_id: UUID
) -> int:
    """Kargo faturası kalemleri: doğal anahtar (hesap, fatura seri no, kalem anahtarı)."""
    return await upsert_rows(
        session,
        CargoInvoiceItem,
        rows,
        tenant_id=tenant_id,
        account_id=account_id,
        conflict=("marketplace_account_id", "invoice_serial_number", "item_key"),
    )


# --- imleç ve çalışma kaydı -----------------------------------------------------------------


async def load_cursor(session: AsyncSession, account_id: UUID, source: str) -> SyncCursor | None:
    return await session.get(SyncCursor, (account_id, source))


async def advance_cursor(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    source: str,
    watermark: datetime,
    window_start: datetime | None,
    backfill_completed_at: datetime | None = None,
) -> None:
    """İmleci ilerletir (geri gitmez: GREATEST). `backfill_completed_at` verilirse (bir kez) yazılır."""
    stmt = pg_insert(cast(Table, SyncCursor.__table__)).values(
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        source=source,
        watermark=watermark,
        last_window_start=window_start,
        backfill_completed_at=backfill_completed_at,
    )
    set_: dict[str, Any] = {
        "watermark": func.greatest(SyncCursor.watermark, stmt.excluded.watermark),
        "last_window_start": stmt.excluded.last_window_start,
        "updated_at": func.now(),
    }
    if backfill_completed_at is not None:
        set_["backfill_completed_at"] = func.coalesce(
            SyncCursor.backfill_completed_at, stmt.excluded.backfill_completed_at
        )
    await session.execute(
        stmt.on_conflict_do_update(index_elements=["marketplace_account_id", "source"], set_=set_)
    )


async def start_run(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    run_group_id: UUID,
    kind: str,
    source: str,
    window_start: datetime | None,
    window_end: datetime | None,
    windows_total: int,
) -> UUID:
    """`running` durumunda bir sync_runs satırı açar ve kimliğini döndürür."""
    run = SyncRun(
        tenant_id=tenant_id,
        marketplace_account_id=account_id,
        run_group_id=run_group_id,
        kind=kind,
        source=source,
        window_start=window_start,
        window_end=window_end,
        status="running",
        windows_total=windows_total,
    )
    session.add(run)
    await session.flush()
    return run.id


async def bump_run(session: AsyncSession, run_id: UUID, *, fetched: int, upserted: int, skipped: int) -> None:
    """Bir pencere tamamlandı: sayaçları artırır (veri yazımıyla AYNI işlemde)."""
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(
            windows_done=SyncRun.windows_done + 1,
            fetched_count=SyncRun.fetched_count + fetched,
            upserted_count=SyncRun.upserted_count + upserted,
            skipped_count=SyncRun.skipped_count + skipped,
            updated_at=func.now(),
        )
    )


async def finish_run(
    session: AsyncSession, run_id: UUID, *, status: str, error_class: str | None = None
) -> None:
    """Çalışma kaydını kapatır. `error_class` yalnız kısa sınıf adıdır (ileti ve gövde yazılmaz)."""
    await session.execute(
        update(SyncRun)
        .where(SyncRun.id == run_id)
        .values(status=status, error_class=error_class, finished_at=func.now(), updated_at=func.now())
    )
