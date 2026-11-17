"""E-posta doğrulama, doğrulanmamış hesap kısıtı ve ön ele geçirme önlemi (denetim S1 O-06).

Kapsam: doğrulama token'ı (tek kullanımlık, süreli, yalnız özet), yeniden gönderme (oturumlu, hız sınırlı),
numaralandırma sızıntısı olmaması, doğrulanmamış hesabın yazma ve TOTP uçlarında 403, parola sıfırlamanın
TOTP davranışı (doğrulanmış: korunur; doğrulanmamış: temizlenir) ve e-posta bağlantılarının web yolları.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from app.core.email import InMemoryOutbox
from tests.conftest import Api, FakeClock

NEW_PASSWORD = "yepyeni-parola-9876"
WEB = "https://app.test.invalid"


def _reset_token(outbox: InMemoryOutbox, email: str) -> str:
    message = outbox.to(email)[-1]
    match = re.search(r"/sifre-sifirla\?token=([A-Za-z0-9_\-]+)", message.body)
    assert match, message.body
    return match.group(1)


def _is_problem(response: Any, status: int, slug: str) -> bool:
    return bool(
        response.status_code == status
        and str(response.headers.get("content-type", "")).startswith("application/problem+json")
        and response.json()["type"].endswith(slug)
    )


# --- kayıt ve doğrulama ------------------------------------------------------------------------------
def test_register_sends_one_email_with_turkish_web_links_and_hash_only_token(
    api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection
) -> None:
    assert api.register("yeni@example.com").status_code == 202
    messages = outbox.to("yeni@example.com")
    assert len(messages) == 1  # hesap bildirimi ve doğrulama tek iletide
    body = messages[0].body
    assert f"{WEB}/e-posta-dogrula?token=" in body
    assert f"{WEB}/giris" in body and f"{WEB}/sifre-sifirla" in body
    assert "/login" not in body and "/forgot-password" not in body and "/reset-password" not in body
    token = api.verification_token("yeni@example.com")
    assert len(token) >= 43  # 256 bit
    rows = admin_conn.execute(
        "SELECT token_hash, expires_at, used_at FROM email_verification_tokens"
    ).fetchall()
    assert [r[0] for r in rows] == [hashlib.sha256(token.encode()).hexdigest()]  # ham token saklanmaz
    assert rows[0][2] is None
    remaining = rows[0][1] - datetime.now(UTC)
    assert timedelta(hours=23, minutes=55) < remaining <= timedelta(hours=24)
    assert admin_conn.execute("SELECT email_verified_at FROM users").fetchone() == (None,)


def test_verify_flow_marks_user_verified_and_token_is_single_use(
    api: Api, admin_conn: psycopg.Connection
) -> None:
    api.register("v@example.com")
    api.login("v@example.com")
    assert api.get("/v1/me").json()["email_verified"] is False
    token = api.verification_token("v@example.com")

    r = api.post("/v1/auth/email/verify", {"token": token})
    assert r.status_code == 204
    assert api.get("/v1/me").json()["email_verified"] is True
    assert admin_conn.execute("SELECT email_verified_at IS NOT NULL FROM users").fetchone() == (True,)

    again = api.post("/v1/auth/email/verify", {"token": token})
    assert _is_problem(again, 400, "invalid-verification-token")
    unknown = api.post("/v1/auth/email/verify", {"token": "x" * 43})
    assert _is_problem(unknown, 400, "invalid-verification-token")
    short = api.post("/v1/auth/email/verify", {"token": "kisa"})
    assert short.status_code == 422
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "auth.email_verified" in actions


def test_verify_works_without_session(make_api: Callable[..., Api]) -> None:
    """Token e-posta kutusuna erişimi kanıtlar; bağlantı başka tarayıcıda da açılabilir."""
    first = make_api()
    first.register("o@example.com")
    token = first.verification_token("o@example.com")
    other = make_api()
    assert other.post("/v1/auth/email/verify", {"token": token}).status_code == 204
    assert other.login("o@example.com").status_code == 200
    assert other.get("/v1/me").json()["email_verified"] is True


def test_verify_token_expires(api: Api, admin_conn: psycopg.Connection) -> None:
    api.register("e@example.com")
    token = api.verification_token("e@example.com")
    admin_conn.execute("UPDATE email_verification_tokens SET expires_at = now() - interval '1 second'")
    assert _is_problem(api.post("/v1/auth/email/verify", {"token": token}), 400, "invalid-verification-token")
    assert admin_conn.execute("SELECT email_verified_at FROM users").fetchone() == (None,)


def test_verify_rejects_extra_fields_and_requires_csrf(api: Api) -> None:
    api.register("c@example.com")
    token = api.verification_token("c@example.com")
    assert api.post("/v1/auth/email/verify", {"token": token, "x": 1}).status_code == 422
    assert api.post("/v1/auth/email/verify", {"token": token}, csrf=False).status_code == 403


def test_verify_is_rate_limited_per_ip_before_body_is_parsed(
    make_api: Callable[..., Api], frozen_ratelimit_clock: float
) -> None:
    api = make_api(rate_limit_verify_confirm_ip=2)
    codes = [api.post("/v1/auth/email/verify", {"token": "y" * 43}).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


# --- yeniden gönderme --------------------------------------------------------------------------------
def test_resend_requires_session(api: Api) -> None:
    assert api.post("/v1/auth/email/resend").status_code == 401


def test_resend_sends_fresh_link_to_own_address_and_invalidates_old(
    api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection
) -> None:
    api.register("r@example.com")
    api.login("r@example.com")
    old = api.verification_token("r@example.com")
    r = api.post("/v1/auth/email/resend")
    assert r.status_code == 202 and r.json() == {"status": "accepted"}
    assert len(outbox.to("r@example.com")) == 2
    assert all(m.to == "r@example.com" for m in outbox.messages)
    new = api.verification_token("r@example.com")
    assert new != old
    # Yalnız en son bağlantı geçerli
    assert _is_problem(api.post("/v1/auth/email/verify", {"token": old}), 400, "invalid-verification-token")
    assert api.post("/v1/auth/email/verify", {"token": new}).status_code == 204
    actions = [r[0] for r in admin_conn.execute("SELECT action FROM audit_log ORDER BY id")]
    assert "auth.email_verification_sent" in actions


def test_resend_takes_no_address_from_the_request(api: Api, outbox: InMemoryOutbox) -> None:
    api.register("own@example.com")
    api.login("own@example.com")
    assert api.post("/v1/auth/email/resend", {"email": "baskasi@example.com"}).status_code in (202, 422)
    assert outbox.to("baskasi@example.com") == []


def test_resend_is_conflict_when_already_verified(api: Api, outbox: InMemoryOutbox) -> None:
    api.signup_and_login("done@example.com")
    sent = len(outbox.messages)
    assert _is_problem(api.post("/v1/auth/email/resend"), 409, "email-already-verified")
    assert len(outbox.messages) == sent


def test_resend_is_rate_limited_per_user(make_api: Callable[..., Api], frozen_ratelimit_clock: float) -> None:
    api = make_api(rate_limit_verify_resend_user=2)
    api.register("lim@example.com")
    api.login("lim@example.com")
    codes = [api.post("/v1/auth/email/resend").status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_resend_is_rate_limited_per_ip(make_api: Callable[..., Api], frozen_ratelimit_clock: float) -> None:
    api = make_api(rate_limit_verify_resend_ip=1)
    api.register("ip@example.com")
    api.login("ip@example.com")
    assert [api.post("/v1/auth/email/resend").status_code for _ in range(2)] == [202, 429]


# --- numaralandırma ----------------------------------------------------------------------------------
def test_register_for_existing_email_is_same_202_and_sends_no_verification_link(
    api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection
) -> None:
    first = api.register("dup@example.com")
    second = api.register("DUP@example.com", password="baska-parola-12345")
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert api.register("hic-yok@example.com").json() == second.json()
    existing_mail = outbox.to("dup@example.com")[-1]
    assert "e-posta-dogrula" not in existing_mail.body  # yeni token üretilmez
    assert f"{WEB}/sifre-sifirla" in existing_mail.body and "/forgot-password" not in existing_mail.body
    assert admin_conn.execute("SELECT count(*) FROM email_verification_tokens").fetchone() == (2,)
    # Mevcut hesabın parolası değişmedi
    assert api.login("dup@example.com").status_code == 200


# --- doğrulanmamış hesap kısıtı ----------------------------------------------------------------------
def test_unverified_account_is_blocked_on_write_and_totp_endpoints(api: Api) -> None:
    api.signup_and_login("u@example.com", verified=False)
    account = uuid.uuid4()
    base = f"/v1/marketplace-accounts/{account}"
    blocked = [
        api.post(
            "/v1/marketplace-accounts",
            {"seller_id": "2738", "api_key": "anahtar-12345678", "api_secret": "sir-12345678"},
        ),
        api.put(
            f"{base}/products/ABC123/costs",
            {"valid_from": "2026-01-01", "unit_cost_excl_vat": "10.00", "vat_rate": "20"},
        ),
        api.post(f"{base}/product-costs/import", files={"file": ("m.csv", b"a;b\n1;2\n", "text/csv")}),
        api.post(f"{base}/profit-settings/variable-expenses", {"name": "x"}),
        api.delete(f"{base}/profit-settings/variable-expenses/{uuid.uuid4()}"),
        api.post("/v1/auth/totp/setup"),
        api.post("/v1/auth/totp/enable", {"code": "123456"}),
    ]
    for response in blocked:
        assert _is_problem(response, 403, "email-not-verified"), response.text
        assert response.json()["status"] == 403 and response.json()["title"]


def test_unverified_account_can_read_and_log_out(api: Api) -> None:
    api.signup_and_login("ro@example.com", verified=False)
    assert api.get("/v1/me").status_code == 200
    assert api.get("/v1/marketplace-accounts").json() == []
    assert api.post("/v1/auth/email/resend").status_code == 202
    assert api.post("/v1/auth/logout").status_code == 204
    assert api.get("/v1/me").status_code == 401


def test_verified_account_passes_the_gate(api: Api) -> None:
    """Doğrulanınca aynı uç artık 403 değil: bilinmeyen hesap için 404 (kapı geçildi)."""
    api.signup_and_login("ok@example.com", verified=False)
    base = f"/v1/marketplace-accounts/{uuid.uuid4()}/products/ABC123/costs"
    body = {"valid_from": "2026-01-01", "unit_cost_excl_vat": "10.00", "vat_rate": "20"}
    assert api.put(base, body).status_code == 403
    assert api.verify_email("ok@example.com").status_code == 204
    assert api.put(base, body).status_code == 404
    totp = api.post("/v1/auth/totp/setup")
    assert totp.status_code == 200


# --- ön ele geçirme (O-06) ---------------------------------------------------------------------------
def test_prehijack_attacker_cannot_lock_out_the_real_owner(
    make_api: Callable[..., Api], outbox: InMemoryOutbox, admin_conn: psycopg.Connection, clock: FakeClock
) -> None:
    """PoC'nin tersi: saldırgan kurbanın e-postasıyla kayıt olur; TOTP kuramaz; sıfırlama hesabı devreder."""
    attacker = make_api()
    victim_email = "ceo@kurban.example"
    attacker.register(victim_email, password="saldirgan-parolasi-77")
    assert attacker.login(victim_email, "saldirgan-parolasi-77").status_code == 200
    assert attacker.post("/v1/auth/totp/setup").status_code == 403  # ikinci faktör kurulamaz
    assert attacker.post("/v1/auth/totp/enable", {"code": "123456"}).status_code == 403

    # Gerçek sahip "şifremi unuttum" ile hesabı devralır.
    victim = make_api()
    assert victim.post("/v1/auth/password-reset/request", {"email": victim_email}).status_code == 202
    token = _reset_token(outbox, victim_email)
    assert (
        victim.post(
            "/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )

    assert attacker.get("/v1/me").status_code == 401  # saldırganın oturumu öldü
    assert attacker.login(victim_email, "saldirgan-parolasi-77").status_code == 401
    ok = victim.login(victim_email, NEW_PASSWORD)
    assert ok.status_code == 200 and ok.json() == {"status": "ok"}
    me = victim.get("/v1/me").json()
    assert me["email_verified"] is True and me["totp_enabled"] is False
    meta = admin_conn.execute("SELECT meta FROM audit_log WHERE action = 'auth.password_reset'").fetchone()
    assert meta == ({"claimed_unverified": True},)
    # Bekleyen doğrulama bağlantısı da kapandı (saldırganın parolasına bağlı hesap tekrar doğrulanamaz)
    assert admin_conn.execute(
        "SELECT count(*) FROM email_verification_tokens WHERE used_at IS NULL"
    ).fetchone() == (0,)


def test_reset_of_unverified_account_clears_totp_even_if_it_was_somehow_enabled(
    make_api: Callable[..., Api], outbox: InMemoryOutbox, admin_conn: psycopg.Connection
) -> None:
    """Savunma derinliği: önceki sürümde kurulmuş saldırgan TOTP'si (veri) sıfırlamayla temizlenir."""
    api = make_api()
    api.register("eski@example.com")
    admin_conn.execute(
        "UPDATE users SET totp_enabled = true, totp_secret_encrypted = 'v1:x', totp_last_step = 5, "
        "totp_failed_count = 3, totp_locked_until = now() + interval '1 hour'"
    )
    api.post("/v1/auth/password-reset/request", {"email": "eski@example.com"})
    token = _reset_token(outbox, "eski@example.com")
    assert (
        api.post(
            "/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )
    row = admin_conn.execute(
        "SELECT totp_enabled, totp_secret_encrypted, totp_last_step, totp_failed_count, totp_locked_until, "
        "email_verified_at IS NOT NULL FROM users"
    ).fetchone()
    assert row == (False, None, None, 0, None, True)
    assert api.login("eski@example.com", NEW_PASSWORD).json() == {"status": "ok"}


# --- parola sıfırlama ve TOTP (madde 6) --------------------------------------------------------------
def _enable_totp(api: Api, clock: FakeClock) -> str:
    secret = str(api.post("/v1/auth/totp/setup").json()["secret"])
    assert api.post("/v1/auth/totp/enable", {"code": clock.code(secret)}).status_code == 204
    clock.advance(30)
    return secret


def test_password_reset_keeps_totp_and_revokes_all_sessions_for_verified_account(
    make_api: Callable[..., Api], outbox: InMemoryOutbox, admin_conn: psycopg.Connection, clock: FakeClock
) -> None:
    email = "guvenli@example.com"
    first = make_api()
    first.signup_and_login(email)
    secret = _enable_totp(first, clock)
    # İkinci açık oturum (başka cihaz): TOTP ile girilmiş
    second = make_api()
    assert second.login(email).json() == {"status": "totp_required"}
    assert second.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200
    clock.advance(30)
    assert first.get("/v1/me").status_code == 200 and second.get("/v1/me").status_code == 200

    # E-posta ele geçirildi varsayımı: saldırgan parolayı sıfırlar.
    attacker = make_api()
    attacker.post("/v1/auth/password-reset/request", {"email": email})
    token = _reset_token(outbox, email)
    assert (
        attacker.post(
            "/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD}
        ).status_code
        == 204
    )

    # Tüm açık oturumlar sonlandı
    assert first.get("/v1/me").status_code == 401 and second.get("/v1/me").status_code == 401
    assert admin_conn.execute("SELECT count(*) FROM sessions WHERE revoked_at IS NULL").fetchone() == (0,)
    # TOTP etkin kaldı ve girişte isteniyor: yeni parola tek başına oturum açmaz
    assert admin_conn.execute(
        "SELECT totp_enabled, totp_secret_encrypted IS NOT NULL FROM users"
    ).fetchone() == (
        True,
        True,
    )
    login = attacker.login(email, NEW_PASSWORD)
    assert login.json() == {"status": "totp_required"}
    assert attacker.get("/v1/me").status_code == 401  # oturum çerezi verilmedi
    bad = attacker.post("/v1/auth/totp/verify", {"code": "000000"})
    assert bad.status_code == 401
    # Gerçek sahip (TOTP cihazı elinde) girebilir
    assert attacker.post("/v1/auth/totp/verify", {"code": clock.code(secret)}).status_code == 200
    meta = admin_conn.execute("SELECT meta FROM audit_log WHERE action = 'auth.password_reset'").fetchone()
    assert meta == ({"claimed_unverified": False},)


def test_reset_of_verified_account_does_not_touch_verification_state(
    api: Api, outbox: InMemoryOutbox, admin_conn: psycopg.Connection
) -> None:
    api.signup_and_login("kalici@example.com")
    before = admin_conn.execute("SELECT email_verified_at FROM users").fetchone()
    api.post("/v1/auth/password-reset/request", {"email": "kalici@example.com"})
    token = _reset_token(outbox, "kalici@example.com")
    api.post("/v1/auth/password-reset/confirm", {"token": token, "new_password": NEW_PASSWORD})
    assert admin_conn.execute("SELECT email_verified_at FROM users").fetchone() == before


def test_reset_email_link_uses_turkish_web_path_with_token(api: Api, outbox: InMemoryOutbox) -> None:
    api.register("link@example.com")
    api.post("/v1/auth/password-reset/request", {"email": "link@example.com"})
    body = outbox.to("link@example.com")[-1].body
    assert re.search(rf"{re.escape(WEB)}/sifre-sifirla\?token=[A-Za-z0-9_\-]{{20,}}", body)
    assert "/reset-password" not in body
    # Doğrulama bağlantısı web sayfasının beklediği ?token= biçiminde ve token şemasına (20-200) uyar
    verify_token = api.verification_token("link@example.com")
    assert re.fullmatch(r"[A-Za-z0-9._~-]{20,200}", verify_token)
