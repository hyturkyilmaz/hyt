"""Sunucu kimliği (instance_id) ve `mark_demo_account` için sıkı davranış (demo tohumu denetimi DT-13, DT-15).

1. `deployment_marks.instance_id`: migrasyon anında `gen_random_uuid()` ile BİR KEZ yazılan, sunucuya özgü
   rastgele kimlik. Tohum betiği ve araçlar uygulama, işçi ve yönetici bağlantılarının AYNI sunucuya gittiğini
   bu değerle karşılaştırır. Neden: unix soketinde `inet_server_addr()` ve `inet_server_port()` NULL döner, kimlik
   yalnız veritabanı adına inerdi; aynı soket dizininde başka porta yönlendirilmiş (ör. SSH ile) aynı adlı bir
   veritabanı tüm denetimlerden geçerdi. `instance_id` o sunucunun kendi verisidir, yönlendirmeyle taklit edilemez.
   Satır zaten varsa (elle yazılmışsa) korunur. Yazma yetkisi 0015'teki gibi yalnız süper kullanıcı ve migrasyon
   sahibinde; uygulama ve işçi yalnız okur.

2. `public.mark_demo_account(uuid)`: hiçbir satır güncellenmediyse (kiracı bağlamı yok, hesap başka kiracıda ya da
   yok) artık SESSİZ dönmez, `42704` ile hata verir (`IF NOT FOUND`). Çağıran (tohum) ayrıca `is_demo`'yu
   doğrular. `CREATE OR REPLACE` sahip ve EXECUTE yetkilerini korur (0015'te verilen yetkiler aynen kalır).
   Gövde yalnız bu iki kural dışında 0015 ile aynıdır.

Geri alma: işlev 0015'teki (sessiz dönen) gövdesine döner, `instance_id` satırı silinir. Başka şema nesnesi yok.

Revision ID: 0016
Revises: 0015
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

_GUARD = """
        IF NOT EXISTS (SELECT 1 FROM public.deployment_marks WHERE key = 'non_production' AND value = 'true') THEN
            RAISE EXCEPTION 'bu veritabani uretim disi olarak isaretli degil (deployment_marks.non_production)'
                USING ERRCODE = '42501';
        END IF;
        UPDATE public.marketplace_accounts SET is_demo = true WHERE id = p_account_id;"""

_STRICT_TAIL = """
        IF NOT FOUND THEN
            RAISE EXCEPTION 'demo hesabi isaretlenemedi: hesap yok ya da kiraci baglami bu hesaba ait degil'
                USING ERRCODE = '42704';
        END IF;"""


def _function(tail: str) -> str:
    return f"""
    CREATE OR REPLACE FUNCTION public.mark_demo_account(p_account_id uuid) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    BEGIN{_GUARD}{tail}
    END
    $$
    """


UPGRADE_SQL = [
    "INSERT INTO deployment_marks (key, value) VALUES ('instance_id', gen_random_uuid()::text) "
    "ON CONFLICT (key) DO NOTHING",
    _function(_STRICT_TAIL),
]

DOWNGRADE_SQL = [
    _function(""),
    "DELETE FROM deployment_marks WHERE key = 'instance_id'",
]


def upgrade() -> None:
    for statement in UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_SQL:
        op.execute(statement)
