"""Trendyol istemcisi hata türleri.

Hata nesneleri yanıt gövdesi, başlık veya kimlik bilgisi TAŞIMAZ: yalnız durum kodu ve uç nokta
grubu. Böylece log'a veya kullanıcıya yanlışlıkla ham veri sızmaz.
"""

from __future__ import annotations


class TrendyolError(Exception):
    """Tüm Trendyol istemcisi hatalarının tabanı."""

    def __init__(self, message: str, *, status: int | None = None, endpoint_group: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.endpoint_group = endpoint_group


class TrendyolConfigError(TrendyolError, ValueError):
    """Geçersiz yapılandırma veya kimlik bilgisi biçimi (istemci kurulmaz)."""


class TrendyolValidationError(TrendyolError, ValueError):
    """İstemci tarafı parametre doğrulaması: Trendyol'a hiç istek gitmez."""


class TrendyolAuthError(TrendyolError):
    """401: API anahtarı veya sırrı geçersiz. Yeniden denenmez."""


class TrendyolForbiddenError(TrendyolError):
    """403: User-Agent, IP veya rol yetkisi reddedildi. Yeniden denenmez."""


class TrendyolRateLimitedError(TrendyolError):
    """429: yeniden deneme bütçesi tükendi."""


class TrendyolServerError(TrendyolError):
    """5xx: yeniden deneme bütçesi tükendi (stage ortamında 503 çoğunlukla IP yetkisizliğidir)."""


class TrendyolRequestError(TrendyolError):
    """Diğer 4xx/3xx yanıtlar (örn. 400 geçersiz parametre). Yeniden denenmez."""


class TrendyolNetworkError(TrendyolError):
    """Bağlantı kurulamadı veya zaman aşımı; yeniden deneme bütçesi tükendi."""


class TrendyolProtocolError(TrendyolError):
    """Yanıt beklenen biçimde değil (geçersiz JSON, şemaya uymayan gövde, döngüye giren imleç)."""


class TrendyolWindowTooLargeError(TrendyolError):
    """v2/orders 10.000 paket penceresini aşan sonuç: stream uç noktası veya dar tarih aralığı gerekir."""

    def __init__(self, total_elements: int) -> None:
        super().__init__(
            f"sonuç penceresi aşıldı: {total_elements} kayıt (en fazla 10000 erişilebilir)",
            endpoint_group="orders",
        )
        self.total_elements = total_elements
