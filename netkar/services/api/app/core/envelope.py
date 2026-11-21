"""Zarf şifreleme: kayıt başına rastgele veri anahtarı (DEK), KEK ile sarılır (G05, ADR-0004).

Şifreli değer biçimi (sürümlü, anahtar kimlikli):

    v2:<kid>:<sarılı_dek_b64>:<veri_b64>

  - `kid`            : sarmada kullanılan KEK'in kimliği (`[A-Za-z0-9_-]{1,32}`, ':' içermez).
  - `sarılı_dek_b64` : base64(nonce12 + AES-256-GCM(KEK, DEK, AAD="netkar:dek-wrap:v2:<kid>")).
  - `veri_b64`       : base64(nonce12 + AES-256-GCM(DEK, düz metin, AAD=çağıranın bağlamı)).

Her `encrypt` çağrısı yeni bir 256 bit DEK ve yeni nonce'lar üretir. Veri AAD'si çağıranın verdiği
bağlamdır (kiracı, hesap, satıcı, alan adı): şifreli değer başka bir bağlama taşınırsa çözülemez.
Anahtar döndürmede (`rewrap`) yalnız sarılı DEK yeniden sarılır; veri gövdesi ve düz metin hiç
açılmaz. KEK'ler ortam değişkeninden gelir (`DATA_KEKS`, `DATA_KEK_ACTIVE`); KMS faz 2'dedir.

Not: Python'da bellekteki düz metin ve anahtar baytları sıfırlanamaz; pencere kısa tutulur.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from collections.abc import ItemsView

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.crypto import DecryptionError

_VERSION = "v2"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_KID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


class KeyRingError(ValueError):
    """Anahtar halkası yapılandırması geçersiz. İleti anahtar değerini ASLA içermez."""


class KeyRing:
    """Kimlikli KEK'ler ve etkin kimlik. Ham anahtar baytları repr ve str'de görünmez."""

    def __init__(self, keys: dict[str, bytes], active: str) -> None:
        if not keys:
            raise KeyRingError("anahtar listesi boş")
        for kid, key in keys.items():
            if not _KID_RE.fullmatch(kid):
                raise KeyRingError("geçersiz kid (en fazla 32 karakter: harf, rakam, '_' ve '-')")
            if len(key) != _KEY_BYTES:
                raise KeyRingError(f"{kid} anahtarı 32 bayt olmalı")
        if active not in keys:
            raise KeyRingError("etkin kid anahtar listesinde yok")
        self._keys = dict(keys)
        self.active = active

    @classmethod
    def parse(cls, spec: str, active: str) -> KeyRing:
        """`kid:base64,kid2:base64` biçimindeki listeyi ve etkin kid'i ayrıştırır."""
        keys: dict[str, bytes] = {}
        for part in (p.strip() for p in spec.split(",")):
            if not part:
                continue
            kid, sep, encoded = part.partition(":")
            if not sep:
                raise KeyRingError("her girdi 'kid:base64' biçiminde olmalı")
            if kid in keys:
                raise KeyRingError("yinelenen kid")
            try:
                keys[kid] = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise KeyRingError(f"{kid or '?'} anahtarı geçerli base64 değil") from None
        return cls(keys, active.strip())

    def key(self, kid: str) -> bytes | None:
        """Kimliğe karşılık gelen KEK (yoksa None)."""
        return self._keys.get(kid)

    def kids(self) -> tuple[str, ...]:
        """Halkadaki kimlikler (ekleme sırasıyla)."""
        return tuple(self._keys)

    def items(self) -> ItemsView[str, bytes]:
        """(kid, anahtar) çiftleri. Yalnız yapılandırma yardımcıları ve testler kullanır."""
        return self._keys.items()

    def __repr__(self) -> str:
        return f"KeyRing(kids={list(self._keys)!r}, active={self.active!r})"

    __str__ = __repr__


