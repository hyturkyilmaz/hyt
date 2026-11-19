"""Kimlik doğrulama iş mantığı. RLS dışı yol yalnız `auth_gate` işlevleri üzerindendir."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import PasswordWorker, generate_token, hash_token
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


async def touch_session(db: AsyncSession, session_id: UUID) -> None:
    """Boşta süresini uzatır. RLS bağlamı ayarlı olmalı.

    Zaman damgası veritabanı saatinden (`now()`) gelir: uygulama saati kayık olsa da 0023 tetikleyicisinin
    `now() + 5 dk` sınırına takılmaz. GREATEST: eşzamanlı iki istekte geç commit eden eski değer
    `last_seen_at`'i geriye çekemez (tetikleyici geri gitmeyi reddeder).
    """
    await db.execute(
        update(SessionRecord)
        .where(SessionRecord.id == session_id)
        .values(last_seen_at=func.greatest(SessionRecord.last_seen_at, func.now()))
    )


async def revoke_session(db: AsyncSession, session_id: UUID) -> None:
    """Oturumu iptal eder (kayıt silinmez). İptal zamanı veritabanı saatindendir (tetikleyici penceresi)."""
    await db.execute(
        update(SessionRecord)
        .where(SessionRecord.id == session_id, SessionRecord.revoked_at.is_(None))
        .values(revoked_at=func.now())
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


@dataclass(frozen=True)
class PasswordResetResult:
    """Başarılı parola sıfırlamanın sonucu."""

    user_id: UUID
    tenant_id: UUID | None
    # Hesap doğrulanmamıştı: sıfırlama e-postayı doğruladı ve TOTP'yi temizledi (denetim O-06).
    claimed_unverified: bool


async def consume_password_reset(
    db: AsyncSession, token: str, new_password_hash: str
) -> PasswordResetResult | None:
    """Token geçerliyse parolayı değiştirir ve tüm oturumları iptal eder.

    Doğrulanmış hesapta TOTP korunur. Doğrulanmamış hesapta e-posta sahipliği kanıtlandığı için hesap
    doğrulanır ve (olası saldırgan) TOTP temizlenir; karar auth_gate işlevinde, tek işlemde verilir.
    """
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
    return PasswordResetResult(
        user_id=row["reset_user_id"],
        tenant_id=row["reset_tenant_id"],
        claimed_unverified=bool(row["reset_claimed_unverified"]),
    )


async def create_email_verification(db: AsyncSession, user_id: UUID, ttl_minutes: int) -> str | None:
    """Doğrulanmamış kullanıcı için tek kullanımlık token üretir (yalnız özeti saklanır).

    Dönüş: ham token; kullanıcı zaten doğrulanmışsa (veya yoksa) None. Eski açık token'lar kapanır.
    """
    token = generate_token()
    created = (
        await db.execute(
            text("SELECT auth_gate.create_email_verification(:u, :h, :t)"),
            {"u": user_id, "h": hash_token(token), "t": ttl_minutes},
        )
    ).scalar_one()
    return token if created else None


async def consume_email_verification(
    db: AsyncSession, token: str, user_id: UUID
) -> tuple[UUID, UUID | None] | None:
    """Token geçerliyse VE `user_id`'ye aitse e-postayı doğrulanmış işaretler.

    Başkasının token'ı tüketilmez ve sonuç geçersiz token ile aynıdır (None). Dönüş: (user_id, tenant_id).
    """
    row = (
        (
            await db.execute(
                text("SELECT * FROM auth_gate.consume_email_verification(:h, :u)"),
                {"h": hash_token(token), "u": user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return row["verified_user_id"], row["verified_tenant_id"]


async def is_email_verified(db: AsyncSession, user_id: UUID) -> bool:
    """Kullanıcının e-postası doğrulanmış mı. RLS bağlamında app.user_id ayarlı olmalı."""
    verified_at = (
        await db.execute(select(User.email_verified_at).where(User.id == user_id))
    ).scalar_one_or_none()
    return verified_at is not None


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


async def verify_account_password(
    db: AsyncSession, passwords: PasswordWorker, email: str, password: str
) -> bool:
    """Oturumdaki hesabın güncel parolasını doğrular (yeniden kimlik doğrulama; özet auth_gate'ten okunur)."""
    candidate = await find_user_for_login(db, email)
    if candidate is None:
        await passwords.burn(password)
        return False
    return await passwords.verify(candidate.password_hash, password)


async def replace_recovery_codes(db: AsyncSession, user_id: UUID, code_hashes: list[str]) -> None:
    """Önceki etkin kodları geçersiz kılar (silmez) ve yenilerini ekler. RLS bağlamı ayarlı olmalı.

    Kullanıcı satırı önce kilitlenir: eşzamanlı iki yenileme sırayla çalışır, 20 etkin kod kalmaz.
    """
    await db.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": user_id})
    await db.execute(
        text(
            "UPDATE mfa_recovery_codes SET revoked_at = now() "
            "WHERE user_id = :u AND used_at IS NULL AND revoked_at IS NULL"
        ),
        {"u": user_id},
    )
    for code_hash in code_hashes:
        await db.execute(
            text("INSERT INTO mfa_recovery_codes (user_id, code_hash) VALUES (:u, :h)"),
            {"u": user_id, "h": code_hash},
        )


async def revoke_recovery_codes(db: AsyncSession, user_id: UUID) -> None:
    """TOTP kapatılırken tüm etkin kurtarma kodlarını geçersiz kılar (silmez)."""
    await db.execute(
        text(
            "UPDATE mfa_recovery_codes SET revoked_at = now() "
            "WHERE user_id = :u AND used_at IS NULL AND revoked_at IS NULL"
        ),
        {"u": user_id},
    )


async def consume_recovery_code(db: AsyncSession, user_id: UUID, code_hash: str) -> bool:
    """Kurtarma kodunu atomik tüketir: koşullu UPDATE ile eşzamanlı denemelerde yalnız biri kazanır."""
    row = await db.execute(
        text(
            "UPDATE mfa_recovery_codes SET used_at = now() "
            "WHERE user_id = :u AND code_hash = :h AND used_at IS NULL AND revoked_at IS NULL "
            "RETURNING id"
        ),
        {"u": user_id, "h": code_hash},
    )
    return row.first() is not None


async def count_recovery_codes(db: AsyncSession, user_id: UUID) -> int:
    """Kullanılabilir (kullanılmamış ve geçersiz kılınmamış) kurtarma kodu sayısı."""
    return int(
        (
            await db.execute(
                text(
                    "SELECT count(*) FROM mfa_recovery_codes "
                    "WHERE user_id = :u AND used_at IS NULL AND revoked_at IS NULL"
                ),
                {"u": user_id},
            )
        ).scalar_one()
    )


async def revoke_other_sessions(db: AsyncSession, user_id: UUID, keep_session_id: UUID) -> int:
    """Geçerli oturum dışındaki tüm oturumları iptal eder (auth_gate; RLS bağlamı ayarlı olmalı)."""
    return int(
        (
            await db.execute(
                text("SELECT auth_gate.revoke_other_sessions(:u, :k)"), {"u": user_id, "k": keep_session_id}
            )
        ).scalar_one()
    )
