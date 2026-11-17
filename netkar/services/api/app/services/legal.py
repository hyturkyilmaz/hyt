"""Kullanım koşulları ve aydınlatma metni sürüm kaydı ile kullanıcı kabulü (TBK m.20-21 ispat notu).

Belge METNİ burada yoktur; yalnız sürüm kodu ve içerik özeti (SHA-256) tutulur. Kabul kaydı yalnız
kullanıcı + belge satırı + zaman içerir (IP/aracı bilgisi saklanmaz). Kayıtlar değişmezdir (0021).
Aydınlatma metni "okudum" bilgisidir, KVKK açık rızası DEĞİLDİR; ayrı bir rıza gerekiyorsa ayrı kayıt olur.
"""

from __future__ import annotations

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


# _CURRENT sabittir (kullanıcı girdisi birleşmez); kullanıcı kimliği bağlı parametredir.
_PENDING = f"""
    SELECT c.id, c.doc_type, c.version, c.published_at
    FROM ({_CURRENT}) c
    WHERE NOT EXISTS (
        SELECT 1 FROM user_legal_acceptances a
        WHERE a.user_id = :uid AND a.document_id = c.id
    )
    ORDER BY c.doc_type
"""  # noqa: S608


async def pending_documents(db: AsyncSession, user_id: UUID) -> list[LegalDocument]:
    """Kullanıcının henüz kabul etmediği güncel sürümler. RLS bağlamında app.user_id ayarlı olmalı."""
    rows = (await db.execute(text(_PENDING), {"uid": user_id})).all()
    return [_row(r) for r in rows]


async def record_acceptance(db: AsyncSession, user_id: UUID, documents: list[LegalDocument]) -> int:
    """Belge sürümlerini kabul kaydına yazar; zaten kayıtlıysa dokunmaz. Eklenen satır sayısını döner.

    RLS bağlamında app.user_id = user_id olmalı (politika başka kullanıcı adına yazmayı reddeder).
    """
    inserted = 0
    for doc in documents:
        result = await db.execute(
            text(
                "INSERT INTO user_legal_acceptances (user_id, document_id) VALUES (:uid, :doc) "
                "ON CONFLICT (user_id, document_id) DO NOTHING"
            ),
            {"uid": user_id, "doc": doc.id},
        )
        inserted += int(result.rowcount or 0)  # type: ignore[attr-defined]
    return inserted
