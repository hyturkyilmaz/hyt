"""Veritabanı kayıtlarından kâr motoru girdisi (`ProfitInput`) kuran besleyici (ADR-0005 §7).

Motor saftır ve I/O yapmaz (docs/12 §11.1); bu modül tek köprüdür: dönemi (İstanbul takvim günleri)
seçer, kayıtları okur ve motorun alan modeline çevirir. Eşleme `schema_v1.parse_input` ile AYNI
kuralları izler (örn. `unit_gross = lineGrossAmount`, sınıflandırma istek tipine göre), böylece altın
senaryolar veritabanı yolundan geçirildiğinde aynı sonucu verir (`tests/test_feed_golden_database.py`).

Dönem seçimi: sipariş paketleri `ordered_at` İstanbul günü [start, end] içinde olanlardır. Ekstre,
iade ve kargo faturası kalemleri bu siparişlerin numarasıyla eşlenir. Siparişe bağlanamayan
`otherfinancials` satırları (hizmet bedeli, bağsız ceza, stopaj, erken ödeme) iki kuralla seçilir:
(a) `paymentOrderId`'si seçilen siparişlerin ekstre satırlarındaki hakedişlerden biriyle aynıysa,
(b) siparişe bağlı değilse ve işlem tarihi (yoksa ödeme tarihi) dönem içindeyse.

Kayıt eksikliği tahminle doldurulmaz: oranı bilinmeyen veya kalem kırılımı tutarsız satır motora
verilmez ve `FeedNotes` sayaçlarında görünür (kâr sessizce yanlış hesaplanmasın).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    CargoInvoiceItem as CargoInvoiceItemRow,
)
from app.models import (
    FinancialTransaction,
    Order,
    OrderLine,
    Product,
    ProductCost,
    Return,
)
from app.profit.inputs import (
    CargoInvoice,
    CargoInvoiceItem,
    Claim,
    ClaimItem,
    CostRecord,
    OrderItem,
    OtherFinancialRow,
    ProfitInput,
    SettlementRow,
)
from app.profit.inputs import Order as EngineOrder
from app.profit.inputs import OrderLine as EngineLine
from app.profit.schema_v1 import ISTANBUL, istanbul_day
from app.profit.settings import ProfitSettings
from app.services.financial_classes import DEFAULT_CLASS_RULES, ClassRule, classify_other_financial

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_ONE_MS = timedelta(milliseconds=1)


@dataclass(slots=True)
class FeedNotes:
    """Motora verilmeyen kayıtların sayacı (sessiz veri kaybı olmasın)."""

    # Oranı (KDV veya komisyon) ne satırda ne üründe olan satır sayısı.
    lines_missing_rates: int = 0
    # Kalem kırılımı adetle uyuşmayan ve indirimi sıfır olmayan (kalemsiz) satır sayısı.
    lines_bad_items: int = 0
    # Tüm satırları elenen için motora verilmeyen paket sayısı.
    orders_without_lines: int = 0
    # Sipariş numarası veya barkodu olmayan ekstre satırı sayısı.
    settlements_unmatched: int = 0
    # Sipariş numarası olmayan kargo faturası kalemi sayısı.
    cargo_items_unmatched: int = 0
    # Sipariş numarası veya kalem kimliği olmayan iade kalemi sayısı.
    claim_items_unmatched: int = 0

    @property
    def total(self) -> int:
        return (
            self.lines_missing_rates
            + self.lines_bad_items
            + self.orders_without_lines
            + self.settlements_unmatched
            + self.cargo_items_unmatched
            + self.claim_items_unmatched
        )


@dataclass(frozen=True, slots=True)
class ProfitFeed:
    """Besleyici çıktısı: motor girdisi ve motora verilmeyen kayıtların notları."""

    profit_input: ProfitInput
    notes: FeedNotes


def epoch_ms(moment: datetime) -> int:
    """Saat dilimli zamanı epoch milisaniyeye çevirir (tamsayı aritmetiği, float yok)."""
    return (moment.astimezone(UTC) - _EPOCH) // _ONE_MS


def period_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """[start 00:00, end+1 00:00) İstanbul gün sınırları (UTC'ye çevrilebilir, saat dilimli)."""
    if end < start:
        raise ValueError("dönem bitişi başlangıçtan önce olamaz")
    lower = datetime.combine(start, time.min, tzinfo=ISTANBUL)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=ISTANBUL)
    return lower, upper


