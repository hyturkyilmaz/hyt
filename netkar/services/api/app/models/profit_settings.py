"""Kâr ayarları için ORM eşlemeleri (şema gerçeği migrasyon 0007 ve 0008'dedir, ADR-0006, ADR-0007).

Üç sürümlü tablo (tarife, hizmet bedeli, değişken gider) DEĞİŞMEZ kayıttır (K42): iş alanları bir kez yazılır;
yalnız kapanış sütunları (`revision_to`, `ended_at`, `ended_by`, `end_reason`) güncellenir ve `netkar_app`
satır silemez. `updated_at` sütunu eski şemadan kalmıştır, artık yazılmaz.

Tutarlar kullanıcı beyanıdır: KDV dahil mi hariç mi girildiği kayıtta saklanır (`*_includes_vat`) ve motora
verilirken K02 ile KDV hariçe çevrilir (`app.services.profit_settings`). Para `numeric(18,6)`, oran
`numeric(9,4)`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.trendyol_data import _AccountScoped

_NOW = func.now()


class _Versioned:
    """Sürüm aralığı ve kapanış sütunları (migrasyon 0008). Etkin satır: `revision_to IS NULL`."""

    revision_from: Mapped[int] = mapped_column(BigInteger)
    revision_to: Mapped[int | None] = mapped_column(BigInteger)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    end_reason: Mapped[str | None] = mapped_column(Text)


class ProfitSettingsRecord(_AccountScoped, Base):
    """Hesap başına tek satır: varsayılan desi ve ayar sürüm sayacı (`revision`)."""

    __tablename__ = "profit_settings"

    default_desi: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    revision: Mapped[int] = mapped_column(BigInteger, server_default="1")
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class CargoTariffRecord(_Versioned, _AccountScoped, Base):
    """Kargo tarifesi sürümü: anlaşma x firma x geçerlilik başlangıcı; kademeler metin tutarlı jsonb."""

    __tablename__ = "cargo_tariffs"

    agreement: Mapped[str] = mapped_column(Text)
    carrier: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date)
    price_includes_vat: Mapped[bool] = mapped_column(Boolean)
    brackets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ServiceFeeEstimateRecord(_Versioned, _AccountScoped, Base):
    """Platform hizmet bedeli tahmini sürümü (sipariş başı tutar)."""

    __tablename__ = "service_fee_estimates"

    valid_from: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    amount_includes_vat: Mapped[bool] = mapped_column(Boolean)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class VariableExpenseRecord(_Versioned, _AccountScoped, Base):
    """Kullanıcı tanımlı değişken gider (KDV hariç tutar ya da satış yüzdesi), geçerlilik aralıklı."""

    __tablename__ = "variable_expenses"

    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    amount_excl_vat: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    entered_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    replaces_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ProfitSettingsChange(_AccountScoped, Base):
    """Ayar günlüğü: ayar sürümü başına tek kayıt (K42). Tutar taşımaz; varsayılan desi istisnadır."""

    __tablename__ = "profit_settings_changes"

    revision: Mapped[int] = mapped_column(BigInteger)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    item: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    replaced_record_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    affects_from: Mapped[date | None] = mapped_column(Date)
    affects_past: Mapped[bool] = mapped_column(Boolean)
    past_change_confirmed: Mapped[bool] = mapped_column(Boolean, server_default="false")
    default_desi_before: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    default_desi_after: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
