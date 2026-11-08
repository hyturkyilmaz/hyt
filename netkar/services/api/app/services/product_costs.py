"""Ürün birim maliyeti: doğrulama kuralları ve veritabanı işlemleri (API ve içe aktarma ortak kullanır).

Kurallar tek yerdedir (PUT gövdesi ve dosya içe aktarma aynı işlevleri çağırır). Para `Decimal`'dir, float
yoktur; saklanan değer projedeki tek yuvarlama işlevi `app.profit.money.rnd` ile kuruşa normalleştirilir.
`vat_rate` YÜZDE olarak saklanır (20 = %20; sütun `numeric(9,4)`, CHECK 0..100, motor `split_exclusive` ile
aynı ölçek). Motor sipariş gününde geçerli en son kaydı seçer (`app.profit.costs.apply_product_cost`: en büyük
`valid_from <= sipariş günü`); burada "bugün geçerli maliyet" aynı kuralla İstanbul gününe göre seçilir.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, literal_column, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketplaceAccount, Product, ProductCost
from app.profit.money import rnd

# Trendyol barkod biçimi docs/research/01_trendyol_api.md'de yazılı değildir: DOĞRULANMADI. Makul allowlist:
# harf veya rakamla başlar, harf, rakam, '.', '_', '-' içerir, en çok 200 karakter (DB CHECK ile uyumlu).
# Formül karakterleriyle (=, +, -, @) başlayan değer bu desene zaten uymaz (CSV/Excel enjeksiyonu).
BARCODE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}"
_BARCODE_RE = re.compile(BARCODE_PATTERN)
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

MAX_UNIT_COST = Decimal("10000000")
ALLOWED_VAT_RATES = frozenset(Decimal(rate) for rate in (0, 1, 10, 20))
MIN_VALID_FROM = date(2000, 1, 1)
MAX_FUTURE_DAYS = 366
_CENT = Decimal("0.01")


class RuleError(ValueError):
    """Alan kuralı ihlali: makine kodu ve Türkçe neden (girdi değeri iletiye KONMAZ)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def check_barcode(value: str) -> str:
    if value.startswith(FORMULA_PREFIXES):
        raise RuleError("barcode_formula", "Barkod formül karakteriyle (=, +, -, @) başlayamaz.")
    if not _BARCODE_RE.fullmatch(value):
        raise RuleError(
            "barcode_invalid",
            "Barkod yalnız harf, rakam, '.', '_' ve '-' içerebilir, harf veya rakamla başlamalı ve "
            "en çok 200 karakter olmalıdır.",
        )
    return value


def check_unit_cost(value: Decimal) -> Decimal:
    """0 < maliyet <= 10.000.000 ve en çok 2 ondalık. Dönüş: kuruşa normalleştirilmiş değer."""
    if not value.is_finite():
        raise RuleError("cost_invalid", "Maliyet geçerli bir sayı olmalıdır.")
    if value <= 0:
        raise RuleError("cost_not_positive", "Maliyet sıfırdan büyük olmalıdır.")
    if value > MAX_UNIT_COST:
        raise RuleError("cost_too_large", "Maliyet en çok 10.000.000 olabilir.")
    if value != value.quantize(_CENT):
        raise RuleError("cost_too_many_decimals", "Maliyet en çok 2 ondalık basamak içerebilir.")
    return rnd(value)


def check_vat_rate(value: Decimal) -> Decimal:
    if not value.is_finite() or value not in ALLOWED_VAT_RATES:
        raise RuleError(
            "vat_rate_invalid",
            "KDV oranı yüzde olarak 0, 1, 10 veya 20 olmalıdır (örneğin %20 için 20, 0,20 değil).",
        )
    return value


def check_valid_from(value: date, today: date) -> date:
    if value < MIN_VALID_FROM or value > today + timedelta(days=MAX_FUTURE_DAYS):
        raise RuleError(
            "valid_from_out_of_range",
            "Geçerlilik tarihi 2000-01-01 ile bugünden 366 gün sonrası arasında olmalıdır.",
        )
    return value


@dataclass(frozen=True, slots=True)
class CostRow:
    """Yazılacak doğrulanmış maliyet satırı."""

    barcode: str
    valid_from: date
    unit_cost_excl_vat: Decimal
    vat_rate: Decimal


@dataclass(frozen=True, slots=True)
class CostView:
    valid_from: date
    unit_cost_excl_vat: Decimal
    vat_rate: Decimal


@dataclass(frozen=True, slots=True)
class ProductListItem:
    barcode: str
    title: str | None
    stock_code: str | None
    current_cost: CostView | None


