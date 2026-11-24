"""Zarf şifreleme (DEK/KEK, kid, AAD): birim testleri. Anahtarlar her çalıştırmada rastgele üretilir."""

from __future__ import annotations

import base64
import os

import pytest

from app.core.config import Settings
from app.core.crypto import DecryptionError
from app.core.envelope import EnvelopeCipher, KeyRing, KeyRingError


def new_key() -> str:
    """Rastgele 32 baytlık anahtarın base64 gösterimi (test için; repoda sabit sır yok)."""
    return base64.b64encode(os.urandom(32)).decode()


def ring(*kids: str, active: str | None = None) -> KeyRing:
    spec = ",".join(f"{kid}:{new_key()}" for kid in kids)
    return KeyRing.parse(spec, active or kids[0])


def with_active(source: KeyRing, extra: str, active: str) -> KeyRing:
    """Aynı anahtarlara yeni bir kid ekler (döndürme senaryosu)."""
    spec = ",".join(f"{kid}:{base64.b64encode(key).decode()}" for kid, key in source.items())
    return KeyRing.parse(f"{spec},{extra}:{new_key()}", active)


AAD = b"marketplace_accounts:v2:t:trendyol:2738:id:api_key"


def test_roundtrip_and_token_format() -> None:
    cipher = EnvelopeCipher(ring("k1"))
    token = cipher.encrypt("gizli-deger", AAD)
    parts = token.split(":")
    assert len(parts) == 4 and parts[0] == "v2" and parts[1] == "k1"
    assert "gizli-deger" not in token
    assert cipher.decrypt(token, AAD) == "gizli-deger"
    assert cipher.key_id(token) == "k1"
    assert EnvelopeCipher.is_envelope(token) and not EnvelopeCipher.is_envelope("v1:abc")


def test_each_record_gets_its_own_dek_and_nonce() -> None:
    cipher = EnvelopeCipher(ring("k1"))
    first, second = cipher.encrypt("ayni", AAD), cipher.encrypt("ayni", AAD)
    assert first != second
    # Sarılı DEK ve veri gövdesi farklı: veri anahtarı kayıt başına rastgele
    assert first.split(":")[2] != second.split(":")[2]
    assert first.split(":")[3] != second.split(":")[3]


@pytest.mark.parametrize(
    "other_aad",
    [
        b"marketplace_accounts:v2:t2:trendyol:2738:id:api_key",  # kiracı
        b"marketplace_accounts:v2:t:trendyol:9999:id:api_key",  # satıcı
        b"marketplace_accounts:v2:t:trendyol:2738:id:api_secret",  # alan
        b"",
    ],
)
def test_wrong_aad_is_rejected(other_aad: bytes) -> None:
    cipher = EnvelopeCipher(ring("k1"))
    token = cipher.encrypt("x", AAD)
    with pytest.raises(DecryptionError):
        cipher.decrypt(token, other_aad)


def test_tampering_is_rejected() -> None:
    cipher = EnvelopeCipher(ring("k1", "k2"))
    version, kid, wrapped, body = cipher.encrypt("x", AAD).split(":")

    def flip(b64: str) -> str:
        raw = bytearray(base64.b64decode(b64))
        raw[-1] ^= 1
        return base64.b64encode(bytes(raw)).decode()

    for bad in (
        f"{version}:{kid}:{flip(wrapped)}:{body}",  # sarılı DEK bozuk
        f"{version}:{kid}:{wrapped}:{flip(body)}",  # şifreli veri bozuk
        f"{version}:k2:{wrapped}:{body}",  # kid değiştirildi (başka KEK ile sarma açılmaz)
        f"{version}:{kid}:{wrapped}",  # eksik parça
        f"{version}:{kid}:%%%:{body}",  # geçersiz base64
        f"v3:{kid}:{wrapped}:{body}",  # bilinmeyen sürüm
        f"{version}:bad kid:{wrapped}:{body}",
        "",
        "v1:abcd",
    ):
        with pytest.raises(DecryptionError):
            cipher.decrypt(bad, AAD)


def test_unknown_kid_is_decryption_error_without_leaking_secrets() -> None:
    writer = EnvelopeCipher(ring("kA"))
    token = writer.encrypt("x", AAD)
    reader = EnvelopeCipher(ring("kB"))
    with pytest.raises(DecryptionError) as info:
        reader.decrypt(token, AAD)
    assert "x" not in str(info.value).replace("bilinmeyen", "")  # düz metin mesajda yok


