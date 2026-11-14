"""Pazaryeri bağlantıları: şifreli Trendyol API anahtarları, FORCE RLS (kiracı izolasyonu).

marketplace_accounts:
  - api_key_encrypted / api_secret_encrypted: AES-256-GCM ("v1:" önekli); iptalde NULL.
  - api_key_last4: yalnız gösterim için son 4 hane.
  - Durum tutarlılığı CHECK ile garanti: revoked <=> şifreli alanlar NULL ve revoked_at dolu.
  - Tekillik: aynı kiracıda aynı platform + satıcı için en fazla bir İPTAL EDİLMEMİŞ satır.
    İptal edilmiş satırlar geçmiş olarak kalır (veri silme yok) ve aynı satıcı yeniden bağlanabilir.
  - netkar_app için DELETE yetkisi verilmez.

Geri alma tabloyu düşürür (yalnız bu migrasyonun eklediği veri kaybolur).

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

TENANT_EXPR = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

UPGRADE_SQL = [
    """
    CREATE TABLE marketplace_accounts (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants (id),
        platform text NOT NULL CHECK (platform IN ('trendyol')),
        seller_id text NOT NULL CHECK (seller_id ~ '^[1-9][0-9]{0,17}$'),
        api_key_encrypted text,
        api_secret_encrypted text,
        api_key_last4 text CHECK (api_key_last4 IS NULL OR char_length(api_key_last4) = 4),
        status text NOT NULL CHECK (status IN ('active', 'invalid', 'revoked')),
        last_validated_at timestamptz,
        created_by uuid NOT NULL REFERENCES users (id),
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        revoked_at timestamptz,
        CONSTRAINT ck_marketplace_accounts_secret_state CHECK (
            (status = 'revoked' AND api_key_encrypted IS NULL AND api_secret_encrypted IS NULL
                AND revoked_at IS NOT NULL)
            OR (status <> 'revoked' AND api_key_encrypted IS NOT NULL AND api_secret_encrypted IS NOT NULL
                AND revoked_at IS NULL)
        )
    )
    """,
    "CREATE INDEX ix_marketplace_accounts_tenant_id ON marketplace_accounts (tenant_id)",
    "CREATE UNIQUE INDEX uq_marketplace_accounts_live_seller "
    "ON marketplace_accounts (tenant_id, platform, seller_id) WHERE status <> 'revoked'",
    "ALTER TABLE marketplace_accounts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE marketplace_accounts FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY tenant_isolation ON marketplace_accounts USING (tenant_id = {TENANT_EXPR}) "
    f"WITH CHECK (tenant_id = {TENANT_EXPR})",
    "GRANT SELECT, INSERT, UPDATE ON marketplace_accounts TO netkar_app",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_accounts")
