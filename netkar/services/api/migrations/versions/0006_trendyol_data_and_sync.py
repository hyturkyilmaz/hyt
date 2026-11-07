"""Trendyol verisi (ürün, maliyet, sipariş, iade, ekstre, kargo faturası), senkron durumu ve worker rolü.

ADR-0005. Bu migrasyon üç iş yapar:

1. Veri tabloları (hepsi `tenant_id` + `marketplace_account_id`, ENABLE + FORCE RLS):
   products, product_costs, orders, order_lines, returns, financial_transactions,
   cargo_invoice_items; senkron durumu: sync_runs, sync_cursors.
   Para alanları NUMERIC(18,6): Trendyol kuruş altı hassasiyetli tutar gönderir (ör. komisyon 74,985)
   ve kâr motoru tam hassasiyetle (Fraction) çalışır, tek yuvarlama motorun çıkışındadır (K01).
   Oranlar NUMERIC(9,4). Son müşteriye ait ad, adres, telefon, TCKN, e-posta bu tablolarda YOKTUR.
2. Ayrı DB rolü `netkar_worker` (S2 D-05): şifreli sütunları SELECT edebilen tek rol. `netkar_app`
   `marketplace_accounts.api_key_encrypted` ve `api_secret_encrypted` sütunlarını artık SELECT edemez
   (INSERT ve UPDATE yetkisi sürer: bağlantı ekleme, yeniden bağlama ve iptal bozulmaz).
3. `sync_gate.syncable_accounts`: kiracı bağlamı olmadan "hangi hesaplar senkronlanmalı" sorusunu
   yanıtlayan dar SECURITY DEFINER işlevi (yalnız kimlik, kiracı ve backfill durumu döndürür; sır yok).

Roller migrasyon öncesi superuser tarafından kurulmuş olmalıdır (netkar_owner CREATEROLE değildir):
`app.db.provision.provision_roles` veya `infra/postgres/init/01-roles.sh` (ADR-0005 §6).

Geri alma: grantleri geri alır, `netkar_app` tablo düzeyi SELECT yetkisini geri verir, işlevi ve
tabloları düşürür (YALNIZ bu migrasyonun eklediği veri kaybolur; veritabanı rolleri kümeye aittir
ve bırakılır). Veri silme politikası uygulama içindir; downgrade bilinçli bir operatör işlemidir.

Revision ID: 0006
Revises: 0005
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# marketplace_accounts: şifreli sütunlar HARİÇ sütunlar (netkar_app yalnız bunları okuyabilir).
ACCOUNT_PUBLIC_COLUMNS = (
    "id, tenant_id, platform, seller_id, api_key_last4, status, last_validated_at, "
    "created_by, created_at, updated_at, revoked_at"
)

# Hesap bağlı veri tabloları: (ad, worker yazabilir mi). product_costs kullanıcı verisidir, worker yalnız okur.
DATA_TABLES = (
    "products",
    "product_costs",
    "orders",
    "order_lines",
    "returns",
    "financial_transactions",
    "cargo_invoice_items",
    "sync_runs",
    "sync_cursors",
)

NUM = "numeric(18,6)"
RATE = "numeric(9,4)"


def _fk_account(table: str) -> str:
    """Hesap ve kiracı tutarlılığı: hesap başka kiracıya ait bir satıra bağlanamaz."""
    return (
        f"CONSTRAINT fk_{table}_account FOREIGN KEY (marketplace_account_id, tenant_id) "
        "REFERENCES marketplace_accounts (id, tenant_id)"
    )


def _common(table: str) -> str:
    return f"""
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        {_fk_account(table)}"""


UPGRADE_SQL = [
    # ---- Rollerin varlığı (migrasyon öncesi kurulmalıdır) -----------------------------------
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netkar_worker')
           OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'netkar_sync_gate') THEN
            RAISE EXCEPTION 'netkar_worker ve netkar_sync_gate rolleri yok: migrasyondan once '
                'app.db.provision.provision_roles veya infra/postgres/init/01-roles.sh calistirin (ADR-0005 6)';
        END IF;
    END
    $$
    """,
    # hesap + kiracı bileşik başvurusu için tekil kısıt
    "ALTER TABLE marketplace_accounts ADD CONSTRAINT uq_marketplace_accounts_id_tenant UNIQUE (id, tenant_id)",
    # ---- products ---------------------------------------------------------------------------
    f"""
    CREATE TABLE products ({_common("products")},
        barcode text NOT NULL CHECK (char_length(barcode) BETWEEN 1 AND 200),
        stock_code text,
        content_id bigint,
        product_main_id text,
        title text,
        category_id bigint,
        category_name text,
        vat_rate {RATE} CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 100),
        commission_rate {RATE} CHECK (commission_rate IS NULL OR commission_rate BETWEEN 0 AND 100),
        -- Ürün kartındaki birim desi (kargo dağıtım ağırlığı, K09): Trendyol vermez, kullanıcı girer.
        unit_desi numeric(12,4) CHECK (unit_desi IS NULL OR unit_desi >= 0),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_products_account_barcode UNIQUE (marketplace_account_id, barcode)
    )
    """,
    "CREATE INDEX ix_products_tenant_account ON products (tenant_id, marketplace_account_id)",
    "CREATE INDEX ix_products_account_stock_code ON products (marketplace_account_id, stock_code)",
    # ---- product_costs (boş başlar; kullanıcı girer) ----------------------------------------
    f"""
    CREATE TABLE product_costs ({_common("product_costs")},
        barcode text NOT NULL CHECK (char_length(barcode) BETWEEN 1 AND 200),
        valid_from date NOT NULL,
        unit_cost_excl_vat {NUM} NOT NULL CHECK (unit_cost_excl_vat >= 0),
        vat_rate {RATE} NOT NULL CHECK (vat_rate BETWEEN 0 AND 100),
        entered_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_product_costs_account_barcode_from UNIQUE (marketplace_account_id, barcode, valid_from)
    )
    """,
    "CREATE INDEX ix_product_costs_tenant_account ON product_costs (tenant_id, marketplace_account_id)",
    # ---- orders (Trendyol sipariş PAKETİ başına bir satır; müşteri verisi yok) ----------------
    f"""
    CREATE TABLE orders ({_common("orders")},
        order_number text NOT NULL,
        shipment_package_id bigint NOT NULL,
        ordered_at timestamptz NOT NULL,
        last_modified_at timestamptz,
        status text NOT NULL DEFAULT 'Unknown',
        carrier text,
        cargo_tracking_number text,
        cargo_deci numeric(12,4),
        deci numeric(12,4),
        who_pays smallint,
        commercial boolean,
        -- Yalnız il (KVKK/EK-6: açık adres, ad, telefon, TCKN, e-posta TUTULMAZ).
        province text,
        province_code integer,
        -- Takma adlı müşteri anahtarı (tuzlu HMAC). Hukuk onayına (K-N07/16) kadar BOŞ kalır (ADR-0005 §8).
        customer_key text,
        package_gross_amount {NUM},
        package_seller_discount {NUM},
        package_ty_discount {NUM},
        package_total_price {NUM},
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_orders_account_package UNIQUE (marketplace_account_id, shipment_package_id),
        CONSTRAINT uq_orders_id_tenant UNIQUE (id, tenant_id)
    )
    """,
    "CREATE INDEX ix_orders_tenant_account_ordered ON orders (tenant_id, marketplace_account_id, ordered_at)",
    "CREATE INDEX ix_orders_account_order_number ON orders (marketplace_account_id, order_number)",
    "CREATE INDEX ix_orders_account_status ON orders (marketplace_account_id, status)",
    # ---- order_lines ------------------------------------------------------------------------
    f"""
    CREATE TABLE order_lines ({_common("order_lines")},
        order_id uuid NOT NULL,
        line_id bigint NOT NULL,
        barcode text NOT NULL CHECK (char_length(barcode) BETWEEN 1 AND 200),
        stock_code text,
        quantity integer NOT NULL CHECK (quantity >= 1),
        -- Trendyol lineGrossAmount: indirimsiz BİRİM brüt fiyat (KDV dahil); motor birim olarak okur.
        line_gross_amount {NUM} NOT NULL,
        -- Satır alanları birim ORTALAMASIDIR (docs/12 K03); gerçek değerler items içindedir.
        line_seller_discount {NUM} NOT NULL DEFAULT 0,
        line_ty_discount {NUM} NOT NULL DEFAULT 0,
        vat_rate {RATE} CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 100),
        commission_rate {RATE} CHECK (commission_rate IS NULL OR commission_rate BETWEEN 0 AND 100),
        status text,
        -- discountDetails[] dizisi: her eleman id, seller_discount, ty_discount alanlı bir nesnedir (metin tutar)
        items jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(items) = 'array'),
        -- Paket güncellemesinde payload'da artık olmayan satır silinmez, işaretlenir (veri silme yok).
        removed_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT fk_order_lines_order FOREIGN KEY (order_id, tenant_id) REFERENCES orders (id, tenant_id),
        CONSTRAINT uq_order_lines_order_line UNIQUE (order_id, line_id)
    )
    """,
    "CREATE INDEX ix_order_lines_tenant_account ON order_lines (tenant_id, marketplace_account_id)",
    "CREATE INDEX ix_order_lines_order ON order_lines (order_id)",
    "CREATE INDEX ix_order_lines_account_barcode ON order_lines (marketplace_account_id, barcode)",
    # ---- returns (iade KALEMİ başına bir satır) -----------------------------------------------
    f"""
    CREATE TABLE returns ({_common("returns")},
        claim_id text NOT NULL,
        claim_item_id text NOT NULL,
        order_number text,
        shipment_package_id bigint,
        order_line_id bigint,
        order_line_item_id text,
        barcode text,
        reason_code text,
        status text,
        claim_date timestamptz,
        last_modified_at timestamptz,
        auto_accepted boolean,
        accepted_by_seller boolean,
        -- Kullanıcı işareti (K10): False ise ürün satılamaz. Senkron bu sütuna ASLA dokunmaz.
        returned_to_stock boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_returns_account_claim_item UNIQUE (marketplace_account_id, claim_id, claim_item_id)
    )
    """,
    "CREATE INDEX ix_returns_tenant_account ON returns (tenant_id, marketplace_account_id)",
    "CREATE INDEX ix_returns_account_order_number ON returns (marketplace_account_id, order_number)",
    # ---- financial_transactions (cari hesap ekstresi) -----------------------------------------
    f"""
    CREATE TABLE financial_transactions ({_common("financial_transactions")},
        source text NOT NULL CHECK (source IN ('settlements', 'other_financials')),
        -- Motorun çektiği istek tipi (K05) ve alt tipi ('' = yok): sınıflandırma bunlara göre yapılır.
        request_type text NOT NULL,
        request_sub_type text NOT NULL DEFAULT '',
        transaction_id text NOT NULL,
        type_text text,
        description text CHECK (description IS NULL OR char_length(description) <= 1000),
        transaction_date timestamptz,
        order_date timestamptz,
        payment_date timestamptz,
        barcode text,
        order_number text,
        shipment_package_id bigint,
        payment_order_id bigint,
        receipt_id bigint,
        debt {NUM} NOT NULL DEFAULT 0,
        credit {NUM} NOT NULL DEFAULT 0,
        commission_rate {RATE},
        commission_amount {NUM},
        seller_revenue {NUM},
        commission_invoice_serial_number text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_financial_transactions_natural
            UNIQUE (marketplace_account_id, source, request_type, request_sub_type, transaction_id)
    )
    """,
    "CREATE INDEX ix_financial_tx_tenant_account_date "
    "ON financial_transactions (tenant_id, marketplace_account_id, transaction_date)",
    "CREATE INDEX ix_financial_tx_account_order ON financial_transactions (marketplace_account_id, order_number)",
    "CREATE INDEX ix_financial_tx_account_payment_order "
    "ON financial_transactions (marketplace_account_id, payment_order_id)",
    # ---- cargo_invoice_items ----------------------------------------------------------------
    f"""
    CREATE TABLE cargo_invoice_items ({_common("cargo_invoice_items")},
        invoice_serial_number text NOT NULL,
        -- Kalemin kimliği: (tip, koli, sipariş, tutar, desi) özeti + aynı özetin sıra numarası (ADR-0005 §2).
        item_key text NOT NULL,
        shipment_package_type text,
        parcel_unique_id bigint,
        order_number text,
        amount {NUM} NOT NULL,
        desi integer,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_cargo_invoice_items_natural UNIQUE (marketplace_account_id, invoice_serial_number, item_key)
    )
    """,
    "CREATE INDEX ix_cargo_items_tenant_account ON cargo_invoice_items (tenant_id, marketplace_account_id)",
    "CREATE INDEX ix_cargo_items_account_order ON cargo_invoice_items (marketplace_account_id, order_number)",
    # ---- sync_runs (gövde YOK: yalnız sayaç, pencere ve hata sınıfı) ------------------------
    f"""
    CREATE TABLE sync_runs ({_common("sync_runs")},
        run_group_id uuid NOT NULL,
        kind text NOT NULL CHECK (kind IN ('backfill', 'incremental')),
        source text NOT NULL CHECK (source IN
            ('orders', 'claims', 'products', 'settlements', 'other_financials', 'cargo_invoices')),
        window_start timestamptz,
        window_end timestamptz,
        status text NOT NULL CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
        windows_total integer NOT NULL DEFAULT 0,
        windows_done integer NOT NULL DEFAULT 0,
        fetched_count integer NOT NULL DEFAULT 0,
        upserted_count integer NOT NULL DEFAULT 0,
        skipped_count integer NOT NULL DEFAULT 0,
        error_class text CHECK (error_class IS NULL OR char_length(error_class) <= 40),
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_sync_runs_failed_has_class CHECK (status <> 'failed' OR error_class IS NOT NULL)
    )
    """,
    "CREATE INDEX ix_sync_runs_tenant_account_started "
    "ON sync_runs (tenant_id, marketplace_account_id, started_at DESC)",
    "CREATE INDEX ix_sync_runs_account_source_started "
    "ON sync_runs (marketplace_account_id, source, started_at DESC)",
    # ---- sync_cursors (kaynak başına son başarılı pencere) -------------------------------------
    """
    CREATE TABLE sync_cursors (
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        marketplace_account_id uuid NOT NULL,
        source text NOT NULL CHECK (source IN
            ('orders', 'claims', 'products', 'settlements', 'other_financials', 'cargo_invoices')),
        -- Bu ana kadar (dahil) her şey yazıldı: son başarıyla tamamlanan pencerenin bitişi.
        watermark timestamptz NOT NULL,
        last_window_start timestamptz,
        backfill_completed_at timestamptz,
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT pk_sync_cursors PRIMARY KEY (marketplace_account_id, source),
        CONSTRAINT fk_sync_cursors_account FOREIGN KEY (marketplace_account_id, tenant_id)
            REFERENCES marketplace_accounts (id, tenant_id)
    )
    """,
    "CREATE INDEX ix_sync_cursors_tenant ON sync_cursors (tenant_id)",
    # ---- RLS: ENABLE + FORCE + kiracı politikası -------------------------------------------
    *[
        stmt
        for t in DATA_TABLES
        for stmt in (
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
            f"WITH CHECK (tenant_id = {TENANT_EXPR})",
        )
    ],
    # ---- Yetkiler: netkar_app (API) ---------------------------------------------------------
    *[f"GRANT SELECT ON {t} TO netkar_app" for t in DATA_TABLES],
    # Maliyeti kullanıcı girer (Excel içe aktarma sonraki tur). DELETE yok: düzeltme yeni kayıttır.
    "GRANT INSERT, UPDATE ON product_costs TO netkar_app",
    # Kullanıcı işareti (K10): iade kalemi stoğa döndü mü.
    "GRANT UPDATE (returned_to_stock, updated_at) ON returns TO netkar_app",
    # ---- Yetkiler: netkar_worker (senkron) --------------------------------------------------
    *[f"GRANT SELECT ON {t} TO netkar_worker" for t in DATA_TABLES],
    *[f"GRANT INSERT, UPDATE ON {t} TO netkar_worker" for t in DATA_TABLES if t != "product_costs"],
    # ---- D-05: şifreli sütunlar yalnız worker'a okunur --------------------------------------
    "REVOKE SELECT ON marketplace_accounts FROM netkar_app",
    f"GRANT SELECT ({ACCOUNT_PUBLIC_COLUMNS}) ON marketplace_accounts TO netkar_app",
    "GRANT SELECT ON marketplace_accounts TO netkar_worker",
    # Worker yalnız geçersizleştirir (401/403): durum ve güncelleme zamanı.
    "GRANT UPDATE (status, updated_at) ON marketplace_accounts TO netkar_worker",
    # Denetim izi (yalnız ekleme) ve rate limit temizliği (periyodik görev worker'da çalışır).
    "GRANT SELECT, INSERT ON audit_log TO netkar_worker",
    "GRANT SELECT, DELETE ON rate_limits TO netkar_worker",
    # procrastinate: worker kuyruğu işletir (netkar_app yalnız iş ekler, 0002 grantleri sürer).
    """
    DO $$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.relname, c.relkind FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relname LIKE 'procrastinate\\_%' AND c.relkind IN ('r', 'S')
        LOOP
            IF r.relkind = 'r' THEN
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO netkar_worker', r.relname);
            ELSE
                EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE public.%I TO netkar_worker', r.relname);
            END IF;
        END LOOP;
    END
    $$
    """,
    # ---- sync_gate: kiracı bağlamı olmadan "hangi hesaplar senkronlanmalı" ----------------------
    "GRANT SELECT (id, tenant_id, status, created_at) ON marketplace_accounts TO netkar_sync_gate",
    "GRANT SELECT (marketplace_account_id, source, backfill_completed_at) ON sync_cursors TO netkar_sync_gate",
    # Yalnız okuma ve yalnız bu rol için açık, adlandırılmış politikalar (auth_gate deseni).
    "CREATE POLICY sync_gate_path ON marketplace_accounts FOR SELECT TO netkar_sync_gate "
    "USING (status = 'active')",
    "CREATE POLICY sync_gate_path ON sync_cursors FOR SELECT TO netkar_sync_gate USING (true)",
    "CREATE SCHEMA sync_gate AUTHORIZATION netkar_sync_gate",
    "SET LOCAL ROLE netkar_sync_gate",
    "REVOKE ALL ON SCHEMA sync_gate FROM PUBLIC",
    "GRANT USAGE ON SCHEMA sync_gate TO netkar_worker",
    """
    CREATE FUNCTION sync_gate.syncable_accounts(p_account_id uuid DEFAULT NULL)
    RETURNS TABLE (tenant_id uuid, account_id uuid, backfilled_sources text[])
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        SELECT a.tenant_id, a.id,
               ARRAY(SELECT c.source FROM public.sync_cursors c
                     WHERE c.marketplace_account_id = a.id AND c.backfill_completed_at IS NOT NULL
                     ORDER BY c.source)
        FROM public.marketplace_accounts a
        WHERE a.status = 'active' AND (p_account_id IS NULL OR a.id = p_account_id)
        ORDER BY a.created_at, a.id
    $$
    """,
    "REVOKE ALL ON FUNCTION sync_gate.syncable_accounts(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION sync_gate.syncable_accounts(uuid) TO netkar_worker",
    "RESET ROLE",
]

