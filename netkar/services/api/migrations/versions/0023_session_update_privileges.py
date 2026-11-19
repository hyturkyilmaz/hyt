"""sessions: UPDATE yetkilerini sütun düzeyine daraltır; iptal, kimlik ve zaman değişmezliği tetikleyicisi.

Sorun: 0001, `netkar_app` ve `netkar_auth` rollerine `sessions` üzerinde tablo düzeyi UPDATE vermişti. Uygulama
yalnız `last_seen_at` (boşta süresi) ve `revoked_at` (iptal) sütunlarını günceller; auth_gate işlevleri (sahibi
`netkar_auth`, SECURITY DEFINER) yalnız `revoked_at` yazar. Tablo düzeyi yetki, ele geçirilmiş bir bağlantının
iptal edilmiş oturumu geri açmasına (`revoked_at = NULL`), `expires_at` uzatmasına ya da oturumu başka
kullanıcıya bağlamasına izin verirdi (ASVS V3.3, V3.7).

1. `netkar_app`: `REVOKE UPDATE` (tablo düzeyi REVOKE sütun yetkilerini de siler), sonra yalnız
   `GRANT UPDATE (last_seen_at, revoked_at)`. `netkar_auth`: `REVOKE UPDATE`, sonra yalnız
   `GRANT UPDATE (revoked_at)`. SELECT ve INSERT aynen kalır.
2. `sessions` BEFORE UPDATE tetikleyicisi (23514; superuser dahil herkes için çalışır, 0020 deseni;
   `ENABLE ALWAYS` olduğundan `session_replication_role = replica` ile de atlanamaz):
   - `revoked_at` NULL değilken değiştirilemez. İlk doldurma serbest ama `now() +- 5 dk` içinde olmalı
     (geçmişe ya da geleceğe oynanmış iptal zamanı reddedilir).
   - `last_seen_at` yalnız ileri gidebilir (`>= eski`) ve `now() + 5 dk` sınırını aşamaz.
   - `expires_at` yalnız kısaltılabilir (`<= eski`).
   - `id`, `token_hash`, `user_id`, `tenant_id`, `created_at` hiçbir rol tarafından değiştirilemez.
   Sütun yetkisi yalnız uygulama ve auth rolünü durdurur; tetikleyici sahip ve superuser yolunu da kapatır.
   Sınır: tablo sahibi ya da superuser `ALTER TABLE ... DISABLE TRIGGER` ile tetikleyiciyi kapatabilir
   (DDL yetkisi; testlerin zaman kaydırması bu yolu kullanır). `ip_hash` ve `user_agent` kapsam dışı
   (sütun yetkisi yok, uygulama yazmaz).
3. `auth_gate` işlevlerine dokunulmaz: yalnız `revoked_at = now()` ile NULL satırları doldurur.

0001'e dokunulmaz. Geri alma: tetikleyici ve işlev kaldırılır, iki role tablo düzeyi UPDATE geri verilir.
Veri silinmez.

Revision ID: 0023
Revises: 0022
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

_UPGRADE = [
    # Tablo düzeyi REVOKE sütun düzeyi yetkileri de siler; sonra yalnız gereken sütunlar verilir.
    "REVOKE UPDATE ON sessions FROM netkar_app",
    "GRANT UPDATE (last_seen_at, revoked_at) ON sessions TO netkar_app",
    "REVOKE UPDATE ON sessions FROM netkar_auth",
    "GRANT UPDATE (revoked_at) ON sessions TO netkar_auth",
    """
    CREATE FUNCTION public.sessions_immutable_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        IF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
            RAISE EXCEPTION 'iptal edilmis oturum yeniden acilamaz' USING ERRCODE = '23514';
        END IF;
        IF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL
           AND NEW.revoked_at NOT BETWEEN now() - interval '5 minutes' AND now() + interval '5 minutes' THEN
            RAISE EXCEPTION 'iptal zamani gecersiz' USING ERRCODE = '23514';
        END IF;
        IF NEW.last_seen_at IS DISTINCT FROM OLD.last_seen_at
           AND (NEW.last_seen_at < OLD.last_seen_at OR NEW.last_seen_at > now() + interval '5 minutes') THEN
            RAISE EXCEPTION 'son gorulme zamani geriye alinamaz' USING ERRCODE = '23514';
        END IF;
        IF NEW.expires_at > OLD.expires_at THEN
            RAISE EXCEPTION 'oturum suresi uzatilamaz' USING ERRCODE = '23514';
        END IF;
        IF NEW.id IS DISTINCT FROM OLD.id
           OR NEW.token_hash IS DISTINCT FROM OLD.token_hash
           OR NEW.user_id IS DISTINCT FROM OLD.user_id
           OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'oturum kimlik sutunlari degistirilemez' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER sessions_immutable_guard BEFORE UPDATE ON sessions "
    "FOR EACH ROW EXECUTE FUNCTION public.sessions_immutable_guard()",
    # Çoğaltma modunda (session_replication_role = replica) da çalışsın.
    "ALTER TABLE sessions ENABLE ALWAYS TRIGGER sessions_immutable_guard",
]

_DOWNGRADE = [
    "DROP TRIGGER IF EXISTS sessions_immutable_guard ON sessions",
    "DROP FUNCTION IF EXISTS public.sessions_immutable_guard()",
    # Sütun yetkilerini temizleyip 0001'deki tablo düzeyi yetkiyi geri verir.
    "REVOKE UPDATE ON sessions FROM netkar_app",
    "GRANT UPDATE ON sessions TO netkar_app",
    "REVOKE UPDATE ON sessions FROM netkar_auth",
    "GRANT UPDATE ON sessions TO netkar_auth",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)
