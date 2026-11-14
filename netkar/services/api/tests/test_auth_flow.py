"""Kayıt, giriş, çıkış, oturum ve CSRF akışları."""

from __future__ import annotations

import hashlib

import psycopg

from app.core.email import InMemoryOutbox
from tests.conftest import GOOD_PASSWORD, Api, FakePwned


def test_register_login_me_logout_flow(api: Api, outbox: InMemoryOutbox) -> None:
    r = api.register("Satici@Example.com", tenant="Deneme Mağaza")
    assert r.status_code == 202
    assert r.json() == {"status": "accepted"}
    assert len(outbox.to("satici@example.com")) == 1  # e-posta normalize edildi

    # Giriş öncesi me: 401
    assert api.get("/v1/me").status_code == 401

    r = api.login("satici@example.com")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    me = api.get("/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "satici@example.com"
    assert body["role"] == "owner"
    assert body["totp_enabled"] is False
    assert body["tenant"]["name"] == "Deneme Mağaza"
    assert body["tenant"]["plan"] == "trial"
    assert body["tenant"]["currency"] == "TRY"
    assert body["tenant"]["trial_ends_at"] is not None
    assert "password" not in me.text
    assert api.get("/v1/auth/me").json() == body  # takma ad

    r = api.post("/v1/auth/logout")
    assert r.status_code == 204
    assert api.get("/v1/me").status_code == 401


def test_session_cookie_attributes_and_hash_only_storage(api: Api, admin_conn: psycopg.Connection) -> None:
    api.register("a@example.com")
    r = api.login("a@example.com")
    cookies = r.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("__Host-nk_session="))
    lowered = session.lower()
    assert "httponly" in lowered and "secure" in lowered
    assert "samesite=lax" in lowered and "path=/" in lowered
    assert "domain" not in lowered
    assert "max-age=2592000" in lowered  # 30 gün
    csrf = next(c for c in cookies if c.startswith("__Host-nk_csrf="))
    assert "secure" in csrf.lower() and "httponly" not in csrf.lower()

    raw = session.split(";")[0].split("=", 1)[1]
    assert len(raw) >= 43  # 256 bit, base64url
    rows = admin_conn.execute("SELECT token_hash FROM sessions").fetchall()
    assert rows == [(hashlib.sha256(raw.encode()).hexdigest(),)]
    assert raw not in str(admin_conn.execute("SELECT * FROM sessions").fetchall())


def test_register_does_not_leak_account_existence(api: Api, outbox: InMemoryOutbox) -> None:
    first = api.register("dup@example.com")
    second = api.register("DUP@example.com", password="baska-parola-12345")
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    subjects = [m.subject for m in outbox.to("dup@example.com")]
    assert len(subjects) == 2 and subjects[0] != subjects[1]
    # İkinci kayıt mevcut parolayı değiştirmemeli
    assert api.login("dup@example.com").status_code == 200


def test_login_failures_are_indistinguishable(api: Api) -> None:
    api.register("known@example.com")
    wrong = api.login("known@example.com", "yanlis-parola-1234")
    unknown = api.login("nobody@example.com", "yanlis-parola-1234")
    assert wrong.status_code == unknown.status_code == 401
    a, b = wrong.json(), unknown.json()
    assert a["type"] == b["type"] and a["title"] == b["title"] and a["detail"] == b["detail"]
    assert wrong.headers["content-type"].startswith("application/problem+json")


def test_password_policy(api: Api) -> None:
    short = api.register("s@example.com", password="kisa-parola")  # 11 karakter
    assert short.status_code == 422
    assert "kisa-parola" not in short.text  # girdi değeri yansıtılmaz
    assert api.register("l@example.com", password="a" * 129).status_code == 422
    assert api.register("ok1@example.com", password="a1b2c3d4e5f6").status_code == 202  # tam 12
    assert api.register("ok2@example.com", password="x" * 128).status_code == 202  # tam 128


def test_register_validation_rejects_bad_input(api: Api) -> None:
    assert (
        api.post(
            "/v1/auth/register", {"email": "gecersiz", "password": GOOD_PASSWORD, "tenant_name": "x"}
        ).status_code
        == 422
    )
    assert (
        api.post(
            "/v1/auth/register", {"email": "a@example.com", "password": GOOD_PASSWORD, "tenant_name": ""}
        ).status_code
        == 422
    )
    r = api.post(
        "/v1/auth/register",
        {"email": "a@example.com", "password": GOOD_PASSWORD, "tenant_name": "x", "role": "owner"},
    )
    assert r.status_code == 422  # beklenmeyen alan reddedilir


def test_pwned_password_rejected_on_register(api: Api, fake_pwned: FakePwned) -> None:
    fake_pwned.pwned.add("sizmis-parola-12345")
    r = api.register("p@example.com", password="sizmis-parola-12345")
    assert r.status_code == 422
    assert r.json()["type"].endswith("weak-password")