# --- sorgu parçaları -----------------------------------------------------------------------------


def _orders_in_period(
    tenant_id: UUID, account_id: UUID, lower: datetime, upper: datetime
) -> list[ColumnElement[bool]]:
    return [
        Order.tenant_id == tenant_id,
        Order.marketplace_account_id == account_id,
        Order.ordered_at >= lower,
        Order.ordered_at < upper,
    ]


def _order_number_in_period(
    column: Any,
    account_column: Any,
    tenant_id: UUID,
    account_id: UUID,
    lower: datetime,
    upper: datetime,
) -> ColumnElement[bool]:
    """`column` (sipariş numarası) dönemdeki bir siparişe aitse doğru (EXISTS)."""
    return exists().where(
        Order.order_number == column,
        Order.marketplace_account_id == account_column,
        *_orders_in_period(tenant_id, account_id, lower, upper),
    )


async def _load_orders(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, lower: datetime, upper: datetime
) -> tuple[Sequence[Order], dict[UUID, list[OrderLine]]]:
    orders = (
        (
            await db.execute(
                select(Order)
                .where(*_orders_in_period(tenant_id, account_id, lower, upper))
                .order_by(Order.ordered_at, Order.shipment_package_id)
            )
        )
        .scalars()
        .all()
    )
    lines: dict[UUID, list[OrderLine]] = defaultdict(list)
    stmt = (
        select(OrderLine)
        .join(Order, OrderLine.order_id == Order.id)
        .where(*_orders_in_period(tenant_id, account_id, lower, upper), OrderLine.removed_at.is_(None))
        .order_by(OrderLine.line_id)
    )
    for line in (await db.execute(stmt)).scalars():
        lines[line.order_id].append(line)
    return orders, lines


def _select_financial(tenant_id: UUID, account_id: UUID, source: str) -> Select[Any]:
    return select(FinancialTransaction).where(
        FinancialTransaction.tenant_id == tenant_id,
        FinancialTransaction.marketplace_account_id == account_id,
        FinancialTransaction.source == source,
    )


# --- eşlemeler -----------------------------------------------------------------------------------


def _engine_items(line: OrderLine, notes: FeedNotes) -> tuple[OrderItem, ...] | None:
    """Kalem kırılımı; adetle uyuşmuyorsa ve indirim varsa None (satır elenir)."""
    stored = line.items or []
    if len(stored) == line.quantity:
        return tuple(
            OrderItem(str(i["id"]), Decimal(i["seller_discount"]), Decimal(i["ty_discount"])) for i in stored
        )
    if not stored and not line.line_seller_discount and not line.line_ty_discount:
        # İndirimsiz satırda kalem kırılımı gelmemiş olabilir: sıfır indirimli adet kalemleri kurulur.
        return tuple(
            OrderItem(f"line-{line.line_id}-{i}", Decimal(0), Decimal(0)) for i in range(line.quantity)
        )
    notes.lines_bad_items += 1
    return None


def _engine_order(
    order: Order, lines: list[OrderLine], products: dict[str, Product], notes: FeedNotes
) -> EngineOrder | None:
    engine_lines: list[EngineLine] = []
    for line in lines:
        product = products.get(line.barcode)
        vat = line.vat_rate if line.vat_rate is not None else (product.vat_rate if product else None)
        commission = (
            line.commission_rate
            if line.commission_rate is not None
            else (product.commission_rate if product else None)
        )
        if vat is None or commission is None:
            notes.lines_missing_rates += 1
            continue
        items = _engine_items(line, notes)
        if items is None:
            continue
        engine_lines.append(
            EngineLine(
                line_id=line.line_id,
                barcode=line.barcode,
                quantity=line.quantity,
                unit_gross=line.line_gross_amount,
                vat_rate=vat,
                commission_rate=commission,
                items=items,
                unit_desi=product.unit_desi if product else None,
            )
        )
    if not engine_lines:
        notes.orders_without_lines += 1
        return None
    return EngineOrder(
        order_number=order.order_number,
        package_id=order.shipment_package_id,
        order_day=istanbul_day(epoch_ms(order.ordered_at)),
        status=order.status,
        carrier=order.carrier or "",
        lines=tuple(engine_lines),
        cargo_deci=order.cargo_deci,
        deci=order.deci,
        who_pays=order.who_pays,
    )


