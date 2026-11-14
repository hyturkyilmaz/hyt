"""Ayar başlığı kilitleme (0010 kapanış denetimi 11 Kasım 2026: ZK-01, ZK-02, ZK-03, ZK-04).

0010 sayacı artırılmadan satır eklemeyi ve sayacı geri sarmayı kapattı, ama üç açık kaldı:

- ZK-01: `netkar_app` `profit_settings` tablosunun TÜM sütunlarını güncelleyebiliyordu. Başlığın
  `marketplace_account_id` değerini aynı kiracıdaki başka hesaba çevirip hesaba yeni başlık (`revision = 1`)
  ekleyerek sayacı dolaylı olarak 1'e indirebiliyordu. Düzeltme: tablo düzeyi UPDATE geri alınır; yalnız
  uygulamanın gerçekten yazdığı dört sütuna (`default_desi`, `revision`, `updated_by`, `updated_at`) sütun düzeyi
  UPDATE verilir. Derinlemesine savunma: tetikleyici `id`, `tenant_id`, `marketplace_account_id` değişimini HER
  rol için (sahip rol ve yönetici dahil) reddeder.
- ZK-02: "atlama reddedilir" yalnız deyim başınaydı; aynı işlemde sayaç istenen kadar artırılabiliyordu.
  Düzeltme: sayaç bu işlemde zaten artırılmışsa (`OLD.revision_xact = pg_current_xact_id()`) yeni artış reddedilir.
  Dürüst akış uyumludur: `finish_write` işlem başına bir kez artırır; yeni başlık oluşturulan işlemde artırma
  yapılmaz.
- ZK-03: sıra kuralları "netkar_app dışındaki her rol muaf" biçimindeydi; ileride yazma yetkisi alacak yeni bir
  rol sessizce muaf olurdu. Düzeltme (olumsuz listeden olumlu listeye): yalnız açıkça adlandırılmış bakım rolleri
  (`netkar_owner` ve süper kullanıcı) muaftır; diğer her rol, `netkar_app` dahil, kurallara tabidir
  (varsayılan ret, "fail closed"). Muafiyet tek bir yardımcı işlevde (`profit_settings_maintenance_role`) durur.
  Yazma yetkili rol kümesini doğrulayan şema testi (yeni rol yetki alırsa kırılır) bu kararı tamamlar.

ZK-04: 0010 downgrade'i 0009 gövdelerini `importlib` ile dosyadan yüklüyordu (kırılgan). 0010 yayımlanmış
sayıldığından değiştirilmedi; bu migrasyon 0010 gövdelerini aşağıda METİN olarak taşır (migrasyonlar dondurulmuş
belgedir) ve downgrade yalnız bunlara dayanır. İşlev gövdelerinin downgrade sonrası beklenen gövdeyle eşitliği
`pg_get_functiondef` ile testle doğrulanır.

Geri alma: başlık tetikleyici işlevi ve üç kural işlevi 0010 gövdelerine döner, yardımcı işlev düşer, sütun
düzeyi UPDATE geri alınıp tablo düzeyi UPDATE verilir. Veri kaybı yoktur.

Revision ID: 0011
Revises: 0010
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

APP_ROLE = "netkar_app"
OWNER_ROLE = "netkar_owner"
VERSION_GUARD = "profit_settings_version_guard"
INSERT_GUARD = "profit_settings_insert_guard"
JOURNAL_GUARD = "profit_settings_changes_guard"
HEAD_GUARD = "profit_settings_head_guard"
MAINTENANCE = "profit_settings_maintenance_role"
SEARCH_PATH = "SET search_path = pg_catalog, public"
APP_UPDATE_COLUMNS = "default_desi, revision, updated_by, updated_at"

# ZK-03: muaf roller açıkça adlandırılır (bakım rolü ve süper kullanıcı); başka hiçbir rol muaf değildir.
MAINTENANCE_SQL = f"""
CREATE FUNCTION public.{MAINTENANCE}() RETURNS boolean LANGUAGE sql STABLE SET search_path = pg_catalog AS $$
    SELECT current_user = '{OWNER_ROLE}'
        OR COALESCE((SELECT r.rolsuper FROM pg_catalog.pg_roles r WHERE r.rolname = current_user), false)
