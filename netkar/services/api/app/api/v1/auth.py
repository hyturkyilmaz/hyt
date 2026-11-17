"""/v1/auth: kayıt, giriş, çıkış, TOTP ve parola sıfırlama."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    AuthDep,
    CipherDep,
    DbDep,
    EmailSenderDep,
    PasswordsDep,
    PwnedDep,
    RateLimiterDep,
    SettingsDep,
    VerifiedAuthDep,
    ip_hash_for,
)
from app.api.v1.schemas import (
    CsrfResponse,
    EmailVerifyRequest,
    LoginCodeRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    ReauthRequest,
    RecoveryCodesResponse,
    RegisterRequest,
    StatusResponse,
    TotpEnableRequest,
    TotpReauthRequest,
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
from app.core.crypto import DecryptionError, FieldCipher
from app.core.email import EmailMessage
from app.core.errors import ProblemError
from app.core.middleware import CSRF_COOKIE, is_valid_csrf_format, new_csrf_token
from app.core.ratelimit import RateLimiter, digest
from app.core.security import (
    PasswordWorker,
    generate_recovery_codes,
    new_totp_secret,
    normalize_recovery_code,
    read_pending_token,
    recovery_code_hash,
    sign_pending_token,
    totp_uri,
    verify_totp_step,
)
from app.db.rls import set_rls_context
from app.models import User
from app.services import auth as auth_service
from app.services.audit import record_audit
from app.services.auth import AuthContext

router = APIRouter(prefix="/auth", tags=["auth"])

_WINDOW_LOGIN = 15 * 60
_WINDOW_HOURLY = 60 * 60


def _web_link(settings: Settings, path: str, token: str | None = None) -> str:
    """Web uygulamasındaki gerçek (Türkçe) yola bağlantı; token'lı biçim sayfanın beklediği `?token=` olur."""
    base = f"{settings.web_base_url}{path}"
    return f"{base}?token={token}" if token else base