async def account_exists(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> bool:
    """Hesap bu kiracıya aitse doğru (şifreli sütunlar sorguya girmez, yalnız kimlik okunur)."""
    found = await db.execute(
        select(MarketplaceAccount.id).where(
            MarketplaceAccount.id == account_id, MarketplaceAccount.tenant_id == tenant_id
        )
    )
    return found.scalar_one_or_none() is not None


async def product_known(db: AsyncSession, tenant_id: UUID, account_id: UUID, barcode: str) -> bool:
    found = await db.execute(
        select(Product.id).where(
            Product.tenant_id == tenant_id,
            Product.marketplace_account_id == account_id,
            Product.barcode == barcode,
        )
    )
    return found.first() is not None


async def known_barcodes(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, barcodes: Sequence[str]
) -> set[str]:
    if not barcodes:
        return set()
    found = await db.execute(
        select(Product.barcode).where(
            Product.tenant_id == tenant_id,
            Product.marketplace_account_id == account_id,
            Product.barcode.in_(list(barcodes)),
        )
    )
    return set(found.scalars())


def _view(valid_from: date | None, cost: Decimal | None, vat: Decimal | None) -> CostView | None:
    if valid_from is None or cost is None or vat is None:
        return None
    return CostView(valid_from, rnd(cost), vat)


async def list_products(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    today: date,
    *,
    search: str | None,
    after: str | None,
    limit: int,
) -> tuple[list[ProductListItem], str | None]:
    """Barkoda göre sıralı sayfa (keyset: `after` = önceki sayfanın son barkodu) ve bugün geçerli maliyet."""
    current = (
        select(ProductCost.valid_from, ProductCost.unit_cost_excl_vat, ProductCost.vat_rate)
        .where(
            ProductCost.tenant_id == tenant_id,
            ProductCost.marketplace_account_id == Product.marketplace_account_id,
            ProductCost.barcode == Product.barcode,
            ProductCost.valid_from <= today,
        )
        .order_by(ProductCost.valid_from.desc())
        .limit(1)
        .lateral("current_cost")
    )
    stmt = (
        select(
            Product.barcode,
            Product.title,
            Product.stock_code,
            current.c.valid_from,
            current.c.unit_cost_excl_vat,
            current.c.vat_rate,
        )
        .outerjoin(current, true())
        .where(Product.tenant_id == tenant_id, Product.marketplace_account_id == account_id)
        .order_by(Product.barcode)
        .limit(limit + 1)
    )
    if search:
        # LIKE joker karakterleri kaçırılır (autoescape); değer parametre olarak bağlanır.
        stmt = stmt.where(
            Product.barcode.icontains(search, autoescape=True)
            | Product.title.icontains(search, autoescape=True)
        )
    if after is not None:
        stmt = stmt.where(Product.barcode > after)
    rows = (await db.execute(stmt)).all()
    page = rows[:limit]
    items = [ProductListItem(r[0], r[1], r[2], _view(r[3], r[4], r[5])) for r in page]
    next_cursor = page[-1][0] if len(rows) > limit else None
    return items, next_cursor


async def cost_history(db: AsyncSession, tenant_id: UUID, account_id: UUID, barcode: str) -> list[CostView]:
    rows = await db.execute(
        select(ProductCost.valid_from, ProductCost.unit_cost_excl_vat, ProductCost.vat_rate)
        .where(
            ProductCost.tenant_id == tenant_id,
            ProductCost.marketplace_account_id == account_id,
            ProductCost.barcode == barcode,
        )
        .order_by(ProductCost.valid_from.desc())
    )
    return [CostView(r[0], rnd(r[1]), r[2]) for r in rows.all()]


async def template_products(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, limit: int
) -> tuple[list[tuple[str, str | None]], bool]:
    """Şablon için (barkod, başlık) satırları; `limit`'ten fazlası varsa ikinci değer doğrudur."""
    rows = (
        await db.execute(
            select(Product.barcode, Product.title)
            .where(Product.tenant_id == tenant_id, Product.marketplace_account_id == account_id)
            .order_by(Product.barcode)
            .limit(limit + 1)
        )
    ).all()
    return [(r[0], r[1]) for r in rows[:limit]], len(rows) > limit


_CHUNK = 1000


async def upsert_costs(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, user_id: UUID, rows: Sequence[CostRow]
) -> tuple[int, int]:
    """(barkod, geçerlilik tarihi) tekilliğiyle upsert; (eklenen, güncellenen) sayısı döner. Satır silinmez.

    Çağıran (barkod, valid_from) çiftlerini tekilleştirmiş olmalıdır (tek ifadede aynı satır iki kez
    güncellenemez). Commit çağırana aittir: tüm parçalar tek işlemdedir.
    """
    created = updated = 0
    for start in range(0, len(rows), _CHUNK):
        values = [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "marketplace_account_id": account_id,
                "barcode": row.barcode,
                "valid_from": row.valid_from,
                "unit_cost_excl_vat": row.unit_cost_excl_vat,
                "vat_rate": row.vat_rate,
                "entered_by": user_id,
            }
            for row in rows[start : start + _CHUNK]
        ]
        insert_stmt = pg_insert(ProductCost).values(values)
        stmt: Any = insert_stmt.on_conflict_do_update(
            index_elements=["marketplace_account_id", "barcode", "valid_from"],
            set_={
                "unit_cost_excl_vat": insert_stmt.excluded.unit_cost_excl_vat,
                "vat_rate": insert_stmt.excluded.vat_rate,
                "entered_by": insert_stmt.excluded.entered_by,
                "updated_at": func.now(),
            },
        ).returning(literal_column("(xmax = 0)"))
        flags = (await db.execute(stmt)).scalars().all()
        created += sum(1 for inserted in flags if inserted)
        updated += sum(1 for inserted in flags if not inserted)
    return created, updated
