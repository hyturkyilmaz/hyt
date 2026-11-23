"""Web push abonelik altyapısı (ADR-0009 D8 birinci yarı, §12 madde 25): gerçek PostgreSQL, gerçek HTTP yolu.

Kapsam: uç nokta izin listesi ve http reddi, bayrak kapalıyken davranış, idempotent abonelik, IDOR, `extra="forbid"`,
hız sınırı, abonelik sınırı, açık çıkış / "diğer oturumları kapat" / parola sıfırlamada iptal (H11), 404/410
yanıtında `revoked_at`, uç noktanın log'a ve denetim kaydına girmemesi, VAPID ayar doğrulayıcısı. Anahtarlar
çalışma anında üretilir (repoda gerçek anahtar yok). Gerçek ağ çağrısı yoktur: gönderici `FakePushSender`'dır.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

import psycopg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.email import InMemoryOutbox
from app.db.rls import tenant_transaction
from app.services import push as push_service
from app.services.push import FakePushSender, PushPayload, PushTarget, PushValidationError
from tests.conftest import GOOD_PASSWORD, TEST_KEK, TEST_KEY, Api, FakeClock


# --------------------------------------------------------------------------- anahtar üretimi (çalışma anında)
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_vapid_pair() -> tuple[str, str]:
    """(genel, özel) VAPID anahtarı, base64url dolgusuz; her çağrıda yeni."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(public), _b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def make_client_keys() -> dict[str, str]:
    """Tarayıcı aboneliğinin `keys` değeri gibi: 65 bayt P-256 noktası ve 16 bayt auth."""
    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"p256dh": _b64url(point), "auth": _b64url(b"0123456789abcdef")}


FCM = "https://fcm.googleapis.com/fcm/send/"


def body(tag: str = "abc", endpoint: str | None = None) -> dict[str, Any]:
    # Gerçek uç noktaya benzer, ama her testte ayırt edilebilir sır içerir.
    return {"endpoint": endpoint or f"{FCM}{tag}-GIZLI-UC-NOKTA-DEGERI", "keys": make_client_keys()}


SUBS = "/v1/me/push-subscriptions"


@pytest.fixture
def push_settings() -> dict[str, Any]:
    public, private = make_vapid_pair()
    return {
        "web_push_enabled": True,
        "web_push_vapid_public_key": public,
        "web_push_vapid_private_key": SecretStr(private),
        "web_push_vapid_subject": "mailto:destek@ornek.invalid",
    }


@pytest.fixture
def papi(make_api: Callable[..., Api], push_settings: dict[str, Any]) -> Api:
    """Bayrak açık, doğrulanmış kullanıcı oturumlu istemci."""
    api = make_api(**push_settings)
    api.signup_and_login("a@example.com", tenant="Mağaza A")
    return api


def rows(conn: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT id, endpoint_host, endpoint_digest, endpoint_enc, p256dh_enc, auth_enc, vapid_key_id, "
        "created_session_id, revoked_at, failure_count, last_success_at FROM push_subscriptions ORDER BY created_at"
    ).fetchall()


# --------------------------------------------------------------------------- izin listesi (birim)
@pytest.mark.parametrize(
    ("endpoint", "host"),
    [
        ("https://fcm.googleapis.com/fcm/send/abc", "fcm.googleapis.com"),
        ("https://updates.push.services.mozilla.com/wpush/v2/abc", "updates.push.services.mozilla.com"),
        ("https://web.push.apple.com/QAbc", "web.push.apple.com"),
        ("https://wns2-par02p.notify.windows.com/?token=abc", "wns2-par02p.notify.windows.com"),
        (
            "https://FCM.GoogleAPIs.com".replace("GoogleAPIs.com", "googleapis.com") + "/x",
            "fcm.googleapis.com",
        ),
        ("https://fcm.googleapis.com:443/x", "fcm.googleapis.com"),
    ],
)
def test_allowed_hosts_are_accepted(endpoint: str, host: str) -> None:
    assert push_service.validate_endpoint(endpoint) == host


