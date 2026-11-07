"""Birim testler: şifreleme, parola, token, TOTP, e-posta, HIBP, ayarlar."""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

import httpx
import pyotp
import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from app.core.config import Settings
from app.core.crypto import DecryptionError, FieldCipher, derive_key, hmac_hex
from app.core.email import EmailMessage, FileEmailSender, InMemoryOutbox
from app.core.pwned import HibpPwnedChecker, NullPwnedChecker
from app.core.security import (
    burn_password_verification,
    constant_time_equals,
    generate_token,
    hash_password,
    hash_token,
    new_totp_secret,
    read_pending_token,
    sign_pending_token,
    totp_uri,
    verify_password,
    verify_totp,
)

MASTER = b"0123456789abcdef0123456789abcdef"


@given(st.text(max_size=200), st.binary(max_size=40))
def test_cipher_roundtrip(plaintext: str, aad: bytes) -> None:
    cipher = FieldCipher(MASTER)
    token = cipher.encrypt(plaintext, aad)
    assert cipher.decrypt(token, aad) == plaintext


def test_cipher_is_randomized_and_authenticated() -> None:
    cipher = FieldCipher(MASTER)
    a, b = cipher.encrypt("sir", b"u1"), cipher.encrypt("sir", b"u1")
    assert a != b and a.startswith("v1:") and "sir" not in a
    with pytest.raises(DecryptionError):
        cipher.decrypt(a, b"u2")  # AAD uyuşmazlığı
    with pytest.raises(DecryptionError):
        FieldCipher(b"x" * 32).decrypt(a, b"u1")  # yanlış anahtar
    tampered = a[:-4] + ("AAAA" if not a.endswith("AAAA") else "BBBB")
    with pytest.raises(DecryptionError):
        cipher.decrypt(tampered, b"u1")
    with pytest.raises(DecryptionError):
        cipher.decrypt("v2:abc", b"u1")
    with pytest.raises(DecryptionError):
        cipher.decrypt("v1:***not-base64***", b"u1")


def test_derived_keys_are_domain_separated() -> None:
    assert derive_key(MASTER, "a") != derive_key(MASTER, "b")
    assert len(derive_key(MASTER, "a")) == 32
    assert hmac_hex(MASTER, "ip", "1.2.3.4") != hmac_hex(MASTER, "email", "1.2.3.4")


def test_password_hash_is_argon2id() -> None:
    hashed = hash_password("uzun-ve-guclu-parola-1")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "uzun-ve-guclu-parola-1")
    assert not verify_password(hashed, "baska-parola-123456")
    assert not verify_password("bozuk-ozet", "x")
    burn_password_verification("herhangi")


def test_tokens_are_random_and_hashed() -> None:
    a, b = generate_token(), generate_token()
    assert a != b and len(a) >= 43
    assert hash_token(a) == hash_token(a) and len(hash_token(a)) == 64 and hash_token(a) != a
    assert constant_time_equals("x", "x") and not constant_time_equals("x", "y")


def test_totp_helpers() -> None:
    secret = new_totp_secret()
    assert verify_totp(secret, pyotp.TOTP(secret).now())
    assert not verify_totp(secret, "abcdef") and not verify_totp(secret, "12345")
    uri = totp_uri(secret, "u@example.com", "NetKâr")
    assert uri.startswith("otpauth://totp/") and "issuer=" in uri


def test_pending_token_roundtrip_and_tamper() -> None:
    uid, tid = uuid.uuid4(), uuid.uuid4()
    token = sign_pending_token(MASTER, uid, tid, 300, now=1000.0)
    assert read_pending_token(MASTER, token, now=1100.0) == (uid, tid)
    assert read_pending_token(MASTER, token, now=1301.0) is None  # süresi doldu
    assert read_pending_token(b"y" * 32, token, now=1100.0) is None  # farklı anahtar
    body, sig = token.split(".")
    assert read_pending_token(MASTER, body + "." + sig[:-2] + "AA", now=1100.0) is None
    assert read_pending_token(MASTER, "bozuk", now=1.0) is None
    forged_body = base64.urlsafe_b64encode(json.dumps({"u": str(uid)}).encode()).decode().rstrip("=")
    assert read_pending_token(MASTER, forged_body + "." + sig, now=1.0) is None


async def test_in_memory_outbox_and_file_sender(tmp_path: Path) -> None:
    box = InMemoryOutbox()
    await box.send(EmailMessage("a@example.com", "konu", "gövde"))
    assert [m.subject for m in box.to("a@example.com")] == ["konu"] and box.to("b@example.com") == []

    path = tmp_path / "out" / "outbox.jsonl"
    sender = FileEmailSender(str(path))
    await sender.send(EmailMessage("a@example.com", "konu", "gövde token=xyz"))
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line == {"to": "a@example.com", "subject": "konu", "body": "gövde token=xyz"}


async def test_file_sender_does_not_log_body_or_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sender = FileEmailSender(str(tmp_path / "o.jsonl"))
    with caplog.at_level("INFO"):
        await sender.send(EmailMessage("a@example.com", "Sıfırlama", "bağlantı ?token=GIZLITOKEN"))
    assert "GIZLITOKEN" not in caplog.text


def _hibp_transport(suffix_line: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.pwnedpasswords.com"
        prefix = request.url.path.rsplit("/", 1)[1]
        assert len(prefix) == 5  # yalnız 5 haneli önek gönderilir
        return httpx.Response(200, text=f"0000000000000000000000000000000000A:3\r\n{suffix_line}\r\n")

    return httpx.MockTransport(handler)


async def test_hibp_checker_k_anonymity() -> None:
    import hashlib

    digest = hashlib.sha1(b"password12345", usedforsecurity=False).hexdigest().upper()
    hit = HibpPwnedChecker(httpx.AsyncClient(transport=_hibp_transport(f"{digest[5:]}:9000")))
    assert await hit.is_pwned("password12345") is True
    padded = HibpPwnedChecker(httpx.AsyncClient(transport=_hibp_transport(f"{digest[5:]}:0")))
    assert await padded.is_pwned("password12345") is False  # dolgu satırı
    miss = HibpPwnedChecker(httpx.AsyncClient(transport=_hibp_transport("1" * 35 + ":2")))
    assert await miss.is_pwned("password12345") is False
    assert await NullPwnedChecker().is_pwned("password12345") is False


async def test_hibp_checker_fails_open_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kapalı")

    checker = HibpPwnedChecker(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert await checker.is_pwned("herhangi-bir-parola") is False


def test_settings_validation() -> None:
    good = base64.b64encode(MASTER).decode()
    s = Settings(database_url="postgresql://u:p@h/d", data_encryption_key=good)  # type: ignore[arg-type]
    assert s.database_url.startswith("postgresql+psycopg://") and s.libpq_url.startswith("postgresql://")
    assert s.pwned_check_enabled is False and s.product_name == "NetKâr"
    assert s.master_key == MASTER
    legacy = Settings(
        database_url="postgres://u:p@h/d", database_migration_url=None, data_encryption_key=good
    )  # type: ignore[arg-type]
    assert legacy.database_url.startswith("postgresql+psycopg://")
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://x", data_encryption_key="kisa")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://x", data_encryption_key=base64.b64encode(b"x" * 16).decode())  # type: ignore[arg-type]