def _dedupe_other(rows: Sequence[FinancialTransaction]) -> list[FinancialTransaction]:
    """Aynı kimlikli DeductionInvoices satırı hem alt tipsiz hem `PlatformServiceFee` isteğinden gelirse
    alt tipli olanı tutar (alt tipsiz kopya aynı bedeli ikinci kez gider yazardı)."""
    chosen: dict[tuple[str, str], FinancialTransaction] = {}
    for row in rows:
        key = (row.request_type, row.transaction_id)
        current = chosen.get(key)
        if current is None or (row.request_sub_type and not current.request_sub_type):
            chosen[key] = row
    return [r for r in rows if chosen[(r.request_type, r.transaction_id)] is r]


# --- giriş noktası -------------------------------------------------------------------------------


async def build_profit_input(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    start: date,
    end: date,
    settings: ProfitSettings | None = None,
    *,
    class_rules: Sequence[ClassRule] = DEFAULT_CLASS_RULES,
) -> ProfitFeed:
    """[start, end] (İstanbul günleri, uçlar dahil) için motor girdisini kurar.

    RLS bağlamı çağıran tarafından kurulmuş olmalıdır (`app.tenant_id`); sorgular ayrıca açık
    `tenant_id` ve hesap süzgeci taşır (çift kilit).
    """
    lower, upper = period_bounds(start, end)
    notes = FeedNotes()
    orders, lines_by_order = await _load_orders(db, tenant_id, account_id, lower, upper)

    products = {
        p.barcode: p
        for p in (
            await db.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id, Product.marketplace_account_id == account_id
                )
            )
        ).scalars()
    }
    engine_orders = [
        engine_order
        for order in orders
        if (engine_order := _engine_order(order, lines_by_order.get(order.id, []), products, notes))
        is not None
    ]

    costs = tuple(
        CostRecord(c.barcode, c.valid_from, c.unit_cost_excl_vat, c.vat_rate)
        for c in (
            await db.execute(
                select(ProductCost)
                .where(ProductCost.tenant_id == tenant_id, ProductCost.marketplace_account_id == account_id)
                .order_by(ProductCost.barcode, ProductCost.valid_from)
            )
        ).scalars()
    )

    in_period = _order_number_in_period(
        FinancialTransaction.order_number,
        FinancialTransaction.marketplace_account_id,
        tenant_id,
        account_id,
        lower,
        upper,
    )
    settlement_rows = (
        (
            await db.execute(
                _select_financial(tenant_id, account_id, "settlements")
                .where(in_period)
                .order_by(FinancialTransaction.transaction_id)
            )
        )
        .scalars()
        .all()
    )
    settlements: list[SettlementRow] = []
    for r in settlement_rows:
        if not r.order_number or not r.barcode:
            notes.settlements_unmatched += 1
            continue
        settlements.append(
            SettlementRow(
                row_id=r.transaction_id,
                request_type=r.request_type,
                order_number=r.order_number,
                barcode=r.barcode,
                debt=r.debt,
                credit=r.credit,
                package_id=r.shipment_package_id,
                commission_amount=r.commission_amount,
                commission_rate=r.commission_rate,
                seller_revenue=r.seller_revenue,
                payment_order_id=r.payment_order_id,
            )
        )

    other_rows = await _load_other_financials(db, tenant_id, account_id, lower, upper, in_period)
    others = []
    for r in _dedupe_other(other_rows):
        category, vat = classify_other_financial(
            r.request_type, r.request_sub_type, r.type_text, r.description, class_rules
        )
        others.append(
            OtherFinancialRow(
                row_id=r.transaction_id,
                request_type=r.request_type,
                debt=r.debt,
                credit=r.credit,
                request_sub_type=r.request_sub_type or None,
                type_text=r.type_text,
                order_number=r.order_number,
                payment_order_id=r.payment_order_id,
                category=category,
                vat_rate=vat,
            )
        )

    cargo_invoices = await _load_cargo_invoices(db, tenant_id, account_id, lower, upper, notes)
    claims = await _load_claims(db, tenant_id, account_id, lower, upper, notes)

    return ProfitFeed(
        profit_input=ProfitInput(
            orders=tuple(engine_orders),
            settings=settings or ProfitSettings(),
            costs=costs,
            catalog_barcodes=tuple(sorted(products)),
            settlements=tuple(settlements),
            other_financials=tuple(others),
            cargo_invoices=cargo_invoices,
            claims=claims,
        ),
        notes=notes,
    )


