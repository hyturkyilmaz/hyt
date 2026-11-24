"""Anahtar araçları: `rewrap_keys` (KEK döndürme) ve `migrate_envelope` (v1 <-> v2 biçim geçişi).

Gerçek PostgreSQL 16 kullanılır. Araçlar RLS'yi aşabilen bir yönetici bağlantısıyla çalışır
(`DATABASE_ADMIN_URL`); testte bu, geçici kümenin superuser bağlantısıdır.
"""

from __future__ import annotations

import base64
import io
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.core.config import Settings
from app.core.crypto import DecryptionError, FieldCipher
from app.core.envelope import EnvelopeCipher, KeyRing
from app.models import MarketplaceAccount
from app.services.marketplace_accounts import decrypt_credentials, legacy_aad
from app.tools import migrate_envelope, rewrap_keys
from tests.conftest import TEST_KEY, Api, DatabaseInfo
from tests.test_envelope import new_key
from tests.test_marketplace_accounts import API_KEY, API_SECRET, URL, FakeTrendyol, body


@pytest.fixture
def trendyol() -> FakeTrendyol:
    return FakeTrendyol()


@pytest.fixture
def owner(trendyol: FakeTrendyol, make_api: Callable[..., Api]) -> Api:
    api = make_api(trendyol_client_factory=trendyol.factory)
    api.signup_and_login("owner@example.com", tenant="Mağaza A")
    return api


def spec_of(ring: KeyRing) -> str:
    return ",".join(f"{kid}:{base64.b64encode(key).decode()}" for kid, key in ring.items())


def env_for(database: DatabaseInfo, ring: KeyRing, **extra: str) -> dict[str, str]:
    return {
        "DATABASE_ADMIN_URL": database.admin_dsn(),
        "DATA_KEKS": spec_of(ring),
        "DATA_KEK_ACTIVE": ring.active,
        "DATA_ENCRYPTION_KEY": TEST_KEY,
        **extra,
    }


def tokens(admin_conn: psycopg.Connection) -> list[tuple[str, str, str]]:
    return [
        (str(r[0]), r[1], r[2])
        for r in admin_conn.execute(
            "SELECT id, api_key_encrypted, api_secret_encrypted FROM marketplace_accounts ORDER BY id"
        )
    ]


def account_from_db(admin_conn: psycopg.Connection, account_id: str) -> MarketplaceAccount:
    row = admin_conn.execute(
        "SELECT id, tenant_id, platform, seller_id, api_key_encrypted, api_secret_encrypted "
        "FROM marketplace_accounts WHERE id = %s",
        (account_id,),
    ).fetchone()
    assert row is not None
    return MarketplaceAccount(
        id=row[0], tenant_id=row[1], platform=row[2], seller_id=row[3],
        api_key_encrypted=row[4], api_secret_encrypted=row[5],
    )  # fmt: skip


def run_tool(module: Any, argv: list[str], environ: dict[str, str]) -> tuple[int, str]:
    out = io.StringIO()
    code = module.main(argv, environ, out)
    return code, out.getvalue()


@pytest.fixture
def old_ring(settings: Settings) -> KeyRing:
    return settings.key_ring


@pytest.fixture
def rotated_ring(old_ring: KeyRing) -> KeyRing:
    return KeyRing.parse(f"{spec_of(old_ring)},rot2:{new_key()}", "rot2")


def connect_two(owner: Api) -> list[str]:
    ids = [owner.post(URL, body()).json()["id"]]
    ids.append(
        owner.post(
            URL, body(seller_id="9999", api_key="BaskaAnahtar99999", api_secret="BaskaSir9999999")
        ).json()["id"]
    )
    return ids


# --- rewrap_keys ---------------------------------------------------------------------------------


def test_new_rows_are_envelope_encrypted_with_active_kid(
    owner: Api, admin_conn: psycopg.Connection, old_ring: KeyRing
) -> None:
    ids = connect_two(owner)
    for _, key_token, secret_token in tokens(admin_conn):
        for token in (key_token, secret_token):
            assert token.startswith(f"v2:{old_ring.active}:")
            assert API_KEY not in token and API_SECRET not in token
    # Her kayıt (ve her alan) ayrı DEK taşır
    wrapped = {t.split(":")[2] for _, k, s in tokens(admin_conn) for t in (k, s)}
    assert len(wrapped) == 4 and len(ids) == 2


