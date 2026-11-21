"""Rapor veri sürümü tekilleştirmesi: GUC yerine xid8 işareti (denetim 2026-11-12 OK-01, OK-09).

0012 tetikleyicisi "işlem başına hesap başına bir artış" kuralını özel GUC `netkar.rdr_<hesap>` ile
uyguluyordu. Noktalı (özel) GUC'ler her rol için USERSET'tir: `netkar_app` ya da `netkar_worker` oturumunda
oturum düzeyinde `SET netkar.rdr_<hex> = '1'` çalıştırılırsa o bağlantıdaki bütün yazımlar sayacı artırmaz
ve önbellek geçersizleştirmesi sessizce kapanırdı.

Bu migrasyon (geri alınabilir):

- `report_data_revisions.last_xact xid8`: sayacı SON artıran işlem. Sütunu istemci yazamaz (uygulama
  rollerinde yalnız SELECT vardır); tek yazar SECURITY DEFINER tetikleyici işlevidir. `pg_current_xact_id()`
  en üst düzey işlem kimliğidir (SAVEPOINT değiştirmez, 64 bit olduğundan sarmalama yoktur), 0010'daki
  `revision_xact` ile aynı desen.
- İşlev gövdesi: `INSERT ... ON CONFLICT DO UPDATE SET revision = revision + 1, last_xact = ... WHERE
  last_xact IS DISTINCT FROM pg_current_xact_id()`. Aynı işlemin ikinci ve sonraki tetiklemeleri koşulu
  sağlamaz, satıra dokunmaz. GUC tamamen kalktı: oturum ayarıyla artış bastırılamaz.
  Eşzamanlı yazarlarda sayaç kaybı olmaz (satır kilidi; bekleyen işlem güncel satırı koşulla yeniden okur,
  kimliği kendisinden farklı olduğu için artırır).
- `owner_counter` politikası `TO CURRENT_USER` yerine açıkça `TO netkar_owner` (OK-09): migrasyon süper
  kullanıcıyla çalışsa da politika doğru role bağlanır. (0011'deki `OWNER_ROLE` ile aynı ad.)
- SECURITY DEFINER, sabit `search_path = pg_catalog, public`, tam nitelikli adlar, ENABLE + FORCE RLS,
  `netkar_app` yalnız SELECT, `netkar_worker` yetkisiz kalır (hiçbiri değişmez).

0013 `upgrade()` başında tablo sahibini doğrular (DK-12, `TABLE_OWNER_GUARD`); sahip `netkar_owner` değilse
hiçbir değişiklik yapmadan durur. 0014'teki tablo+işlev doğrulaması savunma katmanı olarak KALIR: 0013'ün
henüz uygulandığı (guard'sız sürümle çalışmış) ortamları ve sonradan bozulan sahipliği yakalar; iki kontrol
farklı kümeyi denetler (0013 yalnız tablo, 0014 tablo ve işlev), bu yüzden ortak yardımcı yerine her
migrasyonda bağımsız tutuldu (migrasyonlar birbirinin koduna bağlanmasın).

İşlev sahibi `ALTER FUNCTION ... OWNER TO netkar_owner` ile sabitlenir (DK-03); tablo sahipliği ise bu
migrasyonda DEĞİŞMEZ, 0014 tablo ve işlev sahibinin `netkar_owner` olduğunu doğrular (DK-09).

Geri alma: işlev 0012 gövdesine (GUC'li) döner, politika `TO netkar_owner` kalır (DK-02: `CURRENT_USER`
geri alma sırasında yanlış role bağlanıp bütün yazımları kırabilirdi; sahip rolle çalıştırıldığında 0012
durumuyla birebir aynıdır), `last_xact` düşer. Veri kaybı yoktur: `revision`
ve satırlar aynen kalır (`last_xact` türetilmiş bir işarettir).

Revision ID: 0013
Revises: 0012
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

FUNCTION = "bump_report_data_revision"
TABLE = "report_data_revisions"
OWNER_ROLE = "netkar_owner"

UPGRADE_FUNCTION = f"""
CREATE OR REPLACE FUNCTION public.{FUNCTION}() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE
    v_tenant uuid;
    v_account uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_tenant := OLD.tenant_id;
        v_account := OLD.marketplace_account_id;
    ELSE
        v_tenant := NEW.tenant_id;
        v_account := NEW.marketplace_account_id;
    END IF;
    -- İşlem başına hesap başına bir artış: sayacı son artıran işlem satırda (last_xact) durur, istemci
    -- oturum ayarıyla bunu bastıramaz. Aynı işlemde ikinci tetiklemede WHERE koşulu sağlanmaz, satır değişmez.
    INSERT INTO public.{TABLE} AS r (marketplace_account_id, tenant_id, revision, last_xact)
    VALUES (v_account, v_tenant, 1, pg_catalog.pg_current_xact_id())
    ON CONFLICT (marketplace_account_id) DO UPDATE
        SET revision = r.revision + 1, last_xact = pg_catalog.pg_current_xact_id()
        WHERE r.last_xact IS DISTINCT FROM pg_catalog.pg_current_xact_id();
    RETURN NULL;
