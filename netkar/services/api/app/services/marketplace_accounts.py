"""Pazaryeri bağlantıları: sır şifreleme, istemci fabrikası ve Trendyol hata eşlemesi."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.config import Settings
from app.core.crypto import FieldCipher
from app.core.errors import ProblemError
from app.integrations.trendyol import (
    TrendyolAuthError,
    TrendyolClient,
    TrendyolConfig,
    TrendyolCredentials,
    TrendyolEnvironment,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolRateLimitedError,
)
from app.integrations.trendyol.ratelimit import RateLimiterRegistry
from app.models import MarketplaceAccount, MarketplaceAccountStatus, Platform

# Bağlantı doğrulama isteğin içinde çalışır: uzun geri çekilmeyle kullanıcıyı bekletmeyiz.
VALIDATION_MAX_RETRIES = 1


class TrendyolClientFactory(Protocol):
    """Kimlik bilgisinden istemci üretir (testlerde sahte taşımayla değiştirilir)."""

    def __call__(
        self, credentials: TrendyolCredentials, *, max_retries: int | None = None
    ) -> TrendyolClient: ...


def default_client_factory(settings: Settings) -> TrendyolClientFactory:
    """Ayarlardan istemci fabrikası. Hız sınırı kovaları uygulama genelinde paylaşılır."""
    limiter = RateLimiterRegistry()

    def _factory(credentials: TrendyolCredentials, *, max_retries: int | None = None) -> TrendyolClient:
        retries = settings.trendyol_max_retries
        if max_retries is not None:
            retries = min(retries, max_retries)
        config = TrendyolConfig(
            environment=TrendyolEnvironment(settings.trendyol_environment),
            integrator_name=settings.trendyol_integrator_name,
            connect_timeout=settings.trendyol_connect_timeout_seconds,
            read_timeout=settings.trendyol_read_timeout_seconds,
            max_retries=retries,
            backoff_base=settings.trendyol_backoff_base_seconds,
            backoff_cap=max(settings.trendyol_backoff_cap_seconds, settings.trendyol_backoff_base_seconds),
        )
        return TrendyolClient(credentials, config, limiter=limiter)

    return _factory


def _aad(account_id: UUID, field: str) -> bytes:
    """Şifreli değeri satıra ve alana bağlar: başka satıra kopyalanan şifreli değer çözülemez."""
    return f"marketplace_accounts:{account_id}:{field}".encode()


def encrypt_secret(cipher: FieldCipher, account_id: UUID, field: str, value: SecretStr) -> str:
    """Bir sır alanını şifreler (`field`: api_key veya api_secret)."""
    return cipher.encrypt(value.get_secret_value(), _aad(account_id, field))


def decrypt_credentials(cipher: FieldCipher, account: MarketplaceAccount) -> TrendyolCredentials:
    """Satırdaki şifreli anahtarları çözer (senkron işleri için). İptal edilmiş satırda hata verir."""
    if account.api_key_encrypted is None or account.api_secret_encrypted is None:
        raise ValueError("bağlantının anahtarları yok (iptal edilmiş)")
    return TrendyolCredentials(
        seller_id=account.seller_id,
        api_key=SecretStr(cipher.decrypt(account.api_key_encrypted, _aad(account.id, "api_key"))),
        api_secret=SecretStr(cipher.decrypt(account.api_secret_encrypted, _aad(account.id, "api_secret"))),
    )


async def find_live_account(db: AsyncSession, tenant_id: UUID, seller_id: str) -> MarketplaceAccount | None:
    """Kiracıdaki iptal edilmemiş aynı satıcı bağlantısı (varsa). Açık tenant_id süzgeci + RLS."""
    stmt = (
        select(MarketplaceAccount)
        .where(
            MarketplaceAccount.tenant_id == tenant_id,
            MarketplaceAccount.platform == Platform.TRENDYOL.value,
            MarketplaceAccount.seller_id == seller_id,
            MarketplaceAccount.status != MarketplaceAccountStatus.REVOKED.value,
        )
        .options(
            undefer(MarketplaceAccount.api_key_encrypted), undefer(MarketplaceAccount.api_secret_encrypted)
        )
        .with_for_update()
    )
    return (await db.execute(stmt)).scalar_one_or_none()


def problem_for_trendyol(exc: TrendyolError) -> tuple[ProblemError, str]:
    """Trendyol hatasını kullanıcıya uygun problem+json'a ve denetim nedenine çevirir.

    Ham Trendyol ayrıntısı hiçbir zaman aktarılmaz.
    """
    if isinstance(exc, TrendyolAuthError):
        return (
            ProblemError(
                422,
                "Trendyol anahtarları reddedildi",
                "marketplace-credentials-rejected",
                "API anahtarı veya sırrı Trendyol tarafından kabul edilmedi. Bilgileri kontrol edin.",
            ),
            "rejected",
        )
    if isinstance(exc, TrendyolForbiddenError):
        return (
            ProblemError(
                422,
                "Trendyol erişimi reddetti",
                "marketplace-access-denied",
                "Trendyol erişimi reddetti. Entegrasyon anahtarının rolünü ve satıcı kimliğini kontrol edin.",
            ),
            "forbidden",
        )
    if isinstance(exc, TrendyolRateLimitedError):
        return (
            ProblemError(
                503,
                "Trendyol şu an yoğun",
                "marketplace-busy",
                "Trendyol istek sınırı aşıldı. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": "30"},
            ),
            "rate_limited",
        )
    return (
        ProblemError(
            502,
            "Trendyol'a ulaşılamadı",
            "marketplace-unavailable",
            "Trendyol yanıt vermedi veya beklenmeyen bir yanıt döndü. Daha sonra tekrar deneyin.",
        ),
        "unavailable",
    )