@pytest.mark.parametrize(
    ("endpoint", "code"),
    [
        ("http://fcm.googleapis.com/fcm/send/abc", "endpoint_scheme"),
        ("ftp://fcm.googleapis.com/x", "endpoint_scheme"),
        ("//fcm.googleapis.com/x", "endpoint_scheme"),
        ("https://evil.example.com/x", "endpoint_host_not_allowed"),
        ("https://fcm.googleapis.com.evil.com/x", "endpoint_host_not_allowed"),
        ("https://evilfcm.googleapis.com/x", "endpoint_host_not_allowed"),
        ("https://notfcm.googleapis.com.example/x", "endpoint_host_not_allowed"),
        ("https://push.apple.com/x", "endpoint_host_not_allowed"),  # joker en az bir etiket ister
        ("https://notify.windows.com/x", "endpoint_host_not_allowed"),
        ("https://evilpush.apple.com/x", "endpoint_host_not_allowed"),
        ("https://127.0.0.1/x", "endpoint_host_not_allowed"),
        ("https://[::1]/x", "endpoint_invalid"),
        ("https://fcm.googleapis.com./x", "endpoint_invalid"),
        ("https://fcm.googleapis.com:8443/x", "endpoint_port"),
        ("https://fcm.googleapis.com@evil.com/x", "endpoint_invalid"),
        ("https://user:pw@fcm.googleapis.com/x", "endpoint_invalid"),
        ("https://evil.com\\@fcm.googleapis.com/x", "endpoint_invalid"),
        ("https://fcm.googleapis.com/x y", "endpoint_invalid"),
        ("https://fcm.googleapis.com/\nx", "endpoint_invalid"),
        ("https://fcm.googleapis.com/çx", "endpoint_invalid"),
        ("https://fcm.googleapis.com:abc/x", "endpoint_invalid"),
        ("https:///x", "endpoint_invalid"),
        ("https://fcm.googleapis.com/" + "a" * 2100, "endpoint_invalid"),
    ],
)
def test_other_endpoints_are_rejected(endpoint: str, code: str) -> None:
    with pytest.raises(PushValidationError) as raised:
        push_service.validate_endpoint(endpoint)
    assert raised.value.code == code
    assert endpoint not in str(raised.value)


def test_key_validators_accept_browser_shapes_and_reject_the_rest() -> None:
    keys = make_client_keys()
    assert push_service.validate_p256dh(keys["p256dh"]) == keys["p256dh"]
    assert push_service.validate_auth_secret(keys["auth"]) == keys["auth"]
    for bad in ("", "a", "!!!", keys["p256dh"][:-4], "A" * 87, keys["p256dh"] + "=", "x" * 200):
        with pytest.raises(PushValidationError):
            push_service.validate_p256dh(bad)
    # 65 bayt, doğru önek ama eğri üzerinde değil
    off_curve = _b64url(b"\x04" + b"\x01" * 64)
    with pytest.raises(PushValidationError):
        push_service.validate_p256dh(off_curve)
    for bad in ("", "short", keys["auth"] + "AA", "a b" * 8, "y" * 100):
        with pytest.raises(PushValidationError):
            push_service.validate_auth_secret(bad)


# --------------------------------------------------------------------------- API: reddedilen girdiler
def test_api_rejects_unlisted_host_and_http_with_422(papi: Api, admin_conn: psycopg.Connection[Any]) -> None:
    for endpoint, code in (
        ("https://evil.example.com/push/GIZLI-DEGER", "endpoint_host_not_allowed"),
        ("http://fcm.googleapis.com/fcm/send/GIZLI-DEGER", "endpoint_scheme"),
    ):
        response = papi.post(SUBS, {"endpoint": endpoint, "keys": make_client_keys()})
        assert response.status_code == 422
        assert response.json()["errors"] == [{"field": "body.endpoint".split(".", 1)[1], "code": code}]
        assert "GIZLI-DEGER" not in response.text and endpoint not in response.text
    assert rows(admin_conn) == []