def _digest(settings: Settings, purpose: str, value: str) -> str:
    return digest(settings.master_key, purpose, value)


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
    pwned: PwnedDep,
    passwords: PasswordsDep,
    sender: EmailSenderDep,
    background: BackgroundTasks,
) -> StatusResponse:
    """Hesap varlığını sızdırmayan kayıt: her durumda aynı 202 yanıtı döner.

    IP sınırı gövde ayrıştırılmadan önce `IpRateLimitMiddleware` içinde uygulanır.
    """
    # Zamanlama farkını gizlemek için özet her durumda hesaplanır (iş parçacığı havuzunda).
    password_hash = await passwords.hash(body.password)
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
                f"Parolanızı unuttuysanız {_web_link(settings, '/sifre-sifirla')} adresini kullanın."
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
        # Doğrulama bağlantısı hesapla aynı işlemde üretilir; ham token yalnız e-postada bulunur.
        verify_token = await auth_service.create_email_verification(
            db, user_id, settings.email_verification_ttl_hours * 60
        )
        await db.commit()
        message = EmailMessage(
            to=body.email,
            subject=f"{settings.product_name}: e-posta adresinizi doğrulayın",
            body=(
                f"{settings.product_name} hesabınız oluşturuldu. E-posta adresinizi "
                f"{settings.email_verification_ttl_hours} saat içinde şu bağlantıyla doğrulayın: "
                f"{_web_link(settings, '/e-posta-dogrula', verify_token)}\n"
                "Bağlantıyı bu hesapla giriş yaptığınız tarayıcıda açın; gerekirse önce giriş istenir. "
                "Doğrulanana dek mağaza bağlama ve veri girişi kapalıdır. "
                f"Giriş: {_web_link(settings, '/giris')}\n"
                "Bu hesabı siz oluşturmadıysanız bağlantıya tıklamayın; parolanızı "
                f"{_web_link(settings, '/sifre-sifirla')} adresinden sıfırlayarak hesabı devralabilirsiniz."
            ),
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
    passwords: PasswordsDep,
) -> StatusResponse:
    """Parola doğrular; TOTP açıksa ikinci adım için bekleyen çerez verir.

    IP sınırı gövde ayrıştırılmadan önce `IpRateLimitMiddleware` içinde uygulanır.
    """
    await limiter.hit(
        f"login:email:{_digest(settings, 'rl-email', body.email)}",
        settings.rate_limit_login_email,
        _WINDOW_LOGIN,
    )
    candidate = await auth_service.find_user_for_login(db, body.email)
    if candidate is None or candidate.tenant_id is None:
        await db.rollback()
        await passwords.burn(body.password)
        raise _invalid_credentials()
    if not await passwords.verify(candidate.password_hash, body.password):
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
    body: LoginCodeRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    cipher: CipherDep,
) -> StatusResponse:
    """Girişte ikinci adım: bekleyen çerez + 6 haneli TOTP kodu YA DA tek kullanımlık kurtarma kodu.

    Korumalar: IP sınırı (ara katman), kullanıcı başına sınır, ardışık hatada geçici kilit (O-02; TOTP ve
    kurtarma denemeleri aynı sayacı paylaşır), aynı zaman adımının tekrar kullanımının reddi (O-01) ve
    kurtarma kodunun koşullu UPDATE ile atomik tek kullanımı.
    """
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
    await _raise_if_locked(db, user)
    ip_hash = ip_hash_for(request, settings)
    use_recovery = not _is_totp_code(body.code)
    failure_action: str | None = None
    if use_recovery:
        normalized = normalize_recovery_code(body.code)
        if user is None or not user.totp_enabled or normalized is None:
            failure_action = "auth.recovery_failed"
        elif not await auth_service.consume_recovery_code(
            db, user_id, recovery_code_hash(settings.master_key, user_id, normalized)
        ):
            # Bilinmeyen, kullanılmış ya da geçersiz kılınmış kod (ya da eşzamanlı yarışı kaybeden).
            failure_action = "auth.recovery_failed"
    else:
        secret = _decrypt_secret(cipher, user)
        step = (
            verify_totp_step(secret, body.code)
            if user is not None and user.totp_enabled and secret is not None
            else None
        )
        if user is None or step is None:
            failure_action = "auth.totp_failed"
        elif not await auth_service.consume_totp_step(db, user_id, step):
            # Aynı veya daha eski zaman adımı: kod daha önce kullanılmış (tekrar oynatma).
            failure_action = "auth.totp_replay"
    if failure_action is not None:
        meta: dict[str, object] = {}
        if user is not None:
            count, locked_until = await auth_service.register_totp_failure(
                db, user_id, settings.totp_max_failures, settings.totp_lock_seconds
            )
            meta = {"failures": count}
            if locked_until is not None:
                await record_audit(
                    db,
                    tenant_id,
                    "auth.totp_locked",
                    user_id=user_id,
                    ip_hash=ip_hash,
                    meta={"lock_seconds": settings.totp_lock_seconds},
                )
        await record_audit(db, tenant_id, failure_action, user_id=user_id, ip_hash=ip_hash, meta=meta)
        await db.commit()
        raise ProblemError(401, "Geçersiz kod", "invalid-code", "Doğrulama kodu hatalı.")
    if use_recovery:
        # Kurtarma kodu da başarılı ikinci faktördür: kaba kuvvet sayacı sıfırlanır, kullanım denetim kaydına yazılır.
        await db.execute(
            update(User).where(User.id == user_id).values(totp_failed_count=0, totp_locked_until=None)
        )
        await record_audit(
            db,
            tenant_id,
            "auth.recovery_code_used",
            user_id=user_id,
            ip_hash=ip_hash,
            meta={"remaining": await auth_service.count_recovery_codes(db, user_id)},
        )
        await _start_session(request, response, db, settings, user_id, tenant_id, "auth.login_recovery")
    else:
        await _start_session(request, response, db, settings, user_id, tenant_id, "auth.login_totp")
    return StatusResponse(status="ok")


def _is_totp_code(code: str) -> bool:
    return len(code) == 6 and code.isascii() and code.isdigit()


