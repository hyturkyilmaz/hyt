"""Ayar tarihçesi sertleştirmesi (bağımsız denetim 10 Kasım 2026: YT-02, YT-04, YT-09; ADR-0007 §4 Revizyon 1).

0008 hiçbir ortamda çalışmadan YT-03 için yerinde düzeltildi; bu migrasyon denetimin geri kalan şema bulgularını
GERİ ALINABİLİR olarak ekler:

- YT-02: `replaces_id` indeksleri (üç sürümlü tablo, kısmi indeks). `settings-record-ended` halef zinciri
  indekssiz self-FK üzerinde yürüyordu; hesap silme (imha) işinde de her silinen satır tarama demekti.
- YT-04 (derinlemesine savunma): `netkar_app` INSERT ile tarihçeyi sahteleyebiliyordu (geçmiş `revision_from`,
  baştan kapalı satır, sahte `tasima`, başka kiracının kullanıcısı `changed_by`, sayaçtan kopuk `revision_to`).
  * BEFORE INSERT tetikleyicisi (üç sürümlü tablo): satır baştan kapalı olamaz ve `revision_from`, aynı işlemde
    artırılmış ayar sayacına (`profit_settings.revision`) eşit olmalıdır. Yazım akışı (`begin_write` ->
    `finish_write` başlığı flush eder -> satır) bu kuralı zaten böyle uygular.
  * Kapanış kuralı: `netkar_app` bir satırı yalnız sayaçtaki sürümle kapatabilir (`revision_to = sayaç`); mevcut
    `profit_settings_version_guard` işlevi (0008) bu şartla genişletildi.
  * BEFORE INSERT tetikleyicisi (`profit_settings_changes`): günlük kaydının `revision`'ı sayaca eşit olmalı ve
    `tasima` kaydını yalnız taşıma (sahip rol) yazabilir.
  * `changed_by` için kiracıyla bileşik FK: `(changed_by, tenant_id) -> memberships (user_id, tenant_id)`. Başka
    kiracının kullanıcısı yazılamaz; `changed_by` boşsa (yalnız `tasima`) denetlenmez (MATCH SIMPLE). Üyelik
    silme özelliği yoktur (`netkar_app` memberships'te DELETE'e sahip değildir); gelirse üyelik silme bu FK'ye
    takılır ve kimliksizleştirme (üyeliği tutup kullanıcıyı anonimleştirme) tercih edilmelidir.
  Sıra kuralları YALNIZ `netkar_app` için uygulanır (`current_user`): uygulama rolü ele geçirildiğinde ya da
  hatalı kod yazdığında çalışma zamanı yolunu korur. Sahip rol ve yönetici zaten tetikleyiciyi kapatabilir
  (`ALTER TABLE ... DISABLE TRIGGER`); sahip rolle çalışan veri doldurma migrasyonları sıra kuralına takılmaz
  (YT-05, docs/12 K42). Değişmezlik tetikleyicisi (kapanmış satır ve iş alanları) eskisi gibi HERKESİ bağlar.
- YT-09: `ck_profit_settings_changes_replace` sıkılaştırıldı: `defaults` kaydı satır kimliği taşıyamaz, `ekle`
  önceki desiyi, `geri_cek` sonraki desiyi taşıyamaz; diğer kalemlerde `degistir` yerini aldığı satırı taşır.

Geri alma: tetikleyiciler, işlevler, FK, indeksler düşer; kapanış işlevi 0008 gövdesine ve kısıt 0008
tanımına döner. Veri kaybı yoktur (yalnız kısıt ve nesneler).

Revision ID: 0009
Revises: 0008
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

VERSIONED = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")
APP_ROLE = "netkar_app"
VERSION_GUARD = "profit_settings_version_guard"
INSERT_GUARD = "profit_settings_insert_guard"
JOURNAL_GUARD = "profit_settings_changes_guard"

# 0008 gövdesi (downgrade için): kapanmış satır ve iş alanları değişmez.
VERSION_GUARD_0008 = f"""
CREATE OR REPLACE FUNCTION {VERSION_GUARD}() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

VERSION_GUARD_0009 = f"""
CREATE OR REPLACE FUNCTION {VERSION_GUARD}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    head bigint;
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    -- YT-04: uygulama rolü satırı yalnız ayar sayacındaki sürümle kapatabilir.
    IF current_user = '{APP_ROLE}' AND NEW.revision_to IS NOT NULL THEN
        SELECT p.revision INTO head FROM public.profit_settings p
         WHERE p.marketplace_account_id = OLD.marketplace_account_id AND p.tenant_id = OLD.tenant_id;
        IF head IS NULL OR NEW.revision_to <> head THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz ayar sayacindaki surumle kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

INSERT_GUARD_SQL = f"""
CREATE FUNCTION {INSERT_GUARD}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    head bigint;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kar ayari satiri bastan kapali eklenemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision INTO head FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision_from <> head THEN
        RAISE EXCEPTION 'kar ayari satirinin surumu ayar sayacina esit olmali (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