def test_rewrap_dry_run_then_apply_then_idempotent(
    owner: Api,
    admin_conn: psycopg.Connection,
    database: DatabaseInfo,
    old_ring: KeyRing,
    rotated_ring: KeyRing,
) -> None:
    ids = connect_two(owner)
    before = tokens(admin_conn)
    env = env_for(database, rotated_ring)

    code, out = run_tool(rewrap_keys, [], env)  # varsayılan: kuru çalıştırma
    assert code == 0 and "DRY-RUN" in out and "2 kayıt taşınacak" in out
    assert tokens(admin_conn) == before  # hiçbir şey değişmedi

    code, out = run_tool(rewrap_keys, ["--apply"], env)
    assert code == 0 and "2 kayıt taşındı" in out
    after = tokens(admin_conn)
    assert all(k.startswith("v2:rot2:") and s.startswith("v2:rot2:") for _, k, s in after)
    # Veri gövdeleri aynı (düz metin açılıp yeniden şifrelenmedi), yalnız sarılı DEK ve kid değişti
    for (_, k0, s0), (_, k1, s1) in zip(before, after, strict=True):
        assert k0.split(":")[3] == k1.split(":")[3] and s0.split(":")[3] == s1.split(":")[3]
        assert k0.split(":")[2] != k1.split(":")[2]

    # Eski KEK halkadan çıkarılsa da çözülür
    only_new = EnvelopeCipher(
        KeyRing.parse(f"rot2:{base64.b64encode(dict(rotated_ring.items())['rot2']).decode()}", "rot2")
    )
    for account_id in ids:
        creds = decrypt_credentials(only_new, account_from_db(admin_conn, account_id))
        assert creds.api_key.get_secret_value() in {API_KEY, "BaskaAnahtar99999"}
    # Eski anahtarla artık çözülmez (kid halkada yok)
    with pytest.raises(DecryptionError):
        decrypt_credentials(EnvelopeCipher(old_ring), account_from_db(admin_conn, ids[0]))

    # İdempotent: ikinci çalıştırma hiçbir şeyi değiştirmez
    code, out = run_tool(rewrap_keys, ["--apply"], env)
    assert code == 0 and "0 kayıt taşındı" in out and "2 kayıt güncel" in out
    assert tokens(admin_conn) == after


def test_rewrap_writes_audit_rows_without_secrets(
    owner: Api,
    admin_conn: psycopg.Connection,
    database: DatabaseInfo,
    old_ring: KeyRing,
    rotated_ring: KeyRing,
) -> None:
    connect_two(owner)
    run_tool(rewrap_keys, ["--apply"], env_for(database, rotated_ring))
    rows = admin_conn.execute(
        "SELECT action, meta::text FROM audit_log WHERE action = 'marketplace_account.keys_rewrapped'"
    ).fetchall()
    assert len(rows) == 2
    assert all('"to": "rot2"' in meta and f'"from": "{old_ring.active}"' in meta for _, meta in rows)
    assert all(API_KEY not in meta and API_SECRET not in meta for _, meta in rows)


def test_rewrap_fails_closed_when_a_kid_is_missing_from_the_ring(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, old_ring: KeyRing
) -> None:
    connect_two(owner)
    before = tokens(admin_conn)
    stranger = KeyRing.parse(f"yeni:{new_key()}", "yeni")  # eski kid halkada yok
    code, out = run_tool(rewrap_keys, ["--apply"], env_for(database, stranger))
    assert code == 2 and "çözülemedi" in out and old_ring.active in out
    assert tokens(admin_conn) == before  # hiçbir satıra dokunulmadı


def test_rewrap_continues_after_a_bad_row_and_reports_it(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, rotated_ring: KeyRing
) -> None:
    ids = connect_two(owner)
    admin_conn.execute(
        "UPDATE marketplace_accounts SET api_key_encrypted = 'v2:rot2:AAAA:AAAA' WHERE id = %s", (ids[0],)
    )
    code, out = run_tool(rewrap_keys, ["--apply"], env_for(database, rotated_ring))
    assert code == 2 and "1 kayıt taşındı" in out and "1 kayıt başarısız" in out
    assert ids[0] in out and ids[1] not in out.split("başarısız")[-1]


def test_tools_refuse_roles_that_cannot_bypass_rls(
    owner: Api, database: DatabaseInfo, rotated_ring: KeyRing
) -> None:
    connect_two(owner)
    env = env_for(database, rotated_ring, DATABASE_ADMIN_URL=database.app_dsn())  # RLS'ye tabi rol
    for module in (rewrap_keys, migrate_envelope):
        code, out = run_tool(module, ["--apply"], env)
        assert code == 3 and "RLS" in out


