"""Kâr ayarları: kargo tarifesi, platform hizmet bedeli tahmini, değişken giderler, varsayılan desi.

ADR-0006 §3.2 (docs/12 K33-K36). Dört tablo, hepsi `tenant_id` + `marketplace_account_id` taşır, ENABLE + FORCE
RLS ve `tenant_isolation` politikasıyla korunur (0006 ile aynı kalıp):

- `profit_settings`: hesap başına tek satır; varsayılan desi ve ayar sürüm sayacı (`revision`, her ayar
  yazımında +1, iki yöneticinin sessizce birbirini ezmesini önler).
- `cargo_tariffs`: anlaşma (trendyol | seller) x firma x geçerlilik başlangıcı; kademeler `jsonb` (tutarlar METİN).
- `service_fee_estimates`: platform hizmet bedeli tahmini sürümleri (sipariş başı tutar).
- `variable_expenses`: kullanıcı tanımlı değişken giderler (geçerlilik aralıklı).

Para `numeric(18,6)`, oran `numeric(9,4)`. KDV dahil/hariç giriş biçimi kayıtta saklanır; motora verilirken K02 ile
KDV hariçe çevrilir (uygulama katmanı). Sistem parametreleri (KDV oranları, stopaj, eşikler) tabloda yoktur.

Yetkiler (en az ayrıcalık): `netkar_app` dört tabloda SELECT, INSERT, UPDATE; `cargo_tariffs`,
`service_fee_estimates`, `variable_expenses` için ayrıca DELETE (yanlış girilmiş sürümün silinmesi, `audit_log`
kaydıyla). `profit_settings`'te DELETE yoktur. `netkar_worker` dördünde YALNIZ SELECT (ileride senkron sonrası
uyarı üretimi için; yazamaz). `netkar_sync_gate` erişmez.

Geri alma: yetkileri geri alır ve dört tabloyu düşürür (YALNIZ bu migrasyonun verisi kaybolur; roller kümeye
aittir ve bırakılır). Downgrade bilinçli bir operatör işlemidir.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

TABLES = ("profit_settings", "cargo_tariffs", "service_fee_estimates", "variable_expenses")
# Yanlış sürümün silinebildiği tablolar (profit_settings satırı silinmez).
DELETABLE = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")

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
    # ---- profit_settings: hesap başına tek satır ----------------------------------------------
    f"""
    CREATE TABLE profit_settings ({_common("profit_settings")},
        default_desi numeric(9,2) CHECK (default_desi IS NULL OR (default_desi > 0 AND default_desi <= 1000)),
        -- Her ayar yazımında +1 (aynı işlemde); iki yöneticinin eşzamanlı düzenlemesinde 409 için.
        revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
        updated_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_profit_settings_account UNIQUE (marketplace_account_id)
    )
    """,
    # ---- cargo_tariffs: anlaşma x firma x geçerlilik başlangıcı --------------------------------
    f"""
    CREATE TABLE cargo_tariffs ({_common("cargo_tariffs")},
        agreement text NOT NULL CHECK (agreement IN ('trendyol', 'seller')),
        -- '*' = diğer firmalar yedeği (K34). Boşluk kırpılmış, 1-100 karakter.
        carrier text NOT NULL CHECK (char_length(carrier) BETWEEN 1 AND 100 AND carrier = btrim(carrier)),
        valid_from date NOT NULL,
        price_includes_vat boolean NOT NULL,
        -- [{{"max_desi": "2", "price": "54.00"}}, ...] artan max_desi; tutarlar METİN (ADR-0005 order_lines.items).
        brackets jsonb NOT NULL CHECK (jsonb_typeof(brackets) = 'array'
                                       AND jsonb_array_length(brackets) BETWEEN 1 AND 50),
        entered_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_cargo_tariffs_version UNIQUE (marketplace_account_id, agreement, carrier, valid_from)
    )
    """,
    # ---- service_fee_estimates: sipariş başı platform hizmet bedeli tahmini sürümleri ----------
    f"""
    CREATE TABLE service_fee_estimates ({_common("service_fee_estimates")},
        valid_from date NOT NULL,
        amount {NUM} NOT NULL CHECK (amount >= 0 AND amount <= 10000),
        amount_includes_vat boolean NOT NULL,
        entered_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_service_fee_estimates_version UNIQUE (marketplace_account_id, valid_from)
    )
    """,
    # ---- variable_expenses: kullanıcı tanımlı değişken giderler (K17, K36) ----------------------
    f"""
    CREATE TABLE variable_expenses ({_common("variable_expenses")},
        name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
        kind text NOT NULL CHECK (kind IN ('siparis_basi', 'adet_basi', 'satis_yuzdesi')),
        amount_excl_vat {NUM},
        percent {RATE},
        vat_rate {RATE} NOT NULL CHECK (vat_rate IN (0, 1, 10, 20)),
        valid_from date NOT NULL,
        valid_to date CHECK (valid_to IS NULL OR valid_to >= valid_from),
        entered_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT ck_variable_expenses_kind_amount CHECK (
            (kind = 'satis_yuzdesi' AND percent IS NOT NULL AND percent > 0 AND percent <= 100
                 AND amount_excl_vat IS NULL)
         OR (kind IN ('siparis_basi', 'adet_basi') AND amount_excl_vat IS NOT NULL
                 AND amount_excl_vat >= 0 AND amount_excl_vat <= 100000 AND percent IS NULL))
    )
    """,
    *[f"CREATE INDEX ix_{t}_tenant_account ON {t} (tenant_id, marketplace_account_id)" for t in TABLES],
    # ---- RLS: ENABLE + FORCE + kiracı politikası -------------------------------------------
    *[
        stmt
        for t in TABLES
        for stmt in (
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {t} USING (tenant_id = {TENANT_EXPR}) "
            f"WITH CHECK (tenant_id = {TENANT_EXPR})",
        )
    ],
    # ---- Yetkiler ---------------------------------------------------------------------------
    *[f"GRANT SELECT, INSERT, UPDATE ON {t} TO netkar_app" for t in TABLES],
    *[f"GRANT DELETE ON {t} TO netkar_app" for t in DELETABLE],
    *[f"GRANT SELECT ON {t} TO netkar_worker" for t in TABLES],
]

# Downgrade: önce yetkiler, sonra tablolar. Roller kümeye aittir, bırakılır.
DOWNGRADE_SQL = [
    *[f"REVOKE ALL ON {t} FROM netkar_worker" for t in TABLES],
    *[f"REVOKE ALL ON {t} FROM netkar_app" for t in TABLES],
    *[f"DROP TABLE IF EXISTS {t} CASCADE" for t in reversed(TABLES)],
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
