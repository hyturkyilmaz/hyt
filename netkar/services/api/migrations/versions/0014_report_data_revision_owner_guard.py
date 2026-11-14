"""Rapor veri sürümü sahiplik doğrulaması (denetim DK-09).

Sorun: 0012 süper kullanıcıyla çalıştırılmışsa `report_data_revisions` tablosunun sahibi o süper kullanıcıdır.
0013 işlev sahibini `netkar_owner` yapar ama tablo sahipliğine dokunmaz; `netkar_owner` tabloda INSERT/UPDATE/
SELECT yetkisine sahip olmadığından SECURITY DEFINER işlev gövdesi "permission denied" alır. Tetikleyici
ertelenmiş (COMMIT anında çalışır) olduğundan sekiz motor girdisi tablosundaki BÜTÜN yazımlar (senkron,
maliyet içe aktarma, PUT) COMMIT'te düşerdi.

Bu migrasyon yalnız DOĞRULAR: tablo ve işlev sahibi `netkar_owner` değilse açık bir Türkçe hatayla DURUR
(`RAISE EXCEPTION`); veri ya da şema değiştirmez.

Neden `ALTER ... OWNER TO` ile sessizce düzeltmiyoruz (güvenli seçenek: durmak):
  * Nesne sahipliği bir güvenlik sınırıdır. Süper kullanıcı oturumuyla çalışan bir migrasyonun sahipliği
    sessizce devretmesi, hatalı dağıtımı (yanlış rolle migrasyon) fark edilmeden "düzeltir" ve aynı hatanın
    öteki nesnelerde (0011'e kadar olan tablolar, diziler) sürdüğü gizli kalır. Operatör durumu görmelidir.
  * `ALTER ... OWNER TO` için çalıştıran rolün hedef rolün üyesi (ya da süper kullanıcı) olması gerekir;
    değilse zaten başarısız olur. Yani "izin varsa düzelt" dalı ortama göre farklı davranır ve test edilmesi
    zordur; doğrulayıp durmak her ortamda aynı, belirgin sonucu verir.
  * Durmak güvenlidir: DDL işlemlidir, hata migrasyonu geri sarar; sürüm 0013'te kalır, yazım yolları
    (0013 durumunda bile sahip yanlışsa kırık olan) operatör düzeltene dek yeniden denenebilir.
Operatörün yapacağı (hata iletisinde de yazar), süper kullanıcıyla:
    ALTER TABLE public.report_data_revisions OWNER TO netkar_owner;
    ALTER FUNCTION public.bump_report_data_revision() OWNER TO netkar_owner;
ardından `alembic upgrade head` yeniden çalıştırılır.

Geri alma: güvenli no-op (bu migrasyon hiçbir şey değiştirmediği için tam tersi de yoktur).

Revision ID: 0014
Revises: 0013
"""

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

FUNCTION = "bump_report_data_revision"
TABLE = "report_data_revisions"
OWNER_ROLE = "netkar_owner"

GUARD_SQL = f"""
DO $guard$
DECLARE
    v_owner oid;
    v_table_owner name;
    v_func_owner name;
BEGIN
    SELECT oid INTO v_owner FROM pg_catalog.pg_roles WHERE rolname = '{OWNER_ROLE}';
    IF v_owner IS NULL THEN
        RAISE EXCEPTION 'Rol {OWNER_ROLE} bulunamadi; rapor veri surumu sayaci icin bu rol gerekli.';
    END IF;
    SELECT pg_catalog.pg_get_userbyid(c.relowner) INTO v_table_owner
        FROM pg_catalog.pg_class c
        WHERE c.oid = pg_catalog.to_regclass('public.{TABLE}');
    SELECT pg_catalog.pg_get_userbyid(p.proowner) INTO v_func_owner
        FROM pg_catalog.pg_proc p
        WHERE p.oid = pg_catalog.to_regprocedure('public.{FUNCTION}()');
    IF v_table_owner IS DISTINCT FROM '{OWNER_ROLE}' OR v_func_owner IS DISTINCT FROM '{OWNER_ROLE}' THEN
        RAISE EXCEPTION
            'Sahiplik hatasi: public.{TABLE} sahibi=%, public.{FUNCTION}() sahibi=% (beklenen: {OWNER_ROLE}). '
            'Bu haliyle sekiz motor girdisi tablosundaki yazimlar COMMIT aninda duser. Yapilacak: surucu '
            'kullanici ile "ALTER TABLE public.{TABLE} OWNER TO {OWNER_ROLE}; '
            'ALTER FUNCTION public.{FUNCTION}() OWNER TO {OWNER_ROLE};" calistirip migrasyonu yeniden '
            'baslatin. Migrasyonlari her zaman {OWNER_ROLE} rolu ile calistirin.',
            coalesce(v_table_owner, '(yok)'), coalesce(v_func_owner, '(yok)')
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END
$guard$
"""


def upgrade() -> None:
    op.execute(GUARD_SQL)


def downgrade() -> None:
    """Doğrulama migrasyonu hiçbir şey değiştirmediği için geri alınacak bir şey yoktur (güvenli no-op)."""
