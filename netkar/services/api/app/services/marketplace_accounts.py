"""Pazaryeri bağlantıları: sır şifreleme, istemci fabrikası ve Trendyol hata eşlemesi."""

from __future__ import annotations

import asyncio
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.crypto import FieldCipher
from app.core.envelope import EnvelopeCipher
from app.core.errors import ProblemError
from app.integrations.trendyol import (
    TrendyolAuthError,
    TrendyolClient,
    TrendyolConfig,
    TrendyolCredentials,
    TrendyolEnvironment,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolRateLimitedError,
)
from app.integrations.trendyol.models import ConnectionCheck
from app.integrations.trendyol.ratelimit import RateLimiterRegistry
from app.models import MarketplaceAccount, MarketplaceAccountStatus, Platform

# Bağlantı doğrulama isteğin içinde çalışır: uzun geri çekilmeyle kullanıcıyı bekletmeyiz.
VALIDATION_MAX_RETRIES = 1


class TrendyolClientFactory(Protocol):
    """Kimlik bilgisinden istemci üretir (testlerde sahte taşımayla değiştirilir)."""

    def __call__(
        self,
        credentials: TrendyolCredentials,
        *,
        max_retries: int | None = None,
        max_wait: float | None = None,
    ) -> TrendyolClient: ...


def default_client_factory(settings: Settings) -> TrendyolClientFactory:
    """Ayarlardan istemci fabrikası. Hız sınırı kovaları uygulama genelinde paylaşılır."""
    limiter = RateLimiterRegistry()

    def _factory(
        credentials: TrendyolCredentials, *, max_retries: int | None = None, max_wait: float | None = None
    ) -> TrendyolClient:
        # max_wait: istek içi çağrılar (bağlantı doğrulama) için toplam bekleme bütçesi; senkron işleri
        # vermez (None: sınırsız bekleme).
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
            max_total_wait=max_wait,
        )
        return TrendyolClient(credentials, config, limiter=limiter)

    return _factory


def build_aad(tenant_id: UUID, platform: str, seller_id: str, account_id: UUID, field: str) -> bytes:
    """Şifreli değeri kiracıya, platforma, satıcıya, hesaba ve alana bağlar (denetim D-04).

    Şifreli değer başka kiracıya, satıcıya, satıra veya alana taşınırsa çözülemez.
    """
    return f"marketplace_accounts:v2:{tenant_id}:{platform}:{seller_id}:{account_id}:{field}".encode()


def account_aad(account: MarketplaceAccount, field: str) -> bytes:
    """Hesap nesnesinin kimlik alanlarından AAD üretir."""
    return build_aad(account.tenant_id, account.platform, account.seller_id, account.id, field)


def legacy_aad(account_id: UUID, field: str) -> bytes:
    """Eski (v1, FieldCipher) biçimin AAD'si: yalnız satır kimliği ve alan adı. Yalnız okuma/geçiş için."""
    return f"marketplace_accounts:{account_id}:{field}".encode()


def encrypt_secret(
    envelope: EnvelopeCipher, account: MarketplaceAccount, field: str, value: SecretStr
) -> str:
    """Bir sır alanını zarf şifreler (`field`: api_key veya api_secret). AAD hesabın kimliğinden gelir."""
    return envelope.encrypt(value.get_secret_value(), account_aad(account, field))


def _decrypt_field(
    envelope: EnvelopeCipher, legacy: FieldCipher | None, account: MarketplaceAccount, token: str, field: str
) -> str:
    if token.startswith("v1:") and legacy is not None:
        return legacy.decrypt(token, legacy_aad(account.id, field))
    return envelope.decrypt(token, account_aad(account, field))


def decrypt_credentials(
    envelope: EnvelopeCipher, account: MarketplaceAccount, *, legacy: FieldCipher | None = None
) -> TrendyolCredentials:
    """Satırdaki şifreli anahtarları çözer (senkron işleri için). İptal edilmiş satırda hata verir.

    `legacy` verilirse eski `v1:` biçimli değerler de okunur (migrasyon süresince); verilmezse
    yalnız v2 çözülür.
    """
    if account.api_key_encrypted is None or account.api_secret_encrypted is None:
        raise ValueError("bağlantının anahtarları yok (iptal edilmiş)")
    return TrendyolCredentials(
        seller_id=account.seller_id,
        api_key=SecretStr(_decrypt_field(envelope, legacy, account, account.api_key_encrypted, "api_key")),
        api_secret=SecretStr(
            _decrypt_field(envelope, legacy, account, account.api_secret_encrypted, "api_secret")
        ),
    )


async def verify_with_deadline(
    factory: TrendyolClientFactory, credentials: TrendyolCredentials, settings: Settings
) -> ConnectionCheck:
    """Bağlantıyı doğrular: toplam bekleme bütçesi ve toplam son tarihle (istek içinde çalışır).

    Retry-After ve kova beklemesi `trendyol_validation_max_wait_seconds`'ı aşacaksa uyunmadan
    TrendyolWaitBudgetError (503), toplam süre `trendyol_validation_deadline_seconds`'ı aşarsa
    TrendyolNetworkError (502) fırlatır. Yalnız TrendyolError türleri dışarı çıkar.
    """
    try:
        async with asyncio.timeout(settings.trendyol_validation_deadline_seconds):
            async with factory(
                credentials,
                max_retries=VALIDATION_MAX_RETRIES,
                max_wait=settings.trendyol_validation_max_wait_seconds,
            ) as client:
                return await client.verify_connection()
    except TimeoutError:
        pass
    # except dışında fırlatılır: özgün TimeoutError zincire girmez.
    raise TrendyolNetworkError("doğrulama zaman aşımı")


async def find_live_account(db: AsyncSession, tenant_id: UUID, seller_id: str) -> MarketplaceAccount | None:
    """Kiracıdaki iptal edilmemiş aynı satıcı bağlantısı (varsa). Açık tenant_id süzgeci + RLS.

    Şifreli sütunlar `deferred` kalır ve yüklenmez: bağlantı ekleme bunları yalnız üzerine yazar,
    çözme yalnız senkron işçisinde gerekir (denetim D-05).
    """
    stmt = (
        select(MarketplaceAccount)
        .where(
            MarketplaceAccount.tenant_id == tenant_id,
            MarketplaceAccount.platform == Platform.TRENDYOL.value,
            MarketplaceAccount.seller_id == seller_id,
            MarketplaceAccount.status != MarketplaceAccountStatus.REVOKED.value,
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