async def _raise_if_locked(db: AsyncSession, user: User | None) -> None:
    """Ardışık hata kilidi sürüyorsa 429 (Retry-After ile) fırlatır."""
    if user is not None and user.totp_locked_until is not None:
        remaining = (user.totp_locked_until - datetime.now(UTC)).total_seconds()
        if remaining > 0:
            await db.rollback()
            raise ProblemError(
                429,
                "Çok fazla istek",
                "totp-locked",
                "Çok fazla hatalı kod girildi. Lütfen daha sonra tekrar deneyin.",
                headers={"Retry-After": str(max(1, int(remaining)))},
            )


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


async def _reauth_failed(
    request: Request,
    ctx: AuthContext,
    db: AsyncSession,
    settings: Settings,
    factor: str,
    status: int = 403,
) -> ProblemError:
    """Başarısız yeniden doğrulamayı mevcut kilit sayacına işler, denetim kaydı yazar, hatayı döndürür.

    403 verilir (401 değil): web istemcisi 401'i "oturum bitti" sayıp girişe yönlendirir; burada oturum geçerlidir.
    """
    count, locked_until = await auth_service.register_totp_failure(
        db, ctx.user_id, settings.totp_max_failures, settings.totp_lock_seconds
    )
    ip_hash = ip_hash_for(request, settings)
    if locked_until is not None:
        await record_audit(
            db,
            ctx.tenant_id,
            "auth.totp_locked",
            user_id=ctx.user_id,
            ip_hash=ip_hash,
            meta={"lock_seconds": settings.totp_lock_seconds},
        )
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.reauth_failed",
        user_id=ctx.user_id,
        ip_hash=ip_hash,
        meta={"factor": factor, "failures": count},
    )
    await db.commit()
    return ProblemError(
        status,
        "Yeniden doğrulama başarısız",
        "reauth-failed" if factor == "password" else "invalid-code",
        "Parola hatalı." if factor == "password" else "Doğrulama kodu hatalı.",
    )


async def _reauthenticate(
    request: Request,
    ctx: AuthContext,
    db: AsyncSession,
    settings: Settings,
    limiter: RateLimiter,
    passwords: PasswordWorker,
    cipher: FieldCipher,
    password: str,
    code: str | None = None,
    *,
    need_code: bool = False,
) -> User:
    """MFA ayarı değişikliği öncesi yeniden kimlik doğrulama (ASVS V2.5, V7.5; denetim O-05).

    Güncel parola her zaman istenir; `need_code` (TOTP kapatma, kod yenileme) ve hesapta TOTP etkinse `code`
    (güncel TOTP ya da kurtarma kodu) da doğrulanmalıdır. Kurulum/etkinleştirme yalnız parola ister (TOTP henüz yok). Kullanıcı başına hız sınırı ve ardışık hata kilidi girişteki TOTP altyapısını paylaşır.
    Başarıda kullanıcı satırı döner; kurtarma kodu/TOTP adımı bu işlemde tüketilmiştir (çağıran commit eder).
    """
    await limiter.hit(
        f"reauth:user:{_digest(settings, 'rl-user', str(ctx.user_id))}",
        settings.rate_limit_totp_user,
        _WINDOW_LOGIN,
    )
    user = (await db.execute(select(User).where(User.id == ctx.user_id))).scalar_one()
    await _raise_if_locked(db, user)
    if not await auth_service.verify_account_password(db, passwords, user.email, password):
        # find_user_for_login işlem bağlamını değiştirmez; RLS bağlamı hâlâ geçerlidir.
        raise await _reauth_failed(request, ctx, db, settings, "password")
    if not need_code or not user.totp_enabled:
        return user
    if code is None:
        raise await _reauth_failed(request, ctx, db, settings, "code")
    if _is_totp_code(code):
        secret = _decrypt_secret(cipher, user)
        step = verify_totp_step(secret, code) if secret is not None else None
        if step is None or not await auth_service.consume_totp_step(db, user.id, step):
            raise await _reauth_failed(request, ctx, db, settings, "code")
    else:
        normalized = normalize_recovery_code(code)
        if normalized is None or not await auth_service.consume_recovery_code(
            db, user.id, recovery_code_hash(settings.master_key, user.id, normalized)
        ):
            raise await _reauth_failed(request, ctx, db, settings, "code")
    return user