@pytest.mark.parametrize("missing", ["DATABASE_ADMIN_URL", "DATA_KEKS", "DATA_KEK_ACTIVE"])
def test_rewrap_reports_missing_configuration(
    database: DatabaseInfo, old_ring: KeyRing, missing: str
) -> None:
    env = env_for(database, old_ring)
    env.pop(missing)
    code, out = run_tool(rewrap_keys, [], env)
    assert code == 3 and missing in out


def test_rewrap_rejects_bad_keyring_without_leaking_it(database: DatabaseInfo) -> None:
    secret = new_key()
    env = {
        "DATABASE_ADMIN_URL": database.admin_dsn(),
        "DATA_KEKS": f"bad kid:{secret}",
        "DATA_KEK_ACTIVE": "bad kid",
    }
    code, out = run_tool(rewrap_keys, [], env)
    assert code == 3 and secret not in out


def test_compare_and_set_skips_rows_changed_concurrently(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, old_ring: KeyRing
) -> None:
    from app.tools import common

    account_id = connect_two(owner)[0]
    (_, key_token, secret_token) = next(t for t in tokens(admin_conn) if t[0] == account_id)
    admin_conn.execute(
        "UPDATE marketplace_accounts SET api_key_encrypted = 'v2:x:AA:AA' WHERE id = %s", (account_id,)
    )
    with psycopg.connect(database.admin_dsn()) as conn:
        changed = common.compare_and_set(
            conn,
            account_id,
            (key_token, secret_token),
            ("n1", "n2"),
            "marketplace_account.keys_rewrapped",
            {},
        )
        assert changed is False
    stored = admin_conn.execute(
        "SELECT api_key_encrypted FROM marketplace_accounts WHERE id = %s", (account_id,)
    ).fetchone()
    assert stored == ("v2:x:AA:AA",)
    assert admin_conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'marketplace_account.keys_rewrapped'"
    ).fetchone() == (0,)


def test_revoked_rows_are_ignored(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, rotated_ring: KeyRing
) -> None:
    ids = connect_two(owner)
    assert owner.post(f"{URL}/{ids[0]}/revoke").status_code == 200
    code, out = run_tool(rewrap_keys, ["--apply"], env_for(database, rotated_ring))
    assert code == 0 and "1 kayıt taşındı" in out


# --- migrate_envelope: eski v1 biçimi <-> v2 -------------------------------------------------------


def to_legacy(admin_conn: psycopg.Connection, account_id: str) -> None:
    """Satırı eski v1 biçimine çevirir (FieldCipher + eski AAD): migrasyon öncesi veriyi taklit eder."""
    legacy = FieldCipher(base64.b64decode(TEST_KEY))
    admin_conn.execute(
        "UPDATE marketplace_accounts SET api_key_encrypted = %s, api_secret_encrypted = %s WHERE id = %s",
        (
            legacy.encrypt(API_KEY, legacy_aad(UUID(account_id), "api_key")),
            legacy.encrypt(API_SECRET, legacy_aad(UUID(account_id), "api_secret")),
            account_id,
        ),
    )


def test_legacy_v1_rows_are_still_readable(
    owner: Api, admin_conn: psycopg.Connection, old_ring: KeyRing
) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    to_legacy(admin_conn, account_id)
    assert all(t.startswith("v1:") for t in tokens(admin_conn)[0][1:])
    legacy = FieldCipher(base64.b64decode(TEST_KEY))
    account = account_from_db(admin_conn, account_id)
    with pytest.raises(DecryptionError):
        decrypt_credentials(EnvelopeCipher(old_ring), account)  # eski okuyucu yoksa çözülmez
    creds = decrypt_credentials(EnvelopeCipher(old_ring), account, legacy=legacy)
    assert creds.api_key.get_secret_value() == API_KEY and creds.api_secret.get_secret_value() == API_SECRET


