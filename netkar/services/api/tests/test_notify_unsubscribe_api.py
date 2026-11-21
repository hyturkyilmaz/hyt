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
        ("post", "/v1/notifications/unsubscribe%2F"),  # kodlu eğik çizgi: çözülünce sonda `/`
        ("post", "/v1/notifications%2Funsubscribe/x"),
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


def test_percent_encoding_is_decoded_before_matching_so_it_reaches_the_same_exempt_endpoint(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    """`unsubscrib%65` yönlendirmeden önce `unsubscribe` olur: aynı uç, aynı muafiyet (başka uca sızmaz)."""
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    encoded = anonymous.post(
        f"/v1/notifications/unsubscrib%65?token={sign(settings, user, tenant)}", csrf=False
    )
    assert encoded.status_code == 200 and preferences(admin_conn, user) == {(LOSS, "email"): "off"}
    other = anonymous.post("/v1/me/notification-preferenc%65s?token=x.y", csrf=False)  # başka uç: muaf DEĞİL
    assert other.status_code in (403, 404, 405)
    assert not (other.status_code == 200)


def test_a_single_field_multipart_one_click_body_is_accepted_and_others_are_not(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    url = f"{URL}?token={sign(settings, user, tenant)}"

    def multipart(*fields: tuple[str, str]) -> dict[str, Any]:
        boundary = "----netkar"
        body = "".join(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
            for name, value in fields
        )
        return {
            "content": (body + f"--{boundary}--\r\n").encode(),
            "headers": {"content-type": f"multipart/form-data; boundary={boundary}"},
        }

    for bad in (
        multipart(("List-Unsubscribe", "Yes")),
        multipart(("Baska", "One-Click")),
        multipart(("List-Unsubscribe", "One-Click"), ("extra", "1")),  # tek alan değil
        multipart(),
        {"content": b"--x\r\nbozuk", "headers": {"content-type": "multipart/form-data; boundary=x"}},
        {
            "content": b"List-Unsubscribe=One-Click",
            "headers": {"content-type": "multipart/form-data"},
        },  # sınır yok
    ):
        assert anonymous.post(url, csrf=False, **bad).status_code == 400, bad
    assert preferences(admin_conn, user) == {}
    good = anonymous.post(url, csrf=False, **multipart(("List-Unsubscribe", "One-Click")))
    assert good.status_code == 200 and preferences(admin_conn, user) == {(LOSS, "email"): "off"}


@pytest.mark.usefixtures("frozen_ratelimit_clock")
def test_the_token_counter_key_comes_from_the_verified_claim_not_the_token_text(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    api = make_api(rate_limit_notify_unsubscribe_token=2)
    _, (user, tenant), _ = two_users(make_api, admin_conn)
    signer = UnsubscribeSigner.from_settings(settings)
    first = signer.sign(user, tenant, LOSS, "email", datetime.now(UTC))
    # Aynı kullanıcı/kiracı/kural/kanal için ÜRETİLEN başka bir token (farklı bitiş zamanı) aynı sayacı paylaşır.
    second = signer.sign(user, tenant, LOSS, "email", datetime.now(UTC) + timedelta(seconds=7))
    assert first != second
    codes = [api.post(f"{URL}?token={t}", csrf=False).status_code for t in (first, second, first, second)]
    assert codes == [200, 200, 429, 429]
    # Dolgu ekleyerek biçimsel varyant üretme denemesi imza kontrolünden geçmez (kanonik biçim şartı).
    assert api.post(f"{URL}?token={first}=", csrf=False).status_code in (400, 429)


def _timed_post(api: Api, url: str, **kwargs: Any) -> tuple[int, float]:
    import time

    started = time.perf_counter()
    response = api.post(url, csrf=False, **kwargs)
    return response.status_code, time.perf_counter() - started


def test_hostile_bodies_get_400_quickly_never_500_and_are_never_parsed_when_large(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    url = f"{URL}?token={sign(settings, user, tenant)}"
    boundary = "bb"
    ct = {"content-type": f"multipart/form-data; boundary={boundary}"}
    many = (
        b"".join(b'--bb\r\nContent-Disposition: form-data; name="a"\r\n\r\nx\r\n' for _ in range(20_000))
        + b"--bb--\r\n"
    )
    nested = b"".join(b"--bb\r\nContent-Type: multipart/mixed; boundary=bb\r\n\r\n" for _ in range(1000))
    cases: dict[str, dict[str, Any]] = {
        "büyük çok parçalı (1 MiB civarı)": {"content": many, "headers": ct},
        "büyük urlencoded": {
            "content": b"a=" + b"x" * 1_000_000,
            "headers": {"content-type": "application/x-www-form-urlencoded"},
        },
        "iç içe multipart": {"content": nested, "headers": ct},
        "bozuk Content-Disposition (0*)": {
            "content": b"--bb\r\nContent-Disposition: form-data; 0*\r\n\r\nOne-Click\r\n--bb--\r\n",
            "headers": ct,
        },
        "disposition olmayan": {"content": b"--bb\r\nX: y\r\n\r\nOne-Click\r\n--bb--\r\n", "headers": ct},
        "sınır içeren değer": {
            "content": b'--bb\r\nContent-Disposition: form-data; name="List-Unsubscribe"\r\n\r\nOne-Click\r\n--bb\r\n--bb--',
            "headers": ct,
        },
        "ikinci başlık": {
            "content": b'--bb\r\nContent-Disposition: form-data; name="List-Unsubscribe"\r\nX-A: b\r\n\r\nOne-Click\r\n--bb--',
            "headers": ct,
        },
        "ASCII dışı değer": {
            "content": b'--bb\r\nContent-Disposition: form-data; name="List-Unsubscribe"\r\n\r\n\xff\r\n--bb--',
            "headers": ct,
        },
        "1 KiB'den az ama bozuk": {"content": b"\x00" * 900, "headers": ct},
    }
    for name, kwargs in cases.items():
        status, elapsed = _timed_post(anonymous, url, **kwargs)
        # 500 değil: ya uç 400 verir ya da genel gövde sınırı ara katmanı (1 MiB üstü) 413 ile keser.
        assert status in ({400, 413} if "büyük" in name else {400}), name
        assert elapsed < 1.5, (name, elapsed)  # büyük gövdeler ayrıştırılmadan reddedilir
    assert preferences(admin_conn, user) == {}


def test_the_largest_valid_one_click_bodies_stay_accepted(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    anonymous, (user, tenant), _ = two_users(make_api, admin_conn)
    url = f"{URL}?token={sign(settings, user, tenant)}"
    body = b'--b-1\r\nContent-Disposition: form-data; name="List-Unsubscribe"\r\n\r\nOne-Click\r\n--b-1--\r\n'
    assert len(body) < 1024
    ok = anonymous.post(
        url, csrf=False, content=body, headers={"content-type": 'multipart/form-data; boundary="b-1"'}
    )
    assert ok.status_code == 200 and preferences(admin_conn, user) == {(LOSS, "email"): "off"}


@pytest.mark.usefixtures("frozen_ratelimit_clock")
def test_invalid_bodies_count_as_failed_attempts_on_the_ip_counter(
    make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any], settings: Settings
) -> None:
    api = make_api(rate_limit_notify_unsubscribe_ip=2)
    _, (user, tenant), _ = two_users(make_api, admin_conn)
    url = f"{URL}?token={sign(settings, user, tenant)}"  # token GEÇERLİ; gövde geçersiz
    bad = {
        "content": b"List-Unsubscribe=Yes",
        "headers": {"content-type": "application/x-www-form-urlencoded"},
    }
    assert [api.post(url, csrf=False, **bad).status_code for _ in range(4)] == [400, 400, 429, 429]
    assert preferences(admin_conn, user) == {}


def asgi_call(app: Any, method: str, path: str, query: bytes = b"") -> tuple[int, bytes]:
    """Ham yolu ASGI kapsamına DOĞRUDAN verir (istemci kütüphanesi yolu normalleştirmesin)."""
    import asyncio

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query,
        "headers": [(b"host", b"testserver")],
        "client": ("testclient", 50000),
        "server": ("testserver", 443),
    }
    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return int(start["status"]), b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )


def test_raw_double_slash_path_reaches_the_csrf_check_and_is_not_exempt() -> None:
    from app.core.middleware import CSRF_EXEMPT, CsrfMiddleware

    called: list[str] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        called.append(scope["path"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = CsrfMiddleware(inner)
    assert asgi_call(middleware, "POST", "/v1/notifications/unsubscribe")[0] == 204  # tam yol: muaf
    for path in (
        "//v1/notifications/unsubscribe",
        "/v1/notifications/unsubscribe/",
        "/v1/notifications//unsubscribe",
    ):
        status, body = asgi_call(middleware, "POST", path)
        assert status == 403 and b"csrf-failed" in body, path  # ham yol bire bir karşılaştırılır
    assert called == ["/v1/notifications/unsubscribe"]  # iç uygulama yalnız muaf yolda çağrıldı
    assert CSRF_EXEMPT == {("POST", "/v1/notifications/unsubscribe")}


def test_full_app_rejects_the_raw_double_slash_path_without_csrf(make_app: Callable[..., Any]) -> None:
    app = make_app()
    status, body = asgi_call(app, "POST", "//v1/notifications/unsubscribe", b"token=x.y")
    assert status == 403 and b"csrf-failed" in body
