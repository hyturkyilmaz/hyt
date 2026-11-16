"""Açılış kilidi: ortam ile veritabanı işareti uyuşmuyorsa API ve işçi BAŞLAMAZ (denetim DT-14, DT-21).

`public.deployment_marks.non_production = 'true'` satırı yalnız üretim dışı veritabanlarına yazılır (tohum
betiğinin `mark-non-prod` alt komutu). İki yönlü denetim yapılır:

* `ENVIRONMENT=prod`: satır VARSA açılmaz (staging dökümünün üretime geri yüklenmesi ya da `mark-non-prod`'un
  yanlış sunucuda çalıştırılması sessiz kalmaz). Tablo yoksa (0015 öncesi şema) işaret de olamaz, açılır.
* `ENVIRONMENT=staging` (DT-21): satır YOKSA açılmaz. Staging'e yanlışlıkla üretim veritabanı bağlanırsa
  sıfırlama bağlantıları düz metin outbox'a yazılır ve işçi üretim hesaplarını Trendyol stage ile
  senkronlamaya çalışırdı; bu yüzden staging işaret taşımak ZORUNDADIR. Tablo yoksa da açılmaz.

dev ve test ortamlarında hiçbir sorgu atılmaz. Başka her hata (bağlantı yok, yetki yok, süre aşımı) açılışı
durdurur: doğrulanamayan prod ya da staging açılmaz.
"""

from __future__ import annotations

import asyncio

import psycopg
from psycopg import errors
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

NON_PROD_KEY = "non_production"
# Açılış denetimi uygulanan ortamlar; diğerlerinde (dev, test) hiçbir sorgu atılmaz.
CHECKED_ENVIRONMENTS = frozenset({"staging", "prod"})
# Şema nitelikli (DT-18): rolün search_path'i değişse de denetim yanlış tabloya ya da "tablo yok"a düşmez.
_SQL = "SELECT value FROM public.deployment_marks WHERE key = 'non_production'"
# Açılış denetimi üst süresi (sn): işçideki connect_timeout=10 ile aynı. Aşımda doğrulanamayan ortam açılmaz.
CHECK_TIMEOUT_SECONDS = 10


class NonProductionMarkError(RuntimeError):
    """Ortam ile veritabanı işareti uyuşmuyor (ya da işaret doğrulanamadı)."""


def _unverified(environment: str) -> NonProductionMarkError:
    return NonProductionMarkError(
        f"ENVIRONMENT={environment} iken üretim dışı işareti okunamadı; "
        "veritabanı doğrulanamadığı için başlatılmıyor"
    )


def _refuse_marked() -> NonProductionMarkError:
    return NonProductionMarkError(
        "ENVIRONMENT=prod ama bağlanılan veritabanı üretim dışı olarak işaretli "
        "(deployment_marks.non_production). Yanlış veritabanına mı bağlısınız? Başlatılmıyor."
    )


def _refuse_unmarked() -> NonProductionMarkError:
    return NonProductionMarkError(
        "ENVIRONMENT=staging ama bağlanılan veritabanında üretim dışı işareti yok "
        "(deployment_marks.non_production). Bu veritabanı üretim olabilir; yanlış veritabanına "
        "bağlı olabilirsiniz. Başlatılmıyor. Veritabanı gerçekten staging'e aitse işareti bir kez yazın: "
        "`NETKAR_ENV=staging make mark-non-prod` (önce MARK_ARGS olmadan çalıştırıp sunucu kimliğini "
        "doğrulayın, "
        'sonra MARK_ARGS="--confirm VERITABANI@INSTANCE_ID" ile yazın; ayrıntı: services/api/README.md).'
    )


def _verdict(environment: str, value: str | None) -> None:
    """İşaret değerini ortamla karşılaştırır; uyuşmazlıkta hata fırlatır."""
    marked = value == "true"
    if environment == "prod" and marked:
        raise _refuse_marked()
    if environment == "staging" and not marked:
        raise _refuse_unmarked()


async def assert_not_marked_non_production(engine: AsyncEngine, environment: str) -> None:
    """API açılışı: `engine` ile işareti okur; yalnız `staging` ve `prod` iken çalışır (ad tarihsel)."""
    if environment not in CHECKED_ENVIRONMENTS:
        return
    try:
        # Bağlantı ve sorgu birlikte sınırlanır; erişilemeyen veritabanında açılış asılmaz.
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as conn:
            # Değer bağlı parametreyle verilir (profit.py ile aynı desen); SQL'e metin birleştirilmez.
            await conn.execute(
                text("SELECT set_config('statement_timeout', :v, true)"),
                {"v": f"{CHECK_TIMEOUT_SECONDS}s"},
            )
            value = (await conn.execute(text(_SQL))).scalar_one_or_none()
            await conn.rollback()
    except TimeoutError as exc:
        raise _unverified(environment) from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == errors.UndefinedTable.sqlstate:
            # Tablo yok: prod için işaret de olamaz (açılır); staging için işaret yok demektir (açılmaz).
            _verdict(environment, None)
            return
        raise _unverified(environment) from exc
    _verdict(environment, value)


def assert_not_marked_non_production_sync(conninfo: str, environment: str) -> None:
    """İşçi açılışı (senkron, süreç başında bir kez). Yalnız `staging` ve `prod` iken çalışır."""
    if environment not in CHECKED_ENVIRONMENTS:
        return
    try:
        with psycopg.connect(
            conninfo,
            connect_timeout=CHECK_TIMEOUT_SECONDS,
            # Sorgu da sınırlanır (DT-22): kilit tutan bir migrasyon açılışı süresiz bekletmez.
            options=f"-c statement_timeout={CHECK_TIMEOUT_SECONDS}s",
        ) as conn:
            row = conn.execute(_SQL).fetchone()
    except errors.UndefinedTable:
        _verdict(environment, None)
        return
    except psycopg.Error as exc:
        raise _unverified(environment) from exc
    _verdict(environment, None if row is None else row[0])
