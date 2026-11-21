"""Kurtarma kodu zaman damgalarını değiştirilemez yapar; revoke_other_sessions search_path sertleştirmesi.

1. `mfa_recovery_codes` BEFORE UPDATE tetikleyicisi: `used_at` ya da `revoked_at` bir kez dolunca değiştirilemez
   (NULL'a döndürülemez, başka değere çekilemez; 23514). Kullanılmış ya da geçersiz kılınmış kod, SQL enjeksiyonu
   ya da hatalı kodla bile yeniden etkinleştirilemez. İlk doldurma (NULL -> değer) serbesttir.
2. `auth_gate.revoke_other_sessions`: `search_path` sonuna `pg_temp` eklenir (SECURITY DEFINER işlevlerde geçici
   şemanın arama yolunda en sona alınması önerisi). Gövde ve yetkiler aynıdır (`CREATE OR REPLACE` yetkileri korur).

0019'a dokunulmaz. Geri alma: tetikleyici ve işlevi kaldırılır, işlev 0019'daki `search_path` ile geri gelir.
Veri silinmez.

Revision ID: 0020
Revises: 0019
"""

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _revoke_function(search_path: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION auth_gate.revoke_other_sessions(p_user_id uuid, p_keep_session_id uuid)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = {search_path} AS $$
    DECLARE
        v_count integer;
    BEGIN
        IF p_user_id IS DISTINCT FROM {_USER_EXPR} THEN
            RAISE EXCEPTION 'yetkisiz oturum iptali' USING ERRCODE = '42501';
        END IF;
        UPDATE public.sessions s SET revoked_at = now()
        WHERE s.user_id = p_user_id AND s.id <> p_keep_session_id AND s.revoked_at IS NULL;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END
    $$
    """


_TRIGGER = [
    """
    CREATE FUNCTION public.mfa_recovery_codes_immutable_marks() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF (OLD.used_at IS NOT NULL AND NEW.used_at IS DISTINCT FROM OLD.used_at)
           OR (OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at) THEN
            RAISE EXCEPTION 'kurtarma kodu isaretleri degistirilemez' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER mfa_recovery_codes_immutable_marks BEFORE UPDATE ON mfa_recovery_codes "
    "FOR EACH ROW EXECUTE FUNCTION public.mfa_recovery_codes_immutable_marks()",
]


def upgrade() -> None:
    for statement in _TRIGGER:
        op.execute(statement)
    op.execute("SET LOCAL ROLE netkar_auth")
    op.execute(_revoke_function("pg_catalog, public, pg_temp"))
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE netkar_auth")
    op.execute(_revoke_function("pg_catalog, public"))
    op.execute("RESET ROLE")
    op.execute("DROP TRIGGER IF EXISTS mfa_recovery_codes_immutable_marks ON mfa_recovery_codes")
    op.execute("DROP FUNCTION IF EXISTS public.mfa_recovery_codes_immutable_marks()")
