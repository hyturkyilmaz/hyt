"""İstek ve yanıt şemaları."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    SecretStr,
    StringConstraints,
)

from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


def _normalize_email(value: str) -> str:
    return value.strip().lower()


NormalizedEmail = Annotated[EmailStr, StringConstraints(max_length=254), AfterValidator(_normalize_email)]
NewPassword = Annotated[
    str, StringConstraints(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
]
LoginPassword = Annotated[str, StringConstraints(min_length=1, max_length=PASSWORD_MAX_LENGTH)]
TotpCode = Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(_Strict):
    email: NormalizedEmail
    password: NewPassword
    tenant_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class LoginRequest(_Strict):
    email: NormalizedEmail
    password: LoginPassword


class TotpCodeRequest(_Strict):
    code: TotpCode


class PasswordResetRequest(_Strict):
    email: NormalizedEmail


class PasswordResetConfirm(_Strict):
    token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    new_password: NewPassword


class CsrfResponse(BaseModel):
    csrf_token: str


class StatusResponse(BaseModel):
    status: str


class TenantOut(BaseModel):
    id: UUID
    name: str
    plan: str
    status: str
    trial_ends_at: datetime | None
    currency: str
    locale: str


class MeResponse(BaseModel):
    user_id: UUID
    email: str
    role: str
    totp_enabled: bool
    tenant: TenantOut


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str


class MemberOut(BaseModel):
    user_id: UUID
    role: str
    created_at: datetime


class SessionOut(BaseModel):
    id: UUID
    user_id: UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    current: bool


class AuditOut(BaseModel):
    id: int
    user_id: UUID | None
    action: str
    target: str | None
    created_at: datetime
    meta: dict[str, object]


def _seller_id_to_str(value: object) -> object:
    """Satıcı kimliği JSON'da sayı olarak da gelebilir (Trendyol panelinde sayı gösterilir)."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


SellerId = Annotated[
    str,
    BeforeValidator(_seller_id_to_str),
    StringConstraints(strip_whitespace=True, min_length=1, max_length=18, pattern=r"^[1-9][0-9]*$"),
]
# Biçim (ASCII, boşluksuz) TrendyolCredentials içinde doğrulanır; burada yalnız boyut sınırı vardır.
ApiSecretValue = Annotated[SecretStr, StringConstraints(min_length=8, max_length=256)]


class MarketplaceAccountCreate(_Strict):
    """Pazaryeri bağlantısı ekleme isteği. Sırlar SecretStr'dir: repr ve hata metinlerinde görünmez."""

    seller_id: SellerId
    api_key: ApiSecretValue
    api_secret: ApiSecretValue


class MarketplaceAccountOut(BaseModel):
    """Maskeli bağlantı özeti. API anahtarı ve sırrı ASLA döndürülmez; yalnız son 4 hane."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    platform: str
    seller_id: str
    status: str
    api_key_last4: str | None
    last_validated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None
