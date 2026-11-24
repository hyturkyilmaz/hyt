"""Uyarı değerlendirmesi: deneme sayacı ve `dropped` sayaç anahtarı (ADR-0009 D4 düzeltme turu).

`alert_evaluations`: `attempt smallint` (1-3, varsayılan 1) eklenir ve tekil anahtar
(hesap, gün, veri sürümü, ayar sürümü, kural sürümü, attempt) olur. `failed` ile kapanan bir anahtar, 3 denemeye
kadar yeni `attempt` satırıyla yeniden denenebilir (kapanmış satır değişmez; her deneme kendi satırıdır).
`attempt` kimlik sütunudur (kapanış tetikleyicisi değişmesini reddeder) ve worker'a INSERT sütun yetkisi verilir.

`alert_counts_is_safe`: `counts` izin listesine `dropped` (günlük olay tavanını aşıp atılan aday sayısı) eklenir.

Geri alma (0025 deseni): ENVIRONMENT=prod iken HER durumda reddedilir; `attempt > 1` satırı varsa
`NETKAR_ALLOW_ALERT_DATA_LOSS=<attempt > 1 satır sayısı>` tam eşleşmelidir (bu satırlar silinir; eski tekil anahtar
yalnız ilk denemeyi tutabilir). Kapanış tetikleyici işlevi 0025 dosyasından okunarak geri yüklenir; `alert_counts_is_safe` genişletilmiş kalır
(`dropped` anahtarlı satırlar silinmez; 0025 downgrade'i işlevi zaten düşürür).

Revision ID: 0026
Revises: 0025
"""

import importlib.util
import os
from pathlib import Path

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

ALLOW_DATA_LOSS_ENV = "NETKAR_ALLOW_ALERT_DATA_LOSS"


def _previous() -> object:
    """0025 modülü (eski işlev gövdeleri için tek doğru kaynak)."""
    path = Path(__file__).with_name("0025_alert_tables.py")
    spec = importlib.util.spec_from_file_location("_alert_tables_0025", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _old_function(name: str) -> str:
    module = _previous()
    candidates = [*module._PAYLOAD_FUNCTIONS, *module._FUNCTIONS]  # type: ignore[attr-defined]
    (text,) = [t for t in candidates if f"FUNCTION public.{name}(" in t]
    return str(text)


def _replace(text: str) -> str:
    return text.replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def _new_guard() -> str:
    old = _old_function("alert_evaluations_guard")
    marker = "OR NEW.started_at IS DISTINCT FROM OLD.started_at THEN"
    assert marker in old
    return _replace(old).replace(
        marker,
        "OR NEW.started_at IS DISTINCT FROM OLD.started_at\n           OR NEW.attempt IS DISTINCT FROM OLD.attempt THEN",
    )


def _new_counts() -> str:
    old = _old_function("alert_counts_is_safe")
    assert "'duration_ms'" in old
    return _replace(old).replace("'duration_ms'", "'duration_ms', 'dropped'")


def upgrade() -> None:
    op.execute(
        "ALTER TABLE alert_evaluations ADD COLUMN attempt smallint NOT NULL DEFAULT 1 "
        "CONSTRAINT ck_alert_evaluations_attempt CHECK (attempt BETWEEN 1 AND 3)"
    )
    op.execute("ALTER TABLE alert_evaluations DROP CONSTRAINT uq_alert_evaluations_key")
    op.execute(
        "ALTER TABLE alert_evaluations ADD CONSTRAINT uq_alert_evaluations_key UNIQUE "
        "(marketplace_account_id, as_of_date, data_revision, settings_revision, rules_version, attempt)"
    )
    op.execute(_new_guard())
    op.execute(_new_counts())
    op.execute("GRANT INSERT (attempt) ON alert_evaluations TO netkar_worker")


def _guard() -> int:
    """Prod'da reddeder; kaybolacak (`attempt > 1`) satır varsa bayrak tam sayıyla eşleşmeli. Sayıyı verir."""
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "prod":
        raise RuntimeError(
            "0026 downgrade REDDEDİLDİ: ENVIRONMENT=prod iken değerlendirme deneme kayıtları geri alınamaz. "
            "Gerekirse önce yedek alıp ayrı, onaylı bir bakım sürecinde ilerleyin."
        )
    bind = op.get_bind()
    op.execute("LOCK TABLE alert_evaluations IN ACCESS EXCLUSIVE MODE")
    op.execute("ALTER TABLE alert_evaluations NO FORCE ROW LEVEL SECURITY")
    total = int(bind.exec_driver_sql("SELECT count(*) FROM alert_evaluations WHERE attempt > 1").scalar_one())
    if total and os.environ.get(ALLOW_DATA_LOSS_ENV) != str(total):
        raise RuntimeError(
            f"0026 downgrade DURDURULDU: alert_evaluations içinde {total} yeniden deneme satırı (attempt > 1) var. "
            f"Önce yedek alın (pg_dump -t alert_evaluations). Kaybı kabul ediyorsanız {ALLOW_DATA_LOSS_ENV}={total} "
            "ile yeniden çalıştırın. Downgrade uygulama (API ve worker) DURDURULMUŞKEN çalıştırılmalı."
        )
    return total


def downgrade() -> None:
    total = _guard()
    if total:
        op.execute("DELETE FROM alert_evaluations WHERE attempt > 1")
    op.execute("ALTER TABLE alert_evaluations FORCE ROW LEVEL SECURITY")
    op.execute("REVOKE INSERT (attempt) ON alert_evaluations FROM netkar_worker")
    op.execute("ALTER TABLE alert_evaluations DROP CONSTRAINT uq_alert_evaluations_key")
    op.execute("ALTER TABLE alert_evaluations DROP COLUMN attempt")
    op.execute(
        "ALTER TABLE alert_evaluations ADD CONSTRAINT uq_alert_evaluations_key UNIQUE "
        "(marketplace_account_id, as_of_date, data_revision, settings_revision, rules_version)"
    )
    op.execute(_replace(_old_function("alert_evaluations_guard")))
    # `alert_counts_is_safe` BİLEREK eski haline döndürülmez: `dropped` anahtarlı `counts` satırları (üst küme izin
    # listesi zararsızdır) eski işlevle CHECK ihlali olurdu ve veri silmeyi gerektirirdi. 0025 downgrade işlevi düşürür.
