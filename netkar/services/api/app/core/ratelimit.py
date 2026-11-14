"""PostgreSQL tabanlı sabit pencere rate limit.

Tasarım notu ADR-0001'de. Sayaçlar kendi bağlantısında ve autocommit ile yazılır; böylece
isteğin işlem geri alınsa bile (hatalı giriş) deneme sayılmış olur.

Sayaç, istek oturumundan AYRI bir havuzdan bağlanır (`app.db.session.create_rate_limit_engine`): oturum
bağlantısı tutulurken aynı havuzdan ikinci bağlantı istemek tut-ve-bekle kilitlenmesi doğurur
(denetim S4 Y-01).
Ayrı havuz doluysa beklemeden 503 + Retry-After döner (kapalı tarafta başarısızlık).
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.crypto import hmac_hex
from app.core.errors import ProblemError

_UPSERT = text(
    """
    INSERT INTO rate_limits (key, window_start, count)
    VALUES (:key, to_timestamp(:ws), 1)
    ON CONFLICT (key, window_start) DO UPDATE SET count = rate_limits.count + 1
    RETURNING count
    """
)


def digest(master: bytes, purpose: str, value: str) -> str:
    """Sayaç anahtarlarında ham IP/e-posta yerine kullanılan anahtarlı özet (ilk 32 hane)."""
    return hmac_hex(master, purpose, value)[:32]


class RateLimiter:
    """Anahtar başına pencere içinde en fazla `limit` isteğe izin verir."""

    def __init__(self, engine: AsyncEngine, busy_retry_after_seconds: int = 2) -> None:
        self._engine = engine
        self._busy_retry_after = str(max(1, busy_retry_after_seconds))

    async def hit(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> None:
        """Sayacı artırır; aşıldıysa 429 problem fırlatır."""
        current = now if now is not None else time.time()
        window_start = int(current // window_seconds) * window_seconds
        try:
            async with self._engine.connect() as conn:
                conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                count = (await conn.execute(_UPSERT, {"key": key, "ws": window_start})).scalar_one()
        except PoolTimeoutError:
            # Sayaç havuzu doldu: sayamadığımız isteği geçirmeyiz (kapalı başarısızlık) ama 500 de vermeyiz.
            raise ProblemError(
                503,
                "Hız sınırı servisi yoğun",
                "rate-limit-busy",
                "Şu an çok sayıda istek işleniyor. Kısa süre sonra tekrar deneyin.",
                headers={"Retry-After": self._busy_retry_after},
            ) from None
        if count > limit:
            retry_after = max(1, int(window_start + window_seconds - current))
            raise ProblemError(
                429,
                "Çok fazla istek",
                "rate-limited",
                "Çok fazla deneme yapıldı. Lütfen daha sonra tekrar deneyin.",
                headers={"Retry-After": str(retry_after)},
            )
