"""Tek tık kapatma ucu (ADR-0009 §7.5, §12 madde 26): `POST /v1/notifications/unsubscribe`.

Kapsam: imzalı token ile (oturumsuz) yalnız ilgili kullanıcı/kural/kanal `off` olur; başka kullanıcının tercihleri
değişmez; bozuk, süresi dolmuş, başka anahtarla imzalı ve olmayan kullanıcıya ait token aynı 400'ü verir; uç yalnız
`off` yazar (`instant` olamaz); IP hız sınırı; audit izi; yanıtta token ve adres yok.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from app.alerts import AlertRule
from app.core.config import Settings
from app.services.notify_unsubscribe import ALL_RULES, UnsubscribeSigner
from tests.conftest import Api

RULES = [rule.value for rule in AlertRule]
LOSS = AlertRule.LOSS_MAKING_SALE.value
RETURNS = AlertRule.RETURN_RATE_INCREASE.value
URL = "/v1/notifications/unsubscribe"


def identity(conn: psycopg.Connection[Any], email: str) -> tuple[UUID, UUID]:
    row = conn.execute(
        "SELECT u.id, m.tenant_id FROM users u JOIN memberships m ON m.user_id = u.id WHERE u.email = %s",
        (email,),
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def preferences(conn: psycopg.Connection[Any], user_id: UUID) -> dict[tuple[str, str], str]:
    return {
        (r[0], r[1]): r[2]
        for r in conn.execute(
            "SELECT rule, channel, mode FROM notification_preferences WHERE user_id = %s", (user_id,)
        )
    }


def sign(
    settings: Settings,
    user: UUID,
    tenant: UUID,
    rule: str = LOSS,
    channel: str = "email",
    at: datetime | None = None,
) -> str:
    return UnsubscribeSigner.from_settings(settings).sign(
        user, tenant, rule, channel, at or datetime.now(UTC)
    )


def two_users(
    make_api: Callable[..., Api], conn: psycopg.Connection[Any]
) -> tuple[Api, tuple[UUID, UUID], tuple[UUID, UUID]]:
    first = make_api()
    first.signup_and_login("birinci@example.com", tenant="Birinci Mağaza")
    second = make_api()
    second.signup_and_login("ikinci@example.com", tenant="İkinci Mağaza")
    return make_api(), identity(conn, "birinci@example.com"), identity(conn, "ikinci@example.com")


def test_token_turns_off_only_its_rule_and_channel_without_a_session(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), (other_user, other_tenant) = two_users(make_api, admin_conn)
    admin_conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES "
        "(%s, %s, %s, 'email', 'instant'), (%s, %s, %s, 'push', 'instant'), (%s, %s, %s, 'email', 'digest')",
        (tenant, user, LOSS, tenant, user, LOSS, tenant, user, RETURNS),
    )
    admin_conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, 'email', 'instant')",
        (other_tenant, other_user, LOSS),
    )
    response = anonymous.post(f"{URL}?token={sign(settings, user, tenant)}")  # oturum çerezi yok
    assert response.status_code == 200
    assert response.json() == {"rules": [LOSS], "channel": "email", "mode": "off"}
    assert preferences(admin_conn, user) == {
        (LOSS, "email"): "off",
        (LOSS, "push"): "instant",
        (RETURNS, "email"): "digest",
    }
    assert preferences(admin_conn, other_user) == {(LOSS, "email"): "instant"}  # başka kullanıcı etkilenmedi
    # Aynı bağlantı tekrar kullanılabilir ve sonuç aynı (idempotent).
    again = anonymous.post(f"{URL}?token={sign(settings, user, tenant)}")
    assert again.status_code == 200 and preferences(admin_conn, user)[(LOSS, "email")] == "off"
    assert "token" not in response.text and "@" not in response.text  # yanıt token ve adres taşımaz
    audit = admin_conn.execute(
        "SELECT user_id, meta FROM audit_log WHERE action = 'notification.unsubscribe' ORDER BY created_at"
    ).fetchall()
    assert len(audit) == 2 and audit[0][0] == user and audit[0][1] == {"rules": [LOSS], "channel": "email"}


def test_wildcard_token_turns_off_every_rule_of_the_channel_and_inserts_missing_rows(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    response = anonymous.post(f"{URL}?token={sign(settings, user, tenant, ALL_RULES)}")
    assert response.status_code == 200 and response.json()["rules"] == RULES
    assert preferences(admin_conn, user) == {(rule, "email"): "off" for rule in RULES}


def test_the_endpoint_can_only_write_off_never_instant_or_digest(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    admin_conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, 'email', 'digest')",
        (tenant, user, LOSS),
    )
    for extra in (
        "&mode=instant",
        "&mode=digest",
        "&rule=IADE_ORANI_ARTISI",
        "&channel=push",
        "&user_id=" + str(uuid4()),
    ):
        response = anonymous.post(f"{URL}?token={sign(settings, user, tenant)}{extra}")
        assert response.status_code == 200
    assert preferences(admin_conn, user) == {(LOSS, "email"): "off"}  # fazladan parametreler yok sayıldı


@pytest.mark.parametrize("case", ["expired", "tampered", "other_key", "garbage", "unknown_user"])
def test_every_invalid_token_gets_the_same_400_and_changes_nothing(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings, case: str
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    good = sign(settings, user, tenant)
    tokens = {
        "expired": sign(settings, user, tenant, at=datetime.now(UTC) - timedelta(days=91)),
        "tampered": good[:-3] + ("AAA" if not good.endswith("AAA") else "BBB"),
        "other_key": UnsubscribeSigner(b"baska-anahtar-0123456789abcdef", ttl=timedelta(days=90)).sign(
            user, tenant, LOSS, "email", datetime.now(UTC)
        ),
        "garbage": "bozuk.token",
        "unknown_user": sign(settings, uuid4(), tenant),  # imzalı ama kullanıcı yok (yabancı anahtar hatası)
    }
    response = anonymous.post(f"{URL}?token={tokens[case]}")
    assert response.status_code == 400
    body = response.json()
    assert body["type"].endswith("invalid-unsubscribe-token") and body["title"] == "Geçersiz bağlantı"
    assert "süresi dolmuş" in body["detail"]  # tek ortak ileti: ayrım sızdırılmaz
    assert preferences(admin_conn, user) == {}
    assert admin_conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'notification.unsubscribe'"
    ).fetchone() == (0,)


def test_missing_or_empty_token_is_a_validation_error(make_api: Callable[..., Api]) -> None:
    anonymous = make_api()
    assert anonymous.post(URL).status_code == 422
    assert anonymous.post(f"{URL}?token=").status_code == 422
    assert anonymous.post(f"{URL}?token={'a' * 513}").status_code == 422


def test_the_exact_path_is_csrf_exempt_and_neither_reads_nor_writes_cookies(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    anonymous.client.cookies.clear()
    ok = anonymous.post(
        f"{URL}?token={sign(settings, user, tenant)}", csrf=False
    )  # çerezsiz, başlıksız (posta istemcisi)
    assert ok.status_code == 200 and preferences(admin_conn, user) == {(LOSS, "email"): "off"}
    assert "set-cookie" not in ok.headers and not anonymous.client.cookies  # çerez yazmaz
    bad = anonymous.post(f"{URL}?token=bozuk.token", csrf=False)
    assert bad.status_code == 400 and "set-cookie" not in bad.headers
    # Sahte oturum/CSRF çerezleri sonucu değiştirmez (çerez okunmaz).
    anonymous.client.cookies.set("__Host-nk_session", "sahte")
    again = anonymous.post(f"{URL}?token={sign(settings, user, tenant, RETURNS)}", csrf=False)
    assert again.status_code == 200 and preferences(admin_conn, user)[(RETURNS, "email")] == "off"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/notifications/unsubscribe/"),  # sonda eğik çizgi
        ("post", "/v1/notifications/x"),  # önek değil, tam eşleşme
        ("post", "/v1/notifications/unsubscribe/extra"),
        ("post", "/v1/Notifications/unsubscribe"),  # büyük/küçük harf
        ("put", "/v1/me/notification-preferences"),  # başka bildirim ucu muaf DEĞİL
        ("put", "/v1/notifications/unsubscribe"),  # yalnız POST muaf
        ("delete", "/v1/notifications/unsubscribe"),
    ],
)
def test_every_other_state_changing_path_still_needs_csrf(
    make_api: Callable[..., Api], method: str, path: str
) -> None:
    anonymous = make_api()
    response = getattr(anonymous, method)(f"{path}?token=x.y", csrf=False)
    assert response.status_code == 403 and response.json()["type"].endswith("csrf-failed")


def test_get_changes_nothing(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    response = anonymous.get(f"{URL}?token={sign(settings, user, tenant)}")
    assert response.status_code == 405
    assert preferences(admin_conn, user) == {}
    assert admin_conn.execute(
        "SELECT count(*) FROM audit_log WHERE action = 'notification.unsubscribe'"
    ).fetchone() == (0,)


def test_body_is_optional_but_when_present_must_be_the_rfc_8058_form(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    url = f"{URL}?token={sign(settings, user, tenant)}"
    form = {"content-type": "application/x-www-form-urlencoded"}
    for bad_kwargs in (
        {"content": b"List-Unsubscribe=One-Click", "headers": {"content-type": "text/plain"}},
        {"content": b'{"List-Unsubscribe": "One-Click"}', "headers": {"content-type": "application/json"}},
        {"content": b"List-Unsubscribe=Yes", "headers": form},
        {"content": b"List-Unsubscribe=One-Click&extra=1", "headers": form},
        {"content": b"bozuk", "headers": form},
        {"content": "List-Unsubscribe=One-Click\u00e7".encode(), "headers": form},
    ):
        response = anonymous.post(url, csrf=False, **bad_kwargs)
        assert response.status_code == 400, bad_kwargs
    assert preferences(admin_conn, user) == {}
    good = anonymous.post(url, csrf=False, content=b"List-Unsubscribe=One-Click", headers=form)
    assert good.status_code == 200
    charset = anonymous.post(
        url,
        csrf=False,
        content=b"List-Unsubscribe=One-Click",
        headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8"},
    )
    assert charset.status_code == 200 and preferences(admin_conn, user) == {(LOSS, "email"): "off"}


def test_a_user_who_is_no_longer_a_member_of_the_tenant_gets_the_same_400(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), (other_user, other_tenant) = two_users(make_api, admin_conn)
    # Birinci kullanıcı İKİNCİ kiracının üyesi değil: imzalı ama üyelik yok.
    response = anonymous.post(f"{URL}?token={sign(settings, user, other_tenant)}", csrf=False)
    assert response.status_code == 400 and response.json()["type"].endswith("invalid-unsubscribe-token")
    assert preferences(admin_conn, user) == {} and preferences(admin_conn, other_user) == {}
    admin_conn.execute("ALTER TABLE memberships DISABLE TRIGGER USER")
    try:  # üyelikten çıkarılmış
        admin_conn.execute("DELETE FROM memberships WHERE user_id = %s", (user,))
        removed = anonymous.post(f"{URL}?token={sign(settings, user, tenant)}", csrf=False)
    finally:
        admin_conn.execute(
            "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')", (user, tenant)
        )
        admin_conn.execute("ALTER TABLE memberships ENABLE ALWAYS TRIGGER memberships_immutable_guard")
    assert removed.status_code == 400 and preferences(admin_conn, user) == {}


@pytest.mark.usefixtures("frozen_ratelimit_clock")
def test_valid_tokens_use_a_per_token_limit_and_do_not_consume_the_ip_limit(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    api = make_api(rate_limit_notify_unsubscribe_ip=2, rate_limit_notify_unsubscribe_token=3)
    _, (user, tenant), (other_user, other_tenant) = two_users(make_api, admin_conn)
    tok = sign(settings, user, tenant)
    other = sign(settings, other_user, other_tenant)
    codes = [api.post(f"{URL}?token={tok}", csrf=False).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]  # token başına 3
    assert api.post(f"{URL}?token={other}", csrf=False).status_code == 200  # başka token etkilenmez
    # IP sınırı yalnız başarısız doğrulamaya işler: 5 geçerli istek sonrası bile ilk başarısızlık 400.
    fails = [api.post(f"{URL}?token=bozuk.{n}", csrf=False).status_code for n in range(3)]
    assert fails == [400, 400, 429]


@pytest.mark.usefixtures("frozen_ratelimit_clock")
def test_attempts_are_rate_limited_per_ip(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    api = make_api(rate_limit_notify_unsubscribe_ip=2)
    statuses = [api.post(f"{URL}?token=bozuk.token").status_code for _ in range(4)]
    assert statuses == [400, 400, 429, 429]