class EnvelopeCipher:
    """AES-256-GCM zarf şifreleme (DEK + KEK sarma) ve kid ile anahtar döndürme."""

    def __init__(self, ring: KeyRing) -> None:
        self._ring = ring
        self._aeads = {kid: AESGCM(key) for kid, key in ring.items()}

    @property
    def active_kid(self) -> str:
        """Yeni şifrelemelerde kullanılan KEK kimliği."""
        return self._ring.active

    @staticmethod
    def is_envelope(token: str) -> bool:
        """Değer v2 zarf biçiminde mi (önek denetimi; çözme denemez)."""
        return token.startswith(f"{_VERSION}:")

    @staticmethod
    def _wrap_aad(kid: str) -> bytes:
        return f"netkar:dek-wrap:{_VERSION}:{kid}".encode()

    @staticmethod
    def _split(token: str) -> tuple[str, bytes, bytes]:
        """Biçimi doğrular ve (kid, sarılı_dek, veri) döndürür; bozuksa DecryptionError."""
        parts = token.split(":")
        if len(parts) != 4 or parts[0] != _VERSION or not _KID_RE.fullmatch(parts[1]):
            raise DecryptionError("bilinmeyen biçim")
        try:
            wrapped = base64.b64decode(parts[2], validate=True)
            sealed = base64.b64decode(parts[3], validate=True)
        except (binascii.Error, ValueError):
            raise DecryptionError("bozuk biçim") from None
        return parts[1], wrapped, sealed

    def key_id(self, token: str) -> str:
        """Değerin sarıldığı KEK kimliği (çözmeden)."""
        return self._split(token)[0]

    def _unwrap(self, kid: str, wrapped: bytes) -> bytes:
        aead = self._aeads.get(kid)
        if aead is None:
            raise DecryptionError("bilinmeyen anahtar kimliği")
        if len(wrapped) <= _NONCE_BYTES:
            raise DecryptionError("bozuk sarılı anahtar")
        try:
            return aead.decrypt(wrapped[:_NONCE_BYTES], wrapped[_NONCE_BYTES:], self._wrap_aad(kid))
        except InvalidTag:
            raise DecryptionError("anahtar açılamadı") from None

    def _wrap(self, dek: bytes) -> bytes:
        kid = self._ring.active
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + self._aeads[kid].encrypt(nonce, dek, self._wrap_aad(kid))

    def encrypt(self, plaintext: str, aad: bytes) -> str:
        """Yeni DEK üretir, düz metni DEK ile şifreler, DEK'i etkin KEK ile sarar."""
        dek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(_NONCE_BYTES)
        sealed = nonce + AESGCM(dek).encrypt(nonce, plaintext.encode(), aad)
        wrapped = self._wrap(dek)
        return ":".join(
            (
                _VERSION,
                self._ring.active,
                base64.b64encode(wrapped).decode(),
                base64.b64encode(sealed).decode(),
            )
        )

    def decrypt(self, token: str, aad: bytes) -> str:
        """Değeri çözer. Biçim, kid, sarma veya AAD hatasında DecryptionError (ayrıntı vermez)."""
        kid, wrapped, sealed = self._split(token)
        dek = self._unwrap(kid, wrapped)
        if len(sealed) <= _NONCE_BYTES:
            raise DecryptionError("bozuk veri")
        try:
            return AESGCM(dek).decrypt(sealed[:_NONCE_BYTES], sealed[_NONCE_BYTES:], aad).decode()
        except (InvalidTag, UnicodeDecodeError):
            raise DecryptionError("çözülemedi") from None

    def rewrap(self, token: str) -> str:
        """Değeri etkin KEK'e taşır: yalnız sarılı DEK yeniden sarılır, veri gövdesi aynı kalır.

        İdempotenttir: zaten etkin kid ile sarılıysa değer aynen döner.
        """
        kid, wrapped, _ = self._split(token)
        if kid == self._ring.active:
            return token
        dek = self._unwrap(kid, wrapped)
        new_wrapped = base64.b64encode(self._wrap(dek)).decode()
        _, _, _, body = token.split(":")
        return ":".join((_VERSION, self._ring.active, new_wrapped, body))
