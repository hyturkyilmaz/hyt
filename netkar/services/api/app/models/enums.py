"""Ortak enum tanımları."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """Kiracı içi rol."""

    OWNER = "owner"
    ADMIN = "admin"
    VIEWER = "viewer"


class Platform(StrEnum):
    """Desteklenen pazaryeri. Şimdilik yalnız Trendyol."""

    TRENDYOL = "trendyol"


class MarketplaceAccountStatus(StrEnum):
    """Bağlantı durumu: active (çalışıyor), invalid (anahtar reddedildi), revoked (iptal, sırlar boş)."""

    ACTIVE = "active"
    INVALID = "invalid"
    REVOKED = "revoked"
