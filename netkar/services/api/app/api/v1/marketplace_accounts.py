"""/v1/marketplace-accounts: pazaryeri (Trendyol) bağlantıları.

Yanıtlarda API anahtarı ve sırrı hiçbir zaman yer almaz (yalnız son 4 hane). Anahtarlar
zarf şifreleme (AES-256-GCM, DEK/KEK, ADR-0004) ile şifrelenir. Ekleme, Trendyol'a doğrulama çağrısı yapar ve başarısızsa hiçbir şey
kaydetmez. İptal satırı silmez, şifreli alanları boşaltır.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    DbDep,
    EnvelopeDep,
    JobQueueDep,
    RateLimiterDep,
    SettingsDep,
    TrendyolFactoryDep,
    ip_hash_for,
    require_role,
)
from app.api.v1.schemas import MarketplaceAccountCreate, MarketplaceAccountOut
from app.core.errors import ProblemError
from app.core.ratelimit import digest
from app.db.rls import set_rls_context
from app.integrations.trendyol import TrendyolConfigError, TrendyolCredentials, TrendyolError
from app.models import MarketplaceAccount, MarketplaceAccountStatus, Platform, Role
from app.services.audit import record_audit
from app.services.auth import AuthContext
from app.services.marketplace_accounts import (
    encrypt_secret,
    find_live_account,
    problem_for_trendyol,
    verify_with_deadline,
)

logger = logging.getLogger("netkar.marketplace")

router = APIRouter(prefix="/marketplace-accounts", tags=["marketplace-accounts"])

AdminDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN))]
AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]

_HOURLY = 60 * 60


def _conflict() -> ProblemError:
    return ProblemError(
        409,
        "Bağlantı zaten var",
        "marketplace-account-exists",
        "Bu satıcı için kiracıda etkin bir bağlantı zaten var.",
    )


@router.post("", status_code=201, response_model=MarketplaceAccountOut)
async def connect_account(
    body: MarketplaceAccountCreate,
    request: Request,
    ctx: AdminDep,
    db: DbDep,
    settings: SettingsDep,
    envelope: EnvelopeDep,
    limiter: RateLimiterDep,
    factory: TrendyolFactoryDep,
    queue: JobQueueDep,
) -> MarketplaceAccount:
    """Trendyol bağlantısı ekler: anahtarlar önce Trendyol'da doğrulanır, geçerliyse şifreli saklanır."""
    try:
        # Aşağıdaki satır sabit sır değil, istek gövdesinden değişken aktarımıdır (gitleaks yanlış pozitif).
        credentials = TrendyolCredentials(
            seller_id=body.seller_id,
            api_key=body.api_key,  # gitleaks:allow
            api_secret=body.api_secret,  # gitleaks:allow
        )
    except TrendyolConfigError:
        raise ProblemError(
            422,
            "Bağlantı bilgileri geçersiz",
            "marketplace-credentials-malformed",
            "API anahtarı ve sırrı yalnız boşluksuz ASCII karakterlerden oluşmalı; anahtarda ':' olamaz.",
        ) from None

    # Trendyol'a giden her deneme sayılır (IP sınırı ara katmanda, kiracı sınırı burada).
    await limiter.hit(
        f"marketplace-connect:tenant:{digest(settings.master_key, 'rl-tenant', str(ctx.tenant_id))}",
        settings.rate_limit_marketplace_tenant,
        _HOURLY,
    )
    # Platform geneli tavan (tüm kiracılar, tek çıkış IP'si): kiracı sınırından SONRA denetlenir ki tek
    # kiracı kendi sınırında durup genel sayacı tüketmesin. Aşımda Trendyol'a gidilmez, 503 döner.
    try:
        await limiter.hit("marketplace-connect:global", settings.rate_limit_marketplace_global_per_minute, 60)
    except ProblemError as exc:
        raise ProblemError(
            503,
            "Trendyol bağlantıları şu an yoğun",
            "marketplace-busy",
            "Şu an çok sayıda bağlantı denemesi var. Kısa süre sonra tekrar deneyin.",
            headers={"Retry-After": exc.headers.get("Retry-After", "30")},
        ) from None
    ip_hash = ip_hash_for(request, settings)

    # Etkin bağlantı varsa Trendyol'a hiç gitmeden 409.
    existing = await find_live_account(db, ctx.tenant_id, credentials.seller_id)
    if existing is not None and existing.status == MarketplaceAccountStatus.ACTIVE.value:
        raise _conflict()

    # Dış çağrı sırasında veritabanı bağlantısını/işlemini tutmayız; sonra bağlam yeniden kurulur.
    await db.rollback()
    try:
        check = await verify_with_deadline(factory, credentials, settings)
    except TrendyolError as exc:
        problem, reason = problem_for_trendyol(exc)
        await set_rls_context(db, ctx.tenant_id, ctx.user_id)
        await record_audit(
            db,
            ctx.tenant_id,
            "marketplace_account.validation_failed",
            user_id=ctx.user_id,
            target=f"{Platform.TRENDYOL.value}:{credentials.seller_id}",
            ip_hash=ip_hash,
            meta={"reason": reason},
        )
        await db.commit()
        raise problem from None

    now = datetime.now(UTC)
    await set_rls_context(db, ctx.tenant_id, ctx.user_id)
    # Doğrulama sırasında başka bir istek bağlantıyı eklemiş olabilir: kilitli yeniden okuma.
    account = await find_live_account(db, ctx.tenant_id, credentials.seller_id)
    if account is not None and account.status == MarketplaceAccountStatus.ACTIVE.value:
        raise _conflict()
    action = "marketplace_account.reconnected"
    if account is None:
        action = "marketplace_account.connected"
        account = MarketplaceAccount(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            platform=Platform.TRENDYOL.value,
            seller_id=credentials.seller_id,
            created_by=ctx.user_id,
            status=MarketplaceAccountStatus.ACTIVE.value,
        )
        db.add(account)
    account.api_key_encrypted = encrypt_secret(envelope, account, "api_key", body.api_key)
    account.api_secret_encrypted = encrypt_secret(envelope, account, "api_secret", body.api_secret)
    account.api_key_last4 = body.api_key.get_secret_value()[-4:]
    account.status = MarketplaceAccountStatus.ACTIVE.value
    account.last_validated_at = now
    account.updated_at = now
    try:
        await db.flush()
    except IntegrityError:
        # Eşzamanlı ekleme: kısmi tekil indeks ikinci kaydı reddetti.
        await db.rollback()
        raise _conflict() from None
    await record_audit(
        db,
        ctx.tenant_id,
        action,
        user_id=ctx.user_id,
        target=str(account.id),
        ip_hash=ip_hash,
        meta={"platform": Platform.TRENDYOL.value, "total_products": check.total_products},
    )
    await db.commit()
    # Bağlantı kalıcı olduktan SONRA ilk yükleme kuyruğa girer. Kuyruk hatası bağlantıyı bozmaz:
    # planlayıcı backfill'i eksik etkin hesabı bir sonraki turda kuyruğa alır (ADR-0005 §4).
    try:
        await queue.enqueue_backfill(account.id)
    except Exception as exc:
        logger.warning(
            "backfill kuyruğa eklenemedi",
            extra={"account_id": str(account.id), "error_class": type(exc).__name__},
        )
    return account


