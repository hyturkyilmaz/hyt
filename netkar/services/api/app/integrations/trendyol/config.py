"""Trendyol istemcisi yapılandırması (ortam, zaman aşımları, yeniden deneme)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.integrations.trendyol.errors import TrendyolConfigError
from app.integrations.trendyol.identity import validate_integrator_name


class TrendyolEnvironment(StrEnum):
    """Hedef ortam. Varsayılan stage; canlı yalnız açıkça seçilir."""

    STAGE = "stage"
    LIVE = "live"


# Kaynak: docs__3-canlı-test-ortam-bilgileri.md. Eski api.trendyol.com/sapigw adresleri kapandı.
BASE_URLS: dict[TrendyolEnvironment, str] = {
    TrendyolEnvironment.LIVE: "https://apigw.trendyol.com",
    TrendyolEnvironment.STAGE: "https://stageapigw.trendyol.com",
}


@dataclass(frozen=True)
class TrendyolConfig:
    """İstemci ayarları. Geçersiz değerde TrendyolConfigError: istemci kurulmaz."""

    environment: TrendyolEnvironment = TrendyolEnvironment.STAGE
    # Varsayılan ürün kod adı (ASCII). Ürün adı ("NetKâr") Türkçe karakter içerdiği için kullanılamaz.
    integrator_name: str = "NetKar"
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    write_timeout: float = 10.0
    pool_timeout: float = 5.0
    # İlk denemeye ek en fazla bu kadar yeniden deneme (429, 5xx, ağ hatası).
    max_retries: int = 4
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    # Retry-After başlığına uyulur ama bu üst sınırla kırpılır.
    retry_after_cap: float = 60.0

    def __post_init__(self) -> None:
        validate_integrator_name(self.integrator_name)
        for name in ("connect_timeout", "read_timeout", "write_timeout", "pool_timeout"):
            if getattr(self, name) <= 0:
                raise TrendyolConfigError(f"{name} pozitif olmalı")
        if not 0 <= self.max_retries <= 10:
            raise TrendyolConfigError("max_retries 0 ile 10 arasında olmalı")
        if self.backoff_base <= 0 or self.backoff_cap < self.backoff_base or self.retry_after_cap <= 0:
            raise TrendyolConfigError("geri çekilme süreleri geçersiz")

    @property
    def base_url(self) -> str:
        """Seçili ortamın taban adresi."""
        return BASE_URLS[self.environment]
