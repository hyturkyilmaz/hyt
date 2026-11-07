"""İstemci tarafı rate limit: (satıcı, uç nokta grubu) başına token bucket.

Kaynak: docs__1-servis-limitleri.md ve research/01 §2.3. Limitlerin satıcı, API anahtarı veya IP
bazında sayıldığı doğrulanmadı (ADR-0003 K-N07); bu yüzden (satıcı, grup) başına ayrı kova
tutulur ve değerler en tutucu seçilir. Bu kovalar süreç içidir: birden çok worker süreci aynı
satıcıya istek atarsa toplam hız süreç sayısıyla çarpılır; 429 geri çekilmesi bunu tolere eder
(ölçek tetikleyicisi için ADR-0003).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum


class EndpointGroup(StrEnum):
    """Aynı limiti paylaşan uç nokta grupları."""

    ORDERS = "orders"
    ORDERS_STREAM = "orders_stream"
    CLAIMS = "claims"
    FINANCE = "finance"
    PRODUCT_READ = "product_read"
    QNA = "qna"


@dataclass(frozen=True)
class LimitSpec:
    """Dakikadaki istek üst sınırı ve ani artış (burst) kapasitesi."""

    per_minute: float
    burst: int


# En tutucu değerler. Sipariş: seviyeye göre 30-100/dk, en düşüğü (30) alınır. Stream için tabloda
# ayrı limit yok; "en az 5 saniye aralık" önerisi 12/dk ve burst 1 ile uygulanır. Burst, dakikalık
# pencerenin aşılmaması için küçük tutulur (kova kapasitesi + dolum hızı kısa pencerede aşabilir).
DEFAULT_LIMITS: dict[EndpointGroup, LimitSpec] = {
    EndpointGroup.ORDERS: LimitSpec(per_minute=30, burst=5),
    EndpointGroup.ORDERS_STREAM: LimitSpec(per_minute=12, burst=1),
    EndpointGroup.CLAIMS: LimitSpec(per_minute=1000, burst=50),
    EndpointGroup.FINANCE: LimitSpec(per_minute=100, burst=10),
    EndpointGroup.PRODUCT_READ: LimitSpec(per_minute=1000, burst=50),
    EndpointGroup.QNA: LimitSpec(per_minute=1000, burst=50),
}
# Genel kural: aynı uç noktaya 10 saniyede en fazla 50 istek (51. istek 429).
GENERAL_LIMIT = LimitSpec(per_minute=50 * 6, burst=50)


_EPSILON = 1e-9


class TokenBucket:
    """Zamanla dolan jeton kovası (saf, saat dışarıdan verilir)."""

    def __init__(self, per_minute: float, burst: int, now: float) -> None:
        self._rate = per_minute / 60.0
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._updated = now
        self._blocked_until = now

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._updated = now

    def wait_time(self, now: float) -> float:
        """Bir jeton alınabilene kadar beklenecek saniye (0: hemen)."""
        self._refill(now)
        blocked = max(0.0, self._blocked_until - now)
        # Kayan nokta payı: bekleme sonrası jeton 0.999999... kalırsa sonsuz kısa uykuya girilmez.
        if self._tokens >= 1.0 - _EPSILON:
            return blocked
        return max(blocked, (1.0 - self._tokens) / self._rate)

    def take(self, now: float) -> None:
        """Bir jeton tüketir (wait_time 0 döndükten hemen sonra çağrılır)."""
        self._refill(now)
        self._tokens -= 1.0

    def block(self, now: float, seconds: float) -> None:
        """429 sonrası: kovayı boşaltır ve `seconds` boyunca jeton vermez."""
        self._refill(now)
        self._tokens = 0.0
        self._blocked_until = max(self._blocked_until, now + seconds)


Sleep = Callable[[float], Awaitable[None]]


class RateLimitWaitExceededError(Exception):
    """Jeton için gereken bekleme, izin verilen azami beklemeyi aşıyor (jeton tüketilmedi)."""

    def __init__(self, needed: float) -> None:
        super().__init__(f"kova beklemesi {needed:.1f} sn gerektiriyor")
        self.needed = needed


class RateLimiterRegistry:
    """(satıcı, grup) ve (satıcı, uç nokta) kovalarını yönetir; çağrı öncesi `acquire` beklenir."""

    def __init__(
        self,
        limits: dict[EndpointGroup, LimitSpec] | None = None,
        general: LimitSpec = GENERAL_LIMIT,
        clock: Callable[[], float] = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._limits = limits or DEFAULT_LIMITS
        self._general = general
        self._clock = clock
        self._sleep = sleep
        self._group_buckets: dict[tuple[str, EndpointGroup], TokenBucket] = {}
        self._endpoint_buckets: dict[tuple[str, str], TokenBucket] = {}

    def _buckets(self, seller_id: str, group: EndpointGroup, endpoint: str, now: float) -> list[TokenBucket]:
        gkey = (seller_id, group)
        if gkey not in self._group_buckets:
            spec = self._limits[group]
            self._group_buckets[gkey] = TokenBucket(spec.per_minute, spec.burst, now)
        ekey = (seller_id, endpoint)
        if ekey not in self._endpoint_buckets:
            self._endpoint_buckets[ekey] = TokenBucket(self._general.per_minute, self._general.burst, now)
        return [self._group_buckets[gkey], self._endpoint_buckets[ekey]]

    async def acquire(
        self, seller_id: str, group: EndpointGroup, endpoint: str, *, max_wait: float | None = None
    ) -> float:
        """İlgili tüm kovalardan birer jeton alana dek bekler; toplam beklenen süreyi döndürür.

        `max_wait` verilirse ve toplam bekleme bunu aşacaksa uyumadan RateLimitWaitExceededError
        fırlatır (jeton tüketilmez). None: sınırsız bekleme (senkron işleri).
        """
        waited = 0.0
        while True:
            # Kritik bölümde await yok: tek olay döngüsünde atomiktir, kilit gerekmez.
            now = self._clock()
            buckets = self._buckets(seller_id, group, endpoint, now)
            wait = max(bucket.wait_time(now) for bucket in buckets)
            if wait <= 0.0:
                for bucket in buckets:
                    bucket.take(now)
                return waited
            if max_wait is not None and waited + wait > max_wait:
                raise RateLimitWaitExceededError(waited + wait)
            await self._sleep(wait)
            waited += wait

    def penalize(self, seller_id: str, group: EndpointGroup, endpoint: str, seconds: float) -> None:
        """429 alındı: aynı satıcı ve grup için diğer çağrılar da `seconds` bekler."""
        now = self._clock()
        for bucket in self._buckets(seller_id, group, endpoint, now):
            bucket.block(now, seconds)
