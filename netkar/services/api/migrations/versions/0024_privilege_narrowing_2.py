"""Yetki daraltma 2: sessions INSERT, memberships ve tenants yazma yetkileri (0023 açık riskleri).

Sorun: 0001, `netkar_app` rolüne tablo düzeyi yazma yetkileri vermişti ve bunların çoğu kodda kullanılmıyor.
Ele geçirilmiş bir uygulama bağlantısı (ör. SQL enjeksiyonu) şunları yapabilirdi (ASVS V3, V4, en az yetki):
- `sessions`'a INSERT: istediği kiracı ve kullanıcı adına, istediği `expires_at` ile uzun ömürlü oturum yaratmak.
- `memberships` INSERT/UPDATE: `role` sütununu `owner` yapmak, üyelik satırını başka kullanıcıya/kiracıya bağlamak.
- `tenants` UPDATE: `plan`, `status`, `trial_ends_at` (faturalama durumu), `id`, `created_at` değiştirmek.

Kod incelemesi (grep: sessions, memberships, tenants üzerine INSERT/UPDATE/ORM yazma): uygulama rolünün bu üç
tabloya yazdığı tek yer oturumdur. Üyelik ve kiracı yalnız `auth_gate.register_account` (sahibi `netkar_auth`)
ile oluşur; uygulama kodu `memberships` ve `tenants` üzerinde yalnız SELECT yapar (`/v1/me`, `/v1/tenant/members`,
kâr ayarı geçmişi üye sorgusu). Rol değiştirme ya da kiracı güncelleme akışı yoktur. Bu yüzden "gereken sütun"
kümesi boştur ve en dar yetki yazma yetkisinin tamamen kaldırılmasıdır (ileride gerçek bir akış gelirse
sütun düzeyi GRANT ve gerekirse SECURITY DEFINER işlev ayrı migrasyonla eklenir).

1. `auth_gate.create_session(user_id, tenant_id, token_hash, ip_hash, user_agent, absolute_seconds)`:
   SECURITY DEFINER, sahibi `netkar_auth`, `search_path` sabit, PUBLIC'ten EXECUTE alınmış, yalnız `netkar_app`
   çalıştırır. Yalnız sunucu üretimli alanları yazar: `created_at = last_seen_at = now()`, `revoked_at = NULL`,
   `expires_at = now() + LEAST(p_absolute_seconds, 2592000)`. 2592000 sn (30 gün) mutlak üst sınırdır ve koddaki
   `SESSION_ABSOLUTE_MAX_SECONDS` ile aynı değerdir (testle eşitlik doğrulanır): ayar kısaltabilir, uzatamaz.
   Bağlam denetimi: `p_tenant_id` ve `p_user_id`, isteğin RLS bağlamıyla (`app.tenant_id`, `app.user_id`) eşleşmiyorsa
   (bağlamsız çağrı dahil) 42501. Kullanıcının kiracıda üyeliği yoksa 42501. Token özeti 64 haneli, IP özeti 32 haneli
   küçük harf hex değilse, user_agent 200 karakterden uzunsa ya da süre < 1 ise 22023.
   `netkar_auth`'a yalnız gereken sütunlarda INSERT verilir. `netkar_app`'ten `sessions` INSERT kalkar.
   Alternatif (BEFORE INSERT tetikleyicisi) gerekmedi: işlev yaklaşımı mevcut akışı bozmaz (`_start_session`
   aynı işlemde işlevi çağırır; RLS bağlamı zaten ayarlıdır).
2. `memberships`: `netkar_app`'ten INSERT ve UPDATE kalkar (yalnız SELECT). Ek olarak BEFORE UPDATE tetikleyicisi
   `memberships_immutable_guard` (ENABLE ALWAYS): `id`, `user_id`, `tenant_id`, `created_at` hiçbir rolle
   değiştirilemez (23514); rol yükseltme (viewer < admin < owner) yalnız süper kullanıcı ya da `netkar_owner`
   (operasyon/destek yolu) yapabilir, diğer roller 42501 alır. Rol düşürme serbesttir (ileride "son owner"
   kuralı ayrı iştir: mevcut testler tek owner'ı yönetici bağlantısıyla düşürür).
3. `tenants`: `netkar_app`'ten UPDATE kalkar (yalnız SELECT). BEFORE UPDATE tetikleyicisi
   `tenants_immutable_guard` (ENABLE ALWAYS): `id` ve `created_at` hiçbir rolle değiştirilemez (23514).
   Sınır (0023 ile aynı): tablo sahibi ya da süper kullanıcı `ALTER TABLE ... DISABLE TRIGGER` ile tetikleyiciyi
   kapatabilir; testlerin zaman kaydırması bu yolu kullanır.

0001 ve 0023'e dokunulmaz. Geri alma: tetikleyiciler ve işlevler kaldırılır, `netkar_auth`'tan `sessions` INSERT
alınır, `netkar_app`'e 0001'deki tablo düzeyi yetkiler geri verilir (sütun düzeyi ACL kalıntısı kalmaz).
Veri silinmez.

Revision ID: 0024
Revises: 0023
"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_UPGRADE_GRANTS = [
    # Oturum yalnız auth_gate.create_session ile yazılır; uygulama rolünün tablo INSERT'i kalkar.
    "REVOKE INSERT ON sessions FROM netkar_app",
    "GRANT INSERT (token_hash, user_id, tenant_id, created_at, last_seen_at, expires_at, ip_hash, user_agent) "
    "ON sessions TO netkar_auth",
    # Uygulama kodu üyelik ve kiracıya yazmaz (yalnız SELECT); tablo düzeyi REVOKE sütun yetkilerini de siler.
    "REVOKE INSERT, UPDATE ON memberships FROM netkar_app",
    "REVOKE UPDATE ON tenants FROM netkar_app",
]

_UPGRADE_TRIGGERS = [
    """
    CREATE FUNCTION public.memberships_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'uyelik kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        IF (CASE NEW.role::text WHEN 'owner' THEN 3 WHEN 'admin' THEN 2 ELSE 1 END)
           > (CASE OLD.role::text WHEN 'owner' THEN 3 WHEN 'admin' THEN 2 ELSE 1 END)
           AND NOT (
               current_user = 'netkar_owner'
               OR EXISTS (SELECT 1 FROM pg_catalog.pg_roles r WHERE r.rolname = current_user AND r.rolsuper)
           ) THEN
            RAISE EXCEPTION 'rol yukseltme bu rolle yapilamaz' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER memberships_immutable_guard BEFORE UPDATE ON memberships "
    "FOR EACH ROW EXECUTE FUNCTION public.memberships_immutable_guard()",
    "ALTER TABLE memberships ENABLE ALWAYS TRIGGER memberships_immutable_guard",
    """
    CREATE FUNCTION public.tenants_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'kiraci kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER tenants_immutable_guard BEFORE UPDATE ON tenants "
    "FOR EACH ROW EXECUTE FUNCTION public.tenants_immutable_guard()",
    "ALTER TABLE tenants ENABLE ALWAYS TRIGGER tenants_immutable_guard",
]

# auth_gate işlevleri netkar_auth rolüyle oluşturulur (0001 ve 0017 deseni).
_UPGRADE_FUNCTIONS = [
    """
    CREATE FUNCTION auth_gate.create_session(
        p_user_id uuid, p_tenant_id uuid, p_token_hash text, p_ip_hash text, p_user_agent text,
        p_absolute_seconds integer)
    RETURNS uuid
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
    DECLARE
        v_id uuid;
        v_ttl integer;
    BEGIN
        IF p_token_hash IS NULL OR p_token_hash !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'token ozeti gecersiz' USING ERRCODE = '22023';
        END IF;
        -- IP özeti: uygulama `ip_hash_for` ile 32 haneli küçük harf hex üretir (HMAC özetinin ilk 32 hanesi).
        IF p_ip_hash IS NULL OR p_ip_hash !~ '^[0-9a-f]{32}$' THEN
            RAISE EXCEPTION 'ip ozeti gecersiz' USING ERRCODE = '22023';
        END IF;
        -- Uygulama user_agent'ı 200 karaktere keser; daha uzunu sunucuda reddedilir.
        IF p_user_agent IS NOT NULL AND char_length(p_user_agent) > 200 THEN
            RAISE EXCEPTION 'user agent cok uzun' USING ERRCODE = '22023';
        END IF;
        IF p_absolute_seconds IS NULL OR p_absolute_seconds < 1 THEN
            RAISE EXCEPTION 'oturum suresi gecersiz' USING ERRCODE = '22023';
        END IF;
        -- Mutlak süre: 30 gün üst sınır (app.core.config.SESSION_ABSOLUTE_MAX_SECONDS ile aynı değer).
        v_ttl := LEAST(p_absolute_seconds, 2592000);
        -- Bağlam denetimi: oturum yalnız isteğin RLS bağlamındaki (app.tenant_id, app.user_id) kiracı ve
        -- kullanıcı için açılır; bağlamsız ya da başka kiracı/kullanıcı adına çağrı reddedilir.
        IF p_tenant_id IS DISTINCT FROM NULLIF(current_setting('app.tenant_id', true), '')::uuid
           OR p_user_id IS DISTINCT FROM NULLIF(current_setting('app.user_id', true), '')::uuid THEN
            RAISE EXCEPTION 'rls baglami ile uyusmuyor' USING ERRCODE = '42501';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.memberships m WHERE m.user_id = p_user_id AND m.tenant_id = p_tenant_id
        ) THEN
            RAISE EXCEPTION 'kullanici bu kiracinin uyesi degil' USING ERRCODE = '42501';
        END IF;
        INSERT INTO public.sessions
            (token_hash, user_id, tenant_id, created_at, last_seen_at, expires_at, ip_hash, user_agent)
        VALUES
            (p_token_hash, p_user_id, p_tenant_id, now(), now(), now() + make_interval(secs => v_ttl),
             p_ip_hash, NULLIF(p_user_agent, ''))
        RETURNING id INTO v_id;
        RETURN v_id;
    END
    $$
    """,
    "REVOKE ALL ON FUNCTION auth_gate.create_session(uuid, uuid, text, text, text, integer) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION auth_gate.create_session(uuid, uuid, text, text, text, integer) TO netkar_app",
]

_DOWNGRADE_FUNCTIONS = [
    "DROP FUNCTION IF EXISTS auth_gate.create_session(uuid, uuid, text, text, text, integer)",
]

_DOWNGRADE = [
    "DROP TRIGGER IF EXISTS tenants_immutable_guard ON tenants",
    "DROP FUNCTION IF EXISTS public.tenants_immutable_guard()",
    "DROP TRIGGER IF EXISTS memberships_immutable_guard ON memberships",
    "DROP FUNCTION IF EXISTS public.memberships_immutable_guard()",
    # 0001'deki tablo düzeyi yetkiler geri verilir; önce REVOKE ile sütun düzeyi kalıntı temizlenir.
    "REVOKE INSERT ON sessions FROM netkar_auth",
    "REVOKE INSERT ON sessions FROM netkar_app",
    "GRANT INSERT ON sessions TO netkar_app",
    "REVOKE INSERT, UPDATE ON memberships FROM netkar_app",
    "GRANT INSERT, UPDATE ON memberships TO netkar_app",
    "REVOKE UPDATE ON tenants FROM netkar_app",
    "GRANT UPDATE ON tenants TO netkar_app",
]


def upgrade() -> None:
    for statement in _UPGRADE_GRANTS:
        op.execute(statement)
    for statement in _UPGRADE_TRIGGERS:
        op.execute(statement)
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _UPGRADE_FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")


def downgrade() -> None:
    op.execute("SET LOCAL ROLE netkar_auth")
    for statement in _DOWNGRADE_FUNCTIONS:
        op.execute(statement)
    op.execute("RESET ROLE")
    for statement in _DOWNGRADE:
        op.execute(statement)
