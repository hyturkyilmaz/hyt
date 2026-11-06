"""Uygulama ayarları. Tüm yapılandırma ortam değişkenlerinden okunur."""

from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ortam değişkenlerinden okunan ayarlar (önek yok, büyük küçük harf duyarsız)."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Ürün adı tek yerden okunur; marka değişirse yalnız bu ayar değişir.
    product_name: str = "NetKâr"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Uygulama rolü (superuser DEĞİL). Migrasyon rolü ayrıdır.
    database_url: str
    database_migration_url: str | None = None

    # AES-256-GCM ana anahtarı: 32 bayt, base64. Repoya girmez.
    data_encryption_key: SecretStr

    pwned_check_enabled: bool = False
    web_base_url: str = "http://localhost:3000"
    trust_proxy_headers: bool = False

    email_backend: Literal["file", "memory"] = "file"
    email_dev_outbox_path: str = "var/outbox.jsonl"

    # Oturum süreleri (saniye)
    session_idle_seconds: int = 12 * 3600
    session_absolute_seconds: int = 30 * 24 * 3600
    reset_token_ttl_minutes: int = 30
    pending_totp_ttl_seconds: int = 300
    trial_days: int = 14

    # Rate limit eşikleri (pencere uzunlukları kodda sabittir)
    rate_limit_login_ip: int = Field(30, ge=1)
    rate_limit_login_email: int = Field(10, ge=1)
    rate_limit_register_ip: int = Field(10, ge=1)
    rate_limit_reset_ip: int = Field(10, ge=1)
    rate_limit_reset_email: int = Field(3, ge=1)
    rate_limit_totp_user: int = Field(10, ge=1)

    @field_validator("database_url", "database_migration_url")
    @classmethod
    def _normalize_url(cls, value: str | None) -> str | None:
        """SQLAlchemy için psycopg 3 sürücüsünü zorlar."""
        if value is None:
            return None
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        return value

    @field_validator("data_encryption_key")
    @classmethod
    def _validate_key(cls, value: SecretStr) -> SecretStr:
        """Anahtar base64 olmalı ve tam 32 bayt çözülmelidir."""
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("DATA_ENCRYPTION_KEY base64 olmalı") from exc
        if len(raw) != 32:
            raise ValueError("DATA_ENCRYPTION_KEY 32 bayt olmalı")
        return value

    @property
    def master_key(self) -> bytes:
        """Çözülmüş 32 baytlık ana anahtar."""
        return base64.b64decode(self.data_encryption_key.get_secret_value())

    @property
    def libpq_url(self) -> str:
        """Sürücü ekinden arındırılmış bağlantı dizesi (procrastinate için)."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    """Süreç boyunca tek ayar nesnesi (testlerde create_app'e açıkça verilir)."""
    return Settings()
