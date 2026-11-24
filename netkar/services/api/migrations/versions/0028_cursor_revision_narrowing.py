"""Rapor veri sürümü: imleç ilerlemesi sayacı artırmasın (senkron gereksiz önbellek geçersizleştirmesi).

Sorun: 0012, `sync_cursors` tablosuna da `INSERT OR UPDATE OR DELETE ... FOR EACH ROW` sürüm tetikleyicisi
koymuştu. Senkron her pencerede ve her kaynak tamamlanışında imleci ilerletir (`watermark = pencere sonu ya da
şimdi`, `last_window_start`, `updated_at`: her turda DEĞİŞİR). Bu yüzden veri hiç değişmese bile her senkron
turu hesabın sayacını artırıyor, rapor önbelleği boşuna geçersizleşiyor ve uyarı değerlendirme anahtarı
(hesap, gün, VERİ SÜRÜMÜ, ayar sürümü, kural sürümü) her turda yeniden doğuyordu. İmleç değerlerini rapor ya da
uyarı motoru okumaz (`profit_feed`, `alert_inputs`, `profit_settings` imleç tablosuna hiç dokunmaz); imleç yalnız
senkronun "nereden devam" bilgisidir.

Bu migrasyon (geri alınabilir): `sync_cursors` için tek tetikleyici ikiye ayrılır; öteki yedi tablo ve işlev
(`bump_report_data_revision`) AYNEN kalır.

- `bump_rdr_cursor_insert_delete`: `AFTER INSERT OR DELETE ... FOR EACH ROW` (ertelenmiş kısıt tetikleyicisi).
  İmleç satırının doğması ya da silinmesi kaynağın kapsamının değiştiğini gösterir; sayar.
- `bump_rdr_cursor_update`: `AFTER UPDATE ... FOR EACH ROW WHEN (OLD.backfill_completed_at IS DISTINCT FROM
  NEW.backfill_completed_at)`. Yalnız backfill tamamlanma işareti değişince sayar; `watermark`,
  `last_window_start` ve `updated_at` ilerlemesi saymaz. (`WHEN` içinde `OLD` yalnız UPDATE tetikleyicisinde
  geçerlidir; bu yüzden iki tetikleyici gerekir.)

Etki: aynı veriyle yapılan senkron turu sayacı artırmaz. Veri yazan tablolar (orders, order_lines, returns,
financial_transactions, cargo_invoice_items, products, product_costs) değişmedi: onlar gerçek değişiklikte
sayar. Tetikleyici adları `trg_` ile BAŞLAMAZ (o önek 0012'nin tetikleyicisine ayrılmıştır).

Not (uyarı değerlendirmesi): sayaç artık yalnız gerçek değişiklikte arttığından, kaynak hatadan düzelince
veri sürümü değişmez. Uyarı anahtarı bastırma girdisini (bastırılan kural kümesi) ayrıca içerir ve senkron
sonrası erteleme "kaynak düzeldi" geçişinde de tetiklenir (`SourceOutcome.recovered`).

Geri alma: iki yeni tetikleyici düşer, 0012'nin `trg_bump_report_data_revision` tetikleyicisi `sync_cursors`
üzerine geri konur. Veri ve sayaç değerleri değişmez, hiçbir satır silinmez ya da yazılmaz.

Revision ID: 0028
Revises: 0027
"""

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

FUNCTION = "bump_report_data_revision"
OLD_TRIGGER = "trg_bump_report_data_revision"
TABLE = "sync_cursors"
INSERT_DELETE_TRIGGER = "bump_rdr_cursor_insert_delete"
UPDATE_TRIGGER = "bump_rdr_cursor_update"

UPGRADE_SQL = [
    f"DROP TRIGGER {OLD_TRIGGER} ON {TABLE}",
    f"CREATE CONSTRAINT TRIGGER {INSERT_DELETE_TRIGGER} AFTER INSERT OR DELETE ON {TABLE} "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()",
    f"CREATE CONSTRAINT TRIGGER {UPDATE_TRIGGER} AFTER UPDATE ON {TABLE} "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
    f"WHEN (OLD.backfill_completed_at IS DISTINCT FROM NEW.backfill_completed_at) "
    f"EXECUTE FUNCTION public.{FUNCTION}()",
]

DOWNGRADE_SQL = [
    f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER} ON {TABLE}",
    f"DROP TRIGGER IF EXISTS {INSERT_DELETE_TRIGGER} ON {TABLE}",
    f"CREATE CONSTRAINT TRIGGER {OLD_TRIGGER} AFTER INSERT OR UPDATE OR DELETE ON {TABLE} "
    f"DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION}()",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