@router.post("/totp/setup", response_model=TotpSetupResponse)
async def totp_setup(
    body: ReauthRequest,
    request: Request,
    ctx: VerifiedAuthDep,
    db: DbDep,
    settings: SettingsDep,
    cipher: CipherDep,
    limiter: RateLimiterDep,
    passwords: PasswordsDep,
) -> TotpSetupResponse:
    """Yeni TOTP sırrı üretir (şifreli saklanır, henüz etkin değil). Güncel parola ister (yeniden doğrulama).

    E-postası doğrulanmamış hesap TOTP kuramaz: önceden kayıt olan saldırganın ikinci faktörü gerçek
    sahibini kilitleyemesin (denetim O-06).
    """
    user = await _reauthenticate(request, ctx, db, settings, limiter, passwords, cipher, body.password)
    if user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-already-enabled", "TOTP zaten etkin.")
    secret = new_totp_secret()
    encrypted = cipher.encrypt(secret, user.id.bytes)
    # Yeni sır: önceki sırra ait zaman adımı ve hata sayacı sıfırlanır.
    await db.execute(
        update(User)
        .where(User.id == ctx.user_id)
        .values(
            totp_secret_encrypted=encrypted, totp_last_step=None, totp_failed_count=0, totp_locked_until=None
        )
    )
    await record_audit(
        db, ctx.tenant_id, "auth.totp_setup", user_id=ctx.user_id, ip_hash=ip_hash_for(request, settings)
    )
    await db.commit()
    return TotpSetupResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email, settings.product_name))


async def _issue_recovery_codes(db: AsyncSession, settings: Settings, user_id: UUID) -> list[str]:
    """10 yeni kod üretir, yalnız HMAC özetlerini yazar (öncekiler geçersiz kılınır); düz metni döndürür."""
    codes = generate_recovery_codes()
    hashes = []
    for code in codes:
        normalized = normalize_recovery_code(code)
        assert normalized is not None  # kendi ürettiğimiz kod her zaman geçerlidir
        hashes.append(recovery_code_hash(settings.master_key, user_id, normalized))
    await auth_service.replace_recovery_codes(db, user_id, hashes)
    return codes


@router.post("/totp/enable", response_model=RecoveryCodesResponse)
async def totp_enable(
    body: TotpEnableRequest,
    request: Request,
    ctx: VerifiedAuthDep,
    db: DbDep,
    settings: SettingsDep,
    cipher: CipherDep,
    limiter: RateLimiterDep,
    passwords: PasswordsDep,
) -> RecoveryCodesResponse:
    """Parola + kullanıcının ürettiği kodu doğrulayıp TOTP'yi etkinleştirir; 10 kurtarma kodunu BİR KEZ döndürür."""
    user = await _reauthenticate(request, ctx, db, settings, limiter, passwords, cipher, body.password)
    if user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-already-enabled", "TOTP zaten etkin.")
    secret = _decrypt_secret(cipher, user)
    if secret is None:
        raise ProblemError(409, "Çakışma", "totp-not-set-up", "Önce /v1/auth/totp/setup çağrılmalı.")
    step = verify_totp_step(secret, body.code)
    if step is None:
        # Yanlış kod da kilit sayacına işlenir (kurulum kodunu kaba kuvvetle denemek sınırlıdır).
        count, locked_until = await auth_service.register_totp_failure(
            db, ctx.user_id, settings.totp_max_failures, settings.totp_lock_seconds
        )
        await record_audit(
            db,
            ctx.tenant_id,
            "auth.reauth_failed",
            user_id=ctx.user_id,
            ip_hash=ip_hash_for(request, settings),
            meta={"factor": "enable_code", "failures": count, "locked": locked_until is not None},
        )
        await db.commit()
        raise ProblemError(400, "Geçersiz kod", "invalid-code", "Doğrulama kodu hatalı.")
    # Etkinleştirmede kullanılan adım da tüketilir: aynı kodla hemen giriş yapılamaz.
    await db.execute(
        update(User)
        .where(User.id == ctx.user_id)
        .values(totp_enabled=True, totp_last_step=step, totp_failed_count=0, totp_locked_until=None)
    )
    codes = await _issue_recovery_codes(db, settings, ctx.user_id)
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.totp_enabled",
        user_id=ctx.user_id,
        ip_hash=ip_hash_for(request, settings),
        meta={"recovery_codes": len(codes)},
    )
    await db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


