"""Çerez yardımcıları. `__Host-` öneki: Secure, Path=/ ve Domain yok zorunluluğu getirir."""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import Settings
from app.core.middleware import CSRF_COOKIE

SESSION_COOKIE = "__Host-nk_session"
PENDING_COOKIE = "__Host-nk_pending"


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    """Oturum çerezi: HttpOnly, Secure, SameSite=Lax, Path=/; ömrü mutlak süre kadar."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_absolute_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def set_pending_cookie(response: Response, token: str, settings: Settings) -> None:
    """TOTP ikinci adımı için kısa ömürlü imzalı çerez."""
    response.set_cookie(
        PENDING_COOKIE,
        token,
        max_age=settings.pending_totp_ttl_seconds,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    """CSRF çerezi JS tarafından okunup başlığa kopyalanır, bu yüzden HttpOnly değildir."""
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=settings.session_absolute_seconds,
        path="/",
        secure=True,
        httponly=False,
        samesite="lax",
    )


def clear_auth_cookies(response: Response) -> None:
    """Oturum ve bekleyen TOTP çerezlerini siler."""
    for name in (SESSION_COOKIE, PENDING_COOKIE):
        response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")
