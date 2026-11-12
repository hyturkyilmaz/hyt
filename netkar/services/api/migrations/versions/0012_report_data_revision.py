"""Rapor veri sürümü sayacı (denetim 2026-11-12 OS-03, OS-04).

Dönem sonucu önbelleğinin anahtarındaki "veri sürümü" şimdiye dek her istekte (isabet dahil) sekiz tabloyu
`max(updated_at)` ve `count(*)` ile tarayarak hesaplanıyordu (geçmiş hacmiyle büyür) ve `now()` işlem
BAŞLANGIÇ zamanı olduğundan eşzamanlı iki yazarda bir güncellemeyi kaçırabiliyordu.

Bu migrasyon (geri alınabilir):

- `report_data_revisions (marketplace_account_id PK, tenant_id, revision bigint)`: hesap başına tek sayaç.
  ENABLE + FORCE RLS. `netkar_app` yalnız SELECT (kendi kiracısı); `netkar_worker` hiçbir yetki almaz.
  Uygulama rolleri sayacı doğrudan YAZAMAZ ve geri saramaz: tek yazar tetikleyici işlevidir.
- `public.bump_report_data_revision()`: SECURITY DEFINER (sahibi migrasyonu çalıştıran `netkar_owner`),
  sabit `search_path`. Sayacı `INSERT ... ON CONFLICT DO UPDATE SET revision = revision + 1` ile artırır
  (eşzamanlı yazarlarda sayaç kaybı olmaz). Sahip rol FORCE RLS altında olduğundan tabloda yalnız sahip
  için açık, adlandırılmış bir politika vardır (`owner_counter`); sayaç tamsayıdır, kişisel veri taşımaz.
- Sekiz motor girdisi tablosunda (orders, order_lines, returns, financial_transactions, cargo_invoice_items,
  products, product_costs, sync_cursors) `AFTER INSERT OR UPDATE OR DELETE ... FOR EACH ROW` ERTELENMİŞ
  KISIT tetikleyicisi. Tetikleyici işlem COMMIT edilirken çalışır ve işlem başına hesap başına yalnız bir kez
  artırır (yerel GUC `netkar.rdr_<hesap>` ile tekilleştirme). Böylece:
  * hiçbir yazım yolu unutulamaz (uygulama kodu, betik, elle SQL; yeni yazan kod da kapsanır),
  * sayaç satırının kilidi yalnız commit anında tutulur: yazarlar işlem boyunca birbirini beklemez ve
    sayaç kilidi nedeniyle kilitlenme (deadlock) oluşmaz,
  * artış ile veri aynı işlemde görünür olur; sürüm okuyan veriyi de görür (`now()` penceresi kapanır).
  `TRUNCATE` tetiklemez (uygulamada kullanılmaz).
- Mevcut hesaplar için satır yoktur: sürüm 0 sayılır, ilk yazımda 1 olur. Önbellek süreç içidir, sürüm
  anahtar parçasıdır; sürüm biçimi (demet -> tamsayı) değiştiğinden dağıtım sonrası eski girdiler zaten
  başka sürümün anahtarıdır.

Geri alma: tetikleyiciler, işlev ve tablo düşer. Veri kaybı yoktur (sayaç türetilmiş bir önbellek işaretidir).

Revision ID: 0012
Revises: 0011
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
FUNCTION = "bump_report_data_revision"
TABLE = "report_data_revisions"
TRIGGER = "trg_bump_report_data_revision"
# Motor girdisini besleyen tablolar (app.services.profit_feed.build_profit_input + sync_cursors).
VERSIONED_TABLES = (
    "orders",
    "order_lines",
    "returns",
    "financial_transactions",
    "cargo_invoice_items",
    "products",
    "product_costs",
    "sync_cursors",
)

UPGRADE_SQL = [
    f"""
    CREATE TABLE {TABLE} (
        marketplace_account_id uuid PRIMARY KEY,
        tenant_id uuid NOT NULL,
        revision bigint NOT NULL CHECK (revision >= 1)
    )
    """,
    f"CREATE INDEX ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)",
    f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY",
    f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY tenant_isolation ON {TABLE} FOR SELECT TO netkar_app USING (tenant_id = {TENANT_EXPR})",
    # Sahip rol (işlev sahibi) FORCE RLS altındadır: yalnız ona açık, adlandırılmış politika.
    f"CREATE POLICY owner_counter ON {TABLE} FOR ALL TO CURRENT_USER USING (true) WITH CHECK (true)",
    f"GRANT SELECT ON {TABLE} TO netkar_app",
    f"""
    CREATE FUNCTION public.{FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    DECLARE
        v_tenant uuid;
        v_account uuid;
        v_key text;
    BEGIN
        IF TG_OP = 'DELETE' THEN
            v_tenant := OLD.tenant_id;
            v_account := OLD.marketplace_account_id;
        ELSE
            v_tenant := NEW.tenant_id;
            v_account := NEW.marketplace_account_id;
        END IF;
        -- İşlem başına hesap başına bir artış: ilk tetiklemede yerel GUC işaretlenir.
        v_key := 'netkar.rdr_' || replace(v_account::text, '-', '');
        IF current_setting(v_key, true) = '1' THEN
            RETURN NULL;
        END IF;
        INSERT INTO public.{TABLE} AS r (marketplace_account_id, tenant_id, revision)
        VALUES (v_account, v_tenant, 1)
        ON CONFLICT (marketplace_account_id) DO UPDATE SET revision = r.revision + 1;
        PERFORM set_config(v_key, '1', true);
        RETURN NULL;
    END
    $$
    """,
    f"REVOKE ALL ON FUNCTION public.{FUNCTION}() FROM PUBLIC",
    *[
        f"CREATE CONSTRAINT TRIGGER {TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON {t} "
        f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()"
        for t in VERSIONED_TABLES
    ],
]

DOWNGRADE_SQL = [
    *[f"DROP TRIGGER IF EXISTS {TRIGGER} ON {t}" for t in VERSIONED_TABLES],
    f"DROP FUNCTION IF EXISTS public.{FUNCTION}()",
    f"DROP TABLE IF EXISTS {TABLE}",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
