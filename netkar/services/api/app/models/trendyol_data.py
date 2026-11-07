"""Trendyol verisi ve senkron durumu için ORM eşlemeleri (şema gerçeği migrasyon 0006'dadır, ADR-0005).

Hiçbir tabloda son müşteriye ait ad, adres, telefon, TCKN veya e-posta sütunu YOKTUR (KVKK, EK-6).
Para alanları NUMERIC(18,6), oranlar NUMERIC(9,4): Trendyol'un kuruş altı tutarları kayıpsız saklanır.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

_NOW = func.now()


def _money() -> Any:
    return Numeric(18, 6)


def _rate() -> Any:
    return Numeric(9, 4)


class _AccountScoped:
    """Ortak sütunlar: kimlik, kiracı ve pazaryeri hesabı (RLS: tenant_id)."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))


class Product(_AccountScoped, Base):
    """Katalog ürünü (varyant başına bir satır; anahtar barkod)."""

    __tablename__ = "products"

    barcode: Mapped[str] = mapped_column(Text)
    stock_code: Mapped[str | None] = mapped_column(Text)
    content_id: Mapped[int | None] = mapped_column(BigInteger)
    product_main_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(BigInteger)
    category_name: Mapped[str | None] = mapped_column(Text)
    vat_rate: Mapped[Decimal | None] = mapped_column(_rate())
    commission_rate: Mapped[Decimal | None] = mapped_column(_rate())
    unit_desi: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ProductCost(_AccountScoped, Base):
    """Geçerlilik tarihli birim maliyet (KDV hariç). Kullanıcı girer; boş başlar."""

    __tablename__ = "product_costs"

    barcode: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    unit_cost_excl_vat: Mapped[Decimal] = mapped_column(_money())
    vat_rate: Mapped[Decimal] = mapped_column(_rate())
    entered_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Order(_AccountScoped, Base):
    """Sipariş paketi (Trendyol `shipmentPackageId` başına bir satır). Müşteri verisi yok; yalnız il."""

    __tablename__ = "orders"

    order_number: Mapped[str] = mapped_column(Text)
    shipment_package_id: Mapped[int] = mapped_column(BigInteger)
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default="Unknown")
    carrier: Mapped[str | None] = mapped_column(Text)
    cargo_tracking_number: Mapped[str | None] = mapped_column(Text)
    cargo_deci: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    deci: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    who_pays: Mapped[int | None] = mapped_column(SmallInteger)
    commercial: Mapped[bool | None] = mapped_column(Boolean)
    province: Mapped[str | None] = mapped_column(Text)
    province_code: Mapped[int | None] = mapped_column(Integer)
    customer_key: Mapped[str | None] = mapped_column(Text)
    package_gross_amount: Mapped[Decimal | None] = mapped_column(_money())
    package_seller_discount: Mapped[Decimal | None] = mapped_column(_money())
    package_ty_discount: Mapped[Decimal | None] = mapped_column(_money())
    package_total_price: Mapped[Decimal | None] = mapped_column(_money())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class OrderLine(_AccountScoped, Base):
    """Sipariş satırı. `items`: adet başına indirim kırılımı (discountDetails)."""

    __tablename__ = "order_lines"

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    line_id: Mapped[int] = mapped_column(BigInteger)
    barcode: Mapped[str] = mapped_column(Text)
    stock_code: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(Integer)
    line_gross_amount: Mapped[Decimal] = mapped_column(_money())
    line_seller_discount: Mapped[Decimal] = mapped_column(_money(), server_default="0")
    line_ty_discount: Mapped[Decimal] = mapped_column(_money(), server_default="0")
    vat_rate: Mapped[Decimal | None] = mapped_column(_rate())
    commission_rate: Mapped[Decimal | None] = mapped_column(_rate())
    status: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list[dict[str, str]]] = mapped_column(JSONB, server_default="[]")
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class Return(_AccountScoped, Base):
    """İade kalemi (`claimItems[]` başına bir satır)."""

    __tablename__ = "returns"

    claim_id: Mapped[str] = mapped_column(Text)
    claim_item_id: Mapped[str] = mapped_column(Text)
    order_number: Mapped[str | None] = mapped_column(Text)
    shipment_package_id: Mapped[int | None] = mapped_column(BigInteger)
    order_line_id: Mapped[int | None] = mapped_column(BigInteger)
    order_line_item_id: Mapped[str | None] = mapped_column(Text)
    barcode: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    claim_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_accepted: Mapped[bool | None] = mapped_column(Boolean)
    accepted_by_seller: Mapped[bool | None] = mapped_column(Boolean)
    returned_to_stock: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class FinancialTransaction(_AccountScoped, Base):
    """Cari hesap ekstresi satırı (settlements ve otherfinancials)."""

    __tablename__ = "financial_transactions"

    source: Mapped[str] = mapped_column(Text)
    request_type: Mapped[str] = mapped_column(Text)
    request_sub_type: Mapped[str] = mapped_column(Text, server_default="")
    transaction_id: Mapped[str] = mapped_column(Text)
    type_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    transaction_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    barcode: Mapped[str | None] = mapped_column(Text)
    order_number: Mapped[str | None] = mapped_column(Text)
    shipment_package_id: Mapped[int | None] = mapped_column(BigInteger)
    payment_order_id: Mapped[int | None] = mapped_column(BigInteger)
    receipt_id: Mapped[int | None] = mapped_column(BigInteger)
    debt: Mapped[Decimal] = mapped_column(_money(), server_default="0")
    credit: Mapped[Decimal] = mapped_column(_money(), server_default="0")
    commission_rate: Mapped[Decimal | None] = mapped_column(_rate())
    commission_amount: Mapped[Decimal | None] = mapped_column(_money())
    seller_revenue: Mapped[Decimal | None] = mapped_column(_money())
    commission_invoice_serial_number: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class CargoInvoiceItem(_AccountScoped, Base):
    """Kargo faturası kalemi (sipariş numarası düzeyinde)."""

    __tablename__ = "cargo_invoice_items"

    invoice_serial_number: Mapped[str] = mapped_column(Text)
    item_key: Mapped[str] = mapped_column(Text)
    shipment_package_type: Mapped[str | None] = mapped_column(Text)
    parcel_unique_id: Mapped[int | None] = mapped_column(BigInteger)
    order_number: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(_money())
    desi: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SyncRun(_AccountScoped, Base):
    """Bir kaynağın bir senkron adımı: pencere, durum, sayaçlar, hata SINIFI (gövde ve ileti yok)."""

    __tablename__ = "sync_runs"

    run_group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    windows_total: Mapped[int] = mapped_column(Integer, server_default="0")
    windows_done: Mapped[int] = mapped_column(Integer, server_default="0")
    fetched_count: Mapped[int] = mapped_column(Integer, server_default="0")
    upserted_count: Mapped[int] = mapped_column(Integer, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, server_default="0")
    error_class: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SyncCursor(Base):
    """Kaynak başına son başarılı pencere (watermark) ve backfill tamamlanma zamanı."""

    __tablename__ = "sync_cursors"

    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
