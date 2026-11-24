"""MFA kurtarma kodları, diğer oturumları iptal işlevi ve "doğrulanmamış hesapta TOTP" tetikleyicisi.

(Denetim S1 O-05 ve O-06 artığı; OWASP ASVS L2 V2.5 kurtarma, V2.8 OTP, V3 oturum.)

1. `mfa_recovery_codes`: kullanıcı başına tek kullanımlık kurtarma kodları. Düz metin ASLA saklanmaz; yalnız
   HMAC-SHA256 (amaç anahtarlı, uygulama ana anahtarından türetilen "pepper") özeti tutulur. Kodlar 60 bit
   entropili rastgele değerlerdir (parola gibi tahmin edilebilir değildir), bu yüzden yavaş özet yerine anahtarlı
   HMAC yeterlidir ve girişteki kilit/hız sınırı çevrimiçi tahmini sınırlar. Satır silinmez: kullanılan kod
   `used_at`, yenilemeyle/TOTP kapatmayla geçersizleşen kod `revoked_at` alır. ENABLE + FORCE RLS; politika
   `user_id = app.user_id` (users tablosundaki `user_self` ile aynı desen). `netkar_app` yalnız SELECT, INSERT ve
   `used_at`, `revoked_at` sütunlarında UPDATE alabilir (DELETE yok). Tek kullanım yarışı uygulamada koşullu
   `UPDATE ... WHERE used_at IS NULL AND revoked_at IS NULL RETURNING` ile atomik çözülür.
2. `auth_gate.revoke_other_sessions(user_id, keep_session_id)`: kullanıcının (tüm kiracılardaki) diğer oturumlarını
   iptal eder. SECURITY DEFINER olduğu için yalnız çağıranın kendi RLS bağlamındaki kullanıcı için çalışır
   (`user_id = app.user_id` değilse 42501); başkasının oturumlarını iptal etmek için kullanılamaz.
3. Tetikleyici `users_totp_requires_verified_email` (BEFORE INSERT OR UPDATE): `email_verified_at IS NULL`
   iken `totp_enabled = true` YAZILAMAZ (23514). Uygulama zaten 403 verir; bu, veritabanı katmanında ikinci
   savunmadır (0018 "doğrulanmamış + TOTP etkin ise sıfırlama TOTP'yi korur" kuralının yalnız 0017 öncesi
   hesaplara özgü kalmasını sağlar). 0017 öncesi mevcut satırlar ETKİLENMEZ: tetikleyici yalnız yeni INSERT'lerde
   ve `totp_enabled` ya da `email_verified_at` değerinin değiştiği UPDATE'lerde karar verir; zaten (doğrulanmamış +
   TOTP etkin) olan eski satırın başka sütunlarının güncellenmesine (zaman adımı, hata sayacı vb.) izin verilir.

Geri alma: tetikleyici, işlevler ve `mfa_recovery_codes` tablosu kaldırılır (tablodaki kurtarma kodu özetleri
kaybolur; kullanıcılar kodları yeniden üretir, TOTP ve hesap verisi durur). Başka şema nesnesi yok.

Revision ID: 0019
Revises: 0018
"""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

_USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"

_TABLE = [
    """
    CREATE TABLE mfa_recovery_codes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users (id),
        code_hash text NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        used_at timestamptz,
        revoked_at timestamptz,
        CONSTRAINT uq_mfa_recovery_codes_user_hash UNIQUE (user_id, code_hash)
    )
    """,
    "CREATE INDEX ix_mfa_recovery_codes_user_id ON mfa_recovery_codes (user_id)",
    "ALTER TABLE mfa_recovery_codes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE mfa_recovery_codes FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY user_self ON mfa_recovery_codes USING (user_id = {_USER_EXPR}) "
    f"WITH CHECK (user_id = {_USER_EXPR})",
    "GRANT SELECT, INSERT ON mfa_recovery_codes TO netkar_app",
    "GRANT UPDATE (used_at, revoked_at) ON mfa_recovery_codes TO netkar_app",
]

_TRIGGER = [
    """
    CREATE FUNCTION public.users_totp_requires_verified_email() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NEW.totp_enabled AND NEW.email_verified_at IS NULL THEN
            -- 0017 öncesi (doğrulanmamış + TOTP etkin) satır olduğu gibi kalabilir: karar yalnız yeni
            -- satırda ya da ilgili iki sütunun değiştiği güncellemede verilir.
            IF TG_OP = 'INSERT'
               OR OLD.totp_enabled IS DISTINCT FROM NEW.totp_enabled
               OR OLD.email_verified_at IS DISTINCT FROM NEW.email_verified_at THEN
                RAISE EXCEPTION 'e-postasi dogrulanmamis hesapta TOTP etkinlestirilemez'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER users_totp_requires_verified_email BEFORE INSERT OR UPDATE ON users "
    "FOR EACH ROW EXECUTE FUNCTION public.users_totp_requires_verified_email()",
]

_FUNCTIONS = [
    f"""
    CREATE FUNCTION auth_gate.revoke_other_sessions(p_user_id uuid, p_keep_session_id uuid)
    RETURNS integer
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_count integer;
    BEGIN
        -- Yalnız çağıranın kendi bağlamındaki kullanıcı için: başkasının oturumları iptal edilemez.
        IF p_user_id IS DISTINCT FROM {_USER_EXPR} THEN
            RAISE EXCEPTION 'yetkisiz oturum iptali' USING ERRCODE = '42501';
        END IF;
        UPDATE public.sessions s SET revoked_at = now()
        WHERE s.user_id = p_user_id AND s.id <> p_keep_session_id AND s.revoked_at IS NULL;
        GET DIAGNOSTICS v_count = ROW_COUNT;
        RETURN v_count;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION auth_gate.revoke_other_sessions(uuid, uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.revoke_other_sessions(uuid, uuid) TO netkar_app",
]


def upgrade() -> None:
    for statement in _TABLE:
        op.execute(statement)
    for statement in _TRIGGER:
        op.execute(statement)
    # Şema ve işlevlerin sahibi netkar_auth'tur (0017/0018 gibi SET ROLE ile geçilir).
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE netkar_auth")
    op.execute("DROP FUNCTION IF EXISTS auth_gate.revoke_other_sessions(uuid, uuid)")
    op.execute("RESET ROLE")
    op.execute("DROP TRIGGER IF EXISTS users_totp_requires_verified_email ON users")
    op.execute("DROP FUNCTION IF EXISTS public.users_totp_requires_verified_email()")
    op.execute("DROP TABLE IF EXISTS mfa_recovery_codes")
