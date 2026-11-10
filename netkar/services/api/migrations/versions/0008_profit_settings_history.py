"""Kâr ayarı tarihçesi: değişmez ayar satırları, sürüm aralığı ve ayar günlüğü (ADR-0007 §4, docs/12 K42-K44).

Üç sürümlü tablo (`cargo_tariffs`, `service_fee_estimates`, `variable_expenses`) için:

- Sürüm aralığı ve kapanış sütunları: `revision_from` (satırın eklendiği ayar sürümü), `revision_to` (kapandığı
  sürüm; NULL = etkin), `ended_at`, `ended_by`, `end_reason` (`degistirildi` | `geri_cekildi`), `replaces_id`
  (değiştirmede yerini aldığı satır). Tutarlılık CHECK kısıtlarıyla (kapanış sütunları ya hep boş ya hep dolu).
- Benzersizlik yalnız etkin satırlarda (kapanmış satırlar aynı anahtarı taşıyabilir).
- Değişmezlik iki katmanlı: tetikleyici (sahip rol dahil: kapanmış satır ve iş alanları güncellenemez) ve yetki
  (`netkar_app`'ten DELETE ve tablo düzeyi UPDATE kalkar, yalnız kapanış sütunlarında UPDATE kalır).
- `profit_settings_changes`: ayar sürümü başına tek günlük kaydı (kim, ne zaman, kalem, işlem, etki tarihi, onay;
  varsayılan desinin önceki ve yeni değeri). Tutar yoktur (değer değişmez satırdadır). RLS ENABLE + FORCE,
  `netkar_app` yalnız SELECT ve INSERT, `netkar_worker` yalnız SELECT.
- Taşıma: mevcut satırlar o anki ayar sürümüyle işaretlenir ve her hesap için günlükte bir `tasima` kaydı
  düşer (daha eski sürümle yükleme "yeniden kurulamaz" olur, K44).

Revizyon 1 (denetim YT-03, 10 Kasım 2026; 0008 hiçbir ortamda çalışmadan yerinde düzeltildi): ayar başlığı
(`profit_settings`) olmayan ama satırı olan hesaplar için taşıma ÖNCE başlığı `revision = 1` ile oluşturur.
Eski savunma satırı (`revision_from = 1`, başlıksız ve `tasima` kaydısız) kaldırıldı: o durum etkin satırlı
ama damgası 0 bir hesap bırakıyor ve her ilk değiştirme/geri çekmede `ck_<tablo>_ended` ihlaliyle 500
üretiyordu.

ADR taslağından tek sapma: `ck_profit_settings_changes_replace` kısıtı varsayılan desiyi (`defaults`) kapsam dışı
bırakır; desinin değişmesi satır değiştirmesi değildir, `degistir` eyleminde `replaced_record_id` taşıyacak satır
yoktur (taslaktaki kısıt `defaults` + `degistir` kaydını imkansız kılardı).

Geri alma: kapanmış satır ya da `tasima` dışı günlük kaydı varsa eski şemaya sığmaz (aynı anahtarlı kapanmış
satırlar eski tekillik kısıtını bozar) ve silinmeleri gerekir; downgrade `NETKAR_ALLOW_SETTINGS_HISTORY_LOSS=1`
olmadan DURUR (0007 deseni). Bayrakla: kapanmış satırlar ve günlük silinir, etkin satırlar ve değerleri korunur.
Boş ya da yalnız `tasima` kayıtlı tarihçede bayrak gerekmez.

Revision ID: 0008
Revises: 0007
"""

import os

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

VERSIONED = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")
CLOSE_COLUMNS = ("revision_to", "ended_at", "ended_by", "end_reason")
ALLOW_HISTORY_LOSS_ENV = "NETKAR_ALLOW_SETTINGS_HISTORY_LOSS"
GUARD_FUNCTION = "profit_settings_version_guard"
# Üç tablonun satır sahipleri (başlığı olmayan hesapları bulmak için, YT-03).
ALL_ROWS = " UNION ALL ".join(
    f"SELECT tenant_id, marketplace_account_id, entered_by, created_at FROM {t}" for t in VERSIONED
)


