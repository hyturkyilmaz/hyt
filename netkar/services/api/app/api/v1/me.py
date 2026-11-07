"""Oturumdaki kullanıcı ve kiracısı."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import AuthDep, DbDep
from app.api.v1.schemas import MeResponse, TenantOut
from app.core.errors import ProblemError
from app.models import Tenant, User

router = APIRouter(tags=["me"])
auth_alias = APIRouter(prefix="/auth", include_in_schema=False)


async def _me(ctx: AuthDep, db: DbDep) -> MeResponse:
    user = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one_or_none()
    tenant = (await db.execute(select(Tenant).where(Tenant.id == ctx.tenant_id))).scalar_one_or_none()
    if user is None or tenant is None:
        raise ProblemError(401, "Kimlik doğrulama gerekli", "unauthorized")
    return MeResponse(
        user_id=user.id,
        email=user.email,
        role=ctx.role.value,
        totp_enabled=user.totp_enabled,
        tenant=TenantOut(
            id=tenant.id,
            name=tenant.name,
            plan=tenant.plan,
            status=tenant.status,
            trial_ends_at=tenant.trial_ends_at,
            currency=tenant.currency,
            locale=tenant.locale,
        ),
    )


router.add_api_route("/me", _me, methods=["GET"], response_model=MeResponse)
auth_alias.add_api_route("/me", _me, methods=["GET"], response_model=MeResponse)
