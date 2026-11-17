"""Kullanım koşulları ve KVKK aydınlatma metni sürüm kaydı + kullanıcı kabul kaydı (TBK m.20-21 ispat notu).

(Trello P1 "S1-S2 güvenlik ve hesap", madde 4; OWASP ASVS L2 V8 veri koruma, KVKK m.4 veri en aza indirme.)

1. `legal_documents`: yayınlanmış belge sürümleri. Tür {terms, privacy_notice}, sürüm kodu, yayın zamanı ve
   belge içeriğinin SHA-256 özeti. Yalnız ÖZET saklanır (içerik metni burada tutulmaz; metin web sayfasındadır
   ve avukat onayı beklemektedir). Satırlar DEĞİŞMEZ: UPDATE ve DELETE tetikleyiciyle engellenir (23514), ayrıca
   uygulama rolüne yalnız SELECT verilir. Yeni sürüm = yeni satır (`python -m app.tools.legal_documents publish`
   ya da yeni migrasyon). "Güncel sürüm", türün `published_at <= now()` olan en yeni satırıdır.
2. `user_legal_acceptances`: kullanıcının hangi belge sürümünü ne zaman kabul ettiği. YALNIZ gerekli alanlar:
   kullanıcı, belge satırı (tür + sürüm + özet buradan gelir) ve kabul zamanı. IP, IP özeti, kullanıcı aracısı
   SAKLANMAZ (veri en aza indirme). Satırlar DEĞİŞMEZ (UPDATE/DELETE tetikleyiciyle engellenir; `netkar_app`
   yalnız SELECT ve INSERT alır). Aynı kullanıcı aynı belgeyi iki kez kaydedemez (UNIQUE).
3. RLS: ikisi de ENABLE + FORCE. `legal_documents` herkese okunur (kamusal bilgi), yazma politikası yalnız
   `netkar_owner` (migrasyon/yayın aracı) için. `user_legal_acceptances` politikası `user_id = app.user_id`
   (mfa_recovery_codes deseni); worker erişemez.
4. Yer tutucu sürüm "taslak-2026-11" her iki tür için eklenir. Özet, belge METNİNİN değil yer tutucunun
   özetidir (`netkar-legal-placeholder:<tür>:<sürüm>`); gerçek metin onaylanınca YENİ sürüm yayınlanır. Hukuki
   metin yazılmadı.

Geri alma: tablolar ve işlevler kaldırılır. Kabul kaydı (ispat verisi) ya da yer tutucu dışı sürüm varsa
downgrade DURUR (0007 deseni); veri kaybını bilerek kabul etmek için NETKAR_ALLOW_LEGAL_DATA_LOSS=1 ve önce
yedek (pg_dump -t user_legal_acceptances -t legal_documents) gerekir.

Revision ID: 0021
Revises: 0020
"""

import hashlib
import os

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

PLACEHOLDER_VERSION = "taslak-2026-11"
ALLOW_DATA_LOSS_ENV = "NETKAR_ALLOW_LEGAL_DATA_LOSS"
_USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _placeholder_digest(doc_type: str) -> str:
    return hashlib.sha256(f"netkar-legal-placeholder:{doc_type}:{PLACEHOLDER_VERSION}".encode()).hexdigest()


_TABLES = [
    """
    CREATE TABLE legal_documents (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        doc_type text NOT NULL CHECK (doc_type IN ('terms', 'privacy_notice')),
        version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
        published_at timestamptz NOT NULL DEFAULT now(),
        content_sha256 text NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
        CONSTRAINT uq_legal_documents_type_version UNIQUE (doc_type, version)
    )
    """,
    """
    CREATE TABLE user_legal_acceptances (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id uuid NOT NULL REFERENCES users (id),
        document_id uuid NOT NULL REFERENCES legal_documents (id),
        accepted_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_user_legal_acceptances_user_document UNIQUE (user_id, document_id)
    )
    """,
    "CREATE INDEX ix_user_legal_acceptances_user_id ON user_legal_acceptances (user_id)",
]

