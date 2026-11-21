"""E-posta doğrulama sertleştirmesi (bağımsız inceleme turu 1; denetim O-06).

1. `auth_gate.consume_email_verification(token_hash, user_id)`: token yalnız KAYDEDEN oturumun kullanıcısına
   aittir. Token başka kullanıcınınsa hiçbir şey tüketilmez ve sonuç "geçersiz token" ile aynıdır (numaralandırma
   yok). Önceki imza (yalnız token) kaldırılır: oturumsuz doğrulama yolu kalmaz. Zincir: saldırgan kurbanın adresiyle
   kayıt olup oturumunu açık tutar, kurban/e-posta tarayıcısı bağlantıyı açar, hesap doğrulanır, saldırgan TOTP
   kurar. Artık bağlantıyı açan oturum, token'ın sahibi olan oturum değilse doğrulama olmaz.
2. `auth_gate.create_email_verification`: kullanıcı satırı önce `FOR UPDATE` ile kilitlenir (eşzamanlı yeniden
   gönderme ve sıfırlama sırayla çalışır) ve `p_ttl_minutes` 1-4320 dışındaysa 22023 ile hata verir.
3. `auth_gate.consume_password_reset`: doğrulanmamış hesap sıfırlamayla sahiplenilince (a) kiracının deneme süresi
   baştan başlar (`trial_ends_at = now() + (trial_ends_at - created_at)`, yalnız kullanıcının sahibi olduğu `trial`
   planlı kiracılar; kiracı adı ve veriler silinmez), (b) TOTP yalnız ETKİN DEĞİLSE temizlenir. 0017'den sonra
   doğrulanmamış hesapta TOTP etkinleştirilemediği için (uygulama 403 verir) doğrulanmamış + TOTP etkin satırı yalnız
   0017 öncesi hesaplarda bulunabilir; bunlar gerçek kullanıcılar olabilir ve sıfırlama onların ikinci faktörünü
   silmemelidir. Etkinleştirilmemiş (yalnız kurulumu başlatılmış) sır yine temizlenir.
4. `netkar_auth` için `tenants.trial_ends_at` sütununda UPDATE yetkisi (başka sütun değil).

Geri alma: 0017'deki işlev gövdeleri ve imzaları geri gelir, sütun yetkisi geri alınır. Veri silinmez.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_UPGRADE = [
    "DROP FUNCTION auth_gate.consume_email_verification(text)",
    """
    CREATE FUNCTION auth_gate.consume_email_verification(p_token_hash text, p_user_id uuid)
    RETURNS TABLE (verified_user_id uuid, verified_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
    BEGIN
        -- Tek kullanımlık, süreli VE yalnız token'ın sahibi kullanıcıya ait: koşullu UPDATE atomiktir.
        -- Başkasının token'ı tüketilmez; sonuç geçersiz token ile aynıdır.
        UPDATE public.email_verification_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.user_id = p_user_id
          AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        UPDATE public.users u SET email_verified_at = COALESCE(u.email_verified_at, now())
        WHERE u.id = v_user;
        SELECT m.tenant_id INTO v_tenant FROM public.memberships m
        WHERE m.user_id = v_user ORDER BY m.created_at, m.tenant_id LIMIT 1;
        RETURN QUERY SELECT v_user, v_tenant;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION auth_gate.create_email_verification(
        p_user_id uuid, p_token_hash text, p_ttl_minutes integer)
    RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_unverified boolean;
    BEGIN
        IF p_ttl_minutes IS NULL OR p_ttl_minutes < 1 OR p_ttl_minutes > 4320 THEN
            RAISE EXCEPTION 'gecersiz dogrulama suresi (1-4320 dakika)' USING ERRCODE = '22023';
        END IF;
        -- Kullanıcı satırı kilitlenir: eşzamanlı yeniden gönderme ve parola sıfırlama sırayla çalışır.
        SELECT u.email_verified_at IS NULL INTO v_unverified
        FROM public.users u WHERE u.id = p_user_id FOR UPDATE;
        IF NOT FOUND OR NOT v_unverified THEN
            RETURN false;
        END IF;
        -- Yalnız en son istenen bağlantı geçerli kalır.
        UPDATE public.email_verification_tokens t SET used_at = now()
        WHERE t.user_id = p_user_id AND t.used_at IS NULL;
        INSERT INTO public.email_verification_tokens (token_hash, user_id, expires_at)
        VALUES (p_token_hash, p_user_id, now() + make_interval(mins => p_ttl_minutes));
        RETURN true;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION auth_gate.consume_password_reset(p_token_hash text, p_new_password_hash text)
    RETURNS TABLE (reset_user_id uuid, reset_tenant_id uuid, reset_claimed_unverified boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
        v_unverified boolean;
        v_totp_enabled boolean;
    BEGIN
        -- Tek kullanımlık ve süreli: koşullu UPDATE atomiktir, yarışta yalnız biri kazanır.
        UPDATE public.password_reset_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        SELECT u.email_verified_at IS NULL, u.totp_enabled INTO v_unverified, v_totp_enabled
        FROM public.users u WHERE u.id = v_user FOR UPDATE;
        IF v_unverified THEN
            -- Doğrulanmamış hesap: sıfırlama e-posta sahipliğini kanıtlar. Parola yenilenir ve e-posta
            -- doğrulanır. 0017'den sonra bu durumda TOTP etkinleştirilemez; etkin TOTP varsa hesap 0017
            -- öncesindendir (gerçek kullanıcı olabilir) ve ikinci faktörü KORUNUR. Etkin olmayan (yalnız
            -- kurulumu başlatılmış) sır temizlenir.
            UPDATE public.users u SET
                password_hash = p_new_password_hash,
                email_verified_at = now(),
                totp_secret_encrypted = CASE WHEN v_totp_enabled THEN u.totp_secret_encrypted ELSE NULL END,
                totp_last_step = CASE WHEN v_totp_enabled THEN u.totp_last_step ELSE NULL END,
                totp_failed_count = CASE WHEN v_totp_enabled THEN u.totp_failed_count ELSE 0 END,
                totp_locked_until = CASE WHEN v_totp_enabled THEN u.totp_locked_until ELSE NULL END
            WHERE u.id = v_user;
            UPDATE public.email_verification_tokens e SET used_at = now()
            WHERE e.user_id = v_user AND e.used_at IS NULL;
            -- Devralan, ön ele geçirmeyle harcanmış olabilecek deneme süresini baştan alır. Kiracı adı ve
            -- veriler silinmez.
            UPDATE public.tenants tn SET trial_ends_at = now() + (tn.trial_ends_at - tn.created_at)
            WHERE tn.plan = 'trial' AND tn.trial_ends_at IS NOT NULL
              AND tn.id IN (SELECT m.tenant_id FROM public.memberships m
                            WHERE m.user_id = v_user AND m.role = 'owner');
        ELSE
            -- Doğrulanmış hesap: TOTP ve diğer ikinci faktör durumu korunur.
            UPDATE public.users u SET password_hash = p_new_password_hash WHERE u.id = v_user;
        END IF;
        -- Parola değişince tüm oturumlar iptal edilir.
        UPDATE public.sessions s SET revoked_at = now() WHERE s.user_id = v_user AND s.revoked_at IS NULL;
        SELECT m.tenant_id INTO v_tenant FROM public.memberships m
        WHERE m.user_id = v_user ORDER BY m.created_at, m.tenant_id LIMIT 1;
        RETURN QUERY SELECT v_user, v_tenant, v_unverified;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION auth_gate.consume_email_verification(text, uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_email_verification(text, uuid) TO netkar_app",
]

_DOWNGRADE = [
    "DROP FUNCTION auth_gate.consume_email_verification(text, uuid)",
    # 0017'deki gövdeler.
    """
    CREATE FUNCTION auth_gate.consume_email_verification(p_token_hash text)
    RETURNS TABLE (verified_user_id uuid, verified_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
    BEGIN
        UPDATE public.email_verification_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        UPDATE public.users u SET email_verified_at = COALESCE(u.email_verified_at, now())
        WHERE u.id = v_user;
        SELECT m.tenant_id INTO v_tenant FROM public.memberships m
        WHERE m.user_id = v_user ORDER BY m.created_at, m.tenant_id LIMIT 1;
        RETURN QUERY SELECT v_user, v_tenant;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION auth_gate.create_email_verification(
        p_user_id uuid, p_token_hash text, p_ttl_minutes integer)
    RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM public.users u WHERE u.id = p_user_id AND u.email_verified_at IS NULL
        ) THEN
            RETURN false;
        END IF;
        UPDATE public.email_verification_tokens t SET used_at = now()
        WHERE t.user_id = p_user_id AND t.used_at IS NULL;
        INSERT INTO public.email_verification_tokens (token_hash, user_id, expires_at)
        VALUES (p_token_hash, p_user_id, now() + make_interval(mins => p_ttl_minutes));
        RETURN true;
    END
    $$
    """,
    """
    CREATE OR REPLACE FUNCTION auth_gate.consume_password_reset(p_token_hash text, p_new_password_hash text)
    RETURNS TABLE (reset_user_id uuid, reset_tenant_id uuid, reset_claimed_unverified boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
        v_unverified boolean;
    BEGIN
        UPDATE public.password_reset_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        SELECT u.email_verified_at IS NULL INTO v_unverified
        FROM public.users u WHERE u.id = v_user FOR UPDATE;
        IF v_unverified THEN
            UPDATE public.users u SET
                password_hash = p_new_password_hash,
                email_verified_at = now(),
                totp_secret_encrypted = NULL,
                totp_enabled = false,
                totp_last_step = NULL,
                totp_failed_count = 0,
                totp_locked_until = NULL
            WHERE u.id = v_user;
            UPDATE public.email_verification_tokens e SET used_at = now()
            WHERE e.user_id = v_user AND e.used_at IS NULL;
        ELSE
            UPDATE public.users u SET password_hash = p_new_password_hash WHERE u.id = v_user;
        END IF;
        UPDATE public.sessions s SET revoked_at = now() WHERE s.user_id = v_user AND s.revoked_at IS NULL;
        SELECT m.tenant_id INTO v_tenant FROM public.memberships m
        WHERE m.user_id = v_user ORDER BY m.created_at, m.tenant_id LIMIT 1;
        RETURN QUERY SELECT v_user, v_tenant, v_unverified;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION auth_gate.consume_email_verification(text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_email_verification(text) TO netkar_app",
]


def upgrade() -> None:
    # Deneme süresini yenilemek için dar sütun yetkisi (tabloyu sahibi netkar_owner izler).
    op.execute("GRANT UPDATE (trial_ends_at) ON tenants TO netkar_auth")
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _UPGRADE:
        op.execute(statement)
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _DOWNGRADE:
        op.execute(statement)
    op.execute("RESET ROLE")
    op.execute("REVOKE UPDATE (trial_ends_at) ON tenants FROM netkar_auth")
