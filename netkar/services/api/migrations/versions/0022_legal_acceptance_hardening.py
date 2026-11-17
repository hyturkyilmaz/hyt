"""Kabul kaydı sertleştirmesi: sütun düzeyinde INSERT, sunucu alanları, TRUNCATE engeli, downgrade koruması.

(0021 inceleme turu 1; 0021'e dokunulmaz.)

1. `netkar_app` için `user_legal_acceptances` INSERT yetkisi tablo düzeyinden alınır, yalnız `(user_id, document_id)`
   sütunlarına verilir. `id` ve `accepted_at`'i istemci (uygulama kodu ya da ele geçirilmiş bir bağlantı) veremez;
   BEFORE INSERT tetikleyicisi bunları sunucu üretir (`gen_random_uuid()`, `now()`): kabul zamanı geriye ya da ileriye
   yazılamaz. Tetikleyici tüm rollerde çalışır.
2. İki tabloya BEFORE TRUNCATE FOR EACH STATEMENT tetikleyicisi (23514): `TRUNCATE` (CASCADE dahil) kanıt satırlarını
   silemez. Test ve bakım için `SET session_replication_role = replica` (yalnız superuser) tetikleyiciyi atlar.
3. Downgrade koruması 0021'inkinden sıkıdır ve 0021'in downgrade'inden ÖNCE çalışır (her yol 0022'den geçer):
   - ENVIRONMENT=prod iken HER durumda reddedilir (kanıt defterinin üretimde geri alınması desteklenmez).
   - Kabul kaydı ya da yer tutucu dışı sürüm varsa NETKAR_ALLOW_LEGAL_DATA_LOSS tam olarak
     `accepted=<N>,published=<M>` olmalı (silinecek gerçek sayılar); eşleşmezse durur. "1" artık yetmez.
   Doğrulama geçince 0021'in eski ("1") korumasının aynı süreçte geçmesi için ortam değişkeni süreç içinde "1"e
   çekilir (0021 değiştirilmediği için; yalnız bu alembic sürecini etkiler). Koruma 0022'den 0021'e tek adımlık
   geri almada da çalışır (kayıt kaybı olmasa da tutucu davranır).

Geri alma: tetikleyiciler/işlevler kaldırılır, INSERT yetkisi tablo düzeyine döner. Veri silinmez.

Revision ID: 0022
Revises: 0021
"""

import os

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

ALLOW_DATA_LOSS_ENV = "NETKAR_ALLOW_LEGAL_DATA_LOSS"
PLACEHOLDER_VERSION = "taslak-2026-11"

_UPGRADE = [
    "REVOKE INSERT ON user_legal_acceptances FROM netkar_app",
    "GRANT INSERT (user_id, document_id) ON user_legal_acceptances TO netkar_app",
    """
    CREATE FUNCTION public.user_legal_acceptances_server_fields() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        NEW.id := gen_random_uuid();
        NEW.accepted_at := now();
        RETURN NEW;
    END
    $$
    """,
    "CREATE TRIGGER user_legal_acceptances_server_fields BEFORE INSERT ON user_legal_acceptances "
    "FOR EACH ROW EXECUTE FUNCTION public.user_legal_acceptances_server_fields()",
    # Tetikleyici işlevi yalnız tablo sahibi/superuser çalıştırır; EXECUTE yetkisi tetikleyici için gerekmez.
    """
    CREATE FUNCTION public.legal_records_no_truncate() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        RAISE EXCEPTION 'hukuki belge ve kabul kayitlari TRUNCATE ile silinemez' USING ERRCODE = '23514';
    END
    $$
    """,
    "CREATE TRIGGER legal_documents_no_truncate BEFORE TRUNCATE ON legal_documents "
    "FOR EACH STATEMENT EXECUTE FUNCTION public.legal_records_no_truncate()",
    "CREATE TRIGGER user_legal_acceptances_no_truncate BEFORE TRUNCATE ON user_legal_acceptances "
    "FOR EACH STATEMENT EXECUTE FUNCTION public.legal_records_no_truncate()",
]

_DOWNGRADE = [
    "DROP TRIGGER IF EXISTS user_legal_acceptances_no_truncate ON user_legal_acceptances",
    "DROP TRIGGER IF EXISTS legal_documents_no_truncate ON legal_documents",
    "DROP FUNCTION IF EXISTS public.legal_records_no_truncate()",
    "DROP TRIGGER IF EXISTS user_legal_acceptances_server_fields ON user_legal_acceptances",
    "DROP FUNCTION IF EXISTS public.user_legal_acceptances_server_fields()",
    "REVOKE INSERT (user_id, document_id) ON user_legal_acceptances FROM netkar_app",
    "GRANT INSERT ON user_legal_acceptances TO netkar_app",
]


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def _guard() -> None:
    """Prod'da her durumda reddeder; kayıt varsa bayrak tam sayılarla eşleşmeli (bkz. modül açıklaması)."""
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "prod":
        raise RuntimeError(
            "0022 downgrade REDDEDİLDİ: ENVIRONMENT=prod iken hukuki kanıt defteri geri alınamaz. "
            "Gerekirse önce yedek alıp ayrı, onaylı bir bakım sürecinde ilerleyin."
        )
    bind = op.get_bind()
    # FORCE RLS altında sayım için geçici kapatılır; işlem sonunda (ve hata halinde geri alma ile) yerine konur.
    op.execute("ALTER TABLE user_legal_acceptances NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE legal_documents NO FORCE ROW LEVEL SECURITY")
    accepted = int(bind.exec_driver_sql("SELECT count(*) FROM user_legal_acceptances").scalar_one())
    published = int(
        bind.exec_driver_sql(
            f"SELECT count(*) FROM legal_documents WHERE version <> '{PLACEHOLDER_VERSION}'"
        ).scalar_one()
    )
    op.execute("ALTER TABLE user_legal_acceptances FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE legal_documents FORCE ROW LEVEL SECURITY")
    if accepted == 0 and published == 0:
        return
    expected = f"accepted={accepted},published={published}"
    if os.environ.get(ALLOW_DATA_LOSS_ENV) != expected:
        raise RuntimeError(
            f"0022 downgrade DURDURULDU: hukuki kayıt var (kabul kaydı: {accepted}, yer tutucu dışı belge sürümü: "
            f"{published}). Bu kayıtlar ispat verisidir (TBK m.20-21). Önce yedek alın "
            "(pg_dump -t user_legal_acceptances -t legal_documents). Kaybı bilerek kabul ediyorsanız "
            f"{ALLOW_DATA_LOSS_ENV}={expected} ile yeniden çalıştırın (sayılar değiştiyse yeniden hesaplanır)."
        )
    # 0021'in eski koruması "1" bekler; sayılar doğrulandığı için bu süreçte geçmesine izin verilir.
    os.environ[ALLOW_DATA_LOSS_ENV] = "1"


def downgrade() -> None:
    _guard()
    for statement in _DOWNGRADE:
        op.execute(statement)