$$
"""

HEAD_GUARD_0011 = f"""
CREATE OR REPLACE FUNCTION {HEAD_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT public.{MAINTENANCE}() AND NEW.revision <> 1 THEN
            RAISE EXCEPTION 'ayar sayaci 1 ile baslar (K42)' USING ERRCODE = 'check_violation';
        END IF;
        NEW.revision_xact := pg_current_xact_id();
    ELSE
        -- ZK-01: hesap anahtarı değişmez (her rol); başlığı başka hesaba taşıyıp sayacı sıfırlama yolu kapalı.
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
           OR NEW.marketplace_account_id IS DISTINCT FROM OLD.marketplace_account_id THEN
            RAISE EXCEPTION 'ayar basliginin hesap anahtari degistirilemez (K42)' USING ERRCODE = 'check_violation';
        END IF;
        IF NOT public.{MAINTENANCE}() THEN
            IF NEW.revision NOT IN (OLD.revision, OLD.revision + 1) THEN
                RAISE EXCEPTION 'ayar sayaci yalniz bir artabilir, azalamaz (K42)' USING ERRCODE = 'check_violation';
            END IF;
            -- ZK-02: işlem başına tek artış (xid8 işlem bağı); aynı işlemde ikinci artış reddedilir.
            IF NEW.revision <> OLD.revision AND OLD.revision_xact = pg_current_xact_id() THEN
                RAISE EXCEPTION 'ayar sayaci bir islemde yalniz bir kez artar (K42)' USING ERRCODE = 'check_violation';
            END IF;
        END IF;
        IF NEW.revision IS DISTINCT FROM OLD.revision THEN
            NEW.revision_xact := pg_current_xact_id();
        ELSE
            NEW.revision_xact := OLD.revision_xact;
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

VERSION_GUARD_0011 = f"""
CREATE OR REPLACE FUNCTION {VERSION_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    -- YT-04, YK-01: uygulama rolü satırı yalnız ayar sayacındaki sürümle ve sayacı bu işlemde artırarak kapatır.
    IF NOT public.{MAINTENANCE}() AND NEW.revision_to IS NOT NULL THEN
        SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
         WHERE p.marketplace_account_id = OLD.marketplace_account_id AND p.tenant_id = OLD.tenant_id;
        IF head IS NULL OR NEW.revision_to <> head THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz ayar sayacindaki surumle kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
        IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

INSERT_GUARD_0011 = f"""
CREATE OR REPLACE FUNCTION {INSERT_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF public.{MAINTENANCE}() THEN
        RETURN NEW;
    END IF;
    IF NEW.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kar ayari satiri bastan kapali eklenemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision_from <> head THEN
        RAISE EXCEPTION 'kar ayari satirinin surumu ayar sayacina esit olmali (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla eklenebilir (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

JOURNAL_GUARD_0011 = f"""
CREATE OR REPLACE FUNCTION {JOURNAL_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF public.{MAINTENANCE}() THEN
        RETURN NEW;
    END IF;
    IF NEW.item = 'tasima' THEN
        RAISE EXCEPTION 'tasima kaydini uygulama rolu yazamaz (K44)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision <> head THEN
        RAISE EXCEPTION 'ayar gunlugu kaydinin surumu ayar sayacina esit olmali (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'ayar gunlugu kaydi yalniz sayaci bu islemde artiran akisla yazilabilir (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

# ---- 0010 gövdeleri (downgrade için METİN olarak; importlib ya da başka dosyaya bağımlılık yok, ZK-04) ----
HEAD_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {HEAD_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user = '{APP_ROLE}' AND NEW.revision <> 1 THEN
            RAISE EXCEPTION 'ayar sayaci 1 ile baslar (K42)' USING ERRCODE = 'check_violation';
        END IF;
        NEW.revision_xact := pg_current_xact_id();
    ELSE
        IF current_user = '{APP_ROLE}' AND NEW.revision NOT IN (OLD.revision, OLD.revision + 1) THEN
            RAISE EXCEPTION 'ayar sayaci yalniz bir artabilir, azalamaz (K42)' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.revision IS DISTINCT FROM OLD.revision THEN
            NEW.revision_xact := pg_current_xact_id();
        ELSE
            NEW.revision_xact := OLD.revision_xact;
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

VERSION_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {VERSION_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    -- YT-04, YK-01: uygulama rolü satırı yalnız ayar sayacındaki sürümle ve sayacı bu işlemde artırarak kapatır.
    IF current_user = '{APP_ROLE}' AND NEW.revision_to IS NOT NULL THEN
        SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
         WHERE p.marketplace_account_id = OLD.marketplace_account_id AND p.tenant_id = OLD.tenant_id;
        IF head IS NULL OR NEW.revision_to <> head THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz ayar sayacindaki surumle kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
        IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

INSERT_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {INSERT_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kar ayari satiri bastan kapali eklenemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision_from <> head THEN
        RAISE EXCEPTION 'kar ayari satirinin surumu ayar sayacina esit olmali (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla eklenebilir (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

JOURNAL_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {JOURNAL_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.item = 'tasima' THEN
        RAISE EXCEPTION 'tasima kaydini uygulama rolu yazamaz (K44)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision <> head THEN
        RAISE EXCEPTION 'ayar gunlugu kaydinin surumu ayar sayacina esit olmali (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'ayar gunlugu kaydi yalniz sayaci bu islemde artiran akisla yazilabilir (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""


def upgrade() -> None:
    # Yardımcı işlev önce: kural işlevleri onu çağırır (plpgsql gövdesi çalışma anında çözülür, yine de sıra doğru).
    op.execute(MAINTENANCE_SQL)
    for statement in (HEAD_GUARD_0011, VERSION_GUARD_0011, INSERT_GUARD_0011, JOURNAL_GUARD_0011):
        op.execute(statement)
    # ZK-01: tablo düzeyi UPDATE geri alınır (sütun yetkilerini de siler), yalnız yazılan sütunlara verilir.
    op.execute(f"REVOKE UPDATE ON profit_settings FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({APP_UPDATE_COLUMNS}) ON profit_settings TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({APP_UPDATE_COLUMNS}) ON profit_settings FROM {APP_ROLE}")
    op.execute(f"GRANT UPDATE ON profit_settings TO {APP_ROLE}")
    for statement in (HEAD_GUARD_0010, VERSION_GUARD_0010, INSERT_GUARD_0010, JOURNAL_GUARD_0010):
        op.execute(statement)
    op.execute(f"DROP FUNCTION public.{MAINTENANCE}()")