_IMMUTABLE = [
    """
    CREATE FUNCTION public.legal_records_immutable() RETURNS trigger
    LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
    BEGIN
        RAISE EXCEPTION 'hukuki belge ve kabul kayitlari degistirilemez ve silinemez' USING ERRCODE = '23514';
    END
    $$
    """,
    "CREATE TRIGGER legal_documents_immutable BEFORE UPDATE OR DELETE ON legal_documents "
    "FOR EACH ROW EXECUTE FUNCTION public.legal_records_immutable()",
    "CREATE TRIGGER user_legal_acceptances_immutable BEFORE UPDATE OR DELETE ON user_legal_acceptances "
    "FOR EACH ROW EXECUTE FUNCTION public.legal_records_immutable()",
]

_RLS_AND_GRANTS = [
    "ALTER TABLE legal_documents ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE legal_documents FORCE ROW LEVEL SECURITY",
    "CREATE POLICY legal_documents_read ON legal_documents FOR SELECT USING (true)",
    "CREATE POLICY legal_documents_publish ON legal_documents FOR INSERT TO netkar_owner WITH CHECK (true)",
    "ALTER TABLE user_legal_acceptances ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE user_legal_acceptances FORCE ROW LEVEL SECURITY",
    f"CREATE POLICY user_self_read ON user_legal_acceptances FOR SELECT USING (user_id = {_USER_EXPR})",
    f"CREATE POLICY user_self_insert ON user_legal_acceptances FOR INSERT WITH CHECK (user_id = {_USER_EXPR})",
    "GRANT SELECT ON legal_documents TO netkar_app",
    "GRANT SELECT, INSERT ON user_legal_acceptances TO netkar_app",
]


def upgrade() -> None:
    for statement in (*_TABLES, *_IMMUTABLE, *_RLS_AND_GRANTS):
        op.execute(statement)
    for doc_type in ("terms", "privacy_notice"):
        op.execute(
            "INSERT INTO legal_documents (doc_type, version, content_sha256) "
            f"VALUES ('{doc_type}', '{PLACEHOLDER_VERSION}', '{_placeholder_digest(doc_type)}')"
        )


def _guard_evidence() -> None:
    """Kabul kaydı ya da yer tutucu dışı sürüm varsa ve açık onay yoksa downgrade'i durdurur (işlem geri alınır)."""
    bind = op.get_bind()
    # Tablolar FORCE RLS altındadır: sayım için FORCE bu işlemde kapatılır (hata atılırsa işlem geri alınır).
    op.execute("ALTER TABLE user_legal_acceptances NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE legal_documents NO FORCE ROW LEVEL SECURITY")
    accepted = int(bind.exec_driver_sql("SELECT count(*) FROM user_legal_acceptances").scalar_one())
    published = int(
        bind.exec_driver_sql(
            f"SELECT count(*) FROM legal_documents WHERE version <> '{PLACEHOLDER_VERSION}'"
        ).scalar_one()
    )
    if (accepted == 0 and published == 0) or os.environ.get(ALLOW_DATA_LOSS_ENV) == "1":
        return
    raise RuntimeError(
        f"0021 downgrade DURDURULDU: hukuki kayıt var (kabul kaydı: {accepted}, yer tutucu dışı belge sürümü: "
        f"{published}). Bu kayıtlar ispat verisidir (TBK m.20-21) ve geri getirilemez. Önce yedek alın "
        "(pg_dump -t user_legal_acceptances -t legal_documents). Veri kaybını bilerek kabul ediyorsanız komutu "
        f"{ALLOW_DATA_LOSS_ENV}=1 ortam değişkeniyle yeniden çalıştırın."
    )


def downgrade() -> None:
    _guard_evidence()
    # Tetikleyiciler tablolarla birlikte düşer; DROP TABLE satır silme tetikleyicisini çalıştırmaz.
    op.execute("DROP TABLE IF EXISTS user_legal_acceptances")
    op.execute("DROP TABLE IF EXISTS legal_documents")
    op.execute("DROP FUNCTION IF EXISTS public.legal_records_immutable()")
