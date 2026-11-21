"""Demo hesapları ve "üretim değil" işareti (demo tohumu denetimi DT-01, DT-02).

İki küçük, geri alınabilir şema parçası:

1. `marketplace_accounts.is_demo` (boolean, varsayılan false): demo tohumunun yarattığı hesapları işaretler.
   Senkron kapısı (`sync_gate.syncable_accounts` ve sync_gate politikası) `NOT is_demo` ister; böylece
   zamanlayıcı ve çalıştırıcı demo hesabı hiç görmez, sahte anahtarla Trendyol'a istek atılmaz ve hesap
   `invalid` olmaz. `netkar_app` bu sütunu doğrudan YAZAMAZ: tablo düzeyi INSERT yetkisi sütun düzeyine
   daraltılır (is_demo hariç), UPDATE yetkisi zaten sütun düzeyindedir (0005). Bayrağı yalnız
   `public.mark_demo_account(uuid)` açar; bu SECURITY DEFINER işlev, veritabanında
   `deployment_marks.non_production = 'true'` işareti yoksa HATA verir. Üretimde işaret hiç yazılmadığı için
   uygulama rolü hiçbir hesabı demo yapamaz (ve yapsa bile işlev kiracı RLS'si altında yalnız kendi hesabına
   dokunur).

2. `deployment_marks`: veritabanının kendisinde saklanan küçük anahtar-değer tablosu. `non_production`
   işaretini YALNIZ süper kullanıcı ya da migrasyon sahibi yazabilir (uygulama ve işçi rolleri yalnız okur).
   Tohum betiği işaret yoksa durur. Gerekçe: `COMMENT ON DATABASE` salt metindir ve yetkisiz okunamayabilir;
   tablo, bağlantı dizesinden bağımsız olarak "bu veritabanı üretim değil" bilgisini veritabanına bağlar.
   Tablo kiracı verisi değildir (tenant_id yok), bu yüzden RLS taşımaz.

Geri alma: işlev, tablo ve sütun düşer, INSERT yetkisi tablo düzeyine döner, sync_gate eski haline gelir.
`is_demo` ve işaret verisi kaybolur (yalnız bu migrasyonun eklediği veri).

Revision ID: 0015
Revises: 0014
"""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

# is_demo hariç tüm sütunlar (uygulama rolünün INSERT yetkisi).
INSERT_COLUMNS = (
    "id, tenant_id, platform, seller_id, api_key_encrypted, api_secret_encrypted, api_key_last4, status, "
    "last_validated_at, created_by, created_at, updated_at, revoked_at"
)

_FUNCTION_BODY = """
    RETURNS TABLE (tenant_id uuid, account_id uuid, backfilled_sources text[])
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT a.tenant_id, a.id,
               ARRAY(SELECT c.source FROM public.sync_cursors c
                     WHERE c.marketplace_account_id = a.id AND c.backfill_completed_at IS NOT NULL
                     ORDER BY c.source)
        FROM public.marketplace_accounts a
        WHERE a.status = 'active' {extra} AND (p_account_id IS NULL OR a.id = p_account_id)
        ORDER BY a.created_at, a.id
    $$
"""

UPGRADE_SQL = [
    "ALTER TABLE marketplace_accounts ADD COLUMN is_demo boolean NOT NULL DEFAULT false",
    """
    CREATE TABLE deployment_marks (
        key text PRIMARY KEY CHECK (char_length(key) BETWEEN 1 AND 64),
        value text NOT NULL CHECK (char_length(value) <= 200),
        set_at timestamptz NOT NULL DEFAULT now(),
        set_by text NOT NULL DEFAULT current_user
    )
    """,
    "REVOKE ALL ON deployment_marks FROM PUBLIC",
    "GRANT SELECT ON deployment_marks TO netkar_app, netkar_worker",
    # Uygulama rolü is_demo'yu yazamaz: INSERT sütun düzeyine daralır (UPDATE zaten sütun düzeyinde).
    "REVOKE INSERT ON marketplace_accounts FROM netkar_app",
    f"GRANT INSERT ({INSERT_COLUMNS}) ON marketplace_accounts TO netkar_app",
    "GRANT SELECT (is_demo) ON marketplace_accounts TO netkar_app",
    # Senkron kapısı demo hesabı görmez.
    "GRANT SELECT (is_demo) ON marketplace_accounts TO netkar_sync_gate",
    "DROP POLICY sync_gate_path ON marketplace_accounts",
    "CREATE POLICY sync_gate_path ON marketplace_accounts FOR SELECT TO netkar_sync_gate "
    "USING (status = 'active' AND NOT is_demo)",
    "SET LOCAL ROLE netkar_sync_gate",
    "CREATE OR REPLACE FUNCTION sync_gate.syncable_accounts(p_account_id uuid DEFAULT NULL)"
    + _FUNCTION_BODY.format(extra="AND NOT a.is_demo"),
    "RESET ROLE",
    """
    CREATE FUNCTION public.mark_demo_account(p_account_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM public.deployment_marks WHERE key = 'non_production' AND value = 'true') THEN
            RAISE EXCEPTION 'bu veritabani uretim disi olarak isaretli degil (deployment_marks.non_production)'
                USING ERRCODE = '42501';
        END IF;
        UPDATE public.marketplace_accounts SET is_demo = true WHERE id = p_account_id;
    END
    $$
    """,
    "ALTER FUNCTION public.mark_demo_account(uuid) OWNER TO netkar_owner",
    "REVOKE ALL ON FUNCTION public.mark_demo_account(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.mark_demo_account(uuid) TO netkar_app",
]

DOWNGRADE_SQL = [
    "DROP FUNCTION IF EXISTS public.mark_demo_account(uuid)",
    "SET LOCAL ROLE netkar_sync_gate",
    "CREATE OR REPLACE FUNCTION sync_gate.syncable_accounts(p_account_id uuid DEFAULT NULL)"
    + _FUNCTION_BODY.format(extra=""),
    "RESET ROLE",
    "DROP POLICY sync_gate_path ON marketplace_accounts",
    "CREATE POLICY sync_gate_path ON marketplace_accounts FOR SELECT TO netkar_sync_gate "
    "USING (status = 'active')",
    "REVOKE SELECT (is_demo) ON marketplace_accounts FROM netkar_sync_gate",
    "REVOKE SELECT (is_demo) ON marketplace_accounts FROM netkar_app",
    f"REVOKE INSERT ({INSERT_COLUMNS}) ON marketplace_accounts FROM netkar_app",
    "GRANT INSERT ON marketplace_accounts TO netkar_app",
    "ALTER TABLE marketplace_accounts DROP COLUMN is_demo",
    "DROP TABLE deployment_marks",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
