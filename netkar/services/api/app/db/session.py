"""Async motor ve oturum fabrikası."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def create_engine(url: str) -> AsyncEngine:
    """Uygulama rolüyle (superuser olmayan) bağlanan async motor."""
    # hide_parameters: hata metinlerine bağlı parametreler (parola özeti, e-posta) yazılmaz (D-04).
    return create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10, hide_parameters=True)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Commit sonrası nesneleri süresi dolmuş saymayan oturum fabrikası."""
    return async_sessionmaker(engine, expire_on_commit=False)
