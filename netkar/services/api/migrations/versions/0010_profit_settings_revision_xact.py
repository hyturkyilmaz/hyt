"""Ayar sayacına işlem bağı ve tekdüzelik (kapanış denetimi 11 Kasım 2026: YK-01, YK-05).

0009 sıra kuralları satır sürümünün sayaca EŞİT olmasına bakıyordu ama sayacın BU işlemde artırıldığını
denetlemiyordu; üstelik `netkar_app` sayacı serbestçe yazabiliyordu. İki yol açıktı (PoC A ve B): sayaç
artırılmadan yayımlanmış sürüme satır eklemek ve sayacı geri sarıp geçmiş sürüme satır eklemek.

Bu migrasyon (geri alınabilir):

- `profit_settings.revision_xact xid8`: SAYACIN SON ARTIRILDIĞI işlem. Sütunu istemci yazamaz; BEFORE
  INSERT OR UPDATE tetikleyicisi her rol için kendisi atar (sürüm arttıysa ya da satır yeniyse
  `pg_current_xact_id()`, değilse eski değer; istemcinin gönderdiği değer yok sayılır).
- Tekdüzelik (yalnız `netkar_app`): INSERT'te sayaç 1; UPDATE'te sayaç ya aynı kalır ya +1 artar. Azalma ve
  atlama reddedilir. Sahip rol ve yönetici (veri doldurma, düzeltme) bu sınırdan muaftır, tetikleyiciyi zaten
  kapatabilirler; onlar için de `revision_xact` doğru atanır.
- 0009'daki üç sıra kuralı (sürümlü tablolara ekleme, kapanış sürümü, günlük kaydı) ek olarak
  `revision_xact = pg_current_xact_id()` ister: satır ancak sayacı BU işlemde artıran akış tarafından yazılabilir.
  Böylece yayımlanmış (eski) bir sürüme satır eklemek, sayaç artırılmadan mümkün olmaz ve sayaç geri sarılamaz.

Neden `xid8`: `pg_current_xact_id()` en üst düzey işlemin kimliğini döndürür; SAVEPOINT (alt işlem) kimliği
değiştirmez, dolayısıyla alt işlem kullanımı kuralı bozmaz. Uygulama zaten SAVEPOINT kullanmaz (`begin_nested`
yok). `xid8` 64 bit olduğundan sarmalama (wraparound) sorunu yoktur; `txid_current()` yerine PostgreSQL 13+
`pg_current_xact_id()` kullanılır. Alternatif (işlem başlangıç zamanı `now()`) aynı işlemde birden çok yazımı
ayıramaz ve eşzamanlı işlemlerde çakışabilir; `xid8` tam bu amaç için vardır.

Dürüst akış (`begin_write` kilitler, `finish_write` sayacı +1 yapıp flush eder, sonra satır, kapanış ve günlük)
bu kuralları zaten sağlar: sayaç artırıldıktan sonra aynı işlemdeki ikinci başlık UPDATE'i (varsayılan desi)
sürümü değiştirmediği için `revision_xact` korunur. Sayacı artırmayan yazımlar (aynı içerik, onaysız geçmiş
değişiklik) satır eklemez.

YK-05 sertleştirmesi: dört tetikleyici işlevine `SET search_path = pg_catalog, public` eklendi (0006'daki
`sync_gate` işlevleriyle tutarlı). İşlevler SECURITY INVOKER olduğu için çağıranın haklarıyla çalışır ve
`search_path` ile yetki yükseltme riski yoktur; ek önlem yalnızca tutarlılık ve ileriye dönük güvencedir.

Geri alma: tetikleyici, işlev ve sütun düşer; üç kural işlevi 0009 gövdesine döner. Veri kaybı yoktur
(`revision_xact` türetilmiş bir denetim sütunudur).

Revision ID: 0010
Revises: 0009
"""

import importlib.util
from pathlib import Path

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

APP_ROLE = "netkar_app"
VERSION_GUARD = "profit_settings_version_guard"
INSERT_GUARD = "profit_settings_insert_guard"
JOURNAL_GUARD = "profit_settings_changes_guard"
HEAD_GUARD = "profit_settings_head_guard"
VERSIONED = ("cargo_tariffs", "service_fee_estimates", "variable_expenses")
SEARCH_PATH = "SET search_path = pg_catalog, public"

