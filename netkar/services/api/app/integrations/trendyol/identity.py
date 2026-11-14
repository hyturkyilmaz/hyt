"""Kimlik bilgisi ve User-Agent kuralları.

Kaynak: docs/research/01_trendyol_api.md §2.1 ve §2.2 (resmi "2. Authorization" sayfası, yerel
kopyada yok; kurallar araştırma raporundan alındı):
  - Basic Auth: kullanıcı adı API Key, parola API Secret.
  - Her istekte `User-Agent: "{sellerId} - {entegratör adı}"`; yoksa 403.
  - Entegratör adı alfanümerik ve en fazla 30 karakter, Türkçe karakter yok.
Entegratör adındaki boşluk ve noktalama kuralı açıkça yazılmadığı için en katı yorum uygulanır:
yalnız ASCII harf ve rakam (doğrulanmadı, ADR-0003 K-N07).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import SecretStr

from app.integrations.trendyol.errors import TrendyolConfigError

INTEGRATOR_NAME_RE = re.compile(r"^[A-Za-z0-9]{1,30}$")
# Satıcı kimliği pozitif tamsayıdır (int64 sınırı içinde: en fazla 18 hane).
SELLER_ID_RE = re.compile(r"^[1-9][0-9]{0,17}$")
# Basic Auth için: boşluk ve kontrol karakteri yok (başlık enjeksiyonu), ':' kullanıcı adında olamaz.
_SECRET_CHARS_RE = re.compile(r"^[\x21-\x7e]{1,256}$")


def validate_integrator_name(name: str) -> str:
    """Entegratör adını doğrular; geçersizse TrendyolConfigError."""
    if not isinstance(name, str) or not INTEGRATOR_NAME_RE.fullmatch(name):
        raise TrendyolConfigError(
            "entegratör adı yalnız ASCII harf/rakam olmalı ve en fazla 30 karakter olmalı"
        )
    return name


def validate_seller_id(seller_id: str) -> str:
    """Satıcı kimliğini doğrular (yalnız rakam, baştaki sıfır yok)."""
    if not isinstance(seller_id, str) or not SELLER_ID_RE.fullmatch(seller_id):
        raise TrendyolConfigError("satıcı kimliği yalnız rakamlardan oluşmalı")
    return seller_id


def build_user_agent(seller_id: str, integrator_name: str) -> str:
    """`"{sellerId} - {entegratör}"` biçimindeki zorunlu User-Agent değerini üretir."""
    return f"{validate_seller_id(seller_id)} - {validate_integrator_name(integrator_name)}"


@dataclass(frozen=True)
class TrendyolCredentials:
    """Satıcı kimliği ve API anahtar çifti. repr/str sırları göstermez."""

    seller_id: str
    api_key: SecretStr = field(repr=False)
    api_secret: SecretStr = field(repr=False)

    def __post_init__(self) -> None:
        validate_seller_id(self.seller_id)
        key = self.api_key.get_secret_value()
        secret = self.api_secret.get_secret_value()
        if ":" in key or not _SECRET_CHARS_RE.fullmatch(key):
            raise TrendyolConfigError("API anahtarı biçimi geçersiz")
        if not _SECRET_CHARS_RE.fullmatch(secret):
            raise TrendyolConfigError("API sırrı biçimi geçersiz")