END
$$
"""


TABLE_OWNER_GUARD = f"""
DO $guard$
DECLARE
    v_table_owner name;
BEGIN
    SELECT pg_catalog.pg_get_userbyid(c.relowner) INTO v_table_owner
        FROM pg_catalog.pg_class c
        WHERE c.oid = pg_catalog.to_regclass('public.{TABLE}');
    IF v_table_owner IS DISTINCT FROM '{OWNER_ROLE}' THEN
        RAISE EXCEPTION
            'Sahiplik hatasi: public.{TABLE} sahibi=% (beklenen: {OWNER_ROLE}). Super kullanici ile '
            '"ALTER TABLE public.{TABLE} OWNER TO {OWNER_ROLE};" calistirip migrasyonu yeniden baslatin. '
            'Migrasyonlari her zaman {OWNER_ROLE} rolu ile calistirin.',
            coalesce(v_table_owner, '(yok)')
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END
$guard$
"""


def _migration_0012():  # type: ignore[no-untyped-def]
    """0012 gövdelerini (downgrade için) dosyadan yükler; sürüm numarası modül adı olamaz."""
    path = Path(__file__).with_name("0012_report_data_revision.py")
    spec = importlib.util.spec_from_file_location("_netkar_migration_0012", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    # Ön koşul (DK-12): ALTER FUNCTION işlev sahibini `netkar_owner` yapıp COMMIT ETMEDEN önce tablo sahibi
    # doğrulanır. Tablo başka bir rolün (ör. 0012'yi çalıştıran süper kullanıcı) ise `netkar_owner` sayaca
    # yazamaz ve ertelenmiş tetikleyici COMMIT'te bütün motor girdisi yazımlarını düşürürdü; burada durmak
    # sahipliği değiştirmeden ve sürümü 0012'de bırakarak güvenlidir. İşlev sahibi BİLEREK denetlenmez: onu
    # düzelten bu migrasyondur (0012 süper kullanıcıyla çalıştıysa işlev başta süper kullanıcınındır).
    op.execute(TABLE_OWNER_GUARD)
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN last_xact xid8")
    op.execute(UPGRADE_FUNCTION)
    # İşlev sahibi açıkça sabitlenir (DK-03): migrasyon başka bir rolle çalışsa da SECURITY DEFINER işlev
    # süper kullanıcı ya da yanlış rol yetkisiyle değil, FORCE RLS altındaki `netkar_owner` ile çalışır.
    op.execute(f"ALTER FUNCTION public.{FUNCTION}() OWNER TO {OWNER_ROLE}")
    op.execute(f"DROP POLICY owner_counter ON {TABLE}")
    op.execute(f"CREATE POLICY owner_counter ON {TABLE} FOR ALL TO {OWNER_ROLE} USING (true) WITH CHECK (true)")


def downgrade() -> None:
    m = _migration_0012()
    # 0012'nin işlev gövdesi (UPGRADE_SQL içindeki CREATE FUNCTION) aynen geri yüklenir.
    create = next(s for s in m.UPGRADE_SQL if "CREATE FUNCTION" in s)
    op.execute(create.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute(f"DROP POLICY owner_counter ON {TABLE}")
    op.execute(f"CREATE POLICY owner_counter ON {TABLE} FOR ALL TO {OWNER_ROLE} USING (true) WITH CHECK (true)")
    op.execute(f"ALTER TABLE {TABLE} DROP COLUMN last_xact")
