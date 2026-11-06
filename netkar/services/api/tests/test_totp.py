"""TOTP kurulumu, etkinleştirme ve girişte ikinci adım."""

from __future__ import annotations

import base64
import uuid

import psycopg
import pyotp

from app.core.security import sign_pending_token
from tests.conftest import TEST_KEY, Api


def _enable_totp(api: Api) -> str:
    setup = api.post("/v1/auth/totp/setup")
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert api.post("/v1/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}).status_code == 204
    return str(secret)


def test_totp_setup_returns_uri_and_stores_encrypted(api: Api, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("t@example.com")
    body = api.post("/v1/auth/totp/setup").json()
    assert body["otpauth_uri"].startswith("otpauth://totp/")
    assert f"secret={body['secret']}" in body["otpauth_uri"]
    stored = admin_conn.execute("SELECT totp_secret_encrypted, totp_enabled FROM users").fetchone()
    assert stored is not None
    assert body["secret"] not in stored[0] and stored[0].startswith("v1:")
    assert stored[1] is False


def test_totp_enable_requires_valid_code_and_setup(api: Api) -> None:
    api.signup_and_login("t@example.com")
    assert api.post("/v1/auth/totp/enable", {"code": "123456"}).status_code == 409  # kurulum yok
    secret = api.post("/v1/auth/totp/setup").json()["secret"]
    wrong = "000000" if pyotp.TOTP(secret).now() != "000000" else "111111"
    r = api.post("/v1/auth/totp/enable", {"code": wrong})
    assert r.status_code == 400
    assert api.post("/v1/auth/totp/enable", {"code": "abc"}).status_code == 422
    assert api.post("/v1/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}).status_code == 204
    assert api.get("/v1/me").json()["totp_enabled"] is True
    assert api.post("/v1/auth/totp/setup").status_code == 409  # zaten etkin
    assert api.post("/v1/auth/totp/enable", {"code": pyotp.TOTP(secret).now()}).status_code == 409


def test_totp_setup_requires_authentication(api: Api) -> None:
    assert api.post("/v1/auth/totp/setup").status_code == 401
    assert api.post("/v1/auth/totp/enable", {"code": "123456"}).status_code == 401


def test_login_with_totp_second_step(make_api) -> None:  # type: ignore[no-untyped-def]
    first: Api = make_api()
    first.signup_and_login("t2@example.com")
    secret = _enable_totp(first)
    first.post("/v1/auth/logout")

    second: Api = make_api()
    r = second.login("t2@example.com")
    assert r.status_code == 200 and r.json() == {"status": "totp_required"}
    # Parola adımı tam oturum vermez
    assert second.get("/v1/me").status_code == 401
    assert "__Host-nk_session" not in r.headers.get("set-cookie", "")

    bad = second.post("/v1/auth/totp/verify", {"code": "000000"})
    assert bad.status_code == 401
    ok = second.post("/v1/auth/totp/verify", {"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    me = second.get("/v1/me")
    assert me.status_code == 200 and me.json()["totp_enabled"] is True


def test_totp_verify_without_or_with_forged_pending_cookie(api: Api, make_api) -> None:  # type: ignore[no-untyped-def]
    assert api.post("/v1/auth/totp/verify", {"code": "123456"}).status_code == 401
    api.client.cookies.set("__Host-nk_pending", "sahte.imza")
    assert api.post("/v1/auth/totp/verify", {"code": "123456"}).status_code == 401


def test_totp_verify_rejects_expired_pending_token(make_api) -> None:  # type: ignore[no-untyped-def]
    api: Api = make_api()
    api.signup_and_login("t3@example.com")
    secret = _enable_totp(api)
    me = api.get("/v1/me").json()
    api.post("/v1/auth/logout")
    master = base64.b64decode(TEST_KEY)
    expired = sign_pending_token(
        master, uuid.UUID(me["user_id"]), uuid.UUID(me["tenant"]["id"]), 300, now=1.0
    )
    api.client.cookies.set("__Host-nk_pending", expired)
    r = api.post("/v1/auth/totp/verify", {"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401


def test_totp_verify_is_rate_limited(make_api) -> None:  # type: ignore[no-untyped-def]
    api: Api = make_api(rate_limit_totp_user=3)
    api.signup_and_login("t4@example.com")
    _enable_totp(api)
    api.post("/v1/auth/logout")
    api.login("t4@example.com")
    codes = [api.post("/v1/auth/totp/verify", {"code": "000000"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
