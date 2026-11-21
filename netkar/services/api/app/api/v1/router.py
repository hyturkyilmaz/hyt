"""v1 yönlendirici toplayıcısı."""

from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    health,
    legal,
    marketplace_accounts,
    me,
    product_costs,
    profit,
    profit_settings,
    tenant,
)

api_router = APIRouter(prefix="/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(legal.router)
api_router.include_router(me.router)
api_router.include_router(me.auth_alias)
api_router.include_router(tenant.router)
api_router.include_router(marketplace_accounts.router)
api_router.include_router(product_costs.router)
api_router.include_router(profit.router)
api_router.include_router(profit_settings.router)
api_router.include_router(alerts.router)
api_router.include_router(alerts.me_router)

# D5: tek tık bildirim kapatma ucu (D6'nın import bloğuyla çakışmamak için dosyanın sonunda).
from app.api.v1.notify_unsubscribe import router as notify_unsubscribe_router  # noqa: E402

api_router.include_router(notify_unsubscribe_router)
