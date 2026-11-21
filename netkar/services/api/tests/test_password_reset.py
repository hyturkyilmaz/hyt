"""Parola sıfırlama: tek kullanımlık, süreli, hesap varlığını sızdırmaz."""

from __future__ import annotations

import hashlib
import re

import psycopg

from app.core.email import InMemoryOutbox
from tests.conftest import GOOD_PASSWORD, Api, FakePwned

NEW_PASSWORD = "yepyeni-parola-9876"


def _token_from(outbox: InMemoryOutbox, email: str) -> str:
    message = outbox.to(email)[-1]
    match = re.search(r"token=([A-Za-z0-9_\-]+)", message.body)
    assert match
    return match.group(1)


def test_reset_flow_single_use(api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("r@example.com")
    assert api.post("/v1/auth/password-reset/request", {"email": "R@example.com"}).status_code == 202
    token = _token_from(outbox, "r@example.com")

    # DB'de yalnız özet
    stored = admin_conn.execute("SELECT token_hash FROM password_reset_tokens").fetchall()
    assert stored == [(hashlib.sha256(token.encode()).hexdigest(),)]

    r = api.post("/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 204
    # Aynı token ikinci kez kullanılamaz
    again = api.post(
        "/v1/auth/password-reset/confirm", {"token": token, "new_password": "bir-baska-parola-1"}
    )
    assert again.status_code == 400
    assert again.json()["type"].endswith("invalid-reset-token")

    # Eski oturum iptal edildi, eski parola geçersiz, yenisi geçerli
    assert api.get("/v1/me").status_code == 401
    assert api.login("r@example.com", GOOD_PASSWORD).status_code == 401
    assert api.login("r@example.com", NEW_PASSWORD).status_code == 200
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "auth.password_reset" in actions


def test_reset_token_expires(api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection) -> None:
    api.register("x@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "x@example.com"})
    token = _token_from(outbox, "x@example.com")
    admin_conn.execute("UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'")
    r = api.post("/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD})
    assert r.status_code == 400
    assert api.login("x@example.com", GOOD_PASSWORD).status_code == 200  # parola değişmedi


def test_reset_token_lifetime_is_configured_ttl(api: Api, admin_conn: psycopg.Connection) -> None:
    api.register("l@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "l@example.com"})
    minutes = admin_conn.execute(
        "SELECT round(extract(epoch FROM expires_at - created_at) / 60) FROM password_reset_tokens"
    ).fetchone()
    assert minutes is not None and int(minutes[0]) == 30


def test_reset_request_does_not_leak_existence(api: Api, outbox: InMemoryOutbox) -> None:
    api.register("exists@example.com")
    known = api.post("/v1/auth/password-reset/request", {"email": "exists@example.com"})
    unknown = api.post("/v1/auth/password-reset/request", {"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
    assert outbox.to("ghost@example.com") == []
    assert len([m for m in outbox.to("exists@example.com") if "sıfırlama" in m.subject]) == 1


def test_new_request_invalidates_previous_token(api: Api, outbox: InMemoryOutbox) -> None:
    api.register("n@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "n@example.com"})
    first = _token_from(outbox, "n@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "n@example.com"})
    second = _token_from(outbox, "n@example.com")
    assert first != second
    assert (
        api.post(
            "/v1/auth/password-reset/confirm", {"token": first, "new_password": NEW_PASSWORD}
        ).status_code
        == 400
    )
    assert (
        api.post(
            "/v1/auth/password-reset/confirm", {"token": second, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )


def test_reset_confirm_validations(api: Api, outbox: InMemoryOutbox, fake_pwned: FakePwned) -> None:
    api.register("v@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "v@example.com"})
    token = _token_from(outbox, "v@example.com")
    assert (
        api.post("/v1/auth/password-reset/confirm", {"token": token, "new_password": "kisa"}).status_code
        == 422
    )
    fake_pwned.pwned.add("sizmis-parola-12345")
    leaked = api.post(
        "/v1/auth/password-reset/confirm", {"token": token, "new_password": "sizmis-parola-12345"}
    )
    assert leaked.status_code == 422
    # Reddedilen deneme token'ı yakmaz
    assert (
        api.post(
            "/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )
    assert (
        api.post(
            "/v1/auth/password-reset/confirm", {"token": "z" * 40, "new_password": NEW_PASSWORD}
        ).status_code
        == 400
    )
