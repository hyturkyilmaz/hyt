"""Web push abonelik uçlarının şemaları (ADR-0009 §8.2, D8).

Tüm şemalar `extra="forbid"` (bilinmeyen alan 422). Uç nokta ve anahtar doğrulaması `app.services.push` içindedir;
hata iletileri girdi değerini yansıtmaz (genel doğrulama işleyicisi yalnız alan yolu ve kural kodunu yazar).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError

from app.services import push as push_service


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PushKeysIn(_Strict):
    """Tarayıcı `PushSubscription.toJSON().keys` değerleri (dolgusuz base64url)."""

    p256dh: str = Field(min_length=1, max_length=128)
    auth: str = Field(min_length=1, max_length=64)

    @field_validator("p256dh")
    @classmethod
    def _check_p256dh(cls, value: str) -> str:
        try:
            return push_service.validate_p256dh(value)
        except push_service.PushValidationError as exc:
            raise PydanticCustomError(exc.code, "Abonelik anahtarı geçersiz.") from None

    @field_validator("auth")
    @classmethod
    def _check_auth(cls, value: str) -> str:
        try:
            return push_service.validate_auth_secret(value)
        except push_service.PushValidationError as exc:
            raise PydanticCustomError(exc.code, "Abonelik anahtarı geçersiz.") from None


class PushSubscriptionIn(_Strict):
    # Uzunluk sınırı doğrulayıcıdan ÖNCE uygulanır; uzun girdi ayrıştırılmaz.
    endpoint: str = Field(min_length=1, max_length=push_service.MAX_ENDPOINT_LENGTH)
    keys: PushKeysIn

    @field_validator("endpoint")
    @classmethod
    def _check_endpoint(cls, value: str) -> str:
        try:
            push_service.validate_endpoint(value)
        except push_service.PushValidationError as exc:
            raise PydanticCustomError(exc.code, "Uç nokta geçersiz ya da desteklenmiyor.") from None
        return value


class VapidKeyOut(_Strict):
    """Bayrak kapalıyken (ya da genel anahtar yokken) yalnız `enabled: false`."""

    enabled: bool
    public_key: str | None = None
    key_id: str | None = None


class PushSubscriptionOut(_Strict):
    """Maskeli abonelik: ana bilgisayar, oluşturma ve son başarı. Uç nokta ve anahtarlar ASLA dönmez."""

    id: UUID
    endpoint_host: str
    vapid_key_id: str
    created_at: datetime
    last_success_at: datetime | None


class PushSubscriptionListOut(_Strict):
    items: list[PushSubscriptionOut]
