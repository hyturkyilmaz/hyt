"""Alan şifreleme (AES-256-GCM) ve türetilmiş alt anahtarlar."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_PREFIX = "v1:"
_NONCE_BYTES = 12


class DecryptionError(Exception):
    """Şifreli veri çözülemedi (yanlış anahtar, bozuk veri veya AAD uyuşmazlığı)."""


def derive_key(master: bytes, purpose: str) -> bytes:
    """Ana anahtardan amaç bazlı 32 baytlık alt anahtar türetir (HKDF-SHA256)."""
    return HKDF(algorithm=SHA256(), length=32, salt=None, info=f"netkar:{purpose}".encode()).derive(master)


def hmac_hex(master: bytes, purpose: str, value: str) -> str:
    """Amaç bazlı anahtarla HMAC-SHA256 (hex). IP ve e-posta özetleri için."""
    key = derive_key(master, purpose)
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


class FieldCipher:
    """AES-256-GCM ile alan şifreleme. AAD, şifreli veriyi kayda bağlar."""

    def __init__(self, master: bytes) -> None:
        self._aead = AESGCM(derive_key(master, "aes-gcm-field"))

    def encrypt(self, plaintext: str, aad: bytes) -> str:
        """Düz metni şifreler. Çıktı: 'v1:' + base64(nonce + şifreli metin + etiket)."""
        nonce = os.urandom(_NONCE_BYTES)
        sealed = self._aead.encrypt(nonce, plaintext.encode(), aad)
        return _PREFIX + base64.b64encode(nonce + sealed).decode()

    def decrypt(self, token: str, aad: bytes) -> str:
        """Şifreli metni çözer; bozuksa DecryptionError fırlatır."""
        if not token.startswith(_PREFIX):
            raise DecryptionError("bilinmeyen biçim")
        try:
            raw = base64.b64decode(token[len(_PREFIX) :], validate=True)
            nonce, sealed = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
            return self._aead.decrypt(nonce, sealed, aad).decode()
        except (InvalidTag, ValueError) as exc:
            raise DecryptionError("çözülemedi") from exc
