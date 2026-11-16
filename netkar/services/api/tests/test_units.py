"""Birim testler: şifreleme, parola, token, TOTP, e-posta, HIBP, ayarlar."""

from __future__ import annotations

import base64
import json
import os
import time
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
from app.core.email import EmailMessage, FileEmailSender, InMemoryOutbox, OutboxSecurityError
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


def _mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def _prepare_loose(directory: Path) -> Path:
    path = directory / "outbox.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)
    directory.chmod(0o755)
    return path


def _rotated_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("outbox.jsonl.*"))


async def test_file_sender_creates_private_file_and_directory(tmp_path: Path) -> None:
    """DT-20: dosya 0600, yeni dizin 0700 (umask gevşek olsa da)."""
    old = os.umask(0o000)
    try:
        path = tmp_path / "yeni" / "ic" / "derin" / "outbox.jsonl"
        await FileEmailSender(str(path)).send(EmailMessage("a@example.com", "k", "g"))
    finally:
        os.umask(old)
    assert _mode(path) == 0o600
    # L-1: oluşturulan HER dizin 0700 (ara dizinler dahil); var olan tmp_path'e dokunulmaz.
    for directory in (path.parent, path.parent.parent, tmp_path / "yeni"):
        assert _mode(directory) == 0o700
    assert tmp_path / "yeni" == path.parent.parent.parent


def _symlink_to_target(tmp_path: Path) -> tuple[Path, Path]:
    target = tmp_path / "hedef.txt"
    target.write_text("dokunma", encoding="utf-8")
    target.chmod(0o644)
    path = tmp_path / "outbox.jsonl"
    path.symlink_to(target)
    return path, target


def test_file_sender_refuses_symlink_at_active_path_at_construction(tmp_path: Path) -> None:
    """L-2: etkin yoldaki simgesel bağ izlenmez; hedefin içeriği ve izni değişmez."""
    path, target = _symlink_to_target(tmp_path)
    with pytest.raises(OutboxSecurityError, match="simgesel bağ"):
        FileEmailSender(str(path))
    assert target.read_text("utf-8") == "dokunma" and _mode(target) == 0o644


async def test_file_sender_refuses_symlink_created_after_construction(tmp_path: Path) -> None:
    sender = FileEmailSender(str(tmp_path / "outbox.jsonl"))
    _, target = _symlink_to_target(tmp_path)
    with pytest.raises(OutboxSecurityError, match="simgesel bağ"):
        await sender.send(EmailMessage("a@example.com", "k", "g"))
    assert target.read_text("utf-8") == "dokunma" and _mode(target) == 0o644


async def test_file_sender_refuses_hardlinked_active_file(tmp_path: Path) -> None:
    target = tmp_path / "baska.txt"
    target.write_text("dokunma", encoding="utf-8")
    target.chmod(0o644)
    path = tmp_path / "outbox.jsonl"
    os.link(target, path)
    with pytest.raises(OutboxSecurityError, match="güvenli değil"):
        FileEmailSender(str(path))
    (tmp_path / "ok").mkdir()
    sender = FileEmailSender(str(tmp_path / "ok" / "o.jsonl"))
    os.link(target, tmp_path / "ok" / "o.jsonl")
    with pytest.raises(OutboxSecurityError, match="güvenli değil"):
        await sender.send(EmailMessage("a@example.com", "k", "g"))
    assert target.read_text("utf-8") == "dokunma" and _mode(target) == 0o644


def test_file_sender_refuses_non_regular_active_path(tmp_path: Path) -> None:
    (tmp_path / "outbox.jsonl").mkdir()
    with pytest.raises(OSError):  # dizin yazmaya açılamaz
        FileEmailSender(str(tmp_path / "outbox.jsonl"))


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777, 0o722])
def test_file_sender_hardened_refuses_group_or_other_writable_parent(tmp_path: Path, mode: int) -> None:
    parent = tmp_path / "paylasilan"
    parent.mkdir()
    parent.chmod(mode)
    with pytest.raises(OutboxSecurityError, match="yazılabilir"):
        FileEmailSender(str(parent / "outbox.jsonl"), hardened=True)
    FileEmailSender(str(parent / "outbox.jsonl"))  # sertleşmemiş ortamda serbest


def test_file_sender_hardened_accepts_private_or_missing_parent(tmp_path: Path) -> None:
    ok = tmp_path / "ozel"
    ok.mkdir()
    ok.chmod(0o750)
    FileEmailSender(str(ok / "outbox.jsonl"), hardened=True)
    FileEmailSender(str(tmp_path / "yok" / "outbox.jsonl"), hardened=True)


def test_file_sender_constructor_tightens_existing_active_file(tmp_path: Path) -> None:
    path = _prepare_loose(tmp_path)
    FileEmailSender(str(path))
    assert _mode(path) == 0o600


