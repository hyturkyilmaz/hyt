"""Trendyol entegrasyonu: tek istemci, modeller, hız sınırı ve hata türleri."""

from app.integrations.trendyol.client import TrendyolClient
from app.integrations.trendyol.config import TrendyolConfig, TrendyolEnvironment
from app.integrations.trendyol.errors import (
    TrendyolAuthError,
    TrendyolConfigError,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolRequestError,
    TrendyolServerError,
    TrendyolValidationError,
    TrendyolWaitBudgetError,
    TrendyolWindowTooLargeError,
)
from app.integrations.trendyol.identity import (
    TrendyolCredentials,
    build_user_agent,
    validate_integrator_name,
    validate_seller_id,
)

__all__ = [
    "TrendyolAuthError",
    "TrendyolClient",
    "TrendyolConfig",
    "TrendyolConfigError",
    "TrendyolCredentials",
    "TrendyolEnvironment",
    "TrendyolError",
    "TrendyolForbiddenError",
    "TrendyolNetworkError",
    "TrendyolProtocolError",
    "TrendyolRateLimitedError",
    "TrendyolRequestError",
    "TrendyolServerError",
    "TrendyolValidationError",
    "TrendyolWaitBudgetError",
    "TrendyolWindowTooLargeError",
    "build_user_agent",
    "validate_integrator_name",
    "validate_seller_id",
]