def test_rotation_old_kid_still_decrypts_and_rewrap_moves_to_active() -> None:
    old_ring = ring("k1")
    old = EnvelopeCipher(old_ring)
    token = old.encrypt("deger", AAD)

    rotated_ring = with_active(old_ring, "k2", active="k2")
    rotated = EnvelopeCipher(rotated_ring)
    assert rotated.decrypt(token, AAD) == "deger"  # eski kid hâlâ halkada
    new_token = rotated.encrypt("yeni", AAD)
    assert rotated.key_id(new_token) == "k2"

    moved = rotated.rewrap(token)
    assert rotated.key_id(moved) == "k2" and moved != token
    # Veri gövdesi aynı kalır, yalnız sarılı DEK ve kid değişir (düz metin hiç açılmaz)
    assert moved.split(":")[3] == token.split(":")[3]
    # k1 halkadan çıkarılınca da çözülür
    only_new = KeyRing.parse(f"k2:{base64.b64encode(dict(rotated_ring.items())['k2']).decode()}", "k2")
    assert EnvelopeCipher(only_new).decrypt(moved, AAD) == "deger"
    # ...ama eski token artık çözülemez
    with pytest.raises(DecryptionError):
        EnvelopeCipher(only_new).decrypt(token, AAD)


def test_rewrap_is_idempotent_for_active_kid() -> None:
    cipher = EnvelopeCipher(ring("k1"))
    token = cipher.encrypt("x", AAD)
    assert cipher.rewrap(token) == token
    assert cipher.rewrap(cipher.rewrap(token)) == token


def test_rewrap_with_unknown_kid_fails() -> None:
    token = EnvelopeCipher(ring("kA")).encrypt("x", AAD)
    with pytest.raises(DecryptionError):
        EnvelopeCipher(ring("kB")).rewrap(token)


def test_keyring_parse_validation() -> None:
    good = new_key()
    for spec, active in (
        ("", "k1"),
        (f"k1:{good}", "yok"),  # aktif kid halkada değil
        (f"k1:{good},k1:{good}", "k1"),  # yinelenen kid
        (f"k1:{base64.b64encode(b'kisa').decode()}", "k1"),  # 32 bayt değil
        ("k1:***", "k1"),  # base64 değil
        (f"bad kid:{good}", "bad kid"),
        (f"k:1:{good}", "k"),  # çok fazla ayraç -> geçersiz base64 veya kid
        (f"{'x' * 33}:{good}", "x" * 33),  # kid çok uzun
        ("k1", "k1"),
    ):
        with pytest.raises(KeyRingError) as info:
            KeyRing.parse(spec, active)
        assert good not in str(info.value)  # anahtar değeri hata metninde yok


def test_keyring_repr_hides_key_material() -> None:
    key = new_key()
    kr = KeyRing.parse(f"k1:{key}", "k1")
    assert key not in repr(kr) and key not in str(kr) and "k1" in repr(kr)
    assert kr.active == "k1" and kr.kids() == ("k1",)


def test_empty_plaintext_and_unicode_roundtrip() -> None:
    cipher = EnvelopeCipher(ring("k1"))
    for value in ("", "Şişli-çğüöı-İ", "a" * 5000):
        assert cipher.decrypt(cipher.encrypt(value, AAD), AAD) == value


# --- Settings entegrasyonu ---------------------------------------------------------------------


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql://u:p@localhost/db",
        "data_encryption_key": new_key(),
        "email_backend": "memory",
    }
    base.update(kw)
    return Settings(**base)  # type: ignore[arg-type]


def test_settings_parses_keks_and_active() -> None:
    k1, k2 = new_key(), new_key()
    s = _settings(data_keks=f"k1:{k1}, k2:{k2}", data_kek_active="k2")
    kr = s.key_ring
    assert kr.active == "k2" and kr.kids() == ("k1", "k2")
    assert k1 not in repr(s) and k2 not in repr(s)  # SecretStr


@pytest.mark.parametrize(
    "kwargs",
    [
        {"data_keks": "k1:***", "data_kek_active": "k1"},
        {"data_keks": f"k1:{base64.b64encode(b'kisa').decode()}", "data_kek_active": "k1"},
        {"data_keks": f"k1:{base64.b64encode(os.urandom(32)).decode()}"},  # aktif kid yok
        {"data_kek_active": "k1"},  # anahtar listesi yok
    ],
)
def test_settings_rejects_bad_kek_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="DATA_KEK"):
        _settings(**kwargs)


def test_prod_requires_explicit_kek_and_dev_falls_back_to_derived_key() -> None:
    # Not: prod ayrıca e-posta arka ucu kuralına takılır; yalnız DATA_KEKS iletisinin varlığına bakılır.
    with pytest.raises(ValueError, match="DATA_KEKS"):
        _settings(environment="prod")
    with pytest.raises(ValueError) as info:
        _settings(environment="prod", data_keks=f"k1:{new_key()}", data_kek_active="k1")
    assert "DATA_KEKS" not in str(info.value)
    dev = _settings(environment="dev")
    assert dev.key_ring.active == "dev-derived"  # yalnız prod dışı kolaylık
