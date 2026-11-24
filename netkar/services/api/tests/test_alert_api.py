"""Uyarı API'si (ADR-0009 D6): olay listesi, geçişler, toplu okundu, hesap eşikleri, kullanıcı tercihleri.

Dosya adı bilerek `test_alert_api.py` (`test_alerts_*.py` DEĞİL): `make test-alerts` yalnız saf kural testlerini
(DB'siz, `app/alerts` %100 kapsam kapısı) koşar; bu dosya gerçek PostgreSQL ve HTTP istemcisi ister.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy import insert as sa_insert
from sqlalchemy.exc import DBAPIError

from app.api.v1 import alerts as alerts_api
from app.services import alert_api as svc
from tests.conftest import Api, DatabaseInfo, RecordingJobQueue
from tests.product_cost_helpers import Shop, add_account, make_shop_factory

ETAG0 = '"as-0"'


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def shop(make_shop: Callable[..., Shop]) -> Shop:
    return make_shop("a@example.com", "Mağaza A")


@pytest.fixture
def two_shops(make_shop: Callable[..., Shop]) -> tuple[Shop, Shop]:
    return make_shop("a@example.com", "Mağaza A"), make_shop("b@example.com", "Mağaza B", seller_id="9999")


# --------------------------------------------------------------------------- yardımcılar
def add_event(
    conn: psycopg.Connection[Any],
    shop: Shop,
    *,
    rule: str = "ZARARINA_SATIS",
    subject: str = "urun:BC-1",
    account_id: UUID | None = None,
    last_seen: str | None = None,
) -> UUID:
    account = account_id or shop.account_id
    scope = {"urun": "product", "satir": "order_line", "hesap": "account"}[subject.split(":")[0]]
    key = hashlib.sha256(f"{rule}|{account}|{subject}".encode()).hexdigest()
    row = conn.execute(
        "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, "
        "severity, payload, payload_version, data_revision, settings_revision) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'high', %s, 1, 3, 2) RETURNING id",
        (
            shop.tenant_id,
            account,
            rule,
            scope,
            subject,
            key,
            Jsonb({"loss_line_count": 2, "total_loss": "12.50"}),
        ),
    ).fetchone()
    assert row is not None
    event_id: UUID = row[0]
    if last_seen is not None:
        conn.execute("UPDATE alert_events SET last_seen_at = %s WHERE id = %s", (last_seen, event_id))
    return event_id


def system_transition(database: DatabaseInfo, tenant: UUID, event_id: UUID, to: str) -> None:
    """Sistem (worker) geçişi: kullanıcı `resolved` yapamadığı için çözülmüş olay buradan kurulur."""
    with psycopg.connect(database.worker_dsn()) as conn:
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
        conn.execute(
            "INSERT INTO alert_event_transitions (tenant_id, alert_event_id, to_status, muted_until) "
            "VALUES (%s, %s, %s, NULL)",
            (tenant, event_id, to),
        )
        conn.commit()


def status_of(conn: psycopg.Connection[Any], event_id: UUID) -> str:
    row = conn.execute("SELECT status FROM alert_events WHERE id = %s", (event_id,)).fetchone()
    assert row is not None
    return str(row[0])


def ledger(conn: psycopg.Connection[Any], event_id: UUID) -> list[tuple[str, str, str, Any]]:
    rows = conn.execute(
        "SELECT from_status, to_status, actor, actor_user_id FROM alert_event_transitions "
        "WHERE alert_event_id = %s ORDER BY created_at, id",
        (event_id,),
    ).fetchall()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


def audit(conn: psycopg.Connection[Any], shop: Shop, prefix: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT action, target, meta FROM audit_log WHERE tenant_id = %s AND action LIKE %s ORDER BY id",
        (shop.tenant_id, f"{prefix}%"),
    ).fetchall()
    return [{"action": r[0], "target": r[1], "meta": r[2]} for r in rows]


def set_role(conn: psycopg.Connection[Any], shop: Shop, role: str) -> None:
    conn.execute("UPDATE memberships SET role = %s::membership_role WHERE user_id = %s", (role, shop.user_id))


def events_url(shop: Shop, suffix: str = "") -> str:
    return f"{shop.base}/alert-events{suffix}"


def transition(shop: Shop, event_id: UUID | str, body: dict[str, Any]) -> Any:
    return shop.api.post(events_url(shop, f"/{event_id}/transitions"), body)


# --------------------------------------------------------------------------- olay listesi
def test_list_events_requires_authentication(shop: Shop, make_api: Callable[..., Api]) -> None:
    assert make_api().get(events_url(shop)).status_code == 401


def test_list_events_empty(shop: Shop) -> None:
    body = shop.api.get(events_url(shop)).json()
    assert body == {
        "items": [],
        "next_cursor": None,
        "open_count": 0,
        "last_evaluated_at": None,
        "data_revision": None,
        "settings_revision": None,
    }


def test_list_events_shape_and_money_as_strings(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    body = shop.api.get(events_url(shop)).json()
    assert body["open_count"] == 1 and body["next_cursor"] is None
    (item,) = body["items"]
    assert item["id"] == str(event_id)
    assert item["rule"] == "ZARARINA_SATIS" and item["scope"] == "product" and item["status"] == "open"
    assert item["subject"] == "urun:BC-1" and item["severity"] == "high"
    assert item["payload"] == {"loss_line_count": 2, "total_loss": "12.50"}  # tutar metin
    assert item["data_revision"] == 3 and item["settings_revision"] == 2
    assert item["muted_until"] is None and item["resolved_at"] is None
    # İç bildirim defteri alanları yanıtta yok.
    assert not {"dedupe_key", "notified_amount", "last_notified_at", "tenant_id", "notify_mode"} & set(item)


def test_list_filters_by_status_rule_and_date(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    a = add_event(admin_conn, shop, subject="urun:A", last_seen="2026-11-01 12:00+03")
    b = add_event(
        admin_conn, shop, rule="BEKLENMEYEN_KESINTI", subject="satir:1|2|3", last_seen="2026-11-03 09:00+03"
    )
    c = add_event(admin_conn, shop, subject="urun:C", last_seen="2026-11-05 23:30+03")
    assert transition(shop, a, {"to": "read"}).status_code == 200

    def ids(**params: str) -> list[str]:
        r = shop.api.get(events_url(shop), params=params)
        assert r.status_code == 200, r.text
        return [i["id"] for i in r.json()["items"]]

    assert ids() == [str(c), str(b), str(a)]  # son görülmeye göre yeniden eskiye
    assert ids(status="read") == [str(a)]
    assert ids(status="open") == [str(c), str(b)]
    assert ids(status="muted") == [] and ids(status="resolved") == []
    assert ids(rule="BEKLENMEYEN_KESINTI") == [str(b)]
    assert ids(rule="ZARARINA_SATIS", status="open") == [str(c)]
    # Tarih: İstanbul günü, bitiş günü dahil.
    assert ids(start="2026-11-03", end="2026-11-05") == [str(c), str(b)]
    assert ids(start="2026-11-05") == [str(c)]
    assert ids(end="2026-11-01") == [str(a)]
    assert ids(start="2026-11-02", end="2026-11-02") == []
    # open_count süzgeçten bağımsızdır.
    assert shop.api.get(events_url(shop), params={"status": "read"}).json()["open_count"] == 2


@pytest.mark.parametrize(
    "params",
    [
        {"status": "bogus"},
        {"status": "RESOLVED"},
        {"rule": "BASKA_KURAL"},
        {"start": "2026-13-01"},
        {"start": "bugun"},
        {"start": "2026-11-05", "end": "2026-11-01"},
        {"end": "9999-12-31"},
        {"limit": "0"},
        {"limit": "101"},
        {"limit": "abc"},
        {"cursor": ""},
    ],
)
def test_list_rejects_invalid_params(shop: Shop, params: dict[str, str]) -> None:
    r = shop.api.get(events_url(shop), params=params)
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:validation-error"
    assert all("code" in e and "field" in e for e in r.json()["errors"])


def test_list_date_errors_name_the_right_field(shop: Shop) -> None:
    far = shop.api.get(events_url(shop), params={"end": "9999-12-31"}).json()["errors"]
    assert far == [{"field": "end", "code": "date_invalid"}]
    bad_start = shop.api.get(events_url(shop), params={"start": "2026-02-30"}).json()["errors"]
    assert bad_start == [{"field": "start", "code": "date_invalid"}]
    bad_end = shop.api.get(events_url(shop), params={"end": "2026-02-30"}).json()["errors"]
    assert bad_end == [{"field": "end", "code": "date_invalid"}]


def test_list_pagination_is_stable_with_ties(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    stamps = ["2026-11-05 10:00+03"] * 3 + ["2026-11-04 10:00+03", "2026-11-03 10:00+03"]
    expected = [add_event(admin_conn, shop, subject=f"urun:{i}", last_seen=s) for i, s in enumerate(stamps)]
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(5):
        params = {"limit": "2", **({"cursor": cursor} if cursor else {})}
        body = shop.api.get(events_url(shop), params=params).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert cursor is None and len(seen) == 5 and sorted(seen) == sorted(str(e) for e in expected)
    # Sıra: (last_seen_at, id) azalan; bağlar id ile kırılır, tekrar ve atlama yok.
    rows = admin_conn.execute(
        "SELECT id FROM alert_events WHERE tenant_id = %s ORDER BY last_seen_at DESC, id DESC",
        (shop.tenant_id,),
    ).fetchall()
    assert seen == [str(r[0]) for r in rows]


def test_cursor_is_bound_to_filters_account_and_tenant(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    for i in range(3):
        add_event(admin_conn, a, subject=f"urun:{i}", last_seen=f"2026-11-0{i + 1} 10:00+03")
        add_event(admin_conn, b, subject=f"urun:{i}")
    cursor = a.api.get(events_url(a), params={"limit": "1"}).json()["next_cursor"]
    assert cursor
    ok = a.api.get(events_url(a), params={"limit": "1", "cursor": cursor})
    assert ok.status_code == 200
    # Başka süzgeç, başka kiracı, bozulmuş ve uydurma imleç reddedilir (CPU/veri sızdırmaz).
    other_filter = a.api.get(events_url(a), params={"limit": "1", "cursor": cursor, "status": "open"})
    stolen = b.api.get(events_url(b), params={"limit": "1", "cursor": cursor})
    forged = a.api.get(events_url(a), params={"cursor": cursor[:-3] + "AAA"})
    junk = a.api.get(events_url(a), params={"cursor": "uydurma"})
    for r in (other_filter, stolen, forged, junk):
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "cursor_invalid"


def test_list_shows_last_successful_evaluation(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    for stamp, status in (("2026-11-01", "succeeded"), ("2026-11-02", "failed"), ("2026-11-03", "running")):
        admin_conn.execute(
            "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
            "settings_revision, rules_version) VALUES (%s, %s, %s, 7, 9, 1)",
            (shop.tenant_id, shop.account_id, stamp),
        )
        if status != "running":
            admin_conn.execute(
                "UPDATE alert_evaluations SET status = %s, counts = '{}' WHERE as_of_date = %s",
                (status, stamp),
            )
    body = shop.api.get(events_url(shop)).json()
    assert body["data_revision"] == 7 and body["settings_revision"] == 9
    assert body["last_evaluated_at"] is not None


def test_viewer_can_list_and_read_events(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    set_role(admin_conn, shop, "viewer")
    assert shop.api.get(events_url(shop)).status_code == 200
    assert shop.api.get(events_url(shop, f"/{event_id}")).status_code == 200


# --------------------------------------------------------------------------- tek olay
def test_event_detail_has_transition_history(
    shop: Shop, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    event_id = add_event(admin_conn, shop)
    assert transition(shop, event_id, {"to": "read"}).status_code == 200
    assert transition(shop, event_id, {"to": "muted", "muted_days": 7}).status_code == 200
    body = shop.api.get(events_url(shop, f"/{event_id}")).json()
    assert body["event"]["id"] == str(event_id) and body["event"]["status"] == "muted"
    steps = [(t["from_status"], t["to_status"], t["actor"]) for t in body["transitions"]]
    assert steps == [("open", "read", "user"), ("read", "muted", "user")]
    assert all(t["actor_user_id"] == str(shop.user_id) for t in body["transitions"])
    assert body["transitions"][1]["muted_until"] is not None and body["transitions"][0]["muted_until"] is None


def test_event_detail_shows_system_transition(
    shop: Shop, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    event_id = add_event(admin_conn, shop)
    system_transition(database, shop.tenant_id, event_id, "resolved")
    body = shop.api.get(events_url(shop, f"/{event_id}")).json()
    assert body["event"]["status"] == "resolved" and body["event"]["resolved_at"] is not None
    assert body["transitions"][0]["actor"] == "system" and body["transitions"][0]["actor_user_id"] is None
    assert shop.api.get(events_url(shop), params={"status": "resolved"}).json()["items"][0]["id"] == str(
        event_id
    )


def test_unknown_event_and_bad_id(shop: Shop) -> None:
    assert shop.api.get(events_url(shop, f"/{uuid4()}")).status_code == 404
    assert transition(shop, uuid4(), {"to": "read"}).status_code == 404
    assert shop.api.get(events_url(shop, "/not-a-uuid")).status_code == 422


# --------------------------------------------------------------------------- geçişler
def test_read_and_reopen(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    r = transition(shop, event_id, {"to": "read"})
    assert r.status_code == 200
    body = r.json()
    assert body["event"]["status"] == "read" and body["transition_id"]
    assert status_of(admin_conn, event_id) == "read"
    assert transition(shop, event_id, {"to": "open"}).json()["event"]["status"] == "open"
    assert ledger(admin_conn, event_id) == [
        ("open", "read", "user", shop.user_id),
        ("read", "open", "user", shop.user_id),
    ]
    actions = audit(admin_conn, shop, "alert_event.transition")
    assert len(actions) == 2 and actions[0]["target"] == str(event_id)
    assert actions[0]["meta"] == {
        "account_id": str(shop.account_id),
        "from": "open",
        "to": "read",
        "muted_days": None,
    }


def test_mute_sets_until_from_database_clock_and_unmute(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    event_id = add_event(admin_conn, shop)
    r = transition(shop, event_id, {"to": "muted", "muted_days": 30})
    assert r.status_code == 200
    event = r.json()["event"]
    until = datetime.fromisoformat(event["muted_until"])
    assert abs((until - (datetime.now(UTC) + timedelta(days=30))).total_seconds()) < 60
    assert event["status"] == "muted"
    # En uzun susturma: 90 gün tetikleyici sınırına takılmaz.
    other = add_event(admin_conn, shop, subject="urun:2")
    assert transition(shop, other, {"to": "muted", "muted_days": 90}).status_code == 200
    # Susturmayı kaldır.
    opened = transition(shop, event_id, {"to": "open"})
    assert opened.status_code == 200 and opened.json()["event"]["muted_until"] is None
    assert status_of(admin_conn, event_id) == "open"


def test_admin_role_can_mute(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    set_role(admin_conn, shop, "admin")
    assert transition(shop, event_id, {"to": "muted", "muted_days": 1}).status_code == 200


def test_viewer_cannot_mute_or_unmute_but_can_read(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    muted = add_event(admin_conn, shop, subject="urun:M")
    assert transition(shop, muted, {"to": "muted", "muted_days": 5}).status_code == 200
    set_role(admin_conn, shop, "viewer")
    denied = [
        transition(shop, event_id, {"to": "muted", "muted_days": 5}),
        transition(shop, muted, {"to": "open"}),
    ]
    assert [r.status_code for r in denied] == [403, 403]
    assert all(r.json()["type"] == "urn:netkar:problem:forbidden" for r in denied)
    assert status_of(admin_conn, event_id) == "open" and status_of(admin_conn, muted) == "muted"
    assert transition(shop, event_id, {"to": "read"}).status_code == 200
    assert transition(shop, event_id, {"to": "open"}).status_code == 200
    assert len(ledger(admin_conn, event_id)) == 2  # reddedilen denemeler deftere yazılmadı


@pytest.mark.parametrize(
    "body",
    [
        {"to": "resolved"},
        {"to": "resolved", "muted_days": 3},
        {"to": "muted"},
        {"to": "muted", "muted_days": 0},
        {"to": "muted", "muted_days": 91},
        {"to": "muted", "muted_days": -1},
        {"to": "muted", "muted_days": "7"},
        {"to": "muted", "muted_days": 7.5},
        {"to": "muted", "muted_days": True},
        {"to": "read", "muted_days": 5},
        {"to": "open", "muted_days": 5},
        {"to": "read", "from_status": "resolved"},
        {"to": "read", "actor": "system"},
        {"to": "read", "status": "resolved"},
        {"to": "read", "muted_until": "2030-01-01T00:00:00Z"},
        {"to": "unknown"},
        {},
    ],
)
def test_transition_body_is_validated(
    shop: Shop, admin_conn: psycopg.Connection[Any], body: dict[str, Any]
) -> None:
    event_id = add_event(admin_conn, shop)
    r = transition(shop, event_id, body)
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:validation-error"
    assert status_of(admin_conn, event_id) == "open" and ledger(admin_conn, event_id) == []


def test_invalid_transitions_are_conflicts(
    shop: Shop, admin_conn: psycopg.Connection[Any], database: DatabaseInfo
) -> None:
    event_id = add_event(admin_conn, shop)
    assert transition(shop, event_id, {"to": "open"}).status_code == 409  # open -> open
    assert transition(shop, event_id, {"to": "read"}).status_code == 200
    again = transition(shop, event_id, {"to": "read"})  # read -> read
    assert again.status_code == 409 and again.json()["type"] == "urn:netkar:problem:alert-transition-invalid"
    assert transition(shop, event_id, {"to": "muted", "muted_days": 3}).status_code == 200
    assert transition(shop, event_id, {"to": "read"}).status_code == 409  # muted -> read
    assert transition(shop, event_id, {"to": "muted", "muted_days": 3}).status_code == 409  # muted -> muted
    # Çözülmüş olaya kullanıcı hiçbir geçiş yapamaz.
    resolved = add_event(admin_conn, shop, subject="urun:R")
    system_transition(database, shop.tenant_id, resolved, "resolved")
    for body in ({"to": "read"}, {"to": "open"}, {"to": "muted", "muted_days": 2}):
        r = transition(shop, resolved, body)
        assert r.status_code == 409, body
    assert status_of(admin_conn, resolved) == "resolved"


def test_transition_hides_internal_details_on_db_rejection(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Veritabanı tetikleyicisi reddederse ileti sabittir; SQL, tablo adı ve sürücü metni sızmaz."""
    event_id = add_event(admin_conn, shop)

    class Orig(Exception):
        sqlstate = "23514"

    async def boom(*_a: Any, **_k: Any) -> UUID:
        raise DBAPIError("INSERT INTO alert_event_transitions ...", {"to_status": "x"}, Orig("gizli ayrıntı"))

    monkeypatch.setattr(svc, "add_transition", boom)
    r = transition(shop, event_id, {"to": "read"})
    assert r.status_code == 409 and r.json()["type"] == "urn:netkar:problem:alert-transition-invalid"
    assert "alert_event_transitions" not in r.text and "gizli" not in r.text and "INSERT" not in r.text