HEAD_GUARD_SQL = f"""
CREATE FUNCTION {HEAD_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user = '{APP_ROLE}' AND NEW.revision <> 1 THEN
            RAISE EXCEPTION 'ayar sayaci 1 ile baslar (K42)' USING ERRCODE = 'check_violation';
        END IF;
        NEW.revision_xact := pg_current_xact_id();
    ELSE
        IF current_user = '{APP_ROLE}' AND NEW.revision NOT IN (OLD.revision, OLD.revision + 1) THEN
            RAISE EXCEPTION 'ayar sayaci yalniz bir artabilir, azalamaz (K42)' USING ERRCODE = 'check_violation';
        END IF;
        IF NEW.revision IS DISTINCT FROM OLD.revision THEN
            NEW.revision_xact := pg_current_xact_id();
        ELSE
            NEW.revision_xact := OLD.revision_xact;
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

# Sayaç okuması ve iki şart: sürüm sayaca eşit (0009) VE sayaç bu işlemde artırılmış (0010).
VERSION_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {VERSION_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF OLD.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kapanmis kar ayari surumu degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    IF (to_jsonb(NEW) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision_to', 'ended_at', 'ended_by', 'end_reason']) THEN
        RAISE EXCEPTION 'kar ayari surumunun is alanlari degistirilemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    -- YT-04, YK-01: uygulama rolü satırı yalnız ayar sayacındaki sürümle ve sayacı bu işlemde artırarak kapatır.
    IF current_user = '{APP_ROLE}' AND NEW.revision_to IS NOT NULL THEN
        SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
         WHERE p.marketplace_account_id = OLD.marketplace_account_id AND p.tenant_id = OLD.tenant_id;
        IF head IS NULL OR NEW.revision_to <> head THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz ayar sayacindaki surumle kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
        IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
            RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla kapanabilir (K42)'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END
$$
"""

INSERT_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {INSERT_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.revision_to IS NOT NULL THEN
        RAISE EXCEPTION 'kar ayari satiri bastan kapali eklenemez (K42)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision_from <> head THEN
        RAISE EXCEPTION 'kar ayari satirinin surumu ayar sayacina esit olmali (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'kar ayari satiri yalniz sayaci bu islemde artiran akisla eklenebilir (K42)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

JOURNAL_GUARD_0010 = f"""
CREATE OR REPLACE FUNCTION {JOURNAL_GUARD}() RETURNS trigger LANGUAGE plpgsql {SEARCH_PATH} AS $$
DECLARE
    head bigint;
    head_xact xid8;
BEGIN
    IF current_user <> '{APP_ROLE}' THEN
        RETURN NEW;
    END IF;
    IF NEW.item = 'tasima' THEN
        RAISE EXCEPTION 'tasima kaydini uygulama rolu yazamaz (K44)' USING ERRCODE = 'check_violation';
    END IF;
    SELECT p.revision, p.revision_xact INTO head, head_xact FROM public.profit_settings p
     WHERE p.marketplace_account_id = NEW.marketplace_account_id AND p.tenant_id = NEW.tenant_id;
    IF head IS NULL OR NEW.revision <> head THEN
        RAISE EXCEPTION 'ayar gunlugu kaydinin surumu ayar sayacina esit olmali (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    IF head_xact IS DISTINCT FROM pg_current_xact_id() THEN
        RAISE EXCEPTION 'ayar gunlugu kaydi yalniz sayaci bu islemde artiran akisla yazilabilir (K44)'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""


def _migration_0009():  # type: ignore[no-untyped-def]
    """0009 gövdelerini (downgrade için) dosyadan yükler; sürüm numarası modül adı olamaz."""
    path = Path(__file__).with_name("0009_profit_settings_history_hardening.py")
    spec = importlib.util.spec_from_file_location("_netkar_migration_0009", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def upgrade() -> None:
    op.execute("ALTER TABLE profit_settings ADD COLUMN revision_xact xid8")
    op.execute(HEAD_GUARD_SQL)
    op.execute(
        f"CREATE TRIGGER trg_profit_settings_head_guard BEFORE INSERT OR UPDATE ON profit_settings "
        f"FOR EACH ROW EXECUTE FUNCTION {HEAD_GUARD}()"
    )
    for statement in (VERSION_GUARD_0010, INSERT_GUARD_0010, JOURNAL_GUARD_0010):
        op.execute(statement)


def downgrade() -> None:
    m = _migration_0009()
    op.execute(m.VERSION_GUARD_0009)
    op.execute(m.INSERT_GUARD_SQL.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute(m.JOURNAL_GUARD_SQL.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1))
    op.execute("DROP TRIGGER trg_profit_settings_head_guard ON profit_settings")
    op.execute(f"DROP FUNCTION {HEAD_GUARD}()")
    op.execute("ALTER TABLE profit_settings DROP COLUMN revision_xact")