def test_csrf_required_on_state_changing_requests(api: Api) -> None:
    api.register("c@example.com")
    # Başlık ve çerez yok
    r = api.post("/v1/auth/login", {"email": "c@example.com", "password": GOOD_PASSWORD}, csrf=False)
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["type"].endswith("csrf-failed")
    # Çerez var, başlık yok
    api.csrf()
    r = api.post("/v1/auth/login", {"email": "c@example.com", "password": GOOD_PASSWORD}, csrf=False)
    assert r.status_code == 403
    # Başlık çerezle uyuşmuyor
    r = api.post(
        "/v1/auth/login",
        {"email": "c@example.com", "password": GOOD_PASSWORD},
        csrf=False,
        headers={"X-CSRF-Token": "x" * 43},
    )
    assert r.status_code == 403
    # Doğru çift: geçer
    assert api.login("c@example.com").status_code == 200
    # Oturum açıkken CSRF'siz çıkış reddedilir ve oturum bozulmaz
    assert api.post("/v1/auth/logout", csrf=False).status_code == 403
    assert api.get("/v1/me").status_code == 200


def test_csrf_endpoint_keeps_existing_token(api: Api) -> None:
    first = api.csrf()
    assert api.csrf() == first
    assert len(first) >= 32


def test_session_idle_and_absolute_expiry_and_revocation(api: Api, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("e@example.com")
    assert api.get("/v1/me").status_code == 200

    admin_conn.execute("UPDATE sessions SET last_seen_at = now() - interval '11 hours'")
    assert api.get("/v1/me").status_code == 200  # boşta 12 saat dolmadı
    admin_conn.execute("UPDATE sessions SET last_seen_at = now() - interval '13 hours'")
    assert api.get("/v1/me").status_code == 401  # boşta süre doldu

    admin_conn.execute("UPDATE sessions SET last_seen_at = now(), expires_at = now() - interval '1 second'")
    assert api.get("/v1/me").status_code == 401  # mutlak süre doldu

    admin_conn.execute("UPDATE sessions SET expires_at = now() + interval '1 day', revoked_at = now()")
    assert api.get("/v1/me").status_code == 401  # iptal edilmiş


def test_session_last_seen_is_refreshed(api: Api, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("t@example.com")
    admin_conn.execute("UPDATE sessions SET last_seen_at = now() - interval '2 hours'")
    assert api.get("/v1/me").status_code == 200
    age = admin_conn.execute("SELECT extract(epoch FROM now() - last_seen_at) FROM sessions").fetchone()
    assert age is not None and age[0] < 60


def test_logout_revokes_in_db_and_is_idempotent(api: Api, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("o@example.com")
    api.post("/v1/auth/logout")
    revoked = admin_conn.execute("SELECT revoked_at IS NOT NULL FROM sessions").fetchall()
    assert revoked == [(True,)]
    assert api.post("/v1/auth/logout").status_code == 204  # oturumsuz çağrı da 204
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert actions == ["tenant.created", "auth.login", "auth.logout"]


def test_forged_session_cookie_is_rejected(api: Api) -> None:
    api.signup_and_login("f@example.com")
    api.client.cookies.clear()
    api.client.cookies.set("__Host-nk_session", "A" * 43)
    r = api.get("/v1/me")
    assert r.status_code == 401


def test_failed_login_is_audited_without_pii(api: Api, admin_conn: psycopg.Connection) -> None:
    api.register("w@example.com")
    api.login("w@example.com", "yanlis-parola-1234")
    row = admin_conn.execute(
        "SELECT action, meta::text, ip_hash FROM audit_log WHERE action='auth.login_failed'"
    ).fetchone()
    assert row is not None
    assert row[1] == "{}"
    assert "w@example.com" not in str(admin_conn.execute("SELECT * FROM audit_log").fetchall())
    assert row[2] is not None and "testclient" not in row[2]


def test_viewer_cannot_read_admin_endpoints(api: Api, admin_conn: psycopg.Connection) -> None:
    api.signup_and_login("v@example.com")
    admin_conn.execute("UPDATE memberships SET role = 'viewer'")
    assert api.get("/v1/tenant/audit").status_code == 403
    assert api.get("/v1/tenant/sessions").status_code == 403
    assert api.get("/v1/tenant/members").status_code == 200


def test_admin_endpoints_list_own_data(api: Api) -> None:
    api.signup_and_login("own@example.com")
    members = api.get("/v1/tenant/members").json()
    assert len(members) == 1 and members[0]["role"] == "owner"
    sessions = api.get("/v1/tenant/sessions").json()
    assert len(sessions) == 1 and sessions[0]["current"] is True
    assert "token" not in str(sessions)
    audit = api.get("/v1/tenant/audit?limit=2").json()
    assert [a["action"] for a in audit] == ["auth.login", "tenant.created"]
    assert api.get("/v1/tenant/audit?limit=0").status_code == 422
