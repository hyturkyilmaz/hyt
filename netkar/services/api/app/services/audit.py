"""Denetim izi yazımı. Kişisel veri yazılmaz: yalnız kimlikler, eylem adı ve IP özeti."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    db: AsyncSession,
    tenant_id: UUID,
    action: str,
    user_id: UUID | None = None,
    target: str | None = None,
    ip_hash: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """RLS bağlamı (app.tenant_id) ayarlıyken tenant_id ile eşleşen bir kayıt ekler."""
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            target=target,
            ip_hash=ip_hash,
            meta=meta or {},
        )
    )
    await db.flush()
