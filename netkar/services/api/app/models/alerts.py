"""Uyarı olayları ve bildirim tabloları için ORM eşlemeleri (şema gerçeği migrasyon 0025'tedir, ADR-0009 §4).

Kritik kurallar veritabanındadır; bu sınıflar yalnız okuma ve ekleme için sütun haritasıdır:

- `AlertEvent` kimlik sütunları değişmez; `status`, `muted_until`, `resolved_at` yalnız `AlertEventTransition`
  satırı eklenince (veritabanı tetikleyicisiyle) değişir. Uygulama rolü (`netkar_app`) olay tablosuna yazamaz.
- `AlertEventTransition` yalnız ekleme defteridir; `from_status`, `actor`, `actor_user_id`, `id`, `created_at`
  sunucuda türetilir (istemci yalnız `tenant_id`, `alert_event_id`, `to_status`, `muted_until` verir).
- `NotificationOutbox` e-posta adresi SAKLAMAZ (gönderimde `notify_gate.email_for`); yalnız worker yazar.
- `PushSubscription` şifreli sütunları (`*_enc`) yalnız worker okur; `netkar_app` okuyamaz.
- Yeni tablolar `report_data_revisions` veri sürümü tetikleyici listesinde DEĞİLDİR (döngü riski).

Tutarlar `numeric(14,2)` (eşikler, bildirilen tutar); olay yükü (`payload`) tutarları metin olarak taşır.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    FetchedValue,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    Time,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.trendyol_data import _AccountScoped

_NOW = func.now()


def _uuid_pk() -> Any:
    """Birincil anahtar: değeri VERİTABANI üretir (`gen_random_uuid()`); ORM `RETURNING` ile okur.

    Olay ve geçiş tablolarında BEFORE INSERT tetikleyicisi `id`'yi zaten sunucuda yeniden üretir: istemci
    tarafı `default=uuid.uuid4` ORM'nin tuttuğu kimlikle satırın gerçek kimliğini ayırırdı.
    """
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())


class AlertEvent(_AccountScoped, Base):
    """Kalıcı uyarı olayı (kural x kapsam x konu başına tek satır; `dedupe_key` kiracı+hesapla benzersiz)."""

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = _uuid_pk()

    rule: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    occurrence_count: Mapped[int] = mapped_column(Integer, server_default="1")
    severity: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="open")
    muted_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    payload_version: Mapped[int] = mapped_column(SmallInteger)
    data_revision: Mapped[int] = mapped_column(BigInteger)
    settings_revision: Mapped[int] = mapped_column(BigInteger)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notified_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Zarar kuralı: toplam zarar 2 katına çıkınca YALNIZ BİR KEZ daha bildirilir (ADR-0009 §3.1).
    renotified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notify_mode: Mapped[str] = mapped_column(Text, server_default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class AlertEventTransition(Base):
    """Durum geçişi defteri (yalnız ekleme): olay durumunun tek değişiklik yolu."""

    __tablename__ = "alert_event_transitions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    alert_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_status: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    to_status: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text, server_default=FetchedValue())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), server_default=FetchedValue()
    )
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class AlertRuleSettings(Base):
    """Hesap başına bildirim eşikleri ve etkin kurallar (yazma: owner/admin)."""

    __tablename__ = "alert_rule_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    marketplace_account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    loss_min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="5.00")
    ad_share_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="100")
    ad_min_spend: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="50.00")
    deduction_notify_min: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="10.00")
    return_min_diff_points: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default="5")
    rules_enabled: Mapped[list[str]] = mapped_column(ARRAY(Text))
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class NotificationPreference(Base):
    """Kullanıcı x kural x kanal tercihi (`off`, `instant`, `digest`)."""

    __tablename__ = "notification_preferences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    rule: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text, primary_key=True)
    mode: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class NotificationSettings(Base):
    """Kullanıcı başına sessiz saatler (Europe/Istanbul), özet saati ve tutar gösterim tercihleri."""

    __tablename__ = "notification_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    quiet_start: Mapped[time] = mapped_column(Time, server_default="22:00")
    quiet_end: Mapped[time] = mapped_column(Time, server_default="08:00")
    digest_hour: Mapped[int] = mapped_column(SmallInteger, server_default="8")
    show_amounts_email: Mapped[bool] = mapped_column(Boolean, server_default="true")
    show_amounts_push: Mapped[bool] = mapped_column(Boolean, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class PushSubscription(Base):
    """Web push aboneliği. `*_enc` sütunları ADR-0004 zarf şifreli cihaz tanımlayıcısıdır (iptalde NULL)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    endpoint_host: Mapped[str] = mapped_column(Text)
    endpoint_digest: Mapped[str] = mapped_column(Text)
    # Yalnız worker okur (uygulama rolünde bu üç sütunda SELECT yok): yüklenmesi gerekmedikçe `deferred`.
    endpoint_enc: Mapped[str | None] = mapped_column(Text, deferred=True)
    p256dh_enc: Mapped[str | None] = mapped_column(Text, deferred=True)
    auth_enc: Mapped[str | None] = mapped_column(Text, deferred=True)
    vapid_key_id: Mapped[str] = mapped_column(Text)
    created_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sessions.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )
    failure_count: Mapped[int] = mapped_column(Integer, server_default="0")
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )


class NotificationOutbox(Base):
    """İşlemsel giden kutusu. Alıcı adresi YOKTUR: gönderim anında `notify_gate.email_for` ile çözülür."""

    __tablename__ = "notification_outbox"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)
    alert_event_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), server_default="{}")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    not_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_error_class: Mapped[str | None] = mapped_column(Text, server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=FetchedValue())


class AlertEvaluation(_AccountScoped, Base):
    """Değerlendirme günlüğü (idempotent anahtar: hesap, gün, veri/ayar/kural sürümü)."""

    __tablename__ = "alert_evaluations"

    id: Mapped[uuid.UUID] = _uuid_pk()

    as_of_date: Mapped[date] = mapped_column(Date)
    data_revision: Mapped[int] = mapped_column(BigInteger)
    settings_revision: Mapped[int] = mapped_column(BigInteger)
    rules_version: Mapped[int] = mapped_column(Integer)
    # Yeniden deneme sırası (1-3; migrasyon 0026): `failed` anahtar 3 denemeye kadar yeni satırla denenir.
    attempt: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )
    status: Mapped[str] = mapped_column(Text, server_default="running")
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
