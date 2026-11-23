"""Web push (ADR-0009 §7.2, D8 birinci yarı): abonelik kuralları, saklama ve gönderici arayüzü.

Kapsam: abonelik DOĞRULAMASI (uç nokta izin listesi, anahtar biçimi), saklama yardımcıları, çıkış/parola
sıfırlamada iptal (H11) ve gönderici ARAYÜZÜ. Gerçek ağa çıkan gönderim YOKTUR: `PushSender` yalnız bir
sözleşmedir, tek gerçeklemesi testlerdeki `FakePushSender`'dır. Dağıtıcıya (`notify.py`) bağlanmaz; push
satırları `suppressed` kalır (ikinci yarı).

Gizlilik: uç nokta URL'si ve anahtarlar cihaz tanımlayıcısıdır. Veritabanına yalnız ADR-0004 zarf şifreli ve
HMAC özetli yazılır; log'a, `audit_log`'a ve hata iletilerine GİRMEZ (yalnız ana bilgisayar adı, izin listesi
yüzünden zaten bilinen bir değerdir). Bu modülün hiçbir hata iletisi girdi değerini yansıtmaz.

TODO(D8 ikinci yarı): gerçek gönderici için RFC 8291/8292 imzalama ve şifreleme gerekir. Öneri: `pywebpush`
(bağımlılık seçimi `pip-audit` ve bakım durumu denetimiyle yapılır, ADR §7.2); bu yarıda bağımlılık EKLENMEDİ.
Gerçek gönderici `PushSender` arayüzünü uygular, dış çağrıyı yalnız `WEB_PUSH_ENABLED=true` iken yapar ve
yanıt kodunu `apply_delivery_result` ile işler.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import hmac_hex
from app.core.envelope import EnvelopeCipher
from app.models import PushSubscription

# --------------------------------------------------------------------------- uç nokta izin listesi
# ADR-0009 §7.2 öneri listesi (SSRF, API7:2023). `*.` önekli girdiler EN AZ BİR etiket ister (kök tek başına
# geçmez). Liste tarayıcı belgelerinden teyit edilmedi (ADR: "Doğrulanmadı"); yeni servis eklemek koddur.
ALLOWED_EXACT_HOSTS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com"})
ALLOWED_HOST_SUFFIXES = (".push.apple.com", ".notify.windows.com")
MAX_ENDPOINT_LENGTH = 2048
MAX_ACTIVE_PER_USER = 10

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")
# Uç nokta yalnız görünür ASCII: boşluk, denetim karakteri ve ters eğik çizgi (ayrıştırıcı farkı) reddedilir.
_ENDPOINT_CHARS = re.compile(r"[\x21-\x7e]+")


class PushValidationError(ValueError):
    """Abonelik girdisi geçersiz. `code` makine kodu; ileti girdi değerini taşımaz."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_endpoint(endpoint: str) -> str:
    """Uç noktayı doğrular ve küçük harfli ana bilgisayarı döndürür.

    Kurallar: yalnız `https`, kullanıcı bilgisi yok, port yok ya da 443, ana bilgisayar izin listesinde. IP
    değişmezleri, sondaki nokta ve büyük/küçük harf oyunları izin listesini geçemez.
    """
    if len(endpoint) > MAX_ENDPOINT_LENGTH or not _ENDPOINT_CHARS.fullmatch(endpoint) or "\\" in endpoint:
        raise PushValidationError("endpoint_invalid", "Uç nokta geçersiz.")
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        raise PushValidationError("endpoint_invalid", "Uç nokta geçersiz.") from None
    if parts.scheme != "https":
        raise PushValidationError("endpoint_scheme", "Uç nokta https olmalıdır.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise PushValidationError("endpoint_invalid", "Uç nokta geçersiz.")
    if port is not None and port != 443:
        raise PushValidationError("endpoint_port", "Uç nokta portu desteklenmiyor.")
    host = (parts.hostname or "").lower()
    labels = host.split(".")
    if not host or any(not _HOST_LABEL.fullmatch(label) for label in labels):
        raise PushValidationError("endpoint_invalid", "Uç nokta geçersiz.")
    if host not in ALLOWED_EXACT_HOSTS and not host.endswith(ALLOWED_HOST_SUFFIXES):
        raise PushValidationError("endpoint_host_not_allowed", "Bu push servisi desteklenmiyor.")
    return host


def _decode_b64url(value: str) -> bytes | None:
    """Dolgusuz base64url (tarayıcı `PushSubscription.toJSON()` biçimi); bozuksa None."""
    if not _BASE64URL.fullmatch(value):
        return None
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return None


def validate_p256dh(value: str) -> str:
    """İstemci genel anahtarı: 65 bayt sıkıştırılmamış P-256 noktası ve eğri üzerinde."""
    raw = _decode_b64url(value) if len(value) <= 128 else None
    if raw is None or len(raw) != 65 or raw[0] != 4:
        raise PushValidationError("p256dh_invalid", "Abonelik anahtarı geçersiz.")
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    except ValueError:
        raise PushValidationError("p256dh_invalid", "Abonelik anahtarı geçersiz.") from None
    return value


def validate_auth_secret(value: str) -> str:
    """Kimlik doğrulama sırrı: 16 bayt (RFC 8291)."""
    raw = _decode_b64url(value) if len(value) <= 64 else None
    if raw is None or len(raw) != 16:
        raise PushValidationError("auth_invalid", "Abonelik anahtarı geçersiz.")
    return value


# --------------------------------------------------------------------------- kimlik ve şifreleme yardımcıları
def endpoint_digest(master_key: bytes, endpoint: str) -> str:
    """Uç noktanın anahtarlı özeti (64 hex): tekilleştirme için; URL'yi geri vermez."""
    return hmac_hex(master_key, "push-endpoint", endpoint)


def vapid_key_id(public_key: str) -> str:
    """Genel anahtardan türetilen kısa kimlik (`vapid_key_id`); döndürmede istemci farkı bununla görür."""
    return sha256(public_key.encode()).hexdigest()[:16]


def push_aad(tenant_id: UUID, user_id: UUID, field_name: str) -> bytes:
    """Zarf şifre bağlamı: şifreli değer başka kiracı, kullanıcı ya da alana taşınırsa çözülemez.

    Satır kimliği DB'de üretildiği (INSERT yetkisinde `id` yok) için bağlama girmez. Çözen taraf (worker) aynı
    üç değeri kullanır.
    """
    return f"push_subscriptions:v1:{tenant_id}:{user_id}:{field_name}".encode()


# --------------------------------------------------------------------------- saklama (uygulama rolü, RLS)
async def count_active(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(PushSubscription)
                .where(
                    PushSubscription.tenant_id == tenant_id,
                    PushSubscription.user_id == user_id,
                    PushSubscription.revoked_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def find_active_by_digest(
    db: AsyncSession, tenant_id: UUID, user_id: UUID, digest: str
) -> PushSubscription | None:
    """Kullanıcının kendi etkin satırı (RLS başkasınınkini zaten göstermez; filtre ikinci kilittir)."""
    return (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.tenant_id == tenant_id,
                PushSubscription.user_id == user_id,
                PushSubscription.endpoint_digest == digest,
                PushSubscription.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def insert_subscription(
    db: AsyncSession,
    envelope: EnvelopeCipher,
    *,
    tenant_id: UUID,
    user_id: UUID,
    session_id: UUID,
    endpoint: str,
    host: str,
    digest: str,
    p256dh: str,
    auth: str,
    key_id: str,
) -> UUID | None:
    """Etkin satır ekler. Aynı (kiracı, özet) için etkin satır varsa (kısmi UNIQUE) None döner; yazım olmaz.

    `ON CONFLICT DO NOTHING`: çakışan satır başka kullanıcıya aitse RLS yüzünden görünmez, çağıran bunu ayırt
    etmek için `find_active_by_digest` ile kendi satırını arar.
    """
    stmt = (
        pg_insert(PushSubscription)
        .values(
            tenant_id=tenant_id,
            user_id=user_id,
            endpoint_host=host,
            endpoint_digest=digest,
            endpoint_enc=envelope.encrypt(endpoint, push_aad(tenant_id, user_id, "endpoint")),
            p256dh_enc=envelope.encrypt(p256dh, push_aad(tenant_id, user_id, "p256dh")),
            auth_enc=envelope.encrypt(auth, push_aad(tenant_id, user_id, "auth")),
            vapid_key_id=key_id,
            created_session_id=session_id,
        )
        .on_conflict_do_nothing(
            index_elements=["tenant_id", "endpoint_digest"], index_where=PushSubscription.revoked_at.is_(None)
        )
        .returning(PushSubscription.id)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_own(
    db: AsyncSession, tenant_id: UUID, user_id: UUID, subscription_id: UUID
) -> PushSubscription | None:
    """Kendi aboneliği (etkin ya da iptal). Başkasının ya da var olmayan kimlik için None (IDOR: 404)."""
    return (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.id == subscription_id,
                PushSubscription.tenant_id == tenant_id,
                PushSubscription.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def list_active(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> list[PushSubscription]:
    return list(
        (
            await db.execute(
                select(PushSubscription)
                .where(
                    PushSubscription.tenant_id == tenant_id,
                    PushSubscription.user_id == user_id,
                    PushSubscription.revoked_at.is_(None),
                )
                .order_by(PushSubscription.created_at.desc(), PushSubscription.id)
            )
        ).scalars()
    )


async def revoke_own(db: AsyncSession, tenant_id: UUID, user_id: UUID, subscription_id: UUID) -> bool:
    """Tek aboneliği iptal eder (silme yok). Etkin satır iptal edildiyse True."""
    result = await db.execute(
        update(PushSubscription)
        .where(
            PushSubscription.id == subscription_id,
            PushSubscription.tenant_id == tenant_id,
            PushSubscription.user_id == user_id,
            PushSubscription.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount) > 0  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- H11: oturum olaylarında iptal
async def revoke_for_session(db: AsyncSession, session_id: UUID) -> int:
    """Açık çıkış: bu oturumda oluşturulan abonelikler (paylaşılan cihaz: sonraki kişi push görmesin).

    RLS bağlamı (kiracı + kullanıcı) kurulu olmalıdır; satırlar başka kullanıcıya sızamaz.
    """
    result = await db.execute(
        update(PushSubscription)
        .where(PushSubscription.created_session_id == session_id, PushSubscription.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def revoke_for_other_sessions(db: AsyncSession, user_id: UUID, keep_session_id: UUID) -> int:
    """ "Diğer oturumları kapat": geçerli oturum dışındaki oturumlarda oluşturulan abonelikler."""
    result = await db.execute(
        update(PushSubscription)
        .where(
            PushSubscription.user_id == user_id,
            PushSubscription.revoked_at.is_(None),
            PushSubscription.created_session_id.is_distinct_from(keep_session_id),
        )
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


async def revoke_all_for_user(db: AsyncSession, user_id: UUID) -> int:
    """Parola sıfırlama: tüm oturumlar kapanır, kullanıcının tüm abonelikleri de iptal edilir."""
    result = await db.execute(
        update(PushSubscription)
        .where(PushSubscription.user_id == user_id, PushSubscription.revoked_at.is_(None))
        .values(revoked_at=func.now())
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- gönderici arayüzü (ağ YOK)
_TITLE_MAX = 80
_BODY_MAX = 160
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# `notificationclick` yalnız bu önekli, aynı kökenli yollara gider (sw.js aynı kuralı uygular; ADR §7.2).
NOTIFICATION_PATH_PREFIX = "/panel/uyarilar"


def _clean(text_value: str, limit: int) -> str:
    """Kontrol karakterlerini temizler ve keser (ürün başlıkları güvenilmez veridir)."""
    return _CONTROL.sub(" ", text_value).strip()[:limit]


@dataclass(frozen=True)
class PushPayload:
    """Bildirim yükü. Tutar ve müşteri verisi YOKTUR (H3); yol göreli ve izin listeli önektedir."""

    title: str
    body: str
    path: str = NOTIFICATION_PATH_PREFIX

    def __post_init__(self) -> None:
        path = self.path
        if not (path == NOTIFICATION_PATH_PREFIX or path.startswith(NOTIFICATION_PATH_PREFIX + "/")) or (
            "//" in path or "\\" in path or ".." in path
        ):
            raise ValueError("bildirim yolu izin listesinde değil")

    def to_json(self) -> str:
        return json.dumps(
            {
                "title": _clean(self.title, _TITLE_MAX),
                "body": _clean(self.body, _BODY_MAX),
                "path": self.path,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class PushTarget:
    """Gönderim hedefi (çözülmüş). Değerler `repr`'da görünmez: hata ayıklama çıktısı log'a sızmasın."""

    subscription_id: UUID
    endpoint: str = field(repr=False)
    p256dh: str = field(repr=False)
    auth: str = field(repr=False)


@dataclass(frozen=True)
class SendResult:
    """Push servisinin HTTP durum kodu (RFC 8030: 201 kabul)."""

    status_code: int


class PushSender(Protocol):
    """Gönderici sözleşmesi. Gerçek gerçekleme (pywebpush) ikinci yarıdadır."""

    async def send(
        self, target: PushTarget, payload: PushPayload, *, ttl: int, urgency: str, topic: str | None
    ) -> SendResult: ...


@dataclass
class FakePushSender:
    """Test arka ucu: ağa çıkmaz. Hedef başına programlanabilir durum kodu, varsayılan 201."""

    default_status: int = 201
    status_by_subscription: dict[UUID, int] = field(default_factory=dict)
    sent: list[tuple[UUID, str, int, str, str | None]] = field(default_factory=list)

    async def send(
        self, target: PushTarget, payload: PushPayload, *, ttl: int, urgency: str, topic: str | None
    ) -> SendResult:
        self.sent.append((target.subscription_id, payload.to_json(), ttl, urgency, topic))
        return SendResult(self.status_by_subscription.get(target.subscription_id, self.default_status))


DeliveryOutcome = Literal["sent", "revoked", "failed"]


async def apply_delivery_result(db: AsyncSession, subscription_id: UUID, status_code: int) -> DeliveryOutcome:
    """Gönderim sonucunu aboneliğe işler (worker rolü, kiracı bağlamı kurulu).

    404 ve 410: abonelik artık yok, `revoked_at` yazılır (silme yok; şifreli alanlar tetikleyiciyle NULL).
    2xx: `last_success_at` yazılır, `failure_count` sıfırlanır. Diğer: `failure_count` artar (geçici hata;
    180 gün başarısız aboneliğin iptali ADR §7.2, ikinci yarıdaki süpürme işinde).
    """
    active = PushSubscription.id == subscription_id, PushSubscription.revoked_at.is_(None)
    if status_code in (404, 410):
        values: dict[str, object] = {"revoked_at": func.now()}
        outcome: DeliveryOutcome = "revoked"
    elif 200 <= status_code < 300:
        values = {"last_success_at": func.now(), "failure_count": 0}
        outcome = "sent"
    else:
        values = {"failure_count": PushSubscription.failure_count + 1}
        outcome = "failed"
    await db.execute(
        update(PushSubscription).where(*active).values(**values).execution_options(synchronize_session=False)
    )
    return outcome
