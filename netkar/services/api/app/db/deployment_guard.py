"""Üretimde "üretim dışı" işaretli veritabanına bağlı açılışı reddeder (demo tohumu denetimi DT-14).

`deployment_marks.non_production = 'true'` satırı yalnız üretim dışı veritabanlarına yazılır (tohum betiğinin
`mark-non-prod` alt komutu). ENVIRONMENT=prod iken API ve işçi bu satırı açılışta okur; satır varsa süreç
BAŞLAMAZ (açık hata): staging dökümünün üretime geri yüklenmesi ya da `mark-non-prod`'un yanlış sunucuda
çalıştırılması sessiz kalmaz. ENVIRONMENT prod değilse hiçbir sorgu atılmaz. Tablo yoksa (0015 öncesi şema)
işaret de olamaz; başka her hata (bağlantı yok, yetki yok) açılışı durdurur: doğrulanamayan üretim açılmaz.
"""

from __future__ import annotations

import psycopg
from psycopg import errors
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

NON_PROD_KEY = "non_production"
_UNVERIFIED = (
    "ENVIRONMENT=prod iken üretim dışı işareti okunamadı; veritabanı doğrulanamadığı için başlatılmıyor"
)
_SQL = "SELECT value FROM deployment_marks WHERE key = 'non_production'"


class NonProductionMarkError(RuntimeError):
    """ENVIRONMENT=prod iken veritabanı üretim dışı işaretli (ya da işaret doğrulanamadı)."""


def _refuse() -> NonProductionMarkError:
    return NonProductionMarkError(
        "ENVIRONMENT=prod ama bağlanılan veritabanı üretim dışı olarak işaretli "
        "(deployment_marks.non_production). Yanlış veritabanına mı bağlısınız? Başlatılmıyor."
    )


async def assert_not_marked_non_production(engine: AsyncEngine, environment: str) -> None:
    """API açılışı: `engine` ile işareti okur. Yalnız `environment == "prod"` iken çalışır."""
    if environment != "prod":
        return
    try:
        async with engine.connect() as conn:
            value = (await conn.execute(text(_SQL))).scalar_one_or_none()
            await conn.rollback()
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == errors.UndefinedTable.sqlstate:
            return
        raise NonProductionMarkError(_UNVERIFIED) from exc
    if value == "true":
        raise _refuse()


def assert_not_marked_non_production_sync(conninfo: str, environment: str) -> None:
    """İşçi açılışı (senkron, süreç başında bir kez). Yalnız `environment == "prod"` iken çalışır."""
    if environment != "prod":
        return
    try:
        with psycopg.connect(conninfo, connect_timeout=10) as conn:
            row = conn.execute(_SQL).fetchone()
    except errors.UndefinedTable:
        return
    except psycopg.Error as exc:
        raise NonProductionMarkError(_UNVERIFIED) from exc
    if row is not None and row[0] == "true":
        raise _refuse()
