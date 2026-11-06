"""ORM modelleri. Şema gerçeği Alembic migrasyonlarındadır; burası okuma/yazma eşlemesidir."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base
from app.models.enums import Role

_NOW = func.now()


class Tenant(Base):
    """Satıcı firma (hesap). RLS: yalnız kendi satırı."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3))
    locale: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class User(Base):
    """Kullanıcı. password_hash uygulama rolüne açık değildir (yalnız auth_gate işlevleri okur)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(Text)
    # Sütun yetkisi olmadığı için hiçbir zaman yüklenmez.
    password_hash: Mapped[str] = deferred(mapped_column(Text))
    totp_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    # Son başarılı TOTP zaman adımı (tekrar kullanım koruması) ve kaba kuvvet kilidi.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    totp_failed_count: Mapped[int] = mapped_column(Integer, server_default="0")
    totp_locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base):
    """Kullanıcının kiracıdaki rolü. RLS: tenant_id."""

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="membership_role", values_callable=lambda e: [m.value for m in e], create_type=False)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class SessionRecord(Base):
    """Sunucu tarafı oturum. Token'ın yalnız SHA-256 özeti saklanır. RLS: tenant_id."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_hash: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_hash: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    """Eklemeli (append-only) denetim izi. Kişisel veri içermez. RLS: tenant_id."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text)
    target: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")


class RateLimit(Base):
    """Sabit pencere sayaçları (kiracıdan bağımsız, kişisel veri yok)."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
