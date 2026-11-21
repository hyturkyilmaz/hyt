"""Tek tık bildirim kapatma bağlantısı için imzalı, süreli token (ADR-0009 §7.5, §10.1).

Token: `base64url(yük) + "." + base64url(HMAC-SHA256(anahtar, "notify-unsub" || yük))`. Yük
`v1|kullanıcı|kiracı|kural|kanal|bitiş(unix saniye)` biçimindedir; kural dört uyarı kuralından biri ya da `*`
(o kanaldaki tüm kurallar; YALNIZ özet e-postasının `List-Unsubscribe` başlığı için; tek kurallı anlık ileti
başlığı yalnız o kuralı kapatır) olur.

Güvenlik özellikleri:
- Amaca özel: anahtar ana anahtardan `notify-unsub` amacıyla türetilir (başka HMAC kullanımlarıyla karışmaz).
  Anahtar yapılandırmadan gelir (`DATA_ENCRYPTION_KEY`); repoya sır yazılmaz, testlerde sabit test anahtarı
  verilir.
- Kullanıcı, kiracı, kural ve kanala bağlıdır: başka kullanıcı ya da başka kural için kullanılamaz
  (`UnsubscribeSigner.allows`).
- Süreli: bitiş zamanı imzalı yüktedir; süresi dolan ya da gelecekte (ileri saat) üretilmiş ama bitişi geçmiş
  token geçersizdir.
- Yalnız `off` yönü: token başka hiçbir işlem yapamaz (uç nokta yalnız `mode = 'off'` yazar).
- Tüm hata biçimleri (bozuk, imza uyuşmaz, süre dolmuş, bilinmeyen kural) tek sonuç verir: None.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.alerts import AlertRule
from app.core.config import Settings
from app.core.crypto import derive_key

PURPOSE = "notify-unsub"
VERSION = "v1"
# Tüm kurallar (yalnız e-posta özetinin List-Unsubscribe başlığı için).
ALL_RULES = "*"
CHANNELS = frozenset({"email", "push"})
VALID_RULES = frozenset({ALL_RULES, *(rule.value for rule in AlertRule)})
# Aşırı uzun girdi imza hesabına bile girmez.
MAX_TOKEN_CHARS = 512
_B64_ALPHABET = re.compile(r"[A-Za-z0-9_-]*", re.ASCII)


@dataclass(frozen=True, slots=True)
class UnsubscribeClaim:
    """Doğrulanmış token içeriği."""

    user_id: UUID
    tenant_id: UUID
    rule: str
    channel: str
    expires_at: datetime

    @property
    def rules(self) -> tuple[str, ...]:
        """Kapatılacak kurallar (`*` ise dördü de)."""
        if self.rule == ALL_RULES:
            return tuple(rule.value for rule in AlertRule)
        return (self.rule,)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    if not _B64_ALPHABET.fullmatch(text):  # base64 çözücü yabancı karakteri sessizce atar; biz reddederiz
        raise ValueError("base64url değil")
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class UnsubscribeSigner:
    """Token üretici ve doğrulayıcı. Saat dışarıdan verilir (test edilebilirlik)."""

    def __init__(self, key: bytes, *, ttl: timedelta = timedelta(days=90)) -> None:
        if len(key) < 16:
            raise ValueError("imza anahtarı en az 16 bayt olmalı")
        if ttl <= timedelta(0):
            raise ValueError("süre pozitif olmalı")
        self._key = key
        self._ttl = ttl

    @classmethod
    def from_settings(cls, settings: Settings) -> UnsubscribeSigner:
        """Üretim yolu: ana anahtardan `notify-unsub` amacıyla türetilen anahtar, ayarlı ömür."""
        return cls(
            derive_key(settings.master_key, PURPOSE), ttl=timedelta(days=settings.notify_unsubscribe_ttl_days)
        )

    def _mac(self, payload: bytes) -> bytes:
        return hmac.new(self._key, PURPOSE.encode("ascii") + b"\x00" + payload, hashlib.sha256).digest()

    def sign(self, user_id: UUID, tenant_id: UUID, rule: str, channel: str, now: datetime) -> str:
        """Token üretir; bilinmeyen kural ya da kanal ValueError verir."""
        if rule not in VALID_RULES or channel not in CHANNELS:
            raise ValueError("bilinmeyen kural ya da kanal")
        expires = int((now.astimezone(UTC) + self._ttl).timestamp())
        payload = f"{VERSION}|{user_id}|{tenant_id}|{rule}|{channel}|{expires}".encode("ascii")
        return f"{_b64(payload)}.{_b64(self._mac(payload))}"

    def verify(self, token: str, now: datetime) -> UnsubscribeClaim | None:
        """İmzası ve süresi geçerli token'ın içeriği; aksi halde (her nedenle) None."""
        if not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
            return None
        body, _, signature = token.partition(".")
        try:
            payload = _unb64(body)
            given = _unb64(signature)
        except (ValueError, binascii.Error):
            return None
        if not hmac.compare_digest(self._mac(payload), given):
            return None
        try:
            version, user, tenant, rule, channel, expires = payload.decode("ascii").split("|")
            claim = UnsubscribeClaim(
                UUID(user), UUID(tenant), rule, channel, datetime.fromtimestamp(int(expires), UTC)
            )
        except (ValueError, UnicodeDecodeError, OverflowError, OSError):
            return None
        if version != VERSION or rule not in VALID_RULES or channel not in CHANNELS:
            return None
        if claim.expires_at <= now.astimezone(UTC):
            return None
        return claim

    def allows(
        self, token: str, now: datetime, *, user_id: UUID, tenant_id: UUID, rule: str, channel: str
    ) -> bool:
        """Token bu kullanıcı, kiracı, kural ve kanal için geçerli mi (`*` tokenı her kuralı kapsar)."""
        claim = self.verify(token, now)
        return (
            claim is not None
            and claim.user_id == user_id
            and claim.tenant_id == tenant_id
            and claim.channel == channel
            and rule in claim.rules
        )
