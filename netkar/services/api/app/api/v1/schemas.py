"""İstek ve yanıt şemaları."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, StringConstraints

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