def test_api_rejects_bad_keys_and_unknown_fields(papi: Api) -> None:
    good = body()
    bad_p = {**good, "keys": {**good["keys"], "p256dh": "AAAA"}}
    bad_a = {**good, "keys": {**good["keys"], "auth": "AAAA"}}
    assert papi.post(SUBS, bad_p).json()["errors"] == [{"field": "keys.p256dh", "code": "p256dh_invalid"}]
    assert papi.post(SUBS, bad_a).json()["errors"] == [{"field": "keys.auth", "code": "auth_invalid"}]
    for extra in (
        {**good, "user_id": "00000000-0000-4000-8000-000000000001"},
        {**good, "tenant_id": "x"},
        {**good, "expirationTime": None},
        {**good, "keys": {**good["keys"], "extra": "x"}},
    ):
        assert papi.post(SUBS, extra).status_code == 422
    assert papi.post(SUBS, {"keys": good["keys"]}).status_code == 422
    assert papi.post(SUBS, {"endpoint": good["endpoint"]}).status_code == 422
    assert (
        papi.post(
            SUBS, {"endpoint": "https://fcm.googleapis.com/" + "a" * 2100, "keys": good["keys"]}
        ).status_code
        == 422
    )


def test_endpoints_require_a_session(make_api: Callable[..., Api], push_settings: dict[str, Any]) -> None:
    anon = make_api(**push_settings)
    assert anon.get("/v1/push/vapid-public-key").status_code == 401
    assert anon.post(SUBS, body()).status_code == 401
    assert anon.get(SUBS).status_code == 401
    assert anon.delete(f"{SUBS}/00000000-0000-4000-8000-000000000001").status_code == 401