def test_migrate_upgrade_dry_run_apply_idempotent_and_revert(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, old_ring: KeyRing
) -> None:
    ids = connect_two(owner)
    for account_id in ids:
        to_legacy(admin_conn, account_id)
    legacy_state = tokens(admin_conn)
    env = env_for(database, old_ring)

    code, out = run_tool(migrate_envelope, [], env)
    assert code == 0 and "DRY-RUN" in out and "2 kayıt dönüştürülecek" in out
    assert tokens(admin_conn) == legacy_state

    code, out = run_tool(migrate_envelope, ["--apply"], env)
    assert code == 0 and "2 kayıt dönüştürüldü" in out
    upgraded = tokens(admin_conn)
    envelope = EnvelopeCipher(old_ring)
    for account_id in ids:
        account = account_from_db(admin_conn, account_id)
        assert account.api_key_encrypted is not None and account.api_key_encrypted.startswith("v2:")
        creds = decrypt_credentials(envelope, account)  # eski okuyucu olmadan çözülür
        assert creds.api_key.get_secret_value() in {API_KEY, "BaskaAnahtar99999"} or creds.api_key

    code, out = run_tool(migrate_envelope, ["--apply"], env)  # idempotent
    assert code == 0 and "0 kayıt dönüştürüldü" in out and tokens(admin_conn) == upgraded

    # Geri alma: v2 -> v1 (veri silinmez, düz metin aynı kalır)
    code, out = run_tool(migrate_envelope, ["--apply", "--revert"], env)
    assert code == 0 and "2 kayıt dönüştürüldü" in out
    reverted = tokens(admin_conn)
    assert all(t.startswith("v1:") for _, k, s in reverted for t in (k, s))
    legacy = FieldCipher(base64.b64decode(TEST_KEY))
    creds = decrypt_credentials(envelope, account_from_db(admin_conn, ids[0]), legacy=legacy)
    assert creds.api_key.get_secret_value() == API_KEY
    code, out = run_tool(migrate_envelope, ["--apply", "--revert"], env)
    assert code == 0 and "0 kayıt dönüştürüldü" in out and tokens(admin_conn) == reverted


def test_migrate_handles_mixed_rows_and_reports_unreadable(
    owner: Api, admin_conn: psycopg.Connection, database: DatabaseInfo, old_ring: KeyRing
) -> None:
    ids = connect_two(owner)
    to_legacy(admin_conn, ids[0])
    admin_conn.execute(
        "UPDATE marketplace_accounts SET api_secret_encrypted = 'v1:AAAA' WHERE id = %s", (ids[1],)
    )
    code, out = run_tool(migrate_envelope, ["--apply"], env_for(database, old_ring))
    assert code == 2 and "1 kayıt dönüştürüldü" in out and "1 kayıt başarısız" in out and ids[1] in out
    # Bozuk satıra dokunulmadı
    assert admin_conn.execute(
        "SELECT api_secret_encrypted FROM marketplace_accounts WHERE id = %s", (ids[1],)
    ).fetchone() == ("v1:AAAA",)


def test_migrate_requires_legacy_key(database: DatabaseInfo, old_ring: KeyRing) -> None:
    env = env_for(database, old_ring)
    env.pop("DATA_ENCRYPTION_KEY")
    code, out = run_tool(migrate_envelope, [], env)
    assert code == 3 and "DATA_ENCRYPTION_KEY" in out
    env["DATA_ENCRYPTION_KEY"] = "***"
    code, out = run_tool(migrate_envelope, [], env)
    assert code == 3


def test_migrate_rejects_wrong_length_legacy_key_and_unreachable_database(
    database: DatabaseInfo, old_ring: KeyRing
) -> None:
    env = env_for(database, old_ring, DATA_ENCRYPTION_KEY=base64.b64encode(b"kisa").decode())
    code, out = run_tool(migrate_envelope, [], env)
    assert code == 3 and "32 bayt" in out
    env = env_for(database, old_ring, DATABASE_ADMIN_URL="postgresql://u:parola-gizli@127.0.0.1:1/x")
    code, out = run_tool(rewrap_keys, [], env)
    assert code == 3 and "parola-gizli" not in out


def test_tools_skip_rows_changed_concurrently(
    owner: Api,
    database: DatabaseInfo,
    old_ring: KeyRing,
    rotated_ring: KeyRing,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tools import common

    connect_two(owner)
    monkeypatch.setattr(common, "compare_and_set", lambda *a, **k: False)
    code, out = run_tool(rewrap_keys, ["--apply"], env_for(database, rotated_ring))
    assert code == 0 and "ATLANDI" in out and "0 kayıt taşındı" in out and "2 kayıt atlandı" in out
    code, out = run_tool(migrate_envelope, ["--apply", "--revert"], env_for(database, old_ring))
    assert code == 0 and "ATLANDI" in out and "2 kayıt atlandı" in out
