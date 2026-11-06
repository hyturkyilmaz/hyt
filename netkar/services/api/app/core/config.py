"""Uygulama ayarları. Tüm yapılandırma ortam değişkenlerinden okunur."""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


class Settings(BaseSettings):
    """Ortam değişkenlerinden okunan ayarlar (önek yok, büyük küçük harf duyarsız)."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    # Ürün adı tek yerden okunur; marka değişirse yalnız bu ayar değişir.
    product_name: str = "NetKâr"
    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    # Yalnız geliştirme içindir; ENVIRONMENT=prod iken açık olması açılışı engeller.
    debug: bool = False

    # Uygulama rolü (superuser DEĞİL). Migrasyon rolü ayrıdır.
    database_url: str
    database_migration_url: str | None = None

    # AES-256-GCM ana anahtarı: 32 bayt, base64. Repoya girmez.
    data_encryption_key: SecretStr

    pwned_check_enabled: bool = False
    web_base_url: str = "http://localhost:3000"

    # İstemci IP'si için güvenilir vekil yapılandırması (ADR-0002). Varsayılan: hiçbir vekile
    # güvenilmez, X-Forwarded-For yok sayılır ve bağlantının eş adresi esas alınır.
    # TRUSTED_PROXY_CIDRS: virgülle ayrılmış CIDR listesi (ör. "172.18.0.0/16,10.0.0.0/8").
    # Eş adres bu listedeyse X-Forwarded-For sağdan sola okunur ve listedeki adresler atlanır.
    trusted_proxy_cidrs: Annotated[list[IPNetwork], NoDecode] = Field(default_factory=list)
    # TRUSTED_PROXY_HOPS: sağdan sayılan güvenilir vekil sayısı (bağlantının eş adresi dahil).
    # CIDR listesi verilmişse hop sayısı ek olarak uygulanır; ikisi de boşsa vekil yoktur.
    trusted_proxy_hops: int = Field(0, ge=0, le=10)

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
    rate_limit_totp_ip: int = Field(30, ge=1)

    # TOTP kaba kuvvet koruması: ardışık başarısız deneme eşiği aşılırsa hesap geçici kilitlenir.
    totp_max_failures: int = Field(5, ge=1)
    totp_lock_seconds: int = Field(15 * 60, ge=1)

    # İstek gövdesi üst sınırları (bayt). Auth uç noktaları çok daha küçük gövde bekler.
    max_request_body_bytes: int = Field(1024 * 1024, ge=1)
    max_auth_body_bytes: int = Field(64 * 1024, ge=1)

    # Eşzamanlı argon2 özet sayısı (her özet ~64 MiB bellek kullanır). Olay döngüsü
    # bloklanmasın diye özetler iş parçacığı havuzunda ve bu sınırla çalışır.
    password_hash_concurrency: int = Field(default_factory=lambda: min(4, os.cpu_count() or 1), ge=1)

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def _parse_cidrs(cls, value: object) -> object:
        """Ortam değişkeninden gelen 'a/24, b/16' dizesini CIDR listesine çevirir."""
        if isinstance(value, str):
            return [
                ipaddress.ip_network(part.strip(), strict=False) for part in value.split(",") if part.strip()
            ]
        return value

    @model_validator(mode="after")
    def _reject_unsafe_production(self) -> Settings:
        """Üretimde güvensiz varsayılanlar açılışı durdurur (denetim D-08)."""
        if self.environment == "prod":
            problems: list[str] = []
            if self.email_backend in {"file", "memory"}:
                problems.append("ENVIRONMENT=prod iken EMAIL_BACKEND=file/memory kullanılamaz")
            if self.debug:
                problems.append("ENVIRONMENT=prod iken DEBUG açık olamaz")
            if problems:
                raise ValueError("; ".join(problems))
        return self

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