@pytest.mark.parametrize(
    ("state", "status", "slug"),
    [
        ("42501", 403, "forbidden"),
        ("40001", 409, "alert-event-changed"),
        ("40P01", 409, "alert-event-changed"),
        ("23514", 409, "alert-transition-invalid"),
        ("23503", 404, "not-found"),
    ],
)
def test_db_rejection_mapping(state: str, status: int, slug: str) -> None:
    orig = type("Orig", (Exception,), {"sqlstate": state})("ayrıntı")
    problem = alerts_api._db_rejection(DBAPIError("stmt", {}, orig))
    assert problem.status == status and problem.slug == slug
    assert "ayrıntı" not in str(problem.detail)


def test_unmapped_db_error_propagates() -> None:
    exc = DBAPIError("stmt", {}, type("Orig", (Exception,), {"sqlstate": "XX000"})("x"))
    with pytest.raises(DBAPIError):
        alerts_api._db_rejection(exc)


# --------------------------------------------------------------------------- toplu okundu
def test_read_all_marks_open_events_read(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    open_ids = [add_event(admin_conn, shop, subject=f"urun:{i}") for i in range(3)]
    read_id = add_event(admin_conn, shop, subject="urun:read")
    muted_id = add_event(admin_conn, shop, subject="urun:muted")
    assert transition(shop, read_id, {"to": "read"}).status_code == 200
    assert transition(shop, muted_id, {"to": "muted", "muted_days": 3}).status_code == 200
    r = shop.api.post(events_url(shop, "/read-all"))
    assert r.status_code == 200 and r.json() == {"updated": 3, "remaining_open": 0}
    assert {status_of(admin_conn, i) for i in open_ids} == {"read"}
    assert status_of(admin_conn, muted_id) == "muted"  # susturulan olaya dokunulmaz
    assert all(ledger(admin_conn, i) == [("open", "read", "user", shop.user_id)] for i in open_ids)
    (entry,) = audit(admin_conn, shop, "alert_event.read_all")
    assert entry["meta"] == {"account_id": str(shop.account_id), "count": 3}
    # Açık olay kalmadı: ikinci çağrı sıfır döner ve denetim kaydı eklemez.
    again = shop.api.post(events_url(shop, "/read-all"))
    assert again.json() == {"updated": 0, "remaining_open": 0}
    assert len(audit(admin_conn, shop, "alert_event.read_all")) == 1


def test_read_all_is_capped(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    for i in range(5):
        add_event(admin_conn, shop, subject=f"urun:{i}", last_seen=f"2026-11-0{i + 1} 10:00+03")
    monkeypatch.setattr(svc, "READ_ALL_LIMIT", 2)
    first = shop.api.post(events_url(shop, "/read-all")).json()
    assert first == {"updated": 2, "remaining_open": 3}
    # En yeni olaylar önce okunur.
    assert shop.api.get(events_url(shop), params={"status": "read"}).json()["items"][0]["subject"] == "urun:4"
    assert shop.api.post(events_url(shop, "/read-all")).json() == {"updated": 2, "remaining_open": 1}


def test_read_all_default_cap_is_500() -> None:
    assert svc.READ_ALL_LIMIT == 500


def test_read_all_is_allowed_for_viewer_and_scoped_to_account(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    other_account = add_account(admin_conn, shop.tenant_id, shop.user_id, seller_id="5555")
    mine = add_event(admin_conn, shop)
    theirs = add_event(admin_conn, shop, account_id=other_account)
    set_role(admin_conn, shop, "viewer")
    r = shop.api.post(events_url(shop, "/read-all"))
    assert r.status_code == 200 and r.json()["updated"] == 1
    assert status_of(admin_conn, mine) == "read" and status_of(admin_conn, theirs) == "open"


def _serialization_failure() -> DBAPIError:
    return DBAPIError("stmt", {}, type("Orig", (Exception,), {"sqlstate": "40001"})("ayrıntı"))


def test_read_all_retries_once_on_concurrent_change(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eşzamanlı durum değişimi (40001) bir kez yeniden denenir; savepoint geri alındığı için yarım yazım olmaz."""
    event_id = add_event(admin_conn, shop)
    real_insert = sa_insert
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _serialization_failure()
        return real_insert(*args, **kwargs)

    monkeypatch.setattr("app.services.alert_api.insert", flaky)
    assert shop.api.post(events_url(shop, "/read-all")).json() == {"updated": 1, "remaining_open": 0}
    assert calls["n"] == 2 and status_of(admin_conn, event_id) == "read"


@pytest.mark.parametrize("state", ["23514", "40P01"])
def test_read_all_retries_on_other_transient_rejections(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    event_id = add_event(admin_conn, shop)
    real_insert = sa_insert
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise DBAPIError("stmt", {}, type("Orig", (Exception,), {"sqlstate": state})("x"))
        return real_insert(*args, **kwargs)

    monkeypatch.setattr("app.services.alert_api.insert", flaky)
    assert shop.api.post(events_url(shop, "/read-all")).json()["updated"] == 1
    assert calls["n"] == 2 and status_of(admin_conn, event_id) == "read"


def test_event_detail_returns_latest_transitions_when_truncated(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = add_event(admin_conn, shop)
    for to in ("read", "open", "read"):
        assert transition(shop, event_id, {"to": to}).status_code == 200
    full = shop.api.get(events_url(shop, f"/{event_id}")).json()
    assert full["truncated"] is False and len(full["transitions"]) == 3
    monkeypatch.setattr(svc, "TRANSITIONS_LIMIT", 2)
    cut = shop.api.get(events_url(shop, f"/{event_id}")).json()
    assert cut["truncated"] is True
    # Son iki kayıt, eskiden yeniye.
    assert [t["id"] for t in cut["transitions"]] == [t["id"] for t in full["transitions"][1:]]


def test_read_all_gives_conflict_when_retry_also_fails(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    event_id = add_event(admin_conn, shop)

    def always(*_a: Any, **_k: Any) -> Any:
        raise _serialization_failure()

    monkeypatch.setattr("app.services.alert_api.insert", always)
    r = shop.api.post(events_url(shop, "/read-all"))
    assert r.status_code == 409 and r.json()["type"] == "urn:netkar:problem:alert-event-changed"
    assert "ayrıntı" not in r.text and status_of(admin_conn, event_id) == "open"


# --------------------------------------------------------------------------- IDOR
def test_other_tenant_account_and_event_ids_are_404(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    event_a = add_event(admin_conn, a)
    # B, A'nın hesabı üzerinden: hesap bulunamaz (404, 403 değil).
    for r in (
        b.api.get(f"{a.base}/alert-events"),
        b.api.get(f"{a.base}/alert-events/{event_a}"),
        b.api.post(f"{a.base}/alert-events/{event_a}/transitions", {"to": "read"}),
        b.api.post(f"{a.base}/alert-events/read-all"),
        b.api.get(f"{a.base}/alert-settings"),
    ):
        assert r.status_code == 404, r.text
        assert r.json()["type"] == "urn:netkar:problem:not-found"
    # B, kendi hesabında A'nın olay kimliğiyle: 404.
    for r in (
        b.api.get(events_url(b, f"/{event_a}")),
        transition(b, event_a, {"to": "read"}),
        transition(b, event_a, {"to": "muted", "muted_days": 3}),
    ):
        assert r.status_code == 404, r.text
        assert str(event_a) not in r.text.replace(r.request.url.path, "")
    assert status_of(admin_conn, event_a) == "open" and ledger(admin_conn, event_a) == []
    assert b.api.get(events_url(b)).json()["items"] == []
    # Olmayan hesap da 404.
    assert b.api.get(f"/v1/marketplace-accounts/{uuid4()}/alert-events").status_code == 404


def test_same_tenant_other_account_event_is_404(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    other_account = add_account(admin_conn, shop.tenant_id, shop.user_id, seller_id="5555")
    foreign = add_event(admin_conn, shop, account_id=other_account)
    assert shop.api.get(events_url(shop, f"/{foreign}")).status_code == 404
    assert transition(shop, foreign, {"to": "read"}).status_code == 404
    assert shop.api.get(events_url(shop)).json()["items"] == []
    assert status_of(admin_conn, foreign) == "open"


# --------------------------------------------------------------------------- hesap eşikleri
def settings_url(shop: Shop) -> str:
    return f"{shop.base}/alert-settings"


def settings_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "loss_min_amount": "7.50",
        "ad_share_percent": "80",
        "ad_min_spend": "20",
        "deduction_notify_min": "15.00",
        "return_min_diff_points": "6",
        "rules_enabled": ["IADE_ORANI_ARTISI", "ZARARINA_SATIS"],
    }
    body.update(over)
    return body


def put_settings(shop: Shop, etag: str | None, body: dict[str, Any] | None = None) -> Any:
    headers = {} if etag is None else {"If-Match": etag}
    return shop.api.put(settings_url(shop), body if body is not None else settings_body(), headers=headers)


def test_settings_default_get(shop: Shop) -> None:
    r = shop.api.get(settings_url(shop))
    assert r.status_code == 200 and r.headers["ETag"] == ETAG0
    assert r.json() == {
        "loss_min_amount": "5.00",
        "ad_share_percent": "100.00",
        "ad_min_spend": "50.00",
        "deduction_notify_min": "10.00",
        "return_min_diff_points": "5.00",
        "rules_enabled": ["ZARARINA_SATIS", "REKLAM_KARI_YIYOR", "BEKLENMEYEN_KESINTI", "IADE_ORANI_ARTISI"],
        "is_default": True,
        "updated_at": None,
    }


def test_settings_put_creates_then_updates(
    shop: Shop, admin_conn: psycopg.Connection[Any], job_queue: RecordingJobQueue
) -> None:
    r = put_settings(shop, ETAG0)
    assert r.status_code == 200, r.text
    etag1 = r.headers["ETag"]
    assert etag1 != ETAG0 and etag1.startswith('"as-')
    assert r.json()["loss_min_amount"] == "7.50" and r.json()["ad_share_percent"] == "80.00"
    assert r.json()["rules_enabled"] == ["ZARARINA_SATIS", "IADE_ORANI_ARTISI"]  # kanonik sıra
    assert r.json()["is_default"] is False and r.json()["updated_at"] is not None
    got = shop.api.get(settings_url(shop))
    assert got.headers["ETag"] == etag1 and got.json() == r.json()
    row = admin_conn.execute(
        "SELECT updated_by, loss_min_amount, rules_enabled FROM alert_rule_settings WHERE tenant_id = %s",
        (shop.tenant_id,),
    ).fetchone()
    assert row is not None and row[0] == shop.user_id and str(row[1]) == "7.50"
    # Değerlendirme istendi (eşik özeti anahtara girer).
    assert job_queue.alert_evaluations == [shop.account_id]
    # İkinci yazım: güncelleme, yeni ETag.
    r2 = put_settings(shop, etag1, settings_body(loss_min_amount="9.00"))
    assert r2.status_code == 200 and r2.headers["ETag"] != etag1
    assert r2.json()["loss_min_amount"] == "9.00"
    assert job_queue.alert_evaluations == [shop.account_id, shop.account_id]


def test_settings_precondition_required_and_failed(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    assert put_settings(shop, None).status_code == 428
    no_header = put_settings(shop, None)
    assert no_header.json()["type"] == "urn:netkar:problem:precondition-required"
    stale = put_settings(shop, '"as-123"')
    assert stale.status_code == 412 and stale.headers["ETag"] == ETAG0
    assert stale.json()["type"] == "urn:netkar:problem:alert-settings-changed"
    for junk in ("*", "as-0", '"as-0', '"x"', "W/" + ETAG0):
        assert put_settings(shop, junk).status_code == 412
    assert admin_conn.execute("SELECT count(*) FROM alert_rule_settings").fetchone() == (0,)
    assert audit(admin_conn, shop, "alert_settings") == []
    # Başarılı yazımdan sonra eski ETag ile ikinci yazım 412 (kayıp güncelleme yok).
    assert put_settings(shop, ETAG0).status_code == 200
    again = put_settings(shop, ETAG0, settings_body(loss_min_amount="1.00"))
    assert again.status_code == 412
    assert shop.api.get(settings_url(shop)).json()["loss_min_amount"] == "7.50"


def test_settings_write_condition_catches_a_race_after_the_precheck(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ön denetim bayat durumu görür (araya yazım girdi); koşullu UPDATE 0 satır döner, 412 ve güncel ETag."""
    assert put_settings(shop, ETAG0).status_code == 200
    etag = shop.api.get(settings_url(shop)).headers["ETag"]
    real = svc.load_settings
    calls = {"n": 0}

    async def stale_first(*args: Any, **kwargs: Any) -> Any:
        state = await real(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:  # ön denetimden hemen sonra başka işlem satırı değiştirir
            admin_conn.execute("UPDATE alert_rule_settings SET updated_at = updated_at + interval '1 second'")
        return state

    monkeypatch.setattr(svc, "load_settings", stale_first)
    r = put_settings(shop, etag, settings_body(loss_min_amount="3.00"))
    assert r.status_code == 412 and calls["n"] == 2  # ikinci okuma: güncel ETag için
    assert r.headers["ETag"] != etag
    monkeypatch.undo()
    assert shop.api.get(settings_url(shop)).headers["ETag"] == r.headers["ETag"]
    assert shop.api.get(settings_url(shop)).json()["loss_min_amount"] == "7.50"  # ezme yok
    assert len(audit(admin_conn, shop, "alert_settings")) == 1


def test_settings_first_write_race_is_caught_by_on_conflict(
    shop: Shop, admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """İki ilk yazım yarışında kaybeden `INSERT ... ON CONFLICT DO NOTHING` ile 412 alır, kazananı ezmez."""
    real = svc.load_settings
    calls = {"n": 0}

    async def raced(*args: Any, **kwargs: Any) -> Any:
        state = await real(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] == 1:  # ön denetim kayıt yok görür; hemen ardından rakip ilk kaydı yazar
            admin_conn.execute(
                "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, loss_min_amount, updated_by) "
                "VALUES (%s, %s, 1.00, %s)",
                (shop.tenant_id, shop.account_id, shop.user_id),
            )
        return state

    monkeypatch.setattr(svc, "load_settings", raced)
    r = put_settings(shop, ETAG0, settings_body(loss_min_amount="9.00"))
    assert r.status_code == 412 and r.headers["ETag"] != ETAG0
    row = admin_conn.execute("SELECT loss_min_amount FROM alert_rule_settings").fetchone()
    assert row is not None and str(row[0]) == "1.00"
    assert audit(admin_conn, shop, "alert_settings") == []


def test_settings_same_content_is_noop(
    shop: Shop, admin_conn: psycopg.Connection[Any], job_queue: RecordingJobQueue
) -> None:
    etag = put_settings(shop, ETAG0).headers["ETag"]
    job_queue.alert_evaluations.clear()
    same = put_settings(shop, etag, settings_body(rules_enabled=["ZARARINA_SATIS", "IADE_ORANI_ARTISI"]))
    assert same.status_code == 200 and same.headers["ETag"] == etag
    assert job_queue.alert_evaluations == [] and len(audit(admin_conn, shop, "alert_settings")) == 1


def test_settings_default_values_create_a_row_on_first_put(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    body = shop.api.get(settings_url(shop)).json()
    body.pop("is_default")
    body.pop("updated_at")
    r = put_settings(shop, ETAG0, body)
    assert r.status_code == 200 and r.json()["is_default"] is False
    assert admin_conn.execute("SELECT count(*) FROM alert_rule_settings").fetchone() == (1,)


def test_settings_audit_has_no_amounts(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    etag = put_settings(shop, ETAG0).headers["ETag"]
    put_settings(shop, etag, settings_body(loss_min_amount="11.11", rules_enabled=["ZARARINA_SATIS"]))
    first, second = audit(admin_conn, shop, "alert_settings")
    assert first["action"] == "alert_settings.update" and first["target"] == str(shop.account_id)
    assert first["meta"]["created"] is True and "loss_min_amount" in first["meta"]["changed_fields"]
    assert second["meta"]["created"] is False
    assert second["meta"]["changed_fields"] == ["loss_min_amount", "rules_enabled"]
    dumped = json.dumps([first, second])
    assert "11.11" not in dumped and "7.50" not in dumped and "7.5" not in dumped


def test_settings_queue_failure_does_not_fail_the_write(shop: Shop, job_queue: RecordingJobQueue) -> None:
    job_queue.fail = True
    assert put_settings(shop, ETAG0).status_code == 200


@pytest.mark.parametrize(
    ("over", "field", "code"),
    [
        ({"loss_min_amount": "-0.01"}, "loss_min_amount", "greater_than_equal"),
        ({"loss_min_amount": "1000000.01"}, "loss_min_amount", "less_than_equal"),
        ({"loss_min_amount": "1.234"}, "loss_min_amount", "decimal_max_places"),
        ({"loss_min_amount": "abc"}, "loss_min_amount", "decimal_invalid"),
        ({"loss_min_amount": "1e3"}, "loss_min_amount", "decimal_invalid"),
        ({"loss_min_amount": True}, "loss_min_amount", "decimal_invalid"),
        ({"loss_min_amount": None}, "loss_min_amount", "decimal_type"),
        ({"ad_share_percent": "49.99"}, "ad_share_percent", "greater_than_equal"),
        ({"ad_share_percent": "100.01"}, "ad_share_percent", "less_than_equal"),
        ({"ad_min_spend": "-1"}, "ad_min_spend", "greater_than_equal"),
        ({"deduction_notify_min": "2000000"}, "deduction_notify_min", "less_than_equal"),
        ({"return_min_diff_points": "-1"}, "return_min_diff_points", "greater_than_equal"),
        ({"return_min_diff_points": "100.01"}, "return_min_diff_points", "less_than_equal"),
        ({"rules_enabled": ["BASKA"]}, "rules_enabled.0", "literal_error"),
        ({"rules_enabled": ["ZARARINA_SATIS", "ZARARINA_SATIS"]}, "rules_enabled", "rules_duplicate"),
        ({"rules_enabled": "ZARARINA_SATIS"}, "rules_enabled", "list_type"),
        ({"rules_enabled": ["ZARARINA_SATIS"] * 5}, "rules_enabled", "too_long"),
        ({"updated_by": str(uuid4())}, "updated_by", "extra_forbidden"),
        ({"marketplace_account_id": str(uuid4())}, "marketplace_account_id", "extra_forbidden"),
        ({"notify_default_desi_deductions": True}, "notify_default_desi_deductions", "extra_forbidden"),
    ],
)
def test_settings_out_of_range_is_422(
    shop: Shop, admin_conn: psycopg.Connection[Any], over: dict[str, Any], field: str, code: str
) -> None:
    r = put_settings(shop, ETAG0, settings_body(**over))
    assert r.status_code == 422, r.text
    errors = r.json()["errors"]
    assert {"field": field, "code": code} in errors, errors
    # Girdi değeri yalnız `errors` ve `detail` alanlarında aranır (instance/request_id rastgele UUID içerir).
    sent = next(iter(over.values()))
    if isinstance(sent, str) and len(sent) > 3:
        body = r.json()
        assert sent not in json.dumps(body["errors"]) and sent not in str(body.get("detail", ""))
    assert admin_conn.execute("SELECT count(*) FROM alert_rule_settings").fetchone() == (0,)
    assert audit(admin_conn, shop, "alert_settings") == []


def test_settings_missing_field_is_422(shop: Shop) -> None:
    body = settings_body()
    body.pop("ad_min_spend")
    r = put_settings(shop, ETAG0, body)
    assert r.status_code == 422 and {"field": "ad_min_spend", "code": "missing"} in r.json()["errors"]


def test_settings_boundaries_are_accepted(shop: Shop) -> None:
    body = settings_body(
        loss_min_amount="0",
        ad_share_percent="50",
        ad_min_spend="1000000",
        deduction_notify_min="0.00",
        return_min_diff_points="100",
        rules_enabled=[],
    )
    r = put_settings(shop, ETAG0, body)
    assert r.status_code == 200, r.text
    assert r.json()["rules_enabled"] == [] and r.json()["ad_min_spend"] == "1000000.00"
    # JSON sayısı da Decimal'e en kısa gösterimiyle çevrilir (float hatası yok).
    again = put_settings(shop, r.headers["ETag"], settings_body(loss_min_amount=0.1, ad_share_percent=75))
    assert again.status_code == 200 and again.json()["loss_min_amount"] == "0.10"


def test_settings_viewer_can_read_but_not_write(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    assert put_settings(shop, ETAG0).status_code == 200
    etag = shop.api.get(settings_url(shop)).headers["ETag"]
    set_role(admin_conn, shop, "viewer")
    assert shop.api.get(settings_url(shop)).status_code == 200
    denied = put_settings(shop, etag, settings_body(loss_min_amount="1.00"))
    assert denied.status_code == 403 and denied.json()["type"] == "urn:netkar:problem:forbidden"
    assert shop.api.get(settings_url(shop)).json()["loss_min_amount"] == "7.50"
    set_role(admin_conn, shop, "admin")
    assert put_settings(shop, etag, settings_body(loss_min_amount="1.00")).status_code == 200


def test_settings_require_verified_email_and_csrf(
    shop: Shop, admin_conn: psycopg.Connection[Any], make_api: Callable[..., Api]
) -> None:
    admin_conn.execute("UPDATE users SET email_verified_at = NULL")
    r = put_settings(shop, ETAG0)
    assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:email-not-verified"
    assert shop.api.get(settings_url(shop)).status_code == 200  # okuma doğrulama istemez
    anon = make_api()
    assert anon.get(settings_url(shop)).status_code == 401
    assert anon.put(settings_url(shop), settings_body(), headers={"If-Match": ETAG0}).status_code == 401
    admin_conn.execute("UPDATE users SET email_verified_at = now()")
    no_csrf = shop.api.put(settings_url(shop), settings_body(), csrf=False, headers={"If-Match": ETAG0})
    assert no_csrf.status_code == 403 and no_csrf.json()["type"] == "urn:netkar:problem:csrf-failed"


def test_settings_cross_tenant_is_404_and_untouched(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    assert put_settings(a, ETAG0).status_code == 200
    etag = a.api.get(settings_url(a)).headers["ETag"]
    stolen = b.api.put(settings_url(a), settings_body(loss_min_amount="1.00"), headers={"If-Match": etag})
    assert stolen.status_code == 404
    assert b.api.get(settings_url(a)).status_code == 404
    assert a.api.get(settings_url(a)).json()["loss_min_amount"] == "7.50"
    # B kendi hesabında varsayılanları görür (A'nın eşikleri sızmaz).
    assert b.api.get(settings_url(b)).json()["is_default"] is True


# --------------------------------------------------------------------------- kullanıcı tercihleri
PREFS_URL = "/v1/me/notification-preferences"


def prefs_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "matrix": {
            "ZARARINA_SATIS": {"email": "instant", "push": "off"},
            "REKLAM_KARI_YIYOR": {"email": "off", "push": "digest"},
            "BEKLENMEYEN_KESINTI": {"email": "digest", "push": "instant"},
            "IADE_ORANI_ARTISI": {"email": "digest", "push": "off"},
        },
        "quiet_start": "23:30",
        "quiet_end": "07:15",
        "digest_hour": 9,
        "show_amounts_email": False,
        "show_amounts_push": True,
    }
    body.update(over)
    return body


def test_preferences_defaults_for_owner_and_viewer(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    body = shop.api.get(PREFS_URL).json()
    assert body["matrix"] == {
        "ZARARINA_SATIS": {"email": "digest", "push": "instant"},
        "REKLAM_KARI_YIYOR": {"email": "digest", "push": "off"},
        "BEKLENMEYEN_KESINTI": {"email": "digest", "push": "instant"},
        "IADE_ORANI_ARTISI": {"email": "digest", "push": "off"},
    }
    assert (body["quiet_start"], body["quiet_end"], body["digest_hour"]) == ("22:00", "08:00", 8)
    assert body["show_amounts_email"] is True and body["show_amounts_push"] is False
    set_role(admin_conn, shop, "viewer")
    viewer = shop.api.get(PREFS_URL).json()
    assert {m["email"] for m in viewer["matrix"].values()} == {"off"}  # viewer e-postası varsayılan kapalı
    assert viewer["matrix"]["ZARARINA_SATIS"]["push"] == "instant"


def test_preferences_roundtrip_and_upsert(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    r = shop.api.put(PREFS_URL, prefs_body())
    assert r.status_code == 200, r.text
    assert r.json() == shop.api.get(PREFS_URL).json()
    assert r.json()["quiet_start"] == "23:30" and r.json()["digest_hour"] == 9
    assert r.json()["matrix"]["ZARARINA_SATIS"] == {"email": "instant", "push": "off"}
    assert admin_conn.execute(
        "SELECT count(*) FROM notification_preferences WHERE user_id = %s", (shop.user_id,)
    ).fetchone() == (8,)
    # İkinci yazım güncelleme (satır sayısı sabit).
    changed = prefs_body(digest_hour=0, quiet_start="00:00")
    changed["matrix"]["ZARARINA_SATIS"] = {"email": "off", "push": "instant"}
    assert shop.api.put(PREFS_URL, changed).status_code == 200
    got = shop.api.get(PREFS_URL).json()
    assert got["matrix"]["ZARARINA_SATIS"] == {"email": "off", "push": "instant"}
    assert got["digest_hour"] == 0 and got["quiet_start"] == "00:00"
    assert admin_conn.execute(
        "SELECT count(*) FROM notification_preferences WHERE user_id = %s", (shop.user_id,)
    ).fetchone() == (8,)
    assert admin_conn.execute("SELECT count(*) FROM notification_settings").fetchone() == (1,)


def test_preferences_are_per_user_and_per_tenant(
    two_shops: tuple[Shop, Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    a, b = two_shops
    # A kiracısında ikinci bir üye: onun satırlarına dokunulmaz.
    colleague = uuid4()
    admin_conn.execute(
        "INSERT INTO users (id, email, password_hash, email_verified_at) VALUES (%s, 'c@example.com', 'x', now())",
        (colleague,),
    )
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'admin')",
        (colleague, a.tenant_id),
    )
    assert a.api.put(PREFS_URL, prefs_body()).status_code == 200
    rows = admin_conn.execute("SELECT DISTINCT user_id FROM notification_preferences").fetchall()
    assert [r[0] for r in rows] == [a.user_id]
    assert admin_conn.execute(
        "SELECT count(*) FROM notification_preferences WHERE user_id = %s", (colleague,)
    ).fetchone() == (0,)
    # B'nin tercihleri A'nınkinden bağımsızdır ve A'nın değerleri B'ye sızmaz.
    assert b.api.get(PREFS_URL).json()["quiet_start"] == "22:00"
    assert b.api.put(PREFS_URL, prefs_body(quiet_start="01:00")).status_code == 200
    assert a.api.get(PREFS_URL).json()["quiet_start"] == "23:30"
    assert b.api.get(PREFS_URL).json()["quiet_start"] == "01:00"


def test_preferences_identity_cannot_be_chosen_by_client(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    for extra in (
        {"user_id": str(uuid4())},
        {"tenant_id": str(uuid4())},
        {"updated_at": "2020-01-01T00:00:00Z"},
    ):
        r = shop.api.put(PREFS_URL, prefs_body(**extra))
        assert r.status_code == 422 and r.json()["errors"][0]["code"] == "extra_forbidden"
    assert admin_conn.execute("SELECT count(*) FROM notification_preferences").fetchone() == (0,)


@pytest.mark.parametrize(
    "over",
    [
        {"quiet_start": "24:00"},
        {"quiet_start": "22:60"},
        {"quiet_start": "22:00:00"},
        {"quiet_start": "10pm"},
        {"quiet_end": 800},
        {"digest_hour": 24},
        {"digest_hour": -1},
        {"digest_hour": "8"},
        {"digest_hour": 8.5},
        {"show_amounts_email": "yes"},
        {"show_amounts_push": 1},
        {"matrix": {"ZARARINA_SATIS": {"email": "instant", "push": "off"}}},
        {"matrix": {}},
    ],
)
def test_preferences_validation(
    shop: Shop, admin_conn: psycopg.Connection[Any], over: dict[str, Any]
) -> None:
    r = shop.api.put(PREFS_URL, prefs_body(**over))
    assert r.status_code == 422 and r.json()["type"] == "urn:netkar:problem:validation-error"
    assert admin_conn.execute("SELECT count(*) FROM notification_preferences").fetchone() == (0,)


def test_preferences_matrix_cells_are_validated(shop: Shop) -> None:
    for cell in (
        {"email": "always", "push": "off"},
        {"email": "off"},
        {"email": "off", "push": "off", "sms": "off"},
    ):
        body = prefs_body()
        body["matrix"]["ZARARINA_SATIS"] = cell
        assert shop.api.put(PREFS_URL, body).status_code == 422
    body = prefs_body()
    body["matrix"]["BASKA_KURAL"] = {"email": "off", "push": "off"}
    assert shop.api.put(PREFS_URL, body).status_code == 422


def test_preferences_require_auth_and_csrf(shop: Shop, make_api: Callable[..., Api]) -> None:
    anon = make_api()
    assert anon.get(PREFS_URL).status_code == 401 and anon.put(PREFS_URL, prefs_body()).status_code == 401
    r = shop.api.put(PREFS_URL, prefs_body(), csrf=False)
    assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:csrf-failed"


def test_viewer_can_write_own_preferences(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    set_role(admin_conn, shop, "viewer")
    assert shop.api.put(PREFS_URL, prefs_body()).status_code == 200


# --------------------------------------------------------------------------- hız sınırı
def test_transitions_have_user_limit_that_does_not_block_settings_writes(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    frozen_ratelimit_clock: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Viewer'ın geçiş yükü kendi sayacını doldurur; owner'ın eşik yazımı ayrı sayaçla geçer."""
    shop = make_shop("a@example.com", "Mağaza A")
    monkeypatch.setattr(alerts_api, "_TRANSITION_USER_PER_HOUR", 2)
    event_id = add_event(admin_conn, shop)
    set_role(admin_conn, shop, "viewer")
    assert transition(shop, event_id, {"to": "read"}).status_code == 200
    assert shop.api.post(events_url(shop, "/read-all")).status_code == 200
    limited = transition(shop, event_id, {"to": "open"})
    assert limited.status_code == 429 and "Retry-After" in limited.headers
    assert limited.json()["type"] == "urn:netkar:problem:rate-limited"
    assert status_of(admin_conn, event_id) == "read"
    set_role(admin_conn, shop, "owner")
    assert put_settings(shop, ETAG0).status_code == 200
    assert shop.api.get(events_url(shop)).status_code == 200


def test_transitions_have_a_wider_tenant_ceiling(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    frozen_ratelimit_clock: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shop = make_shop("a@example.com", "Mağaza A")
    monkeypatch.setattr(alerts_api, "_TRANSITION_TENANT_PER_HOUR", 2)
    event_id = add_event(admin_conn, shop)
    assert transition(shop, event_id, {"to": "read"}).status_code == 200
    assert transition(shop, event_id, {"to": "open"}).status_code == 200
    assert transition(shop, event_id, {"to": "read"}).status_code == 429
    assert put_settings(shop, ETAG0).status_code == 200  # eşik yazımı etkilenmez


def test_settings_writes_are_rate_limited_per_tenant(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_write_tenant=2)
    etag = put_settings(shop, ETAG0).headers["ETag"]
    assert put_settings(shop, etag, settings_body(loss_min_amount="1.00")).status_code == 200
    assert put_settings(shop, etag, settings_body(loss_min_amount="2.00")).status_code == 429


def test_event_reads_are_rate_limited_per_tenant(
    make_shop: Callable[..., Shop], frozen_ratelimit_clock: float
) -> None:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_settings_read_tenant=2)
    assert shop.api.get(events_url(shop)).status_code == 200
    assert shop.api.get(settings_url(shop)).status_code == 200  # eşik GET'i ayrı sayaç
    assert shop.api.get(events_url(shop)).status_code == 200
    assert shop.api.get(events_url(shop)).status_code == 429
    assert shop.api.get(settings_url(shop)).status_code == 200


def test_preference_writes_are_rate_limited_per_user(shop: Shop, frozen_ratelimit_clock: float) -> None:
    codes = [shop.api.put(PREFS_URL, prefs_body()).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60 and codes[60] == 429
    assert shop.api.get(PREFS_URL).status_code == 200


# --------------------------------------------------------------------------- şema ve OpenAPI
def test_openapi_schema_lists_alert_routes(shop: Shop) -> None:
    """Web istemcisi için şema üretilebilir ve yeni uçları, `If-Match` başlığını ve `extra=forbid`'i içerir."""
    spec = shop.api.client.app.openapi()  # type: ignore[attr-defined]
    paths = spec["paths"]
    base = "/v1/marketplace-accounts/{account_id}"
    assert {"get"} <= set(paths[f"{base}/alert-events"])
    assert {"get"} <= set(paths[f"{base}/alert-events/{{event_id}}"])
    assert {"post"} <= set(paths[f"{base}/alert-events/{{event_id}}/transitions"])
    assert {"post"} <= set(paths[f"{base}/alert-events/read-all"])
    assert {"get", "put"} <= set(paths[f"{base}/alert-settings"])
    assert {"get", "put"} <= set(paths["/v1/me/notification-preferences"])
    put_params = paths[f"{base}/alert-settings"]["put"]["parameters"]
    assert any(p["name"] == "If-Match" and p["in"] == "header" for p in put_params)
    schemas = spec["components"]["schemas"]
    for name in ("TransitionIn", "AlertSettingsIn", "NotificationPreferencesIn", "PreferenceMatrix"):
        assert schemas[name]["additionalProperties"] is False, name
    assert schemas["TransitionIn"]["properties"]["to"]["enum"] == ["read", "open", "muted"]


def test_event_writes_require_verified_email(shop: Shop, admin_conn: psycopg.Connection[Any]) -> None:
    event_id = add_event(admin_conn, shop)
    admin_conn.execute("UPDATE users SET email_verified_at = NULL")
    for r in (transition(shop, event_id, {"to": "read"}), shop.api.post(events_url(shop, "/read-all"))):
        assert r.status_code == 403 and r.json()["type"] == "urn:netkar:problem:email-not-verified"
    assert status_of(admin_conn, event_id) == "open"
    assert shop.api.get(events_url(shop)).status_code == 200  # okuma doğrulama istemez


def test_preferences_db_rejection_is_not_reported_as_a_transition_error(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_a: Any, **_k: Any) -> None:
        raise DBAPIError(
            "INSERT INTO notification_preferences", {}, type("O", (Exception,), {"sqlstate": "23514"})("x")
        )

    monkeypatch.setattr(svc, "save_preferences", boom)
    r = shop.api.put(PREFS_URL, prefs_body())
    assert r.status_code == 409 and r.json()["type"] == "urn:netkar:problem:preferences-rejected"
    assert "transition" not in r.text and "notification_preferences" not in r.text
    monkeypatch.undo()
    orig = type("O", (Exception,), {"sqlstate": "42501"})("x")
    assert alerts_api._preferences_rejection(DBAPIError("s", {}, orig)).status == 403
    with pytest.raises(DBAPIError):
        alerts_api._preferences_rejection(
            DBAPIError("s", {}, type("O", (Exception,), {"sqlstate": "XX000"})("x"))
        )
