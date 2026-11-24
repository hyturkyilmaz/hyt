"""Kullanım koşulları ve aydınlatma metni sürüm kaydı ile kullanıcı kabulü (TBK m.20-21 ispat notu).

Belge METNİ burada yoktur; yalnız sürüm kodu ve içerik özeti (SHA-256) tutulur. Kabul kaydı yalnız
kullanıcı + belge satırı + zaman içerir (IP/aracı bilgisi saklanmaz). Kayıtlar değişmezdir (0021).
Aydınlatma metni "okudum" bilgisidir, KVKK açık rızası DEĞİLDİR; ayrı bir rıza gerekiyorsa ayrı kayıt olur.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DocType(StrEnum):
    TERMS = "terms"
    PRIVACY_NOTICE = "privacy_notice"


@dataclass(frozen=True)
class LegalDocument:
    """Yayınlanmış bir belge sürümü (satır kimliği, tür, sürüm, yayın zamanı)."""

    id: UUID
    doc_type: DocType
    version: str
    published_at: datetime


# Her türün güncel sürümü: yayın zamanı geçmiş en yeni satır (eşitlikte id ile deterministik).
_CURRENT = """
    SELECT DISTINCT ON (doc_type) id, doc_type, version, published_at
    FROM legal_documents
    WHERE published_at <= now()
    ORDER BY doc_type, published_at DESC, id DESC
"""


def _row(row: object) -> LegalDocument:
    m = row._mapping  # type: ignore[attr-defined]
    return LegalDocument(m["id"], DocType(m["doc_type"]), m["version"], m["published_at"])


async def current_documents(db: AsyncSession) -> list[LegalDocument]:
    """Her türün güncel sürümü (tür adına göre sıralı)."""
    return [_row(r) for r in (await db.execute(text(_CURRENT))).all()]


# Herkese açık "güncel belge listesi" için süreç içi kısa önbellek. Yalnız kullanıcıdan bağımsız, kamusal veri
# tutulur (tür, sürüm, yayın zamanı); kullanıcıya özel sonuç (bekleyen belgeler vb.) ASLA buraya girmez.
# İleri tarihli belge yayın anında görünür (önbellek o ana kadar tutulur); hemen yayınlanan
# belge en geç CURRENT_CACHE_TTL_SECONDS sonra görünür. Kayıt ve kabul
# yolları önbelleği KULLANMAZ: sürüm doğrulaması her zaman veritabanındaki gerçek güncel sürümle yapılır.
CURRENT_CACHE_TTL_SECONDS = 60
_clock = time.monotonic  # testte sahte saatle değiştirilebilir
# (doldurma başlangıcı, bitiş, belgeler). Bitiş = min(başlangıç + TTL, sonraki ileri tarihli yayın zamanı):
# yeni sürümün yayın anı geçince önbellek bayat liste göstermez (kayıt 409 döngüsü olmaz).
_current_cache: tuple[float, float, tuple[LegalDocument, ...]] | None = None

# Bir sonraki ileri tarihli yayına kalan saniye (yoksa NULL). Düz sabit dizge.
_SECONDS_TO_NEXT_PUBLISH = (
    "SELECT extract(epoch FROM (min(published_at) - now())) FROM legal_documents WHERE published_at > now()"
)


def reset_current_cache() -> None:
    """Güncel belge önbelleğini boşaltır (testlerin birbirini etkilememesi için)."""
    global _current_cache
    _current_cache = None


async def current_documents_cached(db: AsyncSession) -> tuple[list[LegalDocument], int]:
    """Güncel belgeler ve önbellekte kalan tam saniye (Cache-Control max-age için; 0 altına düşmez).

    Yalnız herkese açık uç içindir. Eşzamanlı doldurmalarda yalnız DAHA YENİ başlayan sonuç yazılır:
    yavaş kalmış eski bir sorgu daha yeni sonucu ezemez.
    """
    global _current_cache
    now = _clock()
    cached = _current_cache
    if cached is not None and 0 <= now - cached[0] and now < cached[1]:
        return list(cached[2]), max(0, int(cached[1] - now))
    docs = await current_documents(db)
    to_next = (await db.execute(text(_SECONDS_TO_NEXT_PUBLISH))).scalar_one_or_none()
    ttl = float(CURRENT_CACHE_TTL_SECONDS)
    if to_next is not None:
        ttl = min(ttl, max(0.0, float(to_next)))
    latest = _current_cache
    if latest is None or now >= latest[0]:
        _current_cache = (now, now + ttl, tuple(docs))
    return docs, max(0, int(ttl))


# Düz sabit dizge (f-string ile birleştirme yok; semgrep avoid-sqlalchemy-text). Alt sorgu _CURRENT ile
# aynıdır; değişirse ikisi birlikte güncellenmeli (test_legal_acceptance güncel sürüm testleri yakalar).
# Kullanıcı kimliği bağlı parametredir.
_PENDING = """
    SELECT c.id, c.doc_type, c.version, c.published_at
    FROM (
        SELECT DISTINCT ON (doc_type) id, doc_type, version, published_at
        FROM legal_documents
        WHERE published_at <= now()
        ORDER BY doc_type, published_at DESC, id DESC
    ) c
    WHERE NOT EXISTS (
        SELECT 1 FROM user_legal_acceptances a
        WHERE a.user_id = :uid AND a.document_id = c.id
    )
    ORDER BY c.doc_type
"""


async def pending_documents(db: AsyncSession, user_id: UUID) -> list[LegalDocument]:
    """Kullanıcının henüz kabul etmediği güncel sürümler. RLS bağlamında app.user_id ayarlı olmalı."""
    rows = (await db.execute(text(_PENDING), {"uid": user_id})).all()
    return [_row(r) for r in rows]


async def record_acceptance(
    db: AsyncSession, user_id: UUID, documents: list[LegalDocument]
) -> list[LegalDocument]:
    """Belge sürümlerini kabul kaydına yazar; zaten kayıtlıysa dokunmaz. YENİ eklenenleri döner.

    RLS bağlamında app.user_id = user_id olmalı (politika başka kullanıcı adına yazmayı reddeder).
    Yalnız (user_id, document_id) yazılır; id ve accepted_at sunucu tarafında (0022 tetikleyicisi) üretilir.
    """
    inserted: list[LegalDocument] = []
    for doc in documents:
        result = await db.execute(
            text(
                "INSERT INTO user_legal_acceptances (user_id, document_id) VALUES (:uid, :doc) "
                "ON CONFLICT (user_id, document_id) DO NOTHING"
            ),
            {"uid": user_id, "doc": doc.id},
        )
        if result.rowcount:  # type: ignore[attr-defined]
            inserted.append(doc)
    return inserted


# Taslak olmayan (gerçek) güncel sürüm var mı: sürüm kodu "taslak-" ile başlamayan güncel satır sayısı.
_REAL_CURRENT = """
    SELECT count(*) FROM (
        SELECT DISTINCT ON (doc_type) doc_type, version
        FROM legal_documents
        WHERE published_at <= now()
        ORDER BY doc_type, published_at DESC, id DESC
    ) c
    WHERE c.version NOT LIKE 'taslak-%'
"""


async def real_current_exists(db: AsyncSession) -> bool:
    """Güncel sürümlerden en az biri taslak değilse True (açılış uyarısı için)."""
    return int((await db.execute(text(_REAL_CURRENT))).scalar_one()) > 0
