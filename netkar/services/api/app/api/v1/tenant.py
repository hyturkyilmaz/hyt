"""Kiracı kapsamlı okuma uç noktaları. Her sorguda açık tenant_id süzgeci + RLS (çift kilit)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbDep, require_role
from app.api.v1.schemas import AuditOut, MemberOut, SessionOut
from app.models import AuditLog, Membership, Role, SessionRecord
from app.services.auth import AuthContext

router = APIRouter(prefix="/tenant", tags=["tenant"])

AdminDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN))]
AnyRoleDep = Annotated[AuthContext, Depends(require_role(Role.OWNER, Role.ADMIN, Role.VIEWER))]


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: AnyRoleDep, db: DbDep) -> list[MemberOut]:
    """Kiracının üyeleri (e-posta içermez; kullanıcı satırları yalnız kendine açıktır)."""
    rows = (
        await db.execute(
            select(Membership).where(Membership.tenant_id == ctx.tenant_id).order_by(Membership.created_at)
        )
    ).scalars()
    return [MemberOut(user_id=m.user_id, role=m.role.value, created_at=m.created_at) for m in rows]


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(ctx: AdminDep, db: DbDep) -> list[SessionOut]:
    """Kiracının oturumları. Token özeti asla döndürülmez."""
    rows = (
        await db.execute(
            select(SessionRecord)
            .where(SessionRecord.tenant_id == ctx.tenant_id)
            .order_by(SessionRecord.created_at.desc())
            .limit(100)
        )
    ).scalars()
    return [
        SessionOut(
            id=s.id,
            user_id=s.user_id,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            revoked_at=s.revoked_at,
            current=s.id == ctx.session_id,
        )
        for s in rows
    ]


@router.get("/audit", response_model=list[AuditOut])
async def list_audit(
    ctx: AdminDep, db: DbDep, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> list[AuditOut]:
    """Kiracının denetim kayıtları (yeniden eskiye)."""
    rows = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == ctx.tenant_id)
            .order_by(AuditLog.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        AuditOut(
            id=a.id,
            user_id=a.user_id,
            action=a.action,
            target=a.target,
            created_at=a.created_at,
            meta=a.meta,
        )
        for a in rows
    ]
