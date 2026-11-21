"""E-posta doğrulaması ve sahiplenilmemiş hesap önlemi (denetim S1 O-06, ASVS V2/V3).

1. `email_verification_tokens`: parola sıfırlama tablosuyla aynı desen. Yalnız token'ın SHA-256 özeti saklanır,
   token tek kullanımlık ve süreli, tablo ENABLE + FORCE RLS ve uygulama rolüne (`netkar_app`) KAPALIDIR; yalnız
   `netkar_auth` (auth_gate işlevlerinin sahibi) erişir.
2. `auth_gate.create_email_verification(user_id, token_hash, ttl_minutes)`: kullanıcı doğrulanmamışsa eski
   açık token'ları kapatır ve yenisini ekler (yalnız en son bağlantı geçerli). Doğrulanmışsa false.
3. `auth_gate.consume_email_verification(token_hash)`: koşullu UPDATE ile atomik tüketim, ardından
   `users.email_verified_at` atanır. Dönüş: (kullanıcı, kiracı).
4. `auth_gate.consume_password_reset` yeniden tanımlanır ve bir sütun ekler (`reset_claimed_unverified`):
   parola sıfırlama e-posta kutusuna erişimi kanıtlar. Hesap doğrulanmamışsa (ön ele geçirme şüphesi) sıfırlama
   `email_verified_at` atar, TOTP sırrını/etkinliğini/sayaçlarını temizler ve bekleyen doğrulama bağlantılarını
   kapatır; böylece önceden kayıt olan saldırganın parolası ve TOTP'si gerçek sahibi kilitleyemez.
   DOĞRULANMIŞ hesapta TOTP'ye dokunulmaz (e-posta ele geçirilse bile ikinci faktör korunur).

Mevcut kullanıcılar geriye dönük doğrulanmış SAYILMAZ (ön ele geçirmeyi meşrulaştırırdı): doğrulama bağlantısını
oturum içinden yeniden isteyebilirler.

Geri alma: üç yeni işlev ve tablo silinir, `consume_password_reset` 0001'deki gövdesine döner. `email_verified_at`
sütunu 0001'den gelir ve korunur; yalnız bekleyen doğrulama token'ları kaybolur (veri silinmez, hesaplar durur).

Revision ID: 0017
Revises: 0016
"""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

_TABLES = [
    """
    CREATE TABLE email_verification_tokens (
        token_hash text PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id),
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ix_email_verification_tokens_user_id ON email_verification_tokens (user_id)",
    "ALTER TABLE email_verification_tokens ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE email_verification_tokens FORCE ROW LEVEL SECURITY",
    "GRANT SELECT, INSERT, UPDATE ON email_verification_tokens TO netkar_auth",
    "CREATE POLICY auth_path ON email_verification_tokens TO netkar_auth USING (true) WITH CHECK (true)",
]

_FUNCTIONS = [
    """
    CREATE FUNCTION auth_gate.create_email_verification(
        p_user_id uuid, p_token_hash text, p_ttl_minutes integer)
    RETURNS boolean
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM public.users u WHERE u.id = p_user_id AND u.email_verified_at IS NULL
        ) THEN
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
    CREATE FUNCTION auth_gate.consume_email_verification(p_token_hash text)
    RETURNS TABLE (verified_user_id uuid, verified_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
    BEGIN
        -- Tek kullanımlık ve süreli: koşullu UPDATE atomiktir, yarışta yalnız biri kazanır.
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
    "DROP FUNCTION auth_gate.consume_password_reset(text, text)",
    """
    CREATE FUNCTION auth_gate.consume_password_reset(p_token_hash text, p_new_password_hash text)
    RETURNS TABLE (reset_user_id uuid, reset_tenant_id uuid, reset_claimed_unverified boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
        v_unverified boolean;
    BEGIN
        -- Tek kullanımlık ve süreli: koşullu UPDATE atomiktir, yarışta yalnız biri kazanır.
        UPDATE public.password_reset_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        SELECT u.email_verified_at IS NULL INTO v_unverified
        FROM public.users u WHERE u.id = v_user FOR UPDATE;
        IF v_unverified THEN
            -- Doğrulanmamış hesap: sıfırlama e-posta sahipliğini kanıtlar. Parola yenilenir, e-posta
            -- doğrulanır ve (olası) saldırgan TOTP'si temizlenir; bekleyen doğrulama bağlantıları kapanır.
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
    "REVOKE ALL ON FUNCTION auth_gate.create_email_verification(uuid, text, integer) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.consume_email_verification(text) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.consume_password_reset(text, text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.create_email_verification(uuid, text, integer) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_email_verification(text) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_password_reset(text, text) TO netkar_app",
]

_DOWNGRADE_FUNCTIONS = [
    "DROP FUNCTION IF EXISTS auth_gate.create_email_verification(uuid, text, integer)",
    "DROP FUNCTION IF EXISTS auth_gate.consume_email_verification(text)",
    "DROP FUNCTION IF EXISTS auth_gate.consume_password_reset(text, text)",
    # 0001'deki özgün gövde.
    """
    CREATE FUNCTION auth_gate.consume_password_reset(p_token_hash text, p_new_password_hash text)
    RETURNS TABLE (reset_user_id uuid, reset_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
    BEGIN
        -- Tek kullanımlık ve süreli: koşullu UPDATE atomiktir, yarışta yalnız biri kazanır.
        UPDATE public.password_reset_tokens t SET used_at = now()
        WHERE t.token_hash = p_token_hash AND t.used_at IS NULL AND t.expires_at > now()
        RETURNING t.user_id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        UPDATE public.users u SET password_hash = p_new_password_hash WHERE u.id = v_user;
        -- Parola değişince tüm oturumlar iptal edilir.
        UPDATE public.sessions s SET revoked_at = now() WHERE s.user_id = v_user AND s.revoked_at IS NULL;
        SELECT m.tenant_id INTO v_tenant FROM public.memberships m
        WHERE m.user_id = v_user ORDER BY m.created_at, m.tenant_id LIMIT 1;
        RETURN QUERY SELECT v_user, v_tenant;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION auth_gate.consume_password_reset(text, text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_password_reset(text, text) TO netkar_app",
]


def upgrade() -> None:
    for statement in _TABLES:
        op.execute(statement)
    # Şema ve işlevlerin sahibi netkar_auth'tur; owner onu devralmaz, SET ROLE ile geçer (0001 gibi).
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _DOWNGRADE_FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")
    op.execute("DROP TABLE IF EXISTS email_verification_tokens")
