"""Uygulama fabrikası."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.crypto import FieldCipher
from app.core.email import EmailSender, FileEmailSender, InMemoryOutbox
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import CsrfMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.pwned import HibpPwnedChecker, NullPwnedChecker, PwnedPasswordChecker
from app.core.ratelimit import RateLimiter
from app.db.session import create_engine, create_sessionmaker


def create_app(
    settings: Settings | None = None,
    email_sender: EmailSender | None = None,
    pwned_checker: PwnedPasswordChecker | None = None,
) -> FastAPI:
    """FastAPI uygulamasını kurar. Bağımlılıklar testte dışarıdan verilebilir."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.rate_limiter = RateLimiter(engine)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title=settings.product_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None if settings.environment == "prod" else "/v1/openapi.json",
    )
    app.state.settings = settings
    app.state.cipher = FieldCipher(settings.master_key)
    if email_sender is None:
        email_sender = (
            InMemoryOutbox()
            if settings.email_backend == "memory"
            else FileEmailSender(settings.email_dev_outbox_path)
        )
    app.state.email_sender = email_sender
    if pwned_checker is None:
        pwned_checker = HibpPwnedChecker() if settings.pwned_check_enabled else NullPwnedChecker()
    app.state.pwned_checker = pwned_checker

    # Ekleme sırasının tersi çalışır: en dışta güvenlik başlıkları, sonra istek bağlamı, en içte CSRF.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(api_router)
    return app
