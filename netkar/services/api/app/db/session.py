"""Async motor ve oturum fabrikası."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(
    url: str, *, pool_size: int = 10, max_overflow: int = 10, pool_timeout: float = 30.0
) -> AsyncEngine:
    """Uygulama rolüyle (superuser olmayan) bağlanan async motor."""
    # hide_parameters: hata metinlerine bağlı parametreler (parola özeti, e-posta) yazılmaz (D-04).
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        hide_parameters=True,
    )


def create_rate_limit_engine(url: str, *, pool_size: int, pool_timeout: float) -> AsyncEngine:
    """Hız sınırı sayacı için AYRI, küçük havuz (denetim S4 Y-01).

    İstek oturumu bağlantısını tutarken sayaç aynı havuzdan ikinci bağlantı isterse, havuz kadar eşzamanlı
    istek birbirini sonsuza dek bekler (tut-ve-bekle). Ayrı havuzda sayaç bağlantısı yalnız tek bir kısa
    UPSERT için tutulur ve hiçbir şey beklerken tutulmaz; taşma yok, bekleme kısa.
    """
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=0,
        pool_timeout=pool_timeout,
        hide_parameters=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Commit sonrası nesneleri süresi dolmuş saymayan oturum fabrikası."""
    return async_sessionmaker(engine, expire_on_commit=False)
