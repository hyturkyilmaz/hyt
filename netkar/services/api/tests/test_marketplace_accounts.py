"""/v1/marketplace-accounts: bağlantı doğrulama, şifreli saklama, maskeleme, RLS, iptal ve audit.

Trendyol çağrıları httpx.MockTransport ile sahtelenir (gerçek ağ yok).
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.crypto import DecryptionError, FieldCipher
from app.integrations.trendyol import TrendyolClient, TrendyolConfig, TrendyolCredentials
from app.integrations.trendyol.ratelimit import RateLimiterRegistry
from app.models import MarketplaceAccount
from app.services.marketplace_accounts import decrypt_credentials
from tests.conftest import TEST_KEY, Api, DatabaseInfo
from tests.test_rls_idor import app_tx
from tests.trendyol_helpers import FakeTime, json_response, load_fixture

API_KEY = "AnahtarDegeri12345"
API_SECRET = "SirDegeriGizli67890"
SELLER = "2738"
URL = "/v1/marketplace-accounts"


@dataclass
class FakeTrendyol:
    """Sahte Trendyol: durum kodunu ve çağrı kaydını tutar."""

    status: int = 200
    network_error: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    requests: list[httpx.Request] = field(default_factory=list)
    fake: FakeTime = field(default_factory=FakeTime)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.network_error:
            raise httpx.ConnectError("sahte bağlantı hatası")
        if self.status == 200:
            return json_response(load_fixture("inventory_and_price.json"))
        return json_response({"exception": "sahte"}, self.status, self.headers)

    def factory(self, credentials: TrendyolCredentials, *, max_retries: int | None = None) -> TrendyolClient:
        retries = 4 if max_retries is None else min(4, max_retries)
        return TrendyolClient(
            credentials,
            TrendyolConfig(max_retries=retries),
            transport=httpx.MockTransport(self.handler),
            limiter=RateLimiterRegistry(clock=self.fake.monotonic, sleep=self.fake.sleep),
            sleep=self.fake.sleep,
            monotonic=self.fake.monotonic,
        )


@pytest.fixture
def trendyol() -> FakeTrendyol:
    return FakeTrendyol()


@pytest.fixture
def make_ty_api(trendyol: FakeTrendyol, make_api: Callable[..., Api]) -> Callable[..., Api]:
    def _make(**overrides: Any) -> Api:
        return make_api(trendyol_client_factory=trendyol.factory, **overrides)

    return _make


@pytest.fixture
def owner(make_ty_api: Callable[..., Api]) -> Api:
    api = make_ty_api()
    api.signup_and_login("owner@example.com", tenant="Mağaza A")
    return api


def body(**kw: Any) -> dict[str, Any]:
    return {"seller_id": SELLER, "api_key": API_KEY, "api_secret": API_SECRET, **kw}


def row(admin_conn: psycopg.Connection, account_id: str) -> dict[str, Any]:
    cur = admin_conn.execute("SELECT * FROM marketplace_accounts WHERE id = %s", (account_id,))
    cols = [d.name for d in cur.description or []]
    values = cur.fetchone()
    assert values is not None
    return dict(zip(cols, values, strict=True))


def cipher() -> FieldCipher:
    return FieldCipher(base64.b64decode(TEST_KEY))


# --- Ekleme ----------------------------------------------------------------------------------


def test_connect_validates_with_trendyol_and_stores_encrypted(
    owner: Api, trendyol: FakeTrendyol, admin_conn: psycopg.Connection
) -> None:
    r = owner.post(URL, body())
    assert r.status_code == 201, r.text
    data = r.json()
    assert set(data) == {
        "id", "platform", "seller_id", "status", "api_key_last4",
        "last_validated_at", "created_at", "updated_at", "revoked_at",
    }  # fmt: skip
    assert data["platform"] == "trendyol" and data["seller_id"] == SELLER and data["status"] == "active"
    assert data["api_key_last4"] == API_KEY[-4:] and data["last_validated_at"] and data["revoked_at"] is None
    # Yanıtta sır yok
    assert API_KEY not in r.text and API_SECRET not in r.text

    # Trendyol'a tek hafif doğrulama çağrısı, doğru kimlikle gitti
    assert len(trendyol.requests) == 1
    request = trendyol.requests[0]
    assert request.url.path == f"/integration/product/sellers/{SELLER}/products/approved/inventory-and-price"
    assert request.headers["User-Agent"] == f"{SELLER} - NetKar"
    assert (
        request.headers["Authorization"]
        == "Basic " + base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
    )

    stored = row(admin_conn, data["id"])
    assert stored["status"] == "active" and stored["platform"] == "trendyol" and stored["seller_id"] == SELLER
    assert stored["created_by"] is not None and stored["last_validated_at"] is not None

    audit = admin_conn.execute(
        "SELECT action, target, meta FROM audit_log WHERE action LIKE 'marketplace_account.%'"
    ).fetchall()
    assert audit == [
        ("marketplace_account.connected", data["id"], {"platform": "trendyol", "total_products": 4321})
    ]


def test_keys_are_encrypted_in_database_raw_sql(owner: Api, admin_conn: psycopg.Connection) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    stored = row(admin_conn, account_id)
    for column in ("api_key_encrypted", "api_secret_encrypted"):
        assert stored[column].startswith("v1:")
        assert API_KEY not in stored[column] and API_SECRET not in stored[column]
    assert stored["api_key_encrypted"] != stored["api_secret_encrypted"]
    # Satırın tamamı (metin gösterimi) ham sırları içermez
    dump = admin_conn.execute(
        "SELECT row_to_json(m)::text FROM marketplace_accounts m WHERE id = %s", (account_id,)
    ).fetchone()
    assert dump is not None and API_KEY not in dump[0] and API_SECRET not in dump[0]
    # Tüm veritabanı sızıntı taraması: audit_log dahil hiçbir tabloda düz metin yok
    audit_dump = admin_conn.execute("SELECT string_agg(a::text, ' ') FROM audit_log a").fetchone()
    assert (
        audit_dump is not None
        and API_KEY not in (audit_dump[0] or "")
        and API_SECRET not in (audit_dump[0] or "")
    )


async def test_ciphertext_roundtrip_and_aad_binding(owner: Api, admin_conn: psycopg.Connection) -> None:
    first = owner.post(URL, body()).json()["id"]
    second = owner.post(
        URL, body(seller_id="9999", api_key="BaskaAnahtar99999", api_secret="BaskaSir9999999")
    ).json()["id"]
    c = cipher()
    stored = row(admin_conn, first)
    account = MarketplaceAccount(
        id=UUID(first), seller_id=SELLER, api_key_encrypted=stored["api_key_encrypted"],
        api_secret_encrypted=stored["api_secret_encrypted"],
    )  # fmt: skip
    creds = decrypt_credentials(c, account)
    assert creds.seller_id == SELLER
    assert creds.api_key.get_secret_value() == API_KEY and creds.api_secret.get_secret_value() == API_SECRET
    # Aynı şifreli değer başka satıra kopyalanırsa çözülemez (AAD satır kimliğine bağlı)
    moved = MarketplaceAccount(
        id=UUID(second), seller_id=SELLER, api_key_encrypted=stored["api_key_encrypted"],
        api_secret_encrypted=stored["api_secret_encrypted"],
    )  # fmt: skip
    with pytest.raises(DecryptionError):
        decrypt_credentials(c, moved)
    # İptal edilmiş (boş) satırda anahtar yok
    with pytest.raises(ValueError):
        decrypt_credentials(c, MarketplaceAccount(id=UUID(first), seller_id=SELLER))


def test_seller_id_may_be_sent_as_number(owner: Api) -> None:
    r = owner.post(URL, {"seller_id": 2738, "api_key": API_KEY, "api_secret": API_SECRET})
    assert r.status_code == 201 and r.json()["seller_id"] == "2738"


@pytest.mark.parametrize(
    ("status", "http_status", "slug"),
    [
        (401, 422, "marketplace-credentials-rejected"),
        (403, 422, "marketplace-access-denied"),
        (429, 503, "marketplace-busy"),
        (500, 502, "marketplace-unavailable"),
        (503, 502, "marketplace-unavailable"),
        (404, 502, "marketplace-unavailable"),
    ],
)
def test_failed_validation_does_not_save(
    owner: Api,
    trendyol: FakeTrendyol,
    admin_conn: psycopg.Connection,
    status: int,
    http_status: int,
    slug: str,
) -> None:
    trendyol.status = status
    r = owner.post(URL, body())
    assert r.status_code == http_status, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"] == f"urn:netkar:problem:{slug}"
    assert API_KEY not in r.text and API_SECRET not in r.text and "sahte" not in r.text
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
    # Başarısız deneme denetim izine yazılır (sırsız)
    audit = admin_conn.execute(
        "SELECT action, meta FROM audit_log WHERE action LIKE 'marketplace_account.%'"
    ).fetchall()
    assert len(audit) == 1 and audit[0][0] == "marketplace_account.validation_failed"
    assert API_KEY not in str(audit) and API_SECRET not in str(audit)
    # 429 için istemciye bekleme ipucu
    if status == 429:
        assert r.headers["retry-after"] == "30"


def test_validation_does_not_retry_on_401_and_retries_once_on_5xx(owner: Api, trendyol: FakeTrendyol) -> None:
    trendyol.status = 401
    assert owner.post(URL, body()).status_code == 422
    assert len(trendyol.requests) == 1  # 401'de yeniden deneme yok
    trendyol.requests.clear()
    trendyol.status = 503
    assert owner.post(URL, body()).status_code == 502
    assert len(trendyol.requests) == 2  # istek içinde en fazla 1 yeniden deneme


def test_network_error_maps_to_502(
    owner: Api, trendyol: FakeTrendyol, admin_conn: psycopg.Connection
) -> None:
    trendyol.network_error = True
    r = owner.post(URL, body())
    assert r.status_code == 502 and r.json()["type"].endswith("marketplace-unavailable")
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)


@pytest.mark.parametrize(
    "payload",
    [
        {"seller_id": "abc", "api_key": API_KEY, "api_secret": API_SECRET},
        {"seller_id": "0123", "api_key": API_KEY, "api_secret": API_SECRET},
        {"seller_id": "2738", "api_key": "kisa", "api_secret": API_SECRET},
        {"seller_id": "2738", "api_key": API_KEY},
        {"seller_id": "2738", "api_key": API_KEY, "api_secret": API_SECRET, "extra": 1},
        {"seller_id": "2738", "api_key": "x" * 300, "api_secret": API_SECRET},
    ],
)
def test_invalid_bodies_are_rejected_without_trendyol_call(
    owner: Api, trendyol: FakeTrendyol, payload: dict[str, Any]
) -> None:
    r = owner.post(URL, payload)
    assert r.status_code == 422 and r.json()["type"].endswith("validation-error")
    assert API_KEY not in r.text and API_SECRET not in r.text
    assert trendyol.requests == []


@pytest.mark.parametrize("bad", ["anahtar:iki", "anahtar bosluk 1", "anahtarçğü12345"])
def test_malformed_key_characters_are_rejected_before_any_call(
    owner: Api, trendyol: FakeTrendyol, bad: str
) -> None:
    r = owner.post(URL, body(api_key=bad))
    assert r.status_code == 422 and r.json()["type"].endswith("marketplace-credentials-malformed")
    assert bad not in r.text and trendyol.requests == []


def test_duplicate_active_account_is_conflict_without_trendyol_call(
    owner: Api, trendyol: FakeTrendyol, admin_conn: psycopg.Connection
) -> None:
    assert owner.post(URL, body()).status_code == 201
    trendyol.requests.clear()
    r = owner.post(URL, body())
    assert r.status_code == 409 and r.json()["type"].endswith("marketplace-account-exists")
    assert trendyol.requests == []
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (1,)


def test_invalid_account_can_be_reconnected_in_place(owner: Api, admin_conn: psycopg.Connection) -> None:
    first = owner.post(URL, body()).json()
    admin_conn.execute("UPDATE marketplace_accounts SET status = 'invalid'")
    r = owner.post(URL, body(api_key="YeniAnahtar123456", api_secret="YeniSir12345678"))
    assert r.status_code == 201 and r.json()["id"] == first["id"] and r.json()["status"] == "active"
    assert r.json()["api_key_last4"] == "3456"
    assert admin_conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (1,)
    stored = row(admin_conn, first["id"])
    creds = decrypt_credentials(
        cipher(),
        MarketplaceAccount(
            id=UUID(first["id"]), seller_id=SELLER, api_key_encrypted=stored["api_key_encrypted"],
            api_secret_encrypted=stored["api_secret_encrypted"],
        ),
    )  # fmt: skip
    assert creds.api_key.get_secret_value() == "YeniAnahtar123456"
    actions = [
        a[0]
        for a in admin_conn.execute(
            "SELECT action FROM audit_log WHERE action LIKE 'marketplace_account.%' ORDER BY id"
        )
    ]
    assert actions == ["marketplace_account.connected", "marketplace_account.reconnected"]


def test_same_seller_can_be_added_again_after_revoke(owner: Api, admin_conn: psycopg.Connection) -> None:
    first = owner.post(URL, body()).json()["id"]
    assert owner.post(f"{URL}/{first}/revoke").status_code == 200
    second = owner.post(URL, body())
    assert second.status_code == 201 and second.json()["id"] != first
    statuses = sorted(r[0] for r in admin_conn.execute("SELECT status FROM marketplace_accounts"))
    assert statuses == ["active", "revoked"]  # eski satır geçmiş olarak kalır


# --- Yetki, CSRF, sınırlar -------------------------------------------------------------------


def test_requires_login_and_csrf(make_ty_api: Callable[..., Api], owner: Api) -> None:
    anonymous = make_ty_api()
    assert anonymous.post(URL, body()).status_code == 401
    assert anonymous.get(URL).status_code == 401
    assert owner.post(URL, body(), csrf=False).status_code == 403  # CSRF başlığı yok


def test_viewer_can_list_but_not_create_or_revoke(owner: Api, admin_conn: psycopg.Connection) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert owner.post(URL, body(seller_id="555")).status_code == 403
    assert owner.post(f"{URL}/{account_id}/revoke").status_code == 403
    listed = owner.get(URL)
    assert listed.status_code == 200 and [a["id"] for a in listed.json()] == [account_id]


def test_admin_role_can_connect(owner: Api, admin_conn: psycopg.Connection) -> None:
    admin_conn.execute("UPDATE memberships SET role = 'admin'")
    assert owner.post(URL, body()).status_code == 201


def test_body_size_limit(owner: Api) -> None:
    r = owner.post(URL, body(api_key="a" * 20_000))
    assert r.status_code == 413 and r.json()["type"].endswith("payload-too-large")


def test_tenant_rate_limit(make_ty_api: Callable[..., Api], trendyol: FakeTrendyol) -> None:
    api = make_ty_api(rate_limit_marketplace_tenant=2)
    api.signup_and_login("limit@example.com")
    trendyol.status = 401
    assert [api.post(URL, body()).status_code for _ in range(2)] == [422, 422]
    r = api.post(URL, body())
    assert r.status_code == 429 and "retry-after" in r.headers
    assert len(trendyol.requests) == 2  # sınır aşılınca Trendyol'a gidilmez


def test_ip_rate_limit_applies_before_body_parsing(
    make_ty_api: Callable[..., Api], trendyol: FakeTrendyol
) -> None:
    api = make_ty_api(rate_limit_marketplace_ip=1)
    api.signup_and_login("iplimit@example.com")
    trendyol.status = 401
    assert api.post(URL, body()).status_code == 422
    r = api.post(URL, {"geçersiz": "gövde"})
    assert r.status_code == 429  # gövde doğrulanmadan reddedildi


# --- Listeleme ve maskeleme ------------------------------------------------------------------


def test_list_is_masked_and_newest_first(owner: Api) -> None:
    a = owner.post(URL, body()).json()["id"]
    b = owner.post(URL, body(seller_id="3333")).json()["id"]
    r = owner.get(URL)
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [b, a]
    assert API_KEY not in r.text and API_SECRET not in r.text
    assert all("encrypted" not in key and "secret" not in key for item in r.json() for key in item)
    assert {x["api_key_last4"] for x in r.json()} == {API_KEY[-4:]}


def test_list_never_selects_encrypted_columns() -> None:
    """Şifreli sütunlar `deferred`: ORM listeleme sorgusuna hiç girmez."""
    sql = str(select(MarketplaceAccount))
    assert "api_key_encrypted" not in sql and "api_secret_encrypted" not in sql


# --- RLS / IDOR ------------------------------------------------------------------------------


@pytest.fixture
def two_accounts(make_ty_api: Callable[..., Api]) -> tuple[Api, str, Api, str]:
    a = make_ty_api()
    a.signup_and_login("a@example.com", tenant="Mağaza A")
    b = make_ty_api()
    b.signup_and_login("b@example.com", tenant="Mağaza B")
    a_id = a.post(URL, body()).json()["id"]
    b_id = b.post(
        URL, body(seller_id="7777", api_key="BKanahtar12345678", api_secret="BKsir123456789")
    ).json()["id"]
    return a, a_id, b, b_id


def test_tenant_a_cannot_see_tenant_b_accounts_via_api(two_accounts: tuple[Api, str, Api, str]) -> None:
    a, a_id, b, b_id = two_accounts
    assert [x["id"] for x in a.get(URL).json()] == [a_id]
    assert [x["id"] for x in b.get(URL).json()] == [b_id]
    assert b_id not in a.get(URL).text and "7777" not in a.get(URL).text


def test_tenant_a_cannot_revoke_tenant_b_account(
    two_accounts: tuple[Api, str, Api, str], admin_conn: psycopg.Connection
) -> None:
    a, _, _, b_id = two_accounts
    r = a.post(f"{URL}/{b_id}/revoke")
    assert r.status_code == 404
    assert row(admin_conn, b_id)["status"] == "active"
    assert a.post(f"{URL}/00000000-0000-0000-0000-000000000000/revoke").status_code == 404
    assert a.post(f"{URL}/not-a-uuid/revoke").status_code == 422


def test_direct_sql_rls_isolation(
    two_accounts: tuple[Api, str, Api, str], database: DatabaseInfo, admin_conn: psycopg.Connection
) -> None:
    a, a_id, b, b_id = two_accounts
    tenant_a = a.get("/v1/me").json()["tenant"]["id"]
    tenant_b = b.get("/v1/me").json()["tenant"]["id"]
    user_a = a.get("/v1/me").json()["user_id"]
    with app_tx(database, tenant_a) as conn:
        assert {str(r[0]) for r in conn.execute("SELECT id FROM marketplace_accounts")} == {a_id}
        assert conn.execute(
            "SELECT count(*) FROM marketplace_accounts WHERE tenant_id = %s", (tenant_b,)
        ).fetchone() == (0,)
        # A bağlamında B satırını güncellemek/silmek etkisiz
        assert (
            conn.execute("UPDATE marketplace_accounts SET status = 'invalid' WHERE id = %s", (b_id,)).rowcount
            == 0
        )
    # Bağlam yok / boş: hiçbir şey görünmez
    for tenant in (None, ""):
        with app_tx(database, tenant) as conn:
            assert conn.execute("SELECT count(*) FROM marketplace_accounts").fetchone() == (0,)
    # A bağlamında B kiracısı adına satır yazılamaz (WITH CHECK)
    with app_tx(database, tenant_a) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(
            "INSERT INTO marketplace_accounts (tenant_id, platform, seller_id, status, created_by, "
            "api_key_encrypted, api_secret_encrypted) VALUES (%s, 'trendyol', '1', 'active', %s, 'x', 'y')",
            (tenant_b, user_a),
        )
    assert row(admin_conn, b_id)["status"] == "active"


def test_app_role_cannot_delete_accounts(
    two_accounts: tuple[Api, str, Api, str], database: DatabaseInfo
) -> None:
    a, _, _, _ = two_accounts
    tenant_a = a.get("/v1/me").json()["tenant"]["id"]
    for statement in ("DELETE FROM marketplace_accounts", "TRUNCATE marketplace_accounts"):
        with app_tx(database, tenant_a) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(statement)  # type: ignore[call-overload]


def test_table_is_forced_rls(admin_conn: psycopg.Connection) -> None:
    flags = admin_conn.execute(
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'marketplace_accounts'"
    ).fetchone()
    assert flags == (True, True)


def test_database_constraints(owner: Api, admin_conn: psycopg.Connection) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    # revoked iken şifreli alan dolu olamaz; aktifken boş olamaz
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE marketplace_accounts SET status = 'revoked', revoked_at = now()")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE marketplace_accounts SET api_key_encrypted = NULL")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE marketplace_accounts SET seller_id = 'abc'")
    with pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE marketplace_accounts SET platform = 'amazon'")
    # Aynı kiracı + platform + satıcı için ikinci iptal edilmemiş satır olamaz
    with pytest.raises(psycopg.errors.UniqueViolation):
        admin_conn.execute(
            "INSERT INTO marketplace_accounts (tenant_id, platform, seller_id, status, created_by, "
            "api_key_encrypted, api_secret_encrypted) "
            "SELECT tenant_id, platform, seller_id, 'invalid', created_by, 'x', 'y' "
            "FROM marketplace_accounts WHERE id = %s",
            (account_id,),
        )


# --- İptal -----------------------------------------------------------------------------------


def test_revoke_clears_encrypted_fields_keeps_row_and_audits(
    owner: Api, admin_conn: psycopg.Connection
) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    r = owner.post(f"{URL}/{account_id}/revoke")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "revoked" and data["revoked_at"] is not None and data["id"] == account_id
    assert API_KEY not in r.text and API_SECRET not in r.text
    stored = row(admin_conn, account_id)  # satır silinmedi
    assert stored["api_key_encrypted"] is None and stored["api_secret_encrypted"] is None
    assert stored["status"] == "revoked" and stored["revoked_at"] is not None
    # Ham veritabanı gösteriminde de iz yok
    dump = admin_conn.execute(
        "SELECT row_to_json(m)::text FROM marketplace_accounts m WHERE id = %s", (account_id,)
    ).fetchone()
    assert dump is not None and "v1:" not in dump[0]
    audit = admin_conn.execute(
        "SELECT action, target FROM audit_log WHERE action = 'marketplace_account.revoked'"
    ).fetchall()
    assert audit == [("marketplace_account.revoked", account_id)]
    # Listede revoked olarak görünür
    assert [(x["id"], x["status"]) for x in owner.get(URL).json()] == [(account_id, "revoked")]


def test_revoke_is_idempotent(owner: Api, admin_conn: psycopg.Connection) -> None:
    account_id = owner.post(URL, body()).json()["id"]
    assert owner.post(f"{URL}/{account_id}/revoke").status_code == 200
    again = owner.post(f"{URL}/{account_id}/revoke")
    assert again.status_code == 200 and again.json()["status"] == "revoked"
    count = admin_conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'marketplace_account.revoked'"
    ).fetchone()
    assert count == (1,)


# --- Sır sızıntısı ---------------------------------------------------------------------------


def test_secrets_never_appear_in_logs(
    owner: Api, trendyol: FakeTrendyol, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        assert owner.post(URL, body()).status_code == 201
        trendyol.status = 401
        assert owner.post(URL, body(seller_id="4444")).status_code == 422
        trendyol.status = 500
        assert owner.post(URL, body(seller_id="5555")).status_code == 502
    text = " ".join(f"{r.getMessage()} {r.__dict__} {r.exc_text or ''}" for r in caplog.records)
    assert API_KEY not in text and API_SECRET not in text
    assert "Basic " not in text


def test_session_less_client_with_csrf_cannot_connect(make_ty_api: Callable[..., Api]) -> None:
    api = make_ty_api()
    api.csrf()
    assert api.post(URL, body()).status_code == 401


# --- Migrasyon -------------------------------------------------------------------------------


def test_migration_0004_is_reversible(alembic_cfg: Config, admin_conn: psycopg.Connection) -> None:
    def table_exists() -> bool:
        return admin_conn.execute("SELECT to_regclass('public.marketplace_accounts')").fetchone() != (None,)

    assert table_exists()
    command.downgrade(alembic_cfg, "0003")
    assert not table_exists()
    command.upgrade(alembic_cfg, "head")
    assert table_exists()
    privileges = admin_conn.execute(
        "SELECT has_table_privilege('netkar_app', 'marketplace_accounts', 'SELECT'),"
        " has_table_privilege('netkar_app', 'marketplace_accounts', 'INSERT'),"
        " has_table_privilege('netkar_app', 'marketplace_accounts', 'UPDATE'),"
        " has_table_privilege('netkar_app', 'marketplace_accounts', 'DELETE')"
    ).fetchone()
    assert privileges == (True, True, True, False)
