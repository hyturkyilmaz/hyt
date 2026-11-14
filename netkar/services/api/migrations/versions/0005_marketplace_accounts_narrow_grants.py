"""marketplace_accounts: uygulama rolünün UPDATE yetkisini gerekli sütunlara daraltır (S2 D-05).

0004 `GRANT SELECT, INSERT, UPDATE` ile tüm sütunlarda UPDATE verdi; bu, kiracı içinde
`seller_id`, `tenant_id`, `created_by`, `created_at` gibi kimlik ve denetim sütunlarının bir hata
veya enjeksiyonla değiştirilmesine izin verirdi. Burada UPDATE yalnız API akışlarının yazdığı
sütunlara verilir (ekleme/yeniden bağlama/iptal): şifreli sütunlar, son 4 hane, durum,
doğrulama ve güncelleme zamanları, iptal zamanı.

SELECT yetkisi korunur: senkron işçisi şifreli sütunları okuyacaktır (ayrı bir işçi rolü
ertelendi, ADR-0004). API tarafında `find_live_account` bu sütunları artık yüklemez.

Geri alma 0004'teki tablo düzeyi UPDATE yetkisini geri verir; veri değişmez.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

UPDATABLE = (
    "api_key_encrypted, api_secret_encrypted, api_key_last4, status, last_validated_at, updated_at, revoked_at"
)


def upgrade() -> None:
    # Tablo düzeyi REVOKE, sütun düzeyi yetkileri de kaldırır.
    op.execute("REVOKE UPDATE ON marketplace_accounts FROM netkar_app")
    op.execute(f"GRANT UPDATE ({UPDATABLE}) ON marketplace_accounts TO netkar_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE ON marketplace_accounts FROM netkar_app")
    op.execute("GRANT UPDATE ON marketplace_accounts TO netkar_app")