@router.post("/totp/disable", status_code=204)
async def totp_disable(
    body: TotpReauthRequest,
    request: Request,
    ctx: VerifiedAuthDep,
    db: DbDep,
    settings: SettingsDep,
    cipher: CipherDep,
    limiter: RateLimiterDep,
    passwords: PasswordsDep,
) -> Response:
    """TOTP'yi kapatır: güncel parola + güncel TOTP (ya da kurtarma) kodu ister; diğer tüm oturumlar iptal edilir.

    Sır, zaman adımı ve sayaçlar temizlenir, kalan kurtarma kodları geçersiz kılınır (satırlar silinmez).
    """
    user = await _reauthenticate(
        request, ctx, db, settings, limiter, passwords, cipher, body.password, body.code, need_code=True
    )
    if not user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-not-enabled", "TOTP etkin değil.")
    await db.execute(
        update(User)
        .where(User.id == ctx.user_id)
        .values(
            totp_enabled=False,
            totp_secret_encrypted=None,
            totp_last_step=None,
            totp_failed_count=0,
            totp_locked_until=None,
        )
    )
    await auth_service.revoke_recovery_codes(db, ctx.user_id)
    revoked = await auth_service.revoke_other_sessions(db, ctx.user_id, ctx.session_id)
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.totp_disabled",
        user_id=ctx.user_id,
        ip_hash=ip_hash_for(request, settings),
        meta={"other_sessions_revoked": revoked},
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/totp/recovery-codes", response_model=RecoveryCodesResponse)
async def recovery_codes_regenerate(
    body: TotpReauthRequest,
    request: Request,
    ctx: VerifiedAuthDep,
    db: DbDep,
    settings: SettingsDep,
    cipher: CipherDep,
    limiter: RateLimiterDep,
    passwords: PasswordsDep,
) -> RecoveryCodesResponse:
    """Kurtarma kodlarını yeniler (eskiler geçersiz olur): güncel parola + TOTP kodu ister; diğer oturumları iptal eder."""
    user = await _reauthenticate(
        request, ctx, db, settings, limiter, passwords, cipher, body.password, body.code, need_code=True
    )
    if not user.totp_enabled:
        raise ProblemError(409, "Çakışma", "totp-not-enabled", "TOTP etkin değil.")
    codes = await _issue_recovery_codes(db, settings, ctx.user_id)
    revoked = await auth_service.revoke_other_sessions(db, ctx.user_id, ctx.session_id)
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.recovery_codes_regenerated",
        user_id=ctx.user_id,
        ip_hash=ip_hash_for(request, settings),
        meta={"recovery_codes": len(codes), "other_sessions_revoked": revoked},
    )
    await db.commit()
    return RecoveryCodesResponse(recovery_codes=codes)


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
    await limiter.hit(
        f"reset:email:{_digest(settings, 'rl-email', body.email)}",
        settings.rate_limit_reset_email,
        _WINDOW_HOURLY,
    )
    created = await auth_service.create_password_reset(db, body.email, settings.reset_token_ttl_minutes)
    await db.commit()
    if created is not None:
        _, token = created
        link = _web_link(settings, "/sifre-sifirla", token)
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
    pwned: PwnedDep,
    passwords: PasswordsDep,
) -> Response:
    """Token tek kullanımlık ve süreli; başarıda tüm oturumlar iptal edilir.

    Doğrulanmış hesapta TOTP etkin kalır ve girişte istenir (e-posta ele geçirilse bile ikinci faktör
    korunur). Doğrulanmamış hesapta sıfırlama e-postayı doğrular ve TOTP'yi temizler (denetim O-06).

    IP sınırı gövde ayrıştırılmadan önce `IpRateLimitMiddleware` içinde uygulanır.
    """
    if await pwned.is_pwned(body.new_password):
        raise _weak_password()
    result = await auth_service.consume_password_reset(
        db, body.token, await passwords.hash(body.new_password)
    )
    if result is None:
        await db.rollback()
        raise ProblemError(
            400, "Geçersiz bağlantı", "invalid-reset-token", "Bağlantı geçersiz veya süresi dolmuş."
        )
    user_id, tenant_id = result.user_id, result.tenant_id
    if tenant_id is not None:
        await set_rls_context(db, tenant_id, user_id)
        ip_hash = ip_hash_for(request, settings)
        await record_audit(
            db,
            tenant_id,
            "auth.password_reset",
            user_id=user_id,
            ip_hash=ip_hash,
            meta={"claimed_unverified": result.claimed_unverified},
        )
        if result.claimed_unverified:
            # Sıfırlama e-posta sahipliğini kanıtladı: hesap doğrulandı, olası saldırgan TOTP'si temizlendi.
            await record_audit(
                db,
                tenant_id,
                "auth.email_verified",
                user_id=user_id,
                ip_hash=ip_hash,
                meta={"via": "password_reset", "totp_cleared": True},
            )
    await db.commit()
    return Response(status_code=204)


