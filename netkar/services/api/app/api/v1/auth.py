"""/v1/auth: kayıt, giriş, çıkış, TOTP ve parola sıfırlama."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthDep,
    CipherDep,
    DbDep,
    EmailSenderDep,
    PwnedDep,
    RateLimiterDep,
    SettingsDep,
    client_ip,
    ip_hash_for,
)
from app.api.v1.schemas import (
    CsrfResponse,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    StatusResponse,
    TotpCodeRequest,
    TotpSetupResponse,
)
from app.core.config import Settings
from app.core.cookies import (
    PENDING_COOKIE,
    SESSION_COOKIE,
    clear_auth_cookies,
    set_csrf_cookie,
    set_pending_cookie,
    set_session_cookie,
)
from app.core.crypto import DecryptionError, FieldCipher, hmac_hex
from app.core.email import EmailMessage
from app.core.errors import ProblemError
from app.core.middleware import CSRF_COOKIE, is_valid_csrf_format, new_csrf_token
from app.core.security import (
    burn_password_verification,
    hash_password,
    new_totp_secret,
    read_pending_token,
    sign_pending_token,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.db.rls import set_rls_context
from app.models import User
from app.services import auth as auth_service
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

_WINDOW_LOGIN = 15 * 60
_WINDOW_HOURLY = 60 * 60


def _digest(settings: Settings, purpose: str, value: str) -> str:
    return hmac_hex(settings.master_key, purpose, value)[:32]


def _invalid_credentials() -> ProblemError:
    return ProblemError(
        401, "Geçersiz kimlik bilgileri", "invalid-credentials", "E-posta veya parola hatalı."
    )


def _weak_password() -> ProblemError:
    return ProblemError(
        422,
        "Parola kabul edilmedi",
        "weak-password",
        "Bu parola bilinen veri sızıntılarında görülmüş. Lütfen farklı bir parola seçin.",
    )


@router.get("/csrf", response_model=CsrfResponse)
async def csrf(request: Request, response: Response, settings: SettingsDep) -> CsrfResponse:
    """CSRF çerezini üretir (varsa geçerli olanı korur) ve değerini döndürür."""
    existing = request.cookies.get(CSRF_COOKIE, "")
    token = existing if is_valid_csrf_format(existing) else new_csrf_token()
    set_csrf_cookie(response, token, settings)
    return CsrfResponse(csrf_token=token)


@router.post("/register", status_code=202, response_model=StatusResponse)
async def register(
    body: RegisterRequest,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    pwned: PwnedDep,
    sender: EmailSenderDep,
    background: BackgroundTasks,
) -> StatusResponse:
    """Hesap varlığını sızdırmayan kayıt: her durumda aynı 202 yanıtı döner."""
    ip = client_ip(request, settings)
    await limiter.hit(
        f"register:ip:{_digest(settings, 'rl-ip', ip)}",
        settings.rate_limit_register_ip,
        _WINDOW_HOURLY,
    )
    # Zamanlama farkını gizlemek için özet her durumda hesaplanır.
    password_hash = hash_password(body.password)
    if await pwned.is_pwned(body.password):
        raise _weak_password()
    created = await auth_service.register_account(
        db, body.email, password_hash, body.tenant_name, settings.trial_days
    )
    if created is None:
        await db.rollback()
        message = EmailMessage(
            to=body.email,
            subject=f"{settings.product_name}: bu e-posta ile zaten bir hesap var",
            body=(
                f"Bu e-posta adresiyle {settings.product_name} üzerinde kayıt olunmak istendi, "
                "ancak adres zaten kayıtlı. Siz değilseniz bu iletiyi yok sayabilirsiniz. "
                f"Parolanızı unuttuysanız {settings.web_base_url}/forgot-password adresini kullanın."
            ),
        )
    else:
        user_id, tenant_id = created
        await set_rls_context(db, tenant_id, user_id)
        await record_audit(
            db,
            tenant_id,
            "tenant.created",
            user_id=user_id,
            target=f"tenant:{tenant_id}",
            ip_hash=ip_hash_for(request, settings),
        )
        await db.commit()
        message = EmailMessage(
            to=body.email,
            subject=f"{settings.product_name}: hesabınız oluşturuldu",
            body=f"{settings.product_name} hesabınız hazır. {settings.web_base_url}/login adresinden giriş yapabilirsiniz.",
        )
    background.add_task(sender.send, message)
    return StatusResponse(status="accepted")


async def _start_session(
    request: Request,
    response: Response,
    db: AsyncSession,
    settings: Settings,
    user_id: UUID,
    tenant_id: UUID,
    action: str,
) -> None:
    """Tenant bağlamını kurar, oturum + denetim kaydı yazar, çerezleri ayarlar."""
    await set_rls_context(db, tenant_id, user_id)
    ip_hash = ip_hash_for(request, settings)
    token = await auth_service.create_session(
        db,
        settings,
        user_id,
        tenant_id,
        ip_hash,
        request.headers.get("user-agent"),
    )
    await record_audit(db, tenant_id, action, user_id=user_id, ip_hash=ip_hash)
    await db.commit()
    set_session_cookie(response, token, settings)
    # Oturum başlangıcında CSRF token'ı yenilenir.
    set_csrf_cookie(response, new_csrf_token(), settings)
    response.delete_cookie(PENDING_COOKIE, path="/", secure=True, httponly=True, samesite="lax")


@router.post("/login", response_model=StatusResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
) -> StatusResponse:
    """Parola doğrular; TOTP açıksa ikinci adım için bekleyen çerez verir."""
    ip = client_ip(request, settings)
    await limiter.hit(
        f"login:ip:{_digest(settings, 'rl-ip', ip)}", settings.rate_limit_login_ip, _WINDOW_LOGIN
    )
    await limiter.hit(
        f"login:email:{_digest(settings, 'rl-email', body.email)}",
        settings.rate_limit_login_email,
        _WINDOW_LOGIN,
    )
    candidate = await auth_service.find_user_for_login(db, body.email)
    if candidate is None or candidate.tenant_id is None:
        await db.rollback()
        burn_password_verification(body.password)
        raise _invalid_credentials()
    if not verify_password(candidate.password_hash, body.password):
        await set_rls_context(db, candidate.tenant_id, candidate.user_id)
        await record_audit(
            db,
            candidate.tenant_id,
            "auth.login_failed",
            user_id=candidate.user_id,
            ip_hash=ip_hash_for(request, settings),
        )
        await db.commit()
        raise _invalid_credentials()
    if candidate.totp_enabled:
        await db.rollback()
        pending = sign_pending_token(
            settings.master_key, candidate.user_id, candidate.tenant_id, settings.pending_totp_ttl_seconds
        )
        set_pending_cookie(response, pending, settings)
        return StatusResponse(status="totp_required")
    await _start_session(
        request, response, db, settings, candidate.user_id, candidate.tenant_id, "auth.login"
    )
    return StatusResponse(status="ok")


@router.post("/totp/verify", response_model=StatusResponse)
async def totp_verify(
    body: TotpCodeRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    cipher: CipherDep,
) -> StatusResponse:
    """Girişte ikinci adım: bekleyen çerez + 6 haneli TOTP kodu."""
    pending = request.cookies.get(PENDING_COOKIE)
    identity = read_pending_token(settings.master_key, pending) if pending else None
    if identity is None:
        raise ProblemError(401, "Kimlik doğrulama gerekli", "unauthorized", "Önce parola ile giriş yapın.")
    user_id, tenant_id = identity
    await limiter.hit(
        f"totp:user:{_digest(settings, 'rl-user', str(user_id))}",
        settings.rate_limit_totp_user,
        _WINDOW_LOGIN,
    )
    await set_rls_context(db, tenant_id, user_id)
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    secret = _decrypt_secret(cipher, user)
    if user is None or secret is None or not user.totp_enabled or not verify_totp(secret, body.code):
        await record_audit(
            db, tenant_id, "auth.totp_failed", user_id=user_id, ip_hash=ip_hash_for(request, settings)
        )
        await db.commit()
        raise ProblemError(401, "Geçersiz kod", "invalid-code", "Doğrulama kodu hatalı.")
    await _start_session(request, response, db, settings, user_id, tenant_id, "auth.login_totp")
    return StatusResponse(status="ok")


@router.post("/logout", status_code=204)
async def logout(request: Request, db: DbDep, settings: SettingsDep) -> Response:
    """Oturumu iptal eder ve çerezleri siler. Oturum yoksa da 204 döner (idempotent)."""
    response = Response(status_code=204)
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        found = await auth_service.lookup_session(db, settings, token)
        if found is not None:
            ctx, _ = found
            await set_rls_context(db, ctx.tenant_id, ctx.user_id)
            await auth_service.revoke_session(db, ctx.session_id)
            await record_audit(
                db, ctx.tenant_id, "auth.logout", user_id=ctx.user_id, ip_hash=ip_hash_for(request, settings)
            )
            await db.commit()
    clear_auth_cookies(response)
    return response


def _decrypt_secret(cipher: FieldCipher, user: User | None) -> str | None:
    if user is None or user.totp_secret_encrypted is None:
        return None
    try:
        return cipher.decrypt(user.totp_secret_encrypted, user.id.bytes)
    except DecryptionError:
        return None


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(
    request: Request, ctx: AuthDep, db: DbDep, settings: SettingsDep, cipher: CipherDep
) -> TotpSetupResponse:
    """Yeni TOTP sırrı üretir (şifreli saklanır, henüz etkin değil)."""
    user = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-already-enabled", "TOTP zaten etkin.")
    secret = new_totp_secret()
    encrypted = cipher.encrypt(secret, user.id.bytes)
    await db.execute(update(User).where(User.id == ctx.user_id).values(totp_secret_encrypted=encrypted))
    await record_audit(
        db, ctx.tenant_id, "auth.totp_setup", user_id=ctx.user_id, ip_hash=ip_hash_for(request, settings)
    )
    await db.commit()
    return TotpSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email, settings.product_name))


@router.post("/totp/enable", status_code=204)
async def totp_enable(
    body: TotpCodeRequest, request: Request, ctx: AuthDep, db: DbDep, settings: SettingsDep, cipher: CipherDep
) -> Response:
    """Kullanıcının ürettiği kodu doğrulayıp TOTP'yi etkinleştirir."""
    user = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    if user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-already-enabled", "TOTP zaten etkin.")
    secret = _decrypt_secret(cipher, user)
    if secret is None:
        raise ProblemError(409, "Çakışma", "totp-not-set-up", "Önce /v1/auth/totp/setup çağrılmalı.")
    if not verify_totp(secret, body.code):
        raise ProblemError(400, "Geçersiz kod", "invalid-code", "Doğrulama kodu hatalı.")
    await db.execute(update(User).where(User.id == ctx.user_id).values(totp_enabled=True))
    await record_audit(
        db, ctx.tenant_id, "auth.totp_enabled", user_id=ctx.user_id, ip_hash=ip_hash_for(request, settings)
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/password-reset/request", status_code=202, response_model=StatusResponse)
async def password_reset_request(
    body: PasswordResetRequest,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    sender: EmailSenderDep,
    background: BackgroundTasks,
) -> StatusResponse:
    """Hesap varlığını sızdırmaz: her durumda 202. E-posta yalnız hesap varsa gider."""
    ip = client_ip(request, settings)
    await limiter.hit(
        f"reset:ip:{_digest(settings, 'rl-ip', ip)}", settings.rate_limit_reset_ip, _WINDOW_HOURLY
    )
    await limiter.hit(
        f"reset:email:{_digest(settings, 'rl-email', body.email)}",
        settings.rate_limit_reset_email,
        _WINDOW_HOURLY,
    )
    created = await auth_service.create_password_reset(db, body.email, settings.reset_token_ttl_minutes)
    await db.commit()
    if created is not None:
        _, token = created
        link = f"{settings.web_base_url}/reset-password?token={token}"
        background.add_task(
            sender.send,
            EmailMessage(
                to=body.email,
                subject=f"{settings.product_name}: parola sıfırlama",
                body=(
                    f"Parolanızı sıfırlamak için {settings.reset_token_ttl_minutes} dakika içinde "
                    f"şu bağlantıyı kullanın: {link}\nBu isteği siz yapmadıysanız yok sayın."
                ),
            ),
        )
    return StatusResponse(status="accepted")


@router.post("/password-reset/confirm", status_code=204)
async def password_reset_confirm(
    body: PasswordResetConfirm,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    pwned: PwnedDep,
) -> Response:
    """Token tek kullanımlık ve süreli; başarıda tüm oturumlar iptal edilir."""
    ip = client_ip(request, settings)
    await limiter.hit(
        f"reset-confirm:ip:{_digest(settings, 'rl-ip', ip)}", settings.rate_limit_reset_ip * 2, _WINDOW_HOURLY
    )
    if await pwned.is_pwned(body.new_password):
        raise _weak_password()
    result = await auth_service.consume_password_reset(db, body.token, hash_password(body.new_password))
    if result is None:
        await db.rollback()
        raise ProblemError(
            400, "Geçersiz bağlantı", "invalid-reset-token", "Bağlantı geçersiz veya süresi dolmuş."
        )
    user_id, tenant_id = result
    if tenant_id is not None:
        await set_rls_context(db, tenant_id, user_id)
        await record_audit(
            db, tenant_id, "auth.password_reset", user_id=user_id, ip_hash=ip_hash_for(request, settings)
        )
    await db.commit()
    return Response(status_code=204)
