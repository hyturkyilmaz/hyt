"""Parola, token, TOTP ve imzalı geçici token yardımcıları."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache
from typing import Any
from uuid import UUID

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.crypto import derive_key

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128

# Argon2id (argon2-cffi varsayılan türü). Parametreler kütüphane varsayılanıdır
# (RFC 9106 düşük bellek profili).
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Parolayı argon2id ile özetler."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Parolayı doğrular; biçim hatası dahil her başarısızlıkta False döner."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@lru_cache
def _dummy_hash() -> str:
    return _hasher.hash("netkar-dummy-parola-zamanlama-esitleme")


def burn_password_verification(password: str) -> None:
    """Kullanıcı yokken de aynı maliyeti ödeyerek zamanlama farkını gizler."""
    verify_password(_dummy_hash(), password)


def generate_token() -> str:
    """256 bitlik rastgele, URL güvenli token."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Token'ın SHA-256 özeti (hex). DB'de yalnız bu saklanır."""
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    """Zamanlama saldırısına dayanıklı karşılaştırma."""
    return hmac.compare_digest(a.encode(), b.encode())


def new_totp_secret() -> str:
    """Yeni base32 TOTP sırrı."""
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str) -> str:
    """Authenticator uygulamaları için otpauth URI."""
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """TOTP kodunu doğrular (önceki ve sonraki 30 sn pencere kabul edilir)."""
    if not (code.isdigit() and len(code) == 6):
        return False
    return bool(pyotp.TOTP(secret).verify(code, valid_window=1))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_pending_token(
    master: bytes, user_id: UUID, tenant_id: UUID, ttl_seconds: int, now: float | None = None
) -> str:
    """Parola geçildi, TOTP bekleniyor: kısa ömürlü imzalı token."""
    payload = {
        "u": str(user_id),
        "t": str(tenant_id),
        "exp": int((now if now is not None else time.time()) + ttl_seconds),
        "p": "totp",
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(derive_key(master, "pending-token"), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def read_pending_token(master: bytes, token: str, now: float | None = None) -> tuple[UUID, UUID] | None:
    """İmzayı ve süreyi doğrular; geçerliyse (user_id, tenant_id) döner."""
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(derive_key(master, "pending-token"), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        payload: dict[str, Any] = json.loads(_unb64(body))
        if payload.get("p") != "totp":
            return None
        if payload["exp"] < (now if now is not None else time.time()):
            return None
        return UUID(payload["u"]), UUID(payload["t"])
    except (ValueError, KeyError, TypeError):
        return None
