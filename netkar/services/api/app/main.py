"""Uygulama fabrikası."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.product_costs import COST_IMPORT_PATH_PATTERN
from app.api.v1.router import api_router
from app.core.clientip import ClientIpResolver
from app.core.config import Settings, get_settings
from app.core.crypto import FieldCipher
from app.core.email import EmailSender, FileEmailSender, InMemoryOutbox
from app.core.envelope import EnvelopeCipher
from app.core.errors import install_error_handlers
from app.core.limits import BodyLimitMiddleware, IpRateLimitMiddleware, IpRule
from app.core.logging import configure_logging
from app.core.middleware import CsrfMiddleware, RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.pwned import HibpPwnedChecker, NullPwnedChecker, PwnedPasswordChecker
from app.core.ratelimit import RateLimiter
from app.core.security import PasswordWorker
from app.db.session import create_engine, create_rate_limit_engine, create_sessionmaker
from app.services.import_gate import ImportGate
from app.services.marketplace_accounts import TrendyolClientFactory, default_client_factory
from app.services.report_cache import ReportCache
from app.services.report_gate import ReportGate
from app.services.xlsx_stream import require_defusedxml
from app.worker.queue import JobQueue, ProcrastinateJobQueue

_WINDOW_LOGIN = 15 * 60
_WINDOW_HOURLY = 60 * 60


def _ip_rate_rules(settings: Settings) -> dict[str, IpRule]:
    """IP başına sınırlar (anahtar öneki ve eşikler eskiyle aynıdır)."""
    return {
        "/v1/auth/login": IpRule("login", settings.rate_limit_login_ip, _WINDOW_LOGIN),
        "/v1/auth/register": IpRule("register", settings.rate_limit_register_ip, _WINDOW_HOURLY),
        "/v1/auth/password-reset/request": IpRule("reset", settings.rate_limit_reset_ip, _WINDOW_HOURLY),
        "/v1/auth/password-reset/confirm": IpRule(
            "reset-confirm", settings.rate_limit_reset_ip * 2, _WINDOW_HOURLY
        ),
        "/v1/auth/totp/verify": IpRule("totp", settings.rate_limit_totp_ip, _WINDOW_LOGIN),
        # Trendyol'a doğrulama çağrısı yaptığı için IP başına da sınırlanır.
        "/v1/marketplace-accounts": IpRule("mpconnect", settings.rate_limit_marketplace_ip, _WINDOW_HOURLY),
    }


def create_app(
    settings: Settings | None = None,
    email_sender: EmailSender | None = None,
    pwned_checker: PwnedPasswordChecker | None = None,
    trendyol_client_factory: TrendyolClientFactory | None = None,
    job_queue: JobQueue | None = None,
) -> FastAPI:
    """FastAPI uygulamasını kurar. Bağımlılıklar testte dışarıdan verilebilir."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # XML ayrıştırma korumasız çalışıyorsa uygulama hiç açılmaz (denetim S3 B-02, fail-closed).
    require_defusedxml()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
        )
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        # Hız sınırı sayacı oturum havuzundan AYRI havuz kullanır (denetim S4 Y-01, kilitlenme).
        limiter_engine = create_rate_limit_engine(
            settings.database_url,
            pool_size=settings.rate_limit_pool_size,
            pool_timeout=settings.rate_limit_pool_timeout_seconds,
        )
        app.state.rate_limiter_engine = limiter_engine
        app.state.rate_limiter = RateLimiter(limiter_engine, settings.rate_limit_busy_retry_after_seconds)
        # CapacityLimiter olay döngüsüne bağlıdır; bu yüzden lifespan içinde üretilir.
        app.state.password_worker = PasswordWorker(settings.password_hash_concurrency)
        # Maliyet içe aktarma: süreç başına ayrıştırma yuvaları ve kiracı kilidi (denetim S3 Y-01).
        app.state.import_gate = ImportGate(
            settings.cost_import_parse_concurrency, settings.cost_import_retry_after_seconds
        )
        # Rapor motoru: kiracı ve süreç başına beklemeyen eşzamanlılık kapısı (denetim S4 Y-01, O-01).
        app.state.report_gate = ReportGate(
            settings.profit_report_process_concurrency,
            settings.profit_report_tenant_concurrency,
            settings.profit_report_retry_after_seconds,
        )
        # Dönem sonucu önbelleği (SU-01): aynı dönem, ayar ve veri sürümü için motor yeniden çalışmaz.
        app.state.report_cache = ReportCache(
            ttl_seconds=settings.profit_report_cache_ttl_seconds,
            max_entries=settings.profit_report_cache_max_entries,
            max_lines=settings.profit_report_cache_max_lines,
            tenant_entries=settings.profit_report_cache_tenant_entries,
        )
        try:
            yield
        finally:
            await limiter_engine.dispose()
            await engine.dispose()

    app = FastAPI(
        title=settings.product_name,
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
        docs_url=None,
        redoc_url=None,
        openapi_url=None if settings.environment == "prod" else "/v1/openapi.json",
    )
    app.state.settings = settings
    app.state.client_ip_resolver = ClientIpResolver(settings.trusted_proxy_cidrs, settings.trusted_proxy_hops)
    app.state.cipher = FieldCipher(settings.master_key)
    # Pazaryeri sırları için zarf şifreleme (KEK halkası ayrı ortam değişkenlerinden gelir).
    app.state.envelope = EnvelopeCipher(settings.key_ring)
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
    # Trendyol istemcisi fabrikası: testlerde sahte taşımalı istemci verilir.
    app.state.trendyol_client_factory = trendyol_client_factory or default_client_factory(settings)
    # İş kuyruğu (bağlantı eklenince backfill): API `netkar_app` rolüyle yalnız iş ekler (ADR-0005).
    app.state.job_queue = job_queue or ProcrastinateJobQueue(settings)

    # Ekleme sırasının tersi çalışır. Dıştan içe: güvenlik başlıkları, istek bağlamı, gövde boyut
    # sınırı, IP rate limit, CSRF. Gövde sınırı ve IP sınırı FastAPI gövdeyi ayrıştırmadan önce
    # çalışır (denetim O-04); 429 alacak istekler gövdesi okunmadan reddedilir.
    app.add_middleware(CsrfMiddleware)
    app.add_middleware(IpRateLimitMiddleware, rules=_ip_rate_rules(settings))
    app.add_middleware(
        BodyLimitMiddleware,
        default_limit=settings.max_request_body_bytes,
        prefix_limits={
            "/v1/auth/": settings.max_auth_body_bytes,
            "/v1/marketplace-accounts": settings.max_marketplace_body_bytes,
        },
        # Maliyet içe aktarma: yalnız bu uç nokta dosya yükler (hesap kimliği yolun ortasındadır).
        pattern_limits={COST_IMPORT_PATH_PATTERN: settings.max_cost_import_body_bytes},
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    install_error_handlers(app)
    app.include_router(api_router)
    return app
