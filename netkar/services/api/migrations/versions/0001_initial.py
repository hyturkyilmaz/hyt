"""Şema v1: kiracılar, kullanıcılar, üyelikler, oturumlar, denetim, rate limit, RLS ve auth_gate.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Roller migrasyon öncesi sağlanır (infra/postgres/init ve testlerde app.db.provision):
#   netkar_owner : migrasyon ve tablo sahibi, giriş yapabilir, superuser DEĞİL
#   netkar_app   : uygulama, superuser/BYPASSRLS DEĞİL
#   netkar_auth  : NOLOGIN, yalnız auth_gate işlevlerinin sahibi; açık politikayla RLS dışı yol

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"

UPGRADE_SQL = [
    # ---- Tipler ve tablolar -------------------------------------------------
    "CREATE TYPE membership_role AS ENUM ('owner', 'admin', 'viewer')",
    """
    CREATE TABLE tenants (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
        plan text NOT NULL DEFAULT 'trial',
        status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'cancelled')),
        trial_ends_at timestamptz,
        currency char(3) NOT NULL DEFAULT 'TRY',
        locale text NOT NULL DEFAULT 'tr',
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE users (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        email text NOT NULL CHECK (email = lower(email) AND char_length(email) <= 254),
        password_hash text NOT NULL,
        totp_secret_encrypted text,
        totp_enabled boolean NOT NULL DEFAULT false,
        email_verified_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX uq_users_email_lower ON users ((lower(email)))",
    """
    CREATE TABLE memberships (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users (id),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        role membership_role NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_memberships_user_tenant UNIQUE (user_id, tenant_id)
    )
    """,
    "CREATE INDEX ix_memberships_tenant_id ON memberships (tenant_id)",
    """
    CREATE TABLE sessions (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        token_hash text NOT NULL,
        user_id uuid NOT NULL REFERENCES users (id),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        last_seen_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        revoked_at timestamptz,
        ip_hash text,
        user_agent text CHECK (char_length(user_agent) <= 200),
        CONSTRAINT uq_sessions_token_hash UNIQUE (token_hash)
    )
    """,
    "CREATE INDEX ix_sessions_tenant_id ON sessions (tenant_id)",
    "CREATE INDEX ix_sessions_user_id ON sessions (user_id)",
    """
    CREATE TABLE password_reset_tokens (
        token_hash text PRIMARY KEY,
        user_id uuid NOT NULL REFERENCES users (id),
        expires_at timestamptz NOT NULL,
        used_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX ix_password_reset_tokens_user_id ON password_reset_tokens (user_id)",
    """
    CREATE TABLE audit_log (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        user_id uuid REFERENCES users (id),
        action text NOT NULL,
        target text,
        created_at timestamptz NOT NULL DEFAULT now(),
        ip_hash text,
        meta jsonb NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX ix_audit_log_tenant_created ON audit_log (tenant_id, created_at DESC)",
    """
    CREATE TABLE rate_limits (
        key text NOT NULL,
        window_start timestamptz NOT NULL,
        count integer NOT NULL,
        PRIMARY KEY (key, window_start)
    )
    """,
    # ---- RLS ---------------------------------------------------------------
    *[
        stmt
        for t in (
            "tenants",
            "users",
            "memberships",
            "sessions",
            "audit_log",
            "password_reset_tokens",
        )
        for stmt in (
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
        )
    ],
    f"CREATE POLICY tenant_isolation ON tenants USING (id = {TENANT_EXPR}) WITH CHECK (id = {TENANT_EXPR})",
    f"CREATE POLICY user_self ON users USING (id = {USER_EXPR}) WITH CHECK (id = {USER_EXPR})",
    *[
        f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
        f"WITH CHECK (tenant_id = {TENANT_EXPR})"
        for t in ("memberships", "sessions", "audit_log")
    ],
    # ---- Yetkiler: uygulama rolü (en az yetki) -------------------------------
    "GRANT SELECT, UPDATE ON tenants TO netkar_app",
    "GRANT SELECT (id, email, totp_secret_encrypted, totp_enabled, email_verified_at, created_at) ON users TO netkar_app",
    "GRANT UPDATE (totp_secret_encrypted, totp_enabled) ON users TO netkar_app",
    "GRANT SELECT, INSERT, UPDATE ON memberships TO netkar_app",
    "GRANT SELECT, INSERT, UPDATE ON sessions TO netkar_app",
    "GRANT SELECT, INSERT ON audit_log TO netkar_app",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON rate_limits TO netkar_app",
    # ---- Yetkiler: netkar_auth (auth_gate işlevlerinin sahibi) ---------------
    "GRANT SELECT, INSERT ON tenants TO netkar_auth",
    "GRANT SELECT, INSERT, UPDATE ON users TO netkar_auth",
    "GRANT SELECT, INSERT ON memberships TO netkar_auth",
    "GRANT SELECT, UPDATE ON sessions TO netkar_auth",
    "GRANT SELECT, INSERT, UPDATE ON password_reset_tokens TO netkar_auth",
    # RLS dışı yol: yalnız netkar_auth rolü için açık, adlandırılmış politikalar.
    *[
        f"CREATE POLICY auth_path ON {t} TO netkar_auth USING (true) WITH CHECK (true)"
        for t in ("tenants", "users", "memberships", "sessions", "password_reset_tokens")
    ],
    # ---- auth_gate şeması ----------------------------------------------------
    "CREATE SCHEMA auth_gate AUTHORIZATION netkar_auth",
    "SET LOCAL ROLE netkar_auth",
    "REVOKE ALL ON SCHEMA auth_gate FROM PUBLIC",
    "GRANT USAGE ON SCHEMA auth_gate TO netkar_app",
    """
    CREATE FUNCTION auth_gate.find_user_for_login(p_email text)
    RETURNS TABLE (user_id uuid, password_hash text, totp_enabled boolean, tenant_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT u.id, u.password_hash, u.totp_enabled, m.tenant_id
        FROM public.users u
        LEFT JOIN LATERAL (
            SELECT mm.tenant_id FROM public.memberships mm
            WHERE mm.user_id = u.id ORDER BY mm.created_at, mm.tenant_id LIMIT 1
        ) m ON true
        WHERE lower(u.email) = lower(p_email)
    $$
    """,
    """
    CREATE FUNCTION auth_gate.get_session(p_token_hash text)
    RETURNS TABLE (session_id uuid, user_id uuid, tenant_id uuid, role text,
                   last_seen_at timestamptz, expires_at timestamptz, revoked_at timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT s.id, s.user_id, s.tenant_id, m.role::text, s.last_seen_at, s.expires_at, s.revoked_at
        FROM public.sessions s
        JOIN public.memberships m ON m.user_id = s.user_id AND m.tenant_id = s.tenant_id
        WHERE s.token_hash = p_token_hash
    $$
    """,
    """
    CREATE FUNCTION auth_gate.register_account(
        p_email text, p_password_hash text, p_tenant_name text, p_trial_days integer)
    RETURNS TABLE (new_user_id uuid, new_tenant_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
        v_tenant uuid;
    BEGIN
        INSERT INTO public.users (email, password_hash)
        VALUES (lower(p_email), p_password_hash)
        ON CONFLICT ((lower(email))) DO NOTHING
        RETURNING id INTO v_user;
        IF v_user IS NULL THEN
            RETURN;
        END IF;
        INSERT INTO public.tenants (name, trial_ends_at)
        VALUES (p_tenant_name, now() + make_interval(days => p_trial_days))
        RETURNING id INTO v_tenant;
        INSERT INTO public.memberships (user_id, tenant_id, role) VALUES (v_user, v_tenant, 'owner');
        RETURN QUERY SELECT v_user, v_tenant;
    END
    $$
    """,
    """
    CREATE FUNCTION auth_gate.create_password_reset(
        p_email text, p_token_hash text, p_ttl_minutes integer)
    RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_user uuid;
    BEGIN
        SELECT u.id INTO v_user FROM public.users u WHERE lower(u.email) = lower(p_email);
        IF v_user IS NULL THEN
            RETURN NULL;
        END IF;
        -- Yalnız en son istenen bağlantı geçerli kalır.
        UPDATE public.password_reset_tokens t SET used_at = now()
        WHERE t.user_id = v_user AND t.used_at IS NULL;
        INSERT INTO public.password_reset_tokens (token_hash, user_id, expires_at)
        VALUES (p_token_hash, v_user, now() + make_interval(mins => p_ttl_minutes));
        RETURN v_user;
    END
    $$
    """,
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
    "REVOKE ALL ON FUNCTION auth_gate.find_user_for_login(text) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.get_session(text) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.register_account(text, text, text, integer) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.create_password_reset(text, text, integer) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION auth_gate.consume_password_reset(text, text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.find_user_for_login(text) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.get_session(text) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.register_account(text, text, text, integer) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.create_password_reset(text, text, integer) TO netkar_app",
    "GRANT EXECUTE ON FUNCTION auth_gate.consume_password_reset(text, text) TO netkar_app",
    "RESET ROLE",
]

DOWNGRADE_SQL = [
    # Şema ve işlevlerin sahibi netkar_auth'tur; owner onu devralmaz, SET ROLE ile geçer.
    "SET LOCAL ROLE netkar_auth",
    "DROP SCHEMA IF EXISTS auth_gate CASCADE",
    "RESET ROLE",
    "DROP TABLE IF EXISTS rate_limits",
    "DROP TABLE IF EXISTS audit_log",
    "DROP TABLE IF EXISTS password_reset_tokens",
    "DROP TABLE IF EXISTS sessions",
    "DROP TABLE IF EXISTS memberships",
    "DROP TABLE IF EXISTS users",
    "DROP TABLE IF EXISTS tenants",
    "DROP TYPE IF EXISTS membership_role",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