def _columns(table: str) -> str:
    return f"""
    ALTER TABLE {table}
        ADD COLUMN revision_from bigint,
        ADD COLUMN revision_to bigint,
        ADD COLUMN ended_at timestamptz,
        ADD COLUMN ended_by uuid REFERENCES users (id),
        ADD COLUMN end_reason text,
        ADD COLUMN replaces_id uuid REFERENCES {table} (id)"""


def _backfill_and_checks(table: str) -> list[str]:
    return [
        f"""
        UPDATE {table} t SET revision_from = p.revision
          FROM profit_settings p
         WHERE p.marketplace_account_id = t.marketplace_account_id AND p.tenant_id = t.tenant_id""",
        f"ALTER TABLE {table} ALTER COLUMN revision_from SET NOT NULL",
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_revision CHECK (revision_from >= 1)",
        f"""
        ALTER TABLE {table} ADD CONSTRAINT ck_{table}_ended CHECK (
              (revision_to IS NULL AND ended_at IS NULL AND ended_by IS NULL AND end_reason IS NULL)
           OR (revision_to IS NOT NULL AND revision_to > revision_from AND ended_at IS NOT NULL
               AND ended_by IS NOT NULL AND end_reason IN ('degistirildi', 'geri_cekildi')))""",
        f"ALTER TABLE {table} ADD CONSTRAINT ck_{table}_replaces CHECK (replaces_id IS NULL OR replaces_id <> id)",
        f"CREATE INDEX ix_{table}_active ON {table} (tenant_id, marketplace_account_id) WHERE revision_to IS NULL",
        f"CREATE INDEX ix_{table}_revision ON {table} (tenant_id, marketplace_account_id, revision_from)",
        f"""
        CREATE TRIGGER trg_{table}_version_guard BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION {GUARD_FUNCTION}()""",
    ]


