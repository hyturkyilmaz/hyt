"""v1 yönlendirici toplayıcısı."""

from fastapi import APIRouter

from app.api.v1 import auth, health, marketplace_accounts, me, product_costs, profit, tenant

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(me.auth_alias)
api_router.include_router(tenant.router)
api_router.include_router(marketplace_accounts.router)
api_router.include_router(product_costs.router)
api_router.include_router(profit.router)