# Downgrade: önce yetkiler ve işlev, sonra tablolar. Roller kümeye aittir, bırakılır.
DOWNGRADE_SQL = [
    "SET LOCAL ROLE netkar_sync_gate",
    "DROP SCHEMA IF EXISTS sync_gate CASCADE",
    "RESET ROLE",
    "DROP POLICY IF EXISTS sync_gate_path ON marketplace_accounts",
    "REVOKE ALL ON marketplace_accounts FROM netkar_sync_gate",
    "REVOKE UPDATE (status, updated_at) ON marketplace_accounts FROM netkar_worker",
    "REVOKE ALL ON marketplace_accounts FROM netkar_worker",
    # 0004/0005 durumu: netkar_app tablo düzeyinde SELECT (şifreli sütunlar dahil) sahibiydi.
    f"REVOKE SELECT ({ACCOUNT_PUBLIC_COLUMNS}) ON marketplace_accounts FROM netkar_app",
    "GRANT SELECT ON marketplace_accounts TO netkar_app",
    "REVOKE ALL ON audit_log FROM netkar_worker",
    "REVOKE ALL ON rate_limits FROM netkar_worker",
    """
    DO $$
    DECLARE
        r record;
    BEGIN
        FOR r IN SELECT c.relname, c.relkind FROM pg_class c
                 JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = 'public' AND c.relname LIKE 'procrastinate\\_%' AND c.relkind IN ('r', 'S')
        LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM netkar_worker', r.relname);
        END LOOP;
    END
    $$
    """,
    *[f"DROP TABLE IF EXISTS {t} CASCADE" for t in reversed(DATA_TABLES)],
    "ALTER TABLE marketplace_accounts DROP CONSTRAINT IF EXISTS uq_marketplace_accounts_id_tenant",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
