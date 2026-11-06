"""Kimlik doğrulama iş mantığı. RLS dışı yol yalnız `auth_gate` işlevleri üzerindendir."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import or_, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import generate_token, hash_token
from app.models import Role, SessionRecord, User

# last_seen_at her istekte yazılmaz; bu kadar saniyeden eskiyse tazelenir.
TOUCH_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class AuthContext:
    """Doğrulanmış istek bağlamı."""

    user_id: UUID
    tenant_id: UUID
    role: Role
    session_id: UUID


@dataclass(frozen=True)
class LoginCandidate:
    """auth_gate.find_user_for_login sonucu."""

    user_id: UUID
    password_hash: str
    totp_enabled: bool
    tenant_id: UUID | None


async def find_user_for_login(db: AsyncSession, email: str) -> LoginCandidate | None:
    """E-postayla kullanıcıyı bulur (RLS dışı dar yol)."""
    row = (
        (await db.execute(text("SELECT * FROM auth_gate.find_user_for_login(:email)"), {"email": email}))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return LoginCandidate(
        user_id=row["user_id"],
        password_hash=row["password_hash"],
        totp_enabled=row["totp_enabled"],
        tenant_id=row["tenant_id"],
    )


async def register_account(
    db: AsyncSession, email: str, password_hash: str, tenant_name: str, trial_days: int
) -> tuple[UUID, UUID] | None:
    """Kullanıcı + kiracı + owner üyeliği oluşturur; e-posta varsa None döner."""
    row = (
        (
            await db.execute(
                text("SELECT * FROM auth_gate.register_account(:e, :h, :n, :d)"),
                {"e": email, "h": password_hash, "n": tenant_name, "d": trial_days},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return row["new_user_id"], row["new_tenant_id"]


async def create_session(
    db: AsyncSession,
    settings: Settings,
    user_id: UUID,
    tenant_id: UUID,
    ip_hash: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> str:
    """Oturum satırı ekler ve ham token'ı döndürür. RLS bağlamı tenant_id ile ayarlı olmalı."""
    current = now or datetime.now(UTC)
    token = generate_token()
    db.add(
        SessionRecord(
            token_hash=hash_token(token),
            user_id=user_id,
            tenant_id=tenant_id,
            created_at=current,
            last_seen_at=current,
            expires_at=current + timedelta(seconds=settings.session_absolute_seconds),
            ip_hash=ip_hash,
            user_agent=(user_agent or "")[:200] or None,
        )
    )
    await db.flush()
    return token


async def lookup_session(
    db: AsyncSession, settings: Settings, token: str, now: datetime | None = None
) -> tuple[AuthContext, datetime] | None:
    """Token özetinden geçerli oturumu bulur: iptal, mutlak ve boşta süre denetimi yapılır.

    Dönüş: (bağlam, last_seen_at). Geçersizse None.
    """
    current = now or datetime.now(UTC)
    row = (
        (await db.execute(text("SELECT * FROM auth_gate.get_session(:h)"), {"h": hash_token(token)}))
        .mappings()
        .first()
    )
    if row is None or row["revoked_at"] is not None:
        return None
    if row["expires_at"] <= current:
        return None
    if row["last_seen_at"] + timedelta(seconds=settings.session_idle_seconds) <= current:
        return None
    ctx = AuthContext(
        user_id=row["user_id"],
        tenant_id=row["tenant_id"],
        role=Role(row["role"]),
        session_id=row["session_id"],
    )
    return ctx, row["last_seen_at"]


async def touch_session(db: AsyncSession, session_id: UUID, now: datetime | None = None) -> None:
    """Boşta süresini uzatır. RLS bağlamı ayarlı olmalı."""
    await db.execute(
        update(SessionRecord)
        .where(SessionRecord.id == session_id)
        .values(last_seen_at=now or datetime.now(UTC))
    )


async def revoke_session(db: AsyncSession, session_id: UUID, now: datetime | None = None) -> None:
    """Oturumu iptal eder (kayıt silinmez)."""
    await db.execute(
        update(SessionRecord)
        .where(SessionRecord.id == session_id, SessionRecord.revoked_at.is_(None))
        .values(revoked_at=now or datetime.now(UTC))
    )


async def create_password_reset(db: AsyncSession, email: str, ttl_minutes: int) -> tuple[UUID, str] | None:
    """Kullanıcı varsa sıfırlama token'ı üretir. Dönüş: (user_id, ham token) veya None."""
    token = generate_token()
    user_id = (
        await db.execute(
            text("SELECT auth_gate.create_password_reset(:e, :h, :t)"),
            {"e": email, "h": hash_token(token), "t": ttl_minutes},
        )
    ).scalar_one()
    if user_id is None:
        return None
    return user_id, token


async def consume_password_reset(
    db: AsyncSession, token: str, new_password_hash: str
) -> tuple[UUID, UUID | None] | None:
    """Token geçerliyse parolayı değiştirir ve oturumları iptal eder. Dönüş: (user_id, tenant_id)."""
    row = (
        (
            await db.execute(
                text("SELECT * FROM auth_gate.consume_password_reset(:h, :p)"),
                {"h": hash_token(token), "p": new_password_hash},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return row["reset_user_id"], row["reset_tenant_id"]


async def consume_totp_step(db: AsyncSession, user_id: UUID, step: int) -> bool:
    """Eşleşen TOTP zaman adımını atomik olarak tüketir (denetim O-01).

    Yalnız saklı son adımdan DAHA YENİ bir adım kabul edilir; aynı veya eski adım (tekrar kullanım)
    ve eşzamanlı yarış kaybedenleri False alır. Başarıda kaba kuvvet sayacı da sıfırlanır.
    RLS bağlamında app.user_id ayarlı olmalı.
    """
    row = await db.execute(
        update(User)
        .where(User.id == user_id, or_(User.totp_last_step.is_(None), User.totp_last_step < step))
        .values(totp_last_step=step, totp_failed_count=0, totp_locked_until=None)
        .returning(User.id)
    )
    return row.first() is not None


_REGISTER_TOTP_FAILURE = text(
    """
    UPDATE users SET
        totp_failed_count = CASE
            WHEN totp_locked_until IS NOT NULL AND totp_locked_until <= now() THEN 1
            ELSE totp_failed_count + 1 END,
        totp_locked_until = CASE
            WHEN (CASE WHEN totp_locked_until IS NOT NULL AND totp_locked_until <= now() THEN 1
                       ELSE totp_failed_count + 1 END) >= :max_failures
            THEN now() + make_interval(secs => :lock_seconds)
            ELSE NULL END
    WHERE id = :user_id
    RETURNING totp_failed_count, totp_locked_until
    """
)


async def register_totp_failure(
    db: AsyncSession, user_id: UUID, max_failures: int, lock_seconds: int
) -> tuple[int, datetime | None]:
    """Başarısız TOTP denemesini sayar; eşik aşılırsa hesabı geçici kilitler (denetim O-02).

    Dönüş: (ardışık hata sayısı, kilit bitişi veya None). Güncelleme tek ifadedir (satır kilidi),
    eşzamanlı denemeler sayacı kaçıramaz. Süresi dolmuş kilitten sonra sayaç 1'den başlar.
    """
    row = (
        (
            await db.execute(
                _REGISTER_TOTP_FAILURE,
                {"user_id": user_id, "max_failures": max_failures, "lock_seconds": lock_seconds},
            )
        )
        .mappings()
        .one()
    )
    return int(row["totp_failed_count"]), row["totp_locked_until"]