# --------------------------------------------------------------------------- bayrak
def test_flag_off_returns_disabled_key_and_409_on_subscribe(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    api = make_api()  # varsayılan: web_push_enabled=False
    api.signup_and_login("kapali@example.com")
    assert api.get("/v1/push/vapid-public-key").json() == {
        "enabled": False,
        "public_key": None,
        "key_id": None,
    }
    response = api.post(SUBS, body())
    assert response.status_code == 409 and response.json()["type"].endswith("push-disabled")
    assert "GIZLI" not in response.text
    assert rows(admin_conn) == []
    assert api.get(SUBS).json() == {"items": []}


def test_flag_on_without_public_key_is_also_disabled(make_api: Callable[..., Api]) -> None:
    api = make_api(web_push_enabled=True)
    api.signup_and_login("ak@example.com")
    assert api.get("/v1/push/vapid-public-key").json()["enabled"] is False
    assert api.post(SUBS, body()).status_code == 409


def test_vapid_key_endpoint_returns_only_public_material(papi: Api, push_settings: dict[str, Any]) -> None:
    response = papi.get("/v1/push/vapid-public-key")
    data = response.json()
    assert data["enabled"] is True and data["public_key"] == push_settings["web_push_vapid_public_key"]
    assert data["key_id"] == push_service.vapid_key_id(data["public_key"]) and len(data["key_id"]) == 16
    assert push_settings["web_push_vapid_private_key"].get_secret_value() not in response.text


def test_delete_and_list_work_after_flag_is_turned_off(
    papi: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    sub = papi.post(SUBS, body()).json()
    papi.client.app.state.settings = papi.client.app.state.settings.model_copy(  # type: ignore[attr-defined]
        update={"web_push_enabled": False}
    )
    assert [i["id"] for i in papi.get(SUBS).json()["items"]] == [sub["id"]]
    assert papi.delete(f"{SUBS}/{sub['id']}").status_code == 204
    assert rows(admin_conn)[0][8] is not None


# --------------------------------------------------------------------------- abonelik ve saklama
def test_subscribe_stores_envelope_encrypted_values_and_masked_response(
    papi: Api, admin_conn: psycopg.Connection[Any], push_settings: dict[str, Any]
) -> None:
    payload = body("kayit")
    response = papi.post(SUBS, payload)
    assert response.status_code == 201
    data = response.json()
    assert set(data) == {"id", "endpoint_host", "vapid_key_id", "created_at", "last_success_at"}
    assert data["endpoint_host"] == "fcm.googleapis.com" and data["last_success_at"] is None
    assert data["vapid_key_id"] == push_service.vapid_key_id(push_settings["web_push_vapid_public_key"])
    assert payload["endpoint"] not in response.text and payload["keys"]["auth"] not in response.text

    ((sid, host, digest, endpoint_enc, p256dh_enc, auth_enc, key_id, session_id, revoked, fails, ok),) = rows(
        admin_conn
    )
    assert str(sid) == data["id"] and host == "fcm.googleapis.com" and revoked is None and fails == 0
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and key_id == data["vapid_key_id"] and ok is None
    assert session_id is not None
    for stored, plain in (
        (endpoint_enc, payload["endpoint"]),
        (p256dh_enc, payload["keys"]["p256dh"]),
        (auth_enc, payload["keys"]["auth"]),
    ):
        assert stored.startswith("v2:") and plain not in stored
    listing = papi.get(SUBS).json()["items"]
    assert [i["id"] for i in listing] == [data["id"]]
    assert "endpoint" not in listing[0] and "keys" not in listing[0]


def test_resubscribing_the_same_endpoint_is_idempotent(
    papi: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    payload = body("tek")
    first = papi.post(SUBS, payload)
    again = papi.post(SUBS, payload)
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    assert len(rows(admin_conn)) == 1
    assert admin_conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'push.subscribe'"
    ).fetchone() == (1,)


def test_resubscribing_after_unsubscribe_creates_a_new_active_row(
    papi: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    payload = body("yeniden")
    first = papi.post(SUBS, payload).json()
    assert papi.delete(f"{SUBS}/{first['id']}").status_code == 204
    second = papi.post(SUBS, payload)
    assert second.status_code == 201 and second.json()["id"] != first["id"]
    states = [(str(r[0]), r[8] is not None) for r in rows(admin_conn)]
    assert states == [
        (first["id"], True),
        (second.json()["id"], False),
    ]  # silme yok, eski satır iptalli kalır


def test_unsubscribe_revokes_clears_secrets_audits_host_and_is_repeatable(
    papi: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    payload = body("sil")
    sub = papi.post(SUBS, payload).json()
    assert papi.delete(f"{SUBS}/{sub['id']}").status_code == 204
    assert papi.delete(f"{SUBS}/{sub['id']}").status_code == 204  # zaten iptal: idempotent
    ((_, _, _, endpoint_enc, p256dh_enc, auth_enc, _, _, revoked, *_),) = rows(admin_conn)
    assert revoked is not None and endpoint_enc is None and p256dh_enc is None and auth_enc is None
    assert papi.get(SUBS).json() == {"items": []}
    audits = admin_conn.execute(
        "SELECT action, target, meta FROM audit_log WHERE action LIKE 'push.%' ORDER BY id"
    ).fetchall()
    assert [(a, t, m) for a, t, m in audits] == [
        ("push.subscribe", sub["id"], {"endpoint_host": "fcm.googleapis.com"}),
        ("push.unsubscribe", sub["id"], {"endpoint_host": "fcm.googleapis.com"}),
    ]
    assert payload["endpoint"] not in json.dumps(audits, default=str)


def test_active_subscription_limit_is_ten_per_user(papi: Api) -> None:
    for i in range(10):
        assert papi.post(SUBS, body(f"c{i}")).status_code == 201
    eleventh = papi.post(SUBS, body("c10"))
    assert eleventh.status_code == 409 and eleventh.json()["type"].endswith("push-subscription-limit")
    # Mevcut abonelik sınırda da idempotent kalır; iptal yer açar.
    same = body("c0")
    assert (
        papi.post(SUBS, {"endpoint": f"{FCM}c0-GIZLI-UC-NOKTA-DEGERI", "keys": same["keys"]}).status_code
        == 200
    )
    first = papi.get(SUBS).json()["items"][0]
    assert papi.delete(f"{SUBS}/{first['id']}").status_code == 204
    assert papi.post(SUBS, body("c10")).status_code == 201


# --------------------------------------------------------------------------- IDOR ve kiracı yalıtımı
def test_other_tenants_cannot_see_or_delete_a_subscription(
    make_api: Callable[..., Api],
    papi: Api,
    push_settings: dict[str, Any],
    admin_conn: psycopg.Connection[Any],
) -> None:
    mine = papi.post(SUBS, body("sahip")).json()
    other = make_api(**push_settings)
    other.signup_and_login("b@example.com", tenant="Mağaza B")
    assert other.get(SUBS).json() == {"items": []}
    assert other.delete(f"{SUBS}/{mine['id']}").status_code == 404
    assert other.delete(f"{SUBS}/00000000-0000-4000-8000-0000000000aa").status_code == 404
    assert other.delete(f"{SUBS}/yok").status_code == 422
    assert rows(admin_conn)[0][8] is None  # sahibinin aboneliği dokunulmadı
    assert [i["id"] for i in papi.get(SUBS).json()["items"]] == [mine["id"]]


def test_same_endpoint_in_another_tenant_is_independent(
    make_api: Callable[..., Api],
    papi: Api,
    push_settings: dict[str, Any],
    admin_conn: psycopg.Connection[Any],
) -> None:
    shared = body("ortak")
    assert papi.post(SUBS, shared).status_code == 201
    other = make_api(**push_settings)
    other.signup_and_login("c@example.com", tenant="Mağaza C")
    assert other.post(SUBS, shared).status_code == 201  # tekillik kiracı kapsamlıdır
    digests = {r[2] for r in rows(admin_conn)}
    assert len(rows(admin_conn)) == 2 and len(digests) == 1


def test_endpoint_held_by_another_user_in_the_same_tenant_is_not_taken_over(
    papi: Api,
    admin_conn: psycopg.Connection[Any],
    make_api: Callable[..., Api],
    push_settings: dict[str, Any],
) -> None:
    """Aynı kiracıda başka kullanıcı (paylaşılan cihaz): satır RLS yüzünden görünmez, devralma yok, 409."""
    shared = body("paylasilan")
    sub = papi.post(SUBS, shared).json()
    row = admin_conn.execute("SELECT tenant_id FROM push_subscriptions").fetchone()
    assert row is not None
    second = make_api(**push_settings)
    # İkinci kullanıcı birinci kiracının üyesi (parola özeti aynı: gerçek giriş akışı kullanılır).
    colleague = admin_conn.execute(
        "INSERT INTO users (email, password_hash, email_verified_at) "
        "SELECT 'ortak@example.com', password_hash, now() FROM users WHERE email = 'a@example.com' RETURNING id"
    ).fetchone()
    assert colleague is not None
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'viewer')", (colleague[0], row[0])
    )
    assert second.login("ortak@example.com").status_code == 200
    assert second.get("/v1/me").json()["tenant"]["id"] == str(row[0])
    assert second.get(SUBS).json() == {"items": []}
    response = second.post(SUBS, shared)
    assert response.status_code == 409 and response.json()["type"].endswith("push-endpoint-in-use")
    assert second.delete(f"{SUBS}/{sub['id']}").status_code == 404
    assert [str(r[0]) for r in rows(admin_conn)] == [sub["id"]]
    assert rows(admin_conn)[0][8] is None


# --------------------------------------------------------------------------- hız sınırı
def test_subscribe_is_rate_limited_per_user(papi: Api, frozen_ratelimit_clock: float) -> None:
    payload = body("hiz")
    codes = [papi.post(SUBS, payload).status_code for _ in range(22)]
    assert codes[:20] == [201] + [200] * 19 and codes[20:] == [429, 429]


def test_vapid_key_reads_are_rate_limited(papi: Api, frozen_ratelimit_clock: float) -> None:
    codes = [papi.get("/v1/push/vapid-public-key").status_code for _ in range(62)]
    assert codes[:60] == [200] * 60 and codes[60:] == [429, 429]


# --------------------------------------------------------------------------- H11: oturum olaylarında iptal
def _revoked(conn: psycopg.Connection[Any]) -> list[bool]:
    return [r[8] is not None for r in rows(conn)]


def test_logout_revokes_the_subscriptions_of_that_session(
    papi: Api, admin_conn: psycopg.Connection[Any]
) -> None:
    assert papi.post(SUBS, body("cikis")).status_code == 201
    assert _revoked(admin_conn) == [False]
    assert papi.post("/v1/auth/logout").status_code == 204
    ((_, _, _, endpoint_enc, p256dh_enc, auth_enc, _, _, revoked, *_),) = rows(admin_conn)
    assert revoked is not None and endpoint_enc is None and p256dh_enc is None and auth_enc is None
    assert admin_conn.execute("SELECT count(*) FROM push_subscriptions").fetchone() == (1,)  # silme yok


def test_logout_keeps_subscriptions_made_in_other_sessions(
    make_api: Callable[..., Api], push_settings: dict[str, Any], admin_conn: psycopg.Connection[Any]
) -> None:
    first = make_api(**push_settings)
    first.signup_and_login("iki@example.com")
    other = make_api(**push_settings)
    assert other.login("iki@example.com").status_code == 200
    assert first.post(SUBS, body("bir")).status_code == 201
    assert other.post(SUBS, body("iki")).status_code == 201
    assert first.post("/v1/auth/logout").status_code == 204
    assert _revoked(admin_conn) == [True, False]


def test_close_other_sessions_revokes_only_other_sessions_subscriptions(
    make_api: Callable[..., Api],
    push_settings: dict[str, Any],
    clock: FakeClock,
    admin_conn: psycopg.Connection[Any],
) -> None:
    first = make_api(**push_settings)
    first.signup_and_login("diger@example.com")
    other = make_api(**push_settings)
    assert other.login("diger@example.com").json() == {"status": "ok"}
    assert first.post(SUBS, body("benim")).status_code == 201
    assert other.post(SUBS, body("baska")).status_code == 201
    setup = first.post("/v1/auth/totp/setup", {"password": GOOD_PASSWORD})
    secret = str(setup.json()["secret"])
    assert (
        first.post(
            "/v1/auth/totp/enable", {"code": clock.code(secret), "password": GOOD_PASSWORD}
        ).status_code
        == 200
    )
    assert other.get("/v1/me").status_code == 401
    assert _revoked(admin_conn) == [False, True]  # çağıran oturumun aboneliği kalır


def test_password_reset_revokes_all_subscriptions_of_the_user(
    make_api: Callable[..., Api],
    push_settings: dict[str, Any],
    outbox: InMemoryOutbox,
    admin_conn: psycopg.Connection[Any],
) -> None:
    api = make_api(**push_settings)
    api.signup_and_login("sifirla@example.com")
    other = make_api(**push_settings)
    assert other.login("sifirla@example.com").status_code == 200
    assert api.post(SUBS, body("s1")).status_code == 201
    assert other.post(SUBS, body("s2")).status_code == 201
    assert api.post("/v1/auth/password-reset/request", {"email": "sifirla@example.com"}).status_code == 202
    token = re.search(r"token=([A-Za-z0-9_\-]+)", outbox.to("sifirla@example.com")[-1].body)
    assert token
    done = api.post(
        "/v1/auth/password-reset/confirm", {"token": token.group(1), "new_password": "yepyeni-parola-9876"}
    )
    assert done.status_code == 204
    assert _revoked(admin_conn) == [True, True]


def test_session_expiry_does_not_revoke(papi: Api, admin_conn: psycopg.Connection[Any]) -> None:
    """H11: süre dolumu iptal etmez (yalnız açık çıkış, diğer oturumları kapat ve parola sıfırlama)."""
    assert papi.post(SUBS, body("sure")).status_code == 201
    admin_conn.execute("UPDATE sessions SET expires_at = now() - interval '1 minute'")
    assert papi.get("/v1/me").status_code == 401
    assert _revoked(admin_conn) == [False]


# --------------------------------------------------------------------------- log ve denetimde uç nokta yok
def test_endpoint_never_reaches_logs_or_audit(
    papi: Api, caplog: pytest.LogCaptureFixture, admin_conn: psycopg.Connection[Any]
) -> None:
    caplog.set_level(logging.DEBUG)
    payload = body("log")
    secret_bits = [
        payload["endpoint"],
        payload["endpoint"].rsplit("/", 1)[1],
        payload["keys"]["p256dh"],
        payload["keys"]["auth"],
    ]
    sub = papi.post(SUBS, payload).json()
    papi.post(SUBS, payload)
    papi.post(SUBS, {"endpoint": "https://evil.example.com/push/LOG-GIZLI", "keys": payload["keys"]})
    papi.post(SUBS, {"endpoint": payload["endpoint"], "keys": {**payload["keys"], "auth": "bozuk"}})
    papi.delete(f"{SUBS}/{sub['id']}")
    papi.post("/v1/auth/logout")
    logged = caplog.text
    for bit in [*secret_bits, "LOG-GIZLI"]:
        assert bit not in logged
    dumped = json.dumps(
        admin_conn.execute("SELECT action, target, meta FROM audit_log").fetchall(), default=str
    )
    for bit in secret_bits:
        assert bit not in dumped
    assert "fcm.googleapis.com" in dumped  # yalnız ana bilgisayar adı


def test_push_target_repr_hides_secrets() -> None:
    target = PushTarget(UUID(int=1), "https://fcm.googleapis.com/GIZLI", "pk-GIZLI", "auth-GIZLI")
    assert "GIZLI" not in repr(target) and "GIZLI" not in str(target)


# --------------------------------------------------------------------------- gönderici ve 404/410
async def _seed_subscription(papi: Api, admin_conn: psycopg.Connection[Any], token: str) -> tuple[UUID, UUID]:
    sub = papi.post(SUBS, body(token)).json()
    tenant = admin_conn.execute(
        "SELECT tenant_id FROM push_subscriptions WHERE id = %s", (sub["id"],)
    ).fetchone()
    assert tenant is not None
    return UUID(sub["id"]), tenant[0]


@pytest.mark.parametrize("status", [404, 410])
async def test_gone_response_sets_revoked_at_and_clears_secrets(
    papi: Api, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine, status: int
) -> None:
    sid, tenant = await _seed_subscription(papi, admin_conn, f"gone{status}")
    sender = FakePushSender(status_by_subscription={sid: status})
    result = await sender.send(
        PushTarget(sid, "e", "p", "a"), PushPayload("Başlık", "Gövde"), ttl=60, urgency="normal", topic=None
    )
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with tenant_transaction(sessions, tenant) as db:
        outcome = await push_service.apply_delivery_result(db, sid, result.status_code)
    assert outcome == "revoked"
    ((_, _, _, endpoint_enc, p256dh_enc, auth_enc, _, _, revoked, fails, ok),) = rows(admin_conn)
    assert revoked is not None and endpoint_enc is None and p256dh_enc is None and auth_enc is None
    assert fails == 0 and ok is None
    # İptal edilmiş satır sonraki sonuçlarla yeniden açılmaz ve sayaç değişmez.
    async with tenant_transaction(sessions, tenant) as db:
        assert await push_service.apply_delivery_result(db, sid, 201) == "sent"
    assert rows(admin_conn)[0][8] == revoked and rows(admin_conn)[0][10] is None


async def test_success_and_transient_failures_update_counters(
    papi: Api, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    sid, tenant = await _seed_subscription(papi, admin_conn, "sayac")
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    for status in (500, 429, 503):
        async with tenant_transaction(sessions, tenant) as db:
            assert await push_service.apply_delivery_result(db, sid, status) == "failed"
    assert rows(admin_conn)[0][9:] == (3, None) and rows(admin_conn)[0][8] is None
    async with tenant_transaction(sessions, tenant) as db:
        assert await push_service.apply_delivery_result(db, sid, 201) == "sent"
    row = rows(admin_conn)[0]
    assert row[9] == 0 and row[10] is not None and row[8] is None


async def test_worker_cannot_touch_another_tenants_subscription(
    papi: Api, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    sid, _ = await _seed_subscription(papi, admin_conn, "yabanci")
    foreign = admin_conn.execute("INSERT INTO tenants (name) VALUES ('Yabancı') RETURNING id").fetchone()
    assert foreign is not None
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with tenant_transaction(sessions, foreign[0]) as db:
        await push_service.apply_delivery_result(db, sid, 410)
    assert rows(admin_conn)[0][8] is None


async def test_fake_sender_records_calls_without_network() -> None:
    sender = FakePushSender(default_status=201)
    sid = UUID(int=7)
    result = await sender.send(
        PushTarget(sid, "e", "p", "a"),
        PushPayload("Zarar uyarısı", "Yeni uyarı var", "/panel/uyarilar/abc"),
        ttl=3600,
        urgency="normal",
        topic="ZARARINA_SATIS",
    )
    assert result.status_code == 201
    assert sender.sent == [
        (
            sid,
            '{"title":"Zarar uyarısı","body":"Yeni uyarı var","path":"/panel/uyarilar/abc"}',
            3600,
            "normal",
            "ZARARINA_SATIS",
        )
    ]


def test_payload_path_is_allow_listed_and_text_is_cleaned() -> None:
    for bad in (
        "https://evil.example/x",
        "//evil.example",
        "/panel/uyarilarx",
        "/panel/uyarilar/../x",
        "/baska",
        "panel/uyarilar",
        "/panel/uyarilar\\x",
    ):
        with pytest.raises(ValueError):
            PushPayload("t", "b", bad)
    data = json.loads(
        PushPayload("A\nB\x00" + "x" * 200, "gövde\r\n" + "y" * 400, "/panel/uyarilar").to_json()
    )
    assert "\n" not in data["title"] and "\x00" not in data["title"] and len(data["title"]) <= 80
    assert len(data["body"]) <= 160 and set(data) == {"title", "body", "path"}


# --------------------------------------------------------------------------- VAPID ayarları
def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "database_url": "postgresql+psycopg://u:p@localhost/db",
        "data_encryption_key": TEST_KEY,
        "data_keks": f"kek1:{TEST_KEK}",
        "data_kek_active": "kek1",
        "email_backend": "memory",
        "web_base_url": "https://app.test.invalid",
    }
    base.update(over)
    return Settings(**base)


def test_flag_defaults_off_and_private_key_is_secret() -> None:
    settings = _settings()
    assert settings.web_push_enabled is False
    public, private = make_vapid_pair()
    configured = _settings(web_push_vapid_public_key=public, web_push_vapid_private_key=private)
    assert private not in repr(configured) and private not in str(configured.model_dump())


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_hardened_environment_requires_keys_when_flag_is_on(environment: str) -> None:
    extra: dict[str, Any] = {"email_backend": "file", "email_dev_outbox_path": "/var/netkar/outbox.jsonl"}
    if environment == "prod":
        extra["email_backend"] = (
            "file"  # prod'un e-posta kuralı bu testin konusu değil: ValueError mesajına bakılır
        )
    with pytest.raises(ValidationError) as raised:
        _settings(environment=environment, web_push_enabled=True, **extra)
    message = str(raised.value)
    assert "WEB_PUSH_VAPID_PUBLIC_KEY" in message and "WEB_PUSH_VAPID_PRIVATE_KEY" in message
    assert "WEB_PUSH_VAPID_SUBJECT" in message


def test_hardened_environment_accepts_complete_keys_and_flag_off_needs_none() -> None:
    public, private = make_vapid_pair()
    settings = _settings(
        environment="staging",
        email_backend="file",
        email_dev_outbox_path="/var/netkar/outbox.jsonl",
        web_push_enabled=True,
        web_push_vapid_public_key=public,
        web_push_vapid_private_key=private,
        web_push_vapid_subject="https://app.test.invalid/iletisim",
    )
    assert settings.web_push_enabled
    off = _settings(
        environment="staging", email_backend="file", email_dev_outbox_path="/var/netkar/outbox.jsonl"
    )
    assert off.web_push_enabled is False


def test_vapid_values_are_validated_when_given() -> None:
    public, private = make_vapid_pair()
    other_public, _ = make_vapid_pair()
    for over, needle in (
        ({"web_push_vapid_subject": "destek@ornek.invalid"}, "WEB_PUSH_VAPID_SUBJECT"),
        ({"web_push_vapid_private_key": "kisa"}, "WEB_PUSH_VAPID_PRIVATE_KEY"),
        ({"web_push_vapid_private_key": private + "="}, "WEB_PUSH_VAPID_PRIVATE_KEY"),
        ({"web_push_vapid_public_key": "kisa"}, "WEB_PUSH_VAPID_PUBLIC_KEY"),
        ({"web_push_vapid_public_key": _b64url(b"\x04" + b"\x01" * 64)}, "WEB_PUSH_VAPID_PUBLIC_KEY"),
        ({"web_push_vapid_public_key": other_public, "web_push_vapid_private_key": private}, "eşleşmiyor"),
    ):
        with pytest.raises(ValidationError) as raised:
            _settings(**over)
        assert needle in str(raised.value)
        assert private not in str(raised.value)
    assert _settings(web_push_vapid_public_key=public, web_push_vapid_private_key=private)
