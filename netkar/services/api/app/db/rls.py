"""Satır düzeyi güvenlik (RLS) bağlam yardımcıları.

Kiracı bağlamı işlem yerel (transaction-local) GUC'lerle verilir; `SET LOCAL` eşdeğeri
`set_config(..., true)` parametre bağlamayı desteklediği için tercih edilir. İşlem biterken
değerler kendiliğinden sıfırlanır, böylece havuzdaki bağlantı yeniden kullanıldığında sızıntı olmaz.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(
    session: AsyncSession, tenant_id: UUID | None = None, user_id: UUID | None = None
) -> None:
    """Geçerli işlem için app.tenant_id ve/veya app.user_id değerlerini ayarlar."""
    if tenant_id is not None:
        await session.execute(text("SELECT set_config('app.tenant_id', :v, true)"), {"v": str(tenant_id)})
    if user_id is not None:
        await session.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": str(user_id)})