JOURNAL_GUARD_SQL = f"""
CREATE FUNCTION {JOURNAL_GUARD}() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    head bigint;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.item = 'tasima' THEN
        RAISE EXCEPTION 'tasima kaydini uygulama rolu yazamaz (K44)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision INTO head FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision <> head THEN
        RAISE EXCEPTION 'ayar gunlugu kaydinin surumu ayar sayacina esit olmali (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

# 0008 tanımı (downgrade) ve sıkılaştırılmış tanım (YT-09).
REPLACE_CHECK_0008 = """
ALTER TABLE profit_settings_changes ADD CONSTRAINT ck_profit_settings_changes_replace CHECK (
    item = 'defaults' OR (action = 'degistir') = (replaced_record_id IS NOT NULL))
"""
REPLACE_CHECK_0009 = """
ALTER TABLE profit_settings_changes ADD CONSTRAINT ck_profit_settings_changes_replace CHECK (
    (item = 'defaults' AND record_id IS NULL AND replaced_record_id IS NULL
        AND (action <> 'ekle' OR default_desi_before IS NULL)
        AND (action <> 'geri_cek' OR default_desi_after IS NULL))
    OR (item <> 'defaults' AND (action = 'degistir') = (replaced_record_id IS NOT NULL)))
"""

UPGRADE_SQL = [
    # ---- YT-02: halef zinciri indeksi ----------------------------------------------------------------
    # Kapsam sütunları da indekste: istatistiği henüz olmayan (yeni doldurulmuş) tabloda planlayıcı yalnız
    # `replaces_id` indeksini değil (tenant, hesap, sürüm) indeksini seçip her adımda hesabın bütün satırlarını
    # tarıyordu (2000 halkada CI'da 1,84 sn). Üç eşitliği karşılayan bu indeks istatistikten bağımsız seçilir.
    *[
        f"CREATE INDEX ix_{t}_replaces ON {t} (replaces_id, tenant_id, marketplace_account_id) "
        "WHERE replaces_id IS NOT NULL"
        for t in VERSIONED
    ],
    # ---- YT-09: günlük kısıtı --------------------------------------------------------------------------
    "ALTER TABLE profit_settings_changes DROP CONSTRAINT ck_profit_settings_changes_replace",
    REPLACE_CHECK_0009,
    # ---- YT-04: changed_by kiracı üyesi olmalı (bileşik FK; changed_by boşsa denetlenmez) -----------------
    """
    ALTER TABLE profit_settings_changes ADD CONSTRAINT fk_profit_settings_changes_member
        FOREIGN KEY (changed_by, tenant_id) REFERENCES memberships (user_id, tenant_id)
    """,
    # ---- YT-04: sıra kuralları (yalnız uygulama rolü) -------------------------------------------------------
    VERSION_GUARD_0009,
    INSERT_GUARD_SQL,
    *[
        f"CREATE TRIGGER trg_{t}_insert_guard BEFORE INSERT ON {t} "
        f"FOR EACH ROW EXECUTE FUNCTION {INSERT_GUARD}()"
        for t in VERSIONED
    ],
    JOURNAL_GUARD_SQL,
    f"CREATE TRIGGER trg_profit_settings_changes_guard BEFORE INSERT ON profit_settings_changes "
    f"FOR EACH ROW EXECUTE FUNCTION {JOURNAL_GUARD}()",
]

DOWNGRADE_SQL = [
    "DROP TRIGGER trg_profit_settings_changes_guard ON profit_settings_changes",
    f"DROP FUNCTION {JOURNAL_GUARD}()",
    *[f"DROP TRIGGER trg_{t}_insert_guard ON {t}" for t in VERSIONED],
    f"DROP FUNCTION {INSERT_GUARD}()",
    VERSION_GUARD_0008,
    "ALTER TABLE profit_settings_changes DROP CONSTRAINT fk_profit_settings_changes_member",
    "ALTER TABLE profit_settings_changes DROP CONSTRAINT ck_profit_settings_changes_replace",
    REPLACE_CHECK_0008,
    *[f"DROP INDEX ix_{t}_replaces" for t in VERSIONED],
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
