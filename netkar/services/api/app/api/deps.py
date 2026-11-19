"""FastAPI bağımlılıkları: ayarlar, DB oturumu, kimlik doğrulama ve rol denetimi."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clientip import ClientIpResolver
from app.core.config import Settings
from app.core.cookies import SESSION_COOKIE
from app.core.crypto import FieldCipher, hmac_hex
from app.core.email import EmailSender
from app.core.envelope import EnvelopeCipher
from app.core.errors import ProblemError
from app.core.pwned import PwnedPasswordChecker
from app.core.ratelimit import RateLimiter
from app.core.security import PasswordWorker
from app.db.rls import set_rls_context
from app.models import Role
from app.services.auth import (
    TOUCH_INTERVAL_SECONDS,
    AuthContext,
    is_email_verified,
    lookup_session,
    touch_session,
)
from app.services.import_gate import ImportGate
from app.services.legal import pending_documents
from app.services.marketplace_accounts import TrendyolClientFactory
from app.services.report_cache import ReportCache
from app.services.report_gate import ReportGate
from app.worker.queue import JobQueue


def get_settings_dep(request: Request) -> Settings:
    """create_app ile kurulan ayarlar."""
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """İstek başına DB oturumu. Commit, işleyicide açıkça yapılır; yapılmazsa geri alınır."""
    async with request.app.state.sessionmaker() as session:
        try:
            yield session
        finally:
            await session.rollback()


DbDep = Annotated[AsyncSession, Depends(get_db)]


def get_rate_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_email_sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender


def get_pwned_checker(request: Request) -> PwnedPasswordChecker:
    checker: PwnedPasswordChecker = request.app.state.pwned_checker
    return checker


def get_cipher(request: Request) -> FieldCipher:
    cipher: FieldCipher = request.app.state.cipher
    return cipher


def get_envelope(request: Request) -> EnvelopeCipher:
    envelope: EnvelopeCipher = request.app.state.envelope
    return envelope


def get_password_worker(request: Request) -> PasswordWorker:
    worker: PasswordWorker = request.app.state.password_worker
    return worker


def get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_import_gate(request: Request) -> ImportGate:
    gate: ImportGate = request.app.state.import_gate
    return gate


def get_report_gate(request: Request) -> ReportGate:
    gate: ReportGate = request.app.state.report_gate
    return gate


def get_report_cache(request: Request) -> ReportCache:
    cache: ReportCache = request.app.state.report_cache
    return cache


def get_trendyol_factory(request: Request) -> TrendyolClientFactory:
    factory: TrendyolClientFactory = request.app.state.trendyol_client_factory
    return factory


PasswordsDep = Annotated[PasswordWorker, Depends(get_password_worker)]
RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
PwnedDep = Annotated[PwnedPasswordChecker, Depends(get_pwned_checker)]
CipherDep = Annotated[FieldCipher, Depends(get_cipher)]
EnvelopeDep = Annotated[EnvelopeCipher, Depends(get_envelope)]
TrendyolFactoryDep = Annotated[TrendyolClientFactory, Depends(get_trendyol_factory)]
JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]
ImportGateDep = Annotated[ImportGate, Depends(get_import_gate)]
ReportGateDep = Annotated[ReportGate, Depends(get_report_gate)]
ReportCacheDep = Annotated[ReportCache, Depends(get_report_cache)]


def client_ip(request: Request) -> str:
    """İstemci IP'si (kova anahtarı). X-Forwarded-For yalnız güvenilir vekilden gelirse okunur (ADR-0002)."""
    resolver: ClientIpResolver = request.app.state.client_ip_resolver
    return resolver.resolve(
        request.client.host if request.client else None, request.headers.get("x-forwarded-for")
    )


def ip_hash_for(request: Request, settings: Settings) -> str:
    """Ham IP saklanmaz; anahtarlı HMAC özetinin ilk 32 hanesi saklanır."""
    return hmac_hex(settings.master_key, "ip-hash", client_ip(request))[:32]


async def get_auth_context(request: Request, db: DbDep, settings: SettingsDep) -> AuthContext:
    """Oturum çerezini doğrular ve RLS bağlamını (kiracı + kullanıcı) kurar."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise _unauthorized()
    found = await lookup_session(db, settings, token)
    if found is None:
        await db.rollback()
        raise _unauthorized()
    ctx, last_seen = found
    await set_rls_context(db, ctx.tenant_id, ctx.user_id)
    now = datetime.now(UTC)
    if (now - last_seen).total_seconds() > TOUCH_INTERVAL_SECONDS:
        await touch_session(db, ctx.session_id)
        await db.commit()
        # Commit işlem yerel GUC'leri sıfırlar; işleyici için yeniden kurulur.
        await set_rls_context(db, ctx.tenant_id, ctx.user_id)
    return ctx


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]


def _unauthorized() -> ProblemError:
    return ProblemError(401, "Kimlik doğrulama gerekli", "unauthorized")


def email_not_verified() -> ProblemError:
    return ProblemError(
        403,
        "E-posta doğrulanmadı",
        "email-not-verified",
        "Bu işlem için e-posta adresinizi doğrulamanız gerekir. "
        "Doğrulama bağlantısını yeniden isteyebilirsiniz.",
    )


def terms_acceptance_required() -> ProblemError:
    return ProblemError(
        403,
        "Güncel koşulların kabulü gerekli",
        "terms-acceptance-required",
        "Kullanım koşulları ya da aydınlatma metni yeni bir sürüme geçti. Devam etmek için panelden "
        "güncel sürümü gözden geçirip kabul edin. Verilerinizi görüntülemeye devam edebilirsiniz.",
    )


async def get_verified_auth_context(ctx: AuthDep, db: DbDep) -> AuthContext:
    """Oturum açık ve e-posta doğrulanmış olmalı (TOTP kurulumu gibi hesap güvenliği uçları)."""
    if not await is_email_verified(db, ctx.user_id):
        raise email_not_verified()
    return ctx


VerifiedAuthDep = Annotated[AuthContext, Depends(get_verified_auth_context)]


def require_role(
    *roles: Role, verified: bool = False, legal_gate: bool = True
) -> Callable[..., Awaitable[AuthContext]]:
    """Belirtilen rollerden birini şart koşan bağımlılık üretir.

    `verified=True`: kullanıcının e-postası da doğrulanmış olmalıdır (yazma uçları; ön ele geçirme önlemi);
    `legal_reacceptance_enforced` açıksa güncel belge sürümleri de kabul edilmiş olmalıdır; `legal_gate=False`
    yalnız veri işlemeyi DURDURMA uçları içindir (mağaza bağlantısı iptali): bu hak kabule bağlanmaz.
    Okuma ve oturum kapama uçları bu koşulu taşımaz. Önce rol, sonra doğrulama denetlenir.
    """

    async def _check(ctx: AuthDep, db: DbDep, settings: SettingsDep) -> AuthContext:
        if ctx.role not in roles:
            raise ProblemError(403, "Erişim reddedildi", "forbidden")
        if verified:
            if not await is_email_verified(db, ctx.user_id):
                raise email_not_verified()
            # Yeniden kabul kapısı (varsayılan kapalı): yalnız tenant verisi YAZAN uçlarda; okuma, dışa
            # aktarma, hesap güvenliği (TOTP), çıkış ve kabul ucu açık kalır (veri/güvenlik rehin tutulmaz).
            if (
                legal_gate
                and settings.legal_reacceptance_enforced
                and await pending_documents(db, ctx.user_id)
            ):
                raise terms_acceptance_required()
        return ctx

    return _check