def test_rotated_name_match_is_exact_and_ascii(tmp_path: Path) -> None:
    """I-3: sonuna eklenmiş ya da Unicode rakamlı adlar bu arka ucun dosyası sayılmaz, silinmez."""
    path = tmp_path / "outbox.jsonl"
    old = time.time() - 40 * 86400
    names = [
        "outbox.jsonl.20260101T000000Z-0001.bak",
        "outbox.jsonl.20260101T000000Z-0001\n",
        "outbox.jsonl.\u0662\u0660260101T000000Z-0001",
    ]
    for name in names:
        (tmp_path / name).write_text("x", encoding="utf-8")
        os.utime(tmp_path / name, (old, old))
    FileEmailSender(str(path), retention_days=7)
    assert all((tmp_path / name).exists() for name in names)


async def test_file_sender_tightens_existing_file_but_keeps_existing_directory(tmp_path: Path) -> None:
    path = _prepare_loose(tmp_path)
    await FileEmailSender(str(path)).send(EmailMessage("a@example.com", "k", "g"))
    assert _mode(path) == 0o600
    assert _mode(tmp_path) == 0o755  # var olan dizinin izni değiştirilmez


async def test_file_sender_rotates_by_size_and_keeps_rotated_files_private(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    sender = FileEmailSender(str(path), max_bytes=200, max_files=10)
    for i in range(6):
        await sender.send(EmailMessage("a@example.com", f"k{i}", "x" * 80))
    rotated = _rotated_files(tmp_path)
    assert rotated and all(p.name.startswith("outbox.jsonl.") for p in rotated)
    assert all(_mode(p) == 0o600 for p in rotated)
    assert path.stat().st_size < 400  # etkin dosya sınırlı kalır
    lines = [
        json.loads(line)["subject"] for p in [*rotated, path] for line in p.read_text("utf-8").splitlines()
    ]
    assert sorted(lines) == [f"k{i}" for i in range(6)]  # döndürme kayıt kaybetmez (sınır içinde)


async def test_file_sender_prunes_rotated_files_by_count_oldest_first(tmp_path: Path) -> None:
    path = tmp_path / "outbox.jsonl"
    sender = FileEmailSender(str(path), max_bytes=100, max_files=2, retention_days=365)
    for i in range(8):
        await sender.send(EmailMessage("a@example.com", f"k{i}", "y" * 90))
    rotated = _rotated_files(tmp_path)
    assert len(rotated) == 2
    subjects = {json.loads(line)["subject"] for p in rotated for line in p.read_text("utf-8").splitlines()}
    assert "k0" not in subjects  # en eski kayıtlar silindi


async def test_file_sender_prunes_rotated_files_by_age_only_its_own(tmp_path: Path) -> None:
    """Yalnız bu arka ucun döndürdüğü kalıptaki düz dosyalar silinir; başkası ve etkin dosya kalır."""
    path = tmp_path / "outbox.jsonl"
    old = time.time() - 30 * 86400
    own_old = tmp_path / "outbox.jsonl.20260101T000000Z-0001"
    own_new = tmp_path / "outbox.jsonl.20261115T000000Z-0001"
    foreign = tmp_path / "outbox.jsonl.yedek"  # kalıba uymaz
    other = tmp_path / "baska.log"
    link_target = tmp_path / "hedef.txt"
    link = tmp_path / "outbox.jsonl.20260101T000000Z-0002"  # kalıba uyan ama simgesel bağ
    for f in (own_old, own_new, foreign, other, link_target):
        f.write_text("x", encoding="utf-8")
    link.symlink_to(link_target)
    for f in (own_old, foreign, other, link_target):
        os.utime(f, (old, old))
    path.write_text("etkin\n", encoding="utf-8")
    os.utime(path, (old, old))
    sender = FileEmailSender(str(path), retention_days=7)  # kurucu da temizler
    assert not own_old.exists()
    assert own_new.exists() and foreign.exists() and other.exists() and link_target.exists()
    assert link.is_symlink() and path.exists()
    await sender.send(EmailMessage("a@example.com", "k", "g"))  # gönderim de temizler, hata vermez
    assert path.read_text("utf-8").startswith("etkin")


async def test_file_sender_prune_failure_does_not_break_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "outbox.jsonl"
    sender = FileEmailSender(str(path))

    def boom(self: Path, **_: object) -> None:
        raise PermissionError("silinemez")

    (tmp_path / "outbox.jsonl.20200101T000000Z-0001").write_text("x", encoding="utf-8")
    os.utime(tmp_path / "outbox.jsonl.20200101T000000Z-0001", (1, 1))
    monkeypatch.setattr(Path, "unlink", boom)
    with caplog.at_level("WARNING"):
        await sender.send(EmailMessage("a@example.com", "k", "g"))
    assert path.exists() and "temizliği yapılamadı" in caplog.text


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