UPGRADE_SQL = [
    # ---- Rollerin varlığı (0006 ile kuruldu; yine de açık hata) --------------------------------
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netkar_worker') THEN
            RAISE EXCEPTION 'netkar_worker rolu yok: migrasyondan once app.db.provision.provision_roles calistirin (ADR-0005 6)';
        END IF;
    END
    $$
    """,
    # ---- Doldurma için FORCE RLS geçici kapatılır (sahip rol satır göremezdi); sonda geri açılır ------
    "ALTER TABLE profit_settings NO FORCE ROW LEVEL SECURITY",
    *[f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY" for t in VERSIONED],
    # ---- 0. Ayar başlığı olmayan hesaplar (denetim YT-03): üç tablodan birinde satırı olup `profit_settings`
    # satırı olmayan hesap için başlık `revision = 1` ile önce oluşturulur. Böylece doldurma ve `tasima` kaydı
    # her hesap için aynı yoldan çalışır; damga 0 iken etkin satır olan tutarsız durum (ve ilk değiştirmede
    # 500) hiç doğmaz. `updated_by`: hesabın en eski satırını giren kullanıcı.
    f"""
    INSERT INTO profit_settings (tenant_id, marketplace_account_id, revision, updated_by)
    SELECT DISTINCT ON (marketplace_account_id) tenant_id, marketplace_account_id, 1, entered_by
      FROM ({ALL_ROWS}) rows
     WHERE NOT EXISTS (SELECT 1 FROM profit_settings p WHERE p.marketplace_account_id = rows.marketplace_account_id)
     ORDER BY marketplace_account_id, created_at, entered_by
    """,
    # ---- 1. Sütunlar, doldurma, kısıtlar, indeksler -----------------------------------------------
    *[_columns(t) for t in VERSIONED],
    # Değişmezlik tetikleyicisi (ADR-0007 §4 madde 4): kapanmış satır ve iş alanları değişmez.
    f"""
    CREATE FUNCTION {GUARD_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$
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
    """,
    *[stmt for t in VERSIONED for stmt in _backfill_and_checks(t)],
    # ---- 2. Tekillik yalnız etkin satırlarda ------------------------------------------------------
    "ALTER TABLE cargo_tariffs DROP CONSTRAINT uq_cargo_tariffs_version",
    """
    CREATE UNIQUE INDEX uq_cargo_tariffs_active_version
        ON cargo_tariffs (marketplace_account_id, agreement, carrier, valid_from) WHERE revision_to IS NULL
    """,
    "ALTER TABLE service_fee_estimates DROP CONSTRAINT uq_service_fee_estimates_version",
    """
    CREATE UNIQUE INDEX uq_service_fee_estimates_active_version
        ON service_fee_estimates (marketplace_account_id, valid_from) WHERE revision_to IS NULL
    """,
    # ---- 3. Ayar günlüğü: ayar sürümü başına tek kayıt -----------------------------------------------
    """
    CREATE TABLE profit_settings_changes (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        CONSTRAINT fk_profit_settings_changes_account FOREIGN KEY (marketplace_account_id, tenant_id)
            REFERENCES marketplace_accounts (id, tenant_id),
        revision bigint NOT NULL CHECK (revision >= 1),
        changed_by uuid REFERENCES users (id),
        changed_at timestamptz NOT NULL DEFAULT now(),
        item text NOT NULL CHECK (item IN ('cargo_tariff', 'service_fee_estimate', 'variable_expense',
                                           'defaults', 'tasima')),
        action text NOT NULL CHECK (action IN ('ekle', 'degistir', 'geri_cek', 'tasima')),
        record_id uuid,
        replaced_record_id uuid,
        affects_from date,
        affects_past boolean NOT NULL,
        past_change_confirmed boolean NOT NULL DEFAULT false,
        default_desi_before numeric(9,2),
        default_desi_after numeric(9,2),
        CONSTRAINT uq_profit_settings_changes_revision UNIQUE (marketplace_account_id, revision),
        CONSTRAINT ck_profit_settings_changes_tasima CHECK ((item = 'tasima') = (action = 'tasima')),
        CONSTRAINT ck_profit_settings_changes_actor CHECK (item = 'tasima' OR changed_by IS NOT NULL),
        CONSTRAINT ck_profit_settings_changes_desi CHECK (
            item IN ('defaults', 'tasima') OR (default_desi_before IS NULL AND default_desi_after IS NULL)),
        CONSTRAINT ck_profit_settings_changes_replace CHECK (
            item = 'defaults' OR (action = 'degistir') = (replaced_record_id IS NOT NULL))
    )
    """,
    """
    CREATE INDEX ix_profit_settings_changes_tenant_account
        ON profit_settings_changes (tenant_id, marketplace_account_id, revision DESC)
    """,
    # ---- 4. Taşıma kaydı: her hesap için mevcut durumun sınırı (K44); RLS henüz açık değil -------------
    """
    INSERT INTO profit_settings_changes (tenant_id, marketplace_account_id, revision, changed_at, item, action,
                                         affects_past, default_desi_after)
    SELECT tenant_id, marketplace_account_id, revision, now(), 'tasima', 'tasima', false, default_desi
      FROM profit_settings
    """,
    "ALTER TABLE profit_settings_changes ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE profit_settings_changes FORCE ROW LEVEL SECURITY",
    f"""
    CREATE POLICY tenant_isolation ON profit_settings_changes
        USING (tenant_id = {TENANT_EXPR}) WITH CHECK (tenant_id = {TENANT_EXPR})
    """,
    # ---- 5. Yetkiler: uygulama rolü yalnız kapanış sütunlarını günceller, hiçbir şeyi silmez -----------
    f"REVOKE UPDATE, DELETE ON {', '.join(VERSIONED)} FROM netkar_app",
    f"GRANT UPDATE ({', '.join(CLOSE_COLUMNS)}) ON {', '.join(VERSIONED)} TO netkar_app",
    "GRANT SELECT, INSERT ON profit_settings_changes TO netkar_app",
    "GRANT SELECT ON profit_settings_changes TO netkar_worker",
    # ---- FORCE RLS geri açılır ----------------------------------------------------------------------
    "ALTER TABLE profit_settings FORCE ROW LEVEL SECURITY",
    *[f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in VERSIONED],
]

# Downgrade (açık sıra, CASCADE yok). Tetikleyiciler önce düşer: kapanmış satırları silmek ve etkin satırların
# `replaces_id`'ini boşaltmak onlara takılmasın.
DOWNGRADE_SQL = [
    *[f"DROP TRIGGER trg_{t}_version_guard ON {t}" for t in VERSIONED],
    f"DROP FUNCTION {GUARD_FUNCTION}()",
    *[f"UPDATE {t} SET replaces_id = NULL WHERE replaces_id IS NOT NULL" for t in VERSIONED],
    *[f"DELETE FROM {t} WHERE revision_to IS NOT NULL" for t in VERSIONED],
    "REVOKE ALL ON profit_settings_changes FROM netkar_worker",
    "REVOKE ALL ON profit_settings_changes FROM netkar_app",
    "DROP TABLE profit_settings_changes",
    *[f"DROP INDEX ix_{t}_active" for t in VERSIONED],
    *[f"DROP INDEX ix_{t}_revision" for t in VERSIONED],
    "DROP INDEX uq_cargo_tariffs_active_version",
    "DROP INDEX uq_service_fee_estimates_active_version",
    """
    ALTER TABLE cargo_tariffs
        ADD CONSTRAINT uq_cargo_tariffs_version UNIQUE (marketplace_account_id, agreement, carrier, valid_from)
    """,
    """
    ALTER TABLE service_fee_estimates
        ADD CONSTRAINT uq_service_fee_estimates_version UNIQUE (marketplace_account_id, valid_from)
    """,
    *[
        stmt
        for t in VERSIONED
        for stmt in (
            f"ALTER TABLE {t} DROP CONSTRAINT ck_{t}_replaces",
            f"ALTER TABLE {t} DROP CONSTRAINT ck_{t}_ended",
            f"ALTER TABLE {t} DROP CONSTRAINT ck_{t}_revision",
            f"""
            ALTER TABLE {t}
                DROP COLUMN replaces_id,
                DROP COLUMN end_reason,
                DROP COLUMN ended_by,
                DROP COLUMN ended_at,
                DROP COLUMN revision_to,
                DROP COLUMN revision_from""",
        )
    ],
    # Sütun düzeyi UPDATE yetkisi sütunlarla birlikte düştü; kalan tablo yetkisi 0007 durumuna getirilir.
    f"REVOKE UPDATE ON {', '.join(VERSIONED)} FROM netkar_app",
    f"GRANT UPDATE, DELETE ON {', '.join(VERSIONED)} TO netkar_app",
    *[f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY" for t in VERSIONED],
    "ALTER TABLE profit_settings FORCE ROW LEVEL SECURITY",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def _guard_history() -> None:
    """Tarihçe (kapanmış satır ya da `tasima` dışı günlük) varsa ve açık onay yoksa downgrade'i durdurur.

    Tablolar FORCE RLS altındadır: sayım için FORCE bu işlemde kapatılır; hata atılırsa işlem geri alınır ve
    FORCE yerinde kalır, devam edilirse downgrade sonunda yeniden açılır.
    """
    bind = op.get_bind()
    for table in ("profit_settings", "profit_settings_changes", *VERSIONED):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    closed = {
        t: int(bind.exec_driver_sql(f"SELECT count(*) FROM {t} WHERE revision_to IS NOT NULL").scalar_one())
        for t in VERSIONED
    }
    history = int(
        bind.exec_driver_sql("SELECT count(*) FROM profit_settings_changes WHERE item <> 'tasima'").scalar_one()
    )
    filled = {t: n for t, n in closed.items() if n > 0}
    if (not filled and history == 0) or os.environ.get(ALLOW_HISTORY_LOSS_ENV) == "1":
        return
    detail = ", ".join([f"{t}: {n} kapanmış satır" for t, n in filled.items()] + [f"günlük: {history} kayıt"])
    raise RuntimeError(
        f"0008 downgrade DURDURULDU: ayar tarihçesi var ({detail}). Eski şema kapanmış satırları ve günlüğü "
        "taşıyamaz; downgrade hepsini siler (etkin satırlar ve değerleri korunur). Önce yedek alın: "
        "psql -c \"\\copy profit_settings_changes TO 'profit_settings_changes.csv' CSV HEADER\" ve her tablo için "
        "psql -c \"\\copy (SELECT * FROM cargo_tariffs WHERE revision_to IS NOT NULL) TO 'cargo_tariffs_closed.csv' "
        "CSV HEADER\" (service_fee_estimates ve variable_expenses için aynı). Kaybı bilerek kabul ediyorsanız "
        f"komutu {ALLOW_HISTORY_LOSS_ENV}=1 ortam değişkeniyle yeniden çalıştırın."
    )


def downgrade() -> None:
    _guard_history()
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