@router.get("", response_model=list[MarketplaceAccountOut])
async def list_accounts(ctx: AnyRoleDep, db: DbDep) -> list[MarketplaceAccount]:
    """Kiracının bağlantıları (maskeli). Şifreli alanlar sorguya hiç girmez (deferred)."""
    rows = await db.execute(
        select(MarketplaceAccount)
        .where(MarketplaceAccount.tenant_id == ctx.tenant_id)
        .order_by(MarketplaceAccount.created_at.desc())
    )
    return list(rows.scalars())


@router.post("/{account_id}/revoke", response_model=MarketplaceAccountOut)
async def revoke_account(
    account_id: UUID, request: Request, ctx: AdminDep, db: DbDep, settings: SettingsDep
) -> MarketplaceAccount:
    """Bağlantıyı iptal eder: durum revoked, şifreli anahtarlar NULL; satır silinmez. İdempotenttir.

    Trendyol'daki anahtar bu işlemle iptal olmaz: satıcı anahtarı Trendyol panelinden de silmelidir.
    """
    account = (
        await db.execute(
            select(MarketplaceAccount)
            .where(MarketplaceAccount.id == account_id, MarketplaceAccount.tenant_id == ctx.tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if account is None:
        raise ProblemError(404, "Bulunamadı", "not-found")
    if account.status == MarketplaceAccountStatus.REVOKED.value:
        return account
    now = datetime.now(UTC)
    account.api_key_encrypted = None
    account.api_secret_encrypted = None
    account.status = MarketplaceAccountStatus.REVOKED.value
    account.revoked_at = now
    account.updated_at = now
    await db.flush()
    await record_audit(
        db,
        ctx.tenant_id,
        "marketplace_account.revoked",
        user_id=ctx.user_id,
        target=str(account.id),
        ip_hash=ip_hash_for(request, settings),
        meta={"platform": account.platform},
    )
    await db.commit()
    return account