@router.post("/email/verify", status_code=204)
async def email_verify(
    body: EmailVerifyRequest, request: Request, ctx: AuthDep, db: DbDep, settings: SettingsDep
) -> Response:
    """E-posta doğrulama token'ını tüketir (tek kullanımlık, süreli, oturumlu).

    Oturum ZORUNLUDUR ve token yalnız oturumdaki kullanıcıya aitse kabul edilir: bağlantıyı açan (ör. e-posta
    tarayıcısı ya da kurban) kayıt olan oturumla aynı kişi değilse doğrulama olmaz. Başka kullanıcının token'ı
    ve geçersiz token aynı 400 yanıtını verir (numaralandırma yok). IP sınırı gövde ayrıştırılmadan önce
    `IpRateLimitMiddleware` içinde uygulanır.
    """
    result = await auth_service.consume_email_verification(db, body.token, ctx.user_id)
    if result is None:
        await db.rollback()
        raise ProblemError(
            400,
            "Geçersiz bağlantı",
            "invalid-verification-token",
            "Doğrulama bağlantısı geçersiz, bu hesaba ait değil, kullanılmış veya süresi dolmuş.",
        )
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.email_verified",
        user_id=ctx.user_id,
        ip_hash=ip_hash_for(request, settings),
        meta={"via": "link"},
    )
    await db.commit()
    return Response(status_code=204)


@router.post("/email/resend", status_code=202, response_model=StatusResponse)
async def email_resend(
    request: Request,
    ctx: AuthDep,
    db: DbDep,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    sender: EmailSenderDep,
    background: BackgroundTasks,
) -> StatusResponse:
    """Oturumdaki kullanıcıya doğrulama bağlantısını yeniden gönderir (kullanıcı başına saatlik sınır).

    Alıcı her zaman oturumdaki hesabın kendi adresidir (istekten adres alınmaz). Önceki bağlantı geçersiz olur.
    """
    await limiter.hit(
        f"verify-resend:user:{_digest(settings, 'rl-user', str(ctx.user_id))}",
        settings.rate_limit_verify_resend_user,
        _WINDOW_HOURLY,
    )
    email = (await db.execute(select(User.email).where(User.id == ctx.user_id))).scalar_one()
    token = await auth_service.create_email_verification(
        db, ctx.user_id, settings.email_verification_ttl_hours * 60
    )
    if token is None:
        await db.rollback()
        raise ProblemError(409, "Çakışma", "email-already-verified", "E-posta adresiniz zaten doğrulanmış.")
    await record_audit(
        db,
        ctx.tenant_id,
        "auth.email_verification_sent",
        user_id=ctx.user_id,
        ip_hash=ip_hash_for(request, settings),
    )
    await db.commit()
    background.add_task(
        sender.send,
        EmailMessage(
            to=email,
            subject=f"{settings.product_name}: e-posta doğrulama",
            body=(
                f"E-posta adresinizi {settings.email_verification_ttl_hours} saat içinde şu bağlantıyla "
                f"doğrulayın: {_web_link(settings, '/e-posta-dogrula', token)}\n"
                "Bu isteği siz yapmadıysanız yok sayın."
            ),
        ),
    )
    return StatusResponse(status="accepted")