async def _load_other_financials(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    lower: datetime,
    upper: datetime,
    order_bound: ColumnElement[bool],
) -> Sequence[FinancialTransaction]:
    """Siparişe bağlı + dönemdeki hakedişlerin ödeme emrine bağlı + dönemdeki bağsız satırlar."""
    # Alt sorgu aynı tabloya ikinci başvurudur: takma ad, dış sorguyla otomatik ilişkilenmeyi önler.
    settled = aliased(FinancialTransaction)
    settled_payment_orders = (
        select(settled.payment_order_id)
        .where(
            settled.tenant_id == tenant_id,
            settled.marketplace_account_id == account_id,
            settled.source == "settlements",
            settled.payment_order_id.is_not(None),
            _order_number_in_period(
                settled.order_number, settled.marketplace_account_id, tenant_id, account_id, lower, upper
            ),
        )
        .scalar_subquery()
    )
    # İşlem tarihi, yoksa ödeme tarihi.
    when = func.coalesce(FinancialTransaction.transaction_date, FinancialTransaction.payment_date)
    dated_in_period = and_(FinancialTransaction.order_number.is_(None), when >= lower, when < upper)
    stmt = _select_financial(tenant_id, account_id, "other_financials").where(
        or_(order_bound, FinancialTransaction.payment_order_id.in_(settled_payment_orders), dated_in_period)
    )
    result = await db.execute(stmt.order_by(FinancialTransaction.transaction_id))
    return cast(Sequence[FinancialTransaction], result.scalars().all())


async def _load_cargo_invoices(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, lower: datetime, upper: datetime, notes: FeedNotes
) -> tuple[CargoInvoice, ...]:
    """Dönemin siparişlerine dokunan faturaların TÜM kalemleri.

    Fatura KDV tespiti (K08) fatura toplamını kalem toplamıyla karşılaştırır; yalnız dönemdeki siparişlerin
    kalemleri verilirse fatura eksik görünür ve tespit "bilinmiyor"a düşerdi.
    """
    touched = aliased(CargoInvoiceItemRow)
    serials = (
        select(touched.invoice_serial_number)
        .where(
            touched.tenant_id == tenant_id,
            touched.marketplace_account_id == account_id,
            _order_number_in_period(
                touched.order_number, touched.marketplace_account_id, tenant_id, account_id, lower, upper
            ),
        )
        .scalar_subquery()
    )
    rows = (
        (
            await db.execute(
                select(CargoInvoiceItemRow)
                .where(
                    CargoInvoiceItemRow.tenant_id == tenant_id,
                    CargoInvoiceItemRow.marketplace_account_id == account_id,
                    CargoInvoiceItemRow.invoice_serial_number.in_(serials),
                )
                .order_by(CargoInvoiceItemRow.invoice_serial_number, CargoInvoiceItemRow.item_key)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[CargoInvoiceItem]] = defaultdict(list)
    for row in rows:
        if not row.order_number:
            notes.cargo_items_unmatched += 1
            continue
        grouped[row.invoice_serial_number].append(
            CargoInvoiceItem(row.shipment_package_type or "", row.order_number, row.amount, row.desi or 0)
        )
    return tuple(CargoInvoice(serial, tuple(items)) for serial, items in grouped.items())


async def _load_claims(
    db: AsyncSession, tenant_id: UUID, account_id: UUID, lower: datetime, upper: datetime, notes: FeedNotes
) -> tuple[Claim, ...]:
    rows = (
        (
            await db.execute(
                select(Return)
                .where(
                    Return.tenant_id == tenant_id,
                    Return.marketplace_account_id == account_id,
                    _order_number_in_period(
                        Return.order_number,
                        Return.marketplace_account_id,
                        tenant_id,
                        account_id,
                        lower,
                        upper,
                    ),
                )
                .order_by(Return.order_number, Return.claim_id, Return.claim_item_id)
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[str, list[ClaimItem]] = defaultdict(list)
    for row in rows:
        if not row.order_number or not row.order_line_item_id:
            notes.claim_items_unmatched += 1
            continue
        grouped[row.order_number].append(
            ClaimItem(row.order_line_item_id, row.status or "", row.returned_to_stock)
        )
    return tuple(Claim(number, tuple(items)) for number, items in grouped.items())
