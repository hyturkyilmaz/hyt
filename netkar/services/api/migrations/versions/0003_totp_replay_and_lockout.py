"""TOTP tekrar kullanım koruması ve kaba kuvvet kilidi (denetim O-01, O-02).

users tablosuna üç sütun eklenir:
  totp_last_step     : son başarıyla kullanılan TOTP zaman adımı (aynı veya eski adım reddedilir)
  totp_failed_count  : ardışık başarısız TOTP denemesi
  totp_locked_until  : dolana kadar TOTP girişi reddedilir

Uygulama rolü bu sütunları okuyup yazabilir (RLS: kullanıcı yalnız kendi satırını görür).
Geri alma sütunları kaldırır; yalnız bu migrasyonun eklediği operasyonel durum kaybolur.

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_COLUMNS = "totp_last_step, totp_failed_count, totp_locked_until"


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN totp_last_step bigint")
    op.execute("ALTER TABLE users ADD COLUMN totp_failed_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN totp_locked_until timestamptz")
    op.execute(f"GRANT SELECT ({_COLUMNS}) ON users TO netkar_app")
    op.execute(f"GRANT UPDATE ({_COLUMNS}) ON users TO netkar_app")


def downgrade() -> None:
    # Sütun silinince sütun yetkileri de kalkar.
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_locked_until")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_failed_count")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS totp_last_step")
