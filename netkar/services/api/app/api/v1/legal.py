"""/v1/legal: güncel kullanım koşulları ve aydınlatma metni sürümünün kabulü (TBK m.20-21 ispat notu)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AuthDep, DbDep, SettingsDep
from app.api.v1.schemas import LegalAcceptRequest, LegalPendingOut, LegalStatus
from app.core.errors import ProblemError
from app.db.rls import set_rls_context
from app.services import legal as legal_service
from app.services.audit import record_audit

router = APIRouter(prefix="/legal", tags=["legal"])


def status_of(pending: list[legal_service.LegalDocument], enforced: bool) -> LegalStatus:
    return LegalStatus(
        pending=[
            LegalPendingOut(doc_type=d.doc_type, version=d.version, published_at=d.published_at)
            for d in pending
        ],
        enforced=enforced,
    )


@router.get("/current", response_model=list[LegalPendingOut])
async def current(db: DbDep) -> list[LegalPendingOut]:
    """Herkese açık: her türün güncel sürümü (tür, sürüm, yayın zamanı). Kişisel veri yoktur.

    Kayıt formu bu sürümleri gösterir ve kayıt isteğiyle geri gönderir (kullanıcının gördüğü sürüm kabul edilir).
    """
    return [
        LegalPendingOut(doc_type=d.doc_type, version=d.version, published_at=d.published_at)
        for d in await legal_service.current_documents(db)
    ]


@router.post("/accept", response_model=LegalStatus)
async def accept(body: LegalAcceptRequest, ctx: AuthDep, db: DbDep, settings: SettingsDep) -> LegalStatus:
    """Kullanıcının gördüğü belge sürümlerini kabul kaydına yazar; kalan bekleyenleri döner.

    Yalnız GÜNCEL sürüm kabul edilebilir (kullanıcı eski bir sürümü görmüşse 409: sayfayı yenileyip yeni
    sürümü görmeden kabul kaydı oluşmaz). Doğrulanmamış e-posta engel değildir (kabul güvenlik işlemi değil).
    Aynı sürümü ikinci kez kabul etmek zararsızdır (kayıt eklenmez). IP ve aracı bilgisi yazılmaz.
    """
    current = {d.doc_type: d for d in await legal_service.current_documents(db)}
    chosen: dict[legal_service.DocType, legal_service.LegalDocument] = {}
    for ref in body.documents:
        doc = current.get(ref.doc_type)
        if doc is None or doc.version != ref.version:
            raise ProblemError(
                409,
                "Belge sürümü güncel değil",
                "legal-version-stale",
                "Kabul etmek istediğiniz sürüm artık güncel değil. Sayfayı yenileyip güncel sürümü okuyun.",
            )
        chosen[ref.doc_type] = doc
    inserted = await legal_service.record_acceptance(db, ctx.user_id, list(chosen.values()))
    if inserted:  # denetim kaydının hedefi yalnız bu istekte YENİ eklenen satırlardır
        await record_audit(
            db,
            ctx.tenant_id,
            "legal.accepted",
            user_id=ctx.user_id,
            target=",".join(f"{d.doc_type}:{d.version}" for d in inserted),
        )
    await db.commit()
    # Commit işlem yerel GUC'leri sıfırlar; kalan bekleyenleri okumak için bağlam yeniden kurulur.
    await set_rls_context(db, ctx.tenant_id, ctx.user_id)
    return status_of(
        await legal_service.pending_documents(db, ctx.user_id), settings.legal_reacceptance_enforced
    )
