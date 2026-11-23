"""Bildirim dağıtıcısı (ADR-0009 D5, §12 madde 20-24): gerçek PostgreSQL, `netkar_worker` rolü, elle kurulmuş outbox.

Kapsam: bayrak kapalıyken gerçek arka ucun ASLA çağrılmaması (satır `suppressed`, ileti yerel `file`/`memory`
arka ucuna), sıklık sınırı (`held` + özete katlanma), sessiz saat (`not_before` = 08:00 İstanbul) ve bırakma, günlük
özet (yeni olay yoksa ileti yok, İstanbul saat eşleşmesi, O-a bastırması), ileti içeriği (sipariş numarası ve barkod
yok, tutar tercihi, başlık temizliği), üyelikten çıkmış ya da doğrulanmamış alıcı (`skipped`), geçici ve kalıcı
hata, deneme tükenmesi, idempotentlik (eşzamanlı iki dağıtıcı bir kez gönderir), birleştirme, log gizliliği.

Saat: `NOW` = 2026-10-10 12:00 UTC (İstanbul 15:00, sessiz saat dışı). `held` bırakma ve `email_for` zamanı veritabanı
saatiyle (`now()`) işler; 2026 tarihli `not_before` değerleri gerçek saate göre geçmişte kalır.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.email import (
    EmailMessage,
    EmailPermanentError,
    EmailTransientError,
    FileEmailSender,
    InMemoryOutbox,
)
from app.db.rls import tenant_transaction as real_tenant_transaction
from app.services.notify import (
    BACKOFF_SECONDS,
    MAX_ATTEMPTS,
    NotificationConfigError,
    NotificationDispatcher,
    digest_dedupe_key,
    error_class_name,
    group_idempotency_key,
)
from app.services.notify_unsubscribe import UnsubscribeSigner
from tests.conftest import DatabaseInfo
from tests.sync_helpers import Seller, make_seller
from tests.test_alert_evaluation import add_sync_run, mark_synced
from tests.test_alert_schema import OUTBOX_INSERT, World, make_world, role_tx, transition


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    """İki kiracı (A: owner, admin, viewer; B: owner); tüm kaynakların yedeklemesi tamam."""
    made = make_world(admin_conn)
    mark_synced(admin_conn, made.a)
    mark_synced(admin_conn, made.b)
    return made


KEY = b"sabit-test-anahtari-0123456789ab"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)  # İstanbul 15:00
NIGHT = datetime(2026, 10, 10, 20, 30, tzinfo=UTC)  # İstanbul 23:30 (sessiz saat)
MORNING = datetime(2026, 10, 11, 5, 1, tzinfo=UTC)  # İstanbul 08:01 (sessiz saat bitti)
DIGEST_AT = datetime(2026, 10, 10, 5, 13, tzinfo=UTC)  # İstanbul 08:13
# Olayların ilk görülme zamanı (özet penceresi `[tik - 24 sa, tik]`): tikten 2 saat önce.
SEEN = datetime(2026, 10, 10, 3, 13, tzinfo=UTC)
LOSS = "ZARARINA_SATIS"
DEDUCTION = "BEKLENMEYEN_KESINTI"
RETURNS = "IADE_ORANI_ARTISI"
ORDER_NO = "9876543"
BARCODE = "GIZLI-BARKOD-77"

_keys = itertools.count(1)


# ---- göndericiler ----------------------------------------------------------------------------------------------------


class LiveBox:
    """Ağa çıkan (yerel OLMAYAN) sahte gerçek gönderici: iletileri ve idempotency anahtarlarını kaydeder."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.keys: list[str | None] = []

    async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        self.messages.append(message)
        self.keys.append(idempotency_key)


class ExplodingSender:
    """Çağrılırsa test başarısız olur: bayrak kapalıyken gerçek arka uç asla çağrılmaz."""

    def __init__(self) -> None:
        self.calls = 0

    async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        self.calls += 1
        raise AssertionError("gerçek arka uç çağrılmamalıydı")


class FailingSender:
    """Verilen hatayı fırlatır (hata metni alıcı adresini içerir: sızıntı testi için)."""

    def __init__(self, error: type[Exception] = EmailTransientError) -> None:
        self.error = error
        self.calls = 0

    async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        self.calls += 1
        raise self.error(f"550 {message.to} reddedildi")


class SlowSender(LiveBox):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self.delay = delay

    async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
        await asyncio.sleep(self.delay)
        await super().send(message, idempotency_key=idempotency_key)


def make(
    engine: AsyncEngine,
    *,
    enabled: bool = True,
    sender: Any = None,
    dev: Any = None,
    now: datetime = NOW,
    **kw: Any,
) -> NotificationDispatcher:
    return NotificationDispatcher(
        engine,
        sender=sender if sender is not None else LiveBox(),
        dev_sender=dev,
        enabled=enabled,
        product_name="NetKâr",
        web_base_url="https://app.test.invalid",
        signer=UnsubscribeSigner(KEY),
        now=lambda: now,
        **kw,
    )


# ---- veri kurucular --------------------------------------------------------------------------------------------------


def event(
    conn: psycopg.Connection[Any],
    seller: Seller,
    *,
    rule: str = LOSS,
    subject: str | None = None,
    scope: str = "product",
    amount: str = "425.00",
    certainty: str = "kesin",
    notify_mode: str = "normal",
    severity: str = "high",
    data_revision: int = 3,
) -> UUID:
    subject = subject or f"urun:{BARCODE}-{next(_keys)}"
    key = {LOSS: "total_loss", DEDUCTION: "difference"}.get(rule, "ad_spend")
    payload = {"certainty": certainty, "evidence": {key: amount}}
    row = conn.execute(
        "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, severity, "
        "payload, payload_version, data_revision, settings_revision, notify_mode) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, 2, %s) RETURNING id",
        (
            seller.tenant_id,
            seller.account_id,
            rule,
            scope,
            subject,
            hashlib.sha256(f"{rule}|{seller.account_id}|{subject}".encode()).hexdigest(),
            severity,
            Jsonb(payload),
            data_revision,
            notify_mode,
        ),
    ).fetchone()
    assert row is not None
    conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:
        conn.execute("UPDATE alert_events SET first_seen_at = %s WHERE id = %s", (SEEN, row[0]))
    finally:
        conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")
    return row[0]  # type: ignore[no-any-return]


def payload_of(rule: str = LOSS, count: int = 1, amount: str | None = "425.00") -> dict[str, Any]:
    entry: dict[str, Any] = {"event_count": count, "window_days": 7}
    if amount is not None:
        entry["total_amount"] = amount
    return {
        "rule_counts": {rule: count},
        "event_count": count,
        "certainty": "kesin",
        "settings_revision": 3,
        "data_revision": 4,
        rule: entry,
    }


def seed(
    conn: psycopg.Connection[Any],
    seller: Seller,
    *,
    user_id: UUID | None = None,
    kind: str = "instant",
    status: str = "pending",
    channel: str = "email",
    payload: dict[str, Any] | None = None,
    events: list[UUID] | None = None,
    not_before: datetime | None = None,
) -> UUID:
    if events is None:
        events = [event(conn, seller)] if kind != "test" else []
    row = conn.execute(
        OUTBOX_INSERT,
        (
            seller.tenant_id,
            user_id or seller.user_id,
            channel,
            kind,
            hashlib.sha256(f"seed-{next(_keys)}".encode()).hexdigest(),
            events,
            Jsonb(payload if payload is not None else payload_of()),
            status,
            not_before or NOW - timedelta(minutes=5),
        ),
    ).fetchone()
    assert row is not None
    return row[0]  # type: ignore[no-any-return]


def state(conn: psycopg.Connection[Any], outbox_id: UUID) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT status, attempts, last_error_class, not_before, sent_at, kind, alert_event_ids "
        "FROM notification_outbox WHERE id = %s",
        (outbox_id,),
    )
    names = [d.name for d in cur.description or ()]
    found = cur.fetchone()
    assert found is not None
    return dict(zip(names, found, strict=True))


def rows(conn: psycopg.Connection[Any], seller: Seller, kind: str | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, user_id, kind, status, channel, last_error_class, alert_event_ids, payload, dedupe_key "
        "FROM notification_outbox WHERE tenant_id = %s AND (%s::text IS NULL OR kind = %s) "
        "ORDER BY created_at, id",
        (seller.tenant_id, kind, kind),
    )
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def email_of(conn: psycopg.Connection[Any], user_id: UUID) -> str:
    found = conn.execute("SELECT email FROM users WHERE id = %s", (user_id,)).fetchone()
    assert found is not None
    return str(found[0])


def user_settings(
    conn: psycopg.Connection[Any],
    seller: Seller,
    user_id: UUID | None = None,
    *,
    digest_hour: int = 8,
    amounts: bool = True,
    quiet: tuple[str, str] = ("00:00", "00:00"),
) -> None:
    """Bildirim ayarı satırı; varsayılan: sessiz saat KAPALI (başlangıç = bitiş), özet 08."""
    conn.execute(
        "INSERT INTO notification_settings (tenant_id, user_id, quiet_start, quiet_end, digest_hour, "
        "show_amounts_email) VALUES (%s, %s, %s, %s, %s, %s)",
        (seller.tenant_id, user_id or seller.user_id, quiet[0], quiet[1], digest_hour, amounts),
    )


def preference(
    conn: psycopg.Connection[Any], seller: Seller, user_id: UUID, rule: str, mode: str, channel: str = "email"
) -> None:
    conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, %s, %s)",
        (seller.tenant_id, user_id, rule, channel, mode),
    )


def product(conn: psycopg.Connection[Any], seller: Seller, barcode: str, title: str) -> None:
    conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title, vat_rate) "
        "VALUES (%s, %s, %s, %s, 20)",
        (seller.tenant_id, seller.account_id, barcode, title),
    )


def mark_sent(conn: psycopg.Connection[Any], seller: Seller, count: int, user_id: UUID | None = None) -> None:
    """`count` adet GÖNDERİLMİŞ anlık e-posta satırı (sent_at tetikleyiciyle şimdi olur)."""
    for _ in range(count):
        outbox_id = seed(conn, seller, user_id=user_id, status="pending")
        conn.execute("UPDATE notification_outbox SET status = 'sent' WHERE id = %s", (outbox_id,))


# ===================================================================================== ADR 20: bayrak kapalı


async def test_disabled_flag_never_calls_the_real_backend_and_suppresses_the_row(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    real, dev = ExplodingSender(), InMemoryOutbox()
    result = await make(worker_engine, enabled=False, sender=real, dev=dev).dispatch()

    assert real.calls == 0 and result.get("errors") == 0  # gerçek arka uç çağrılmadı
    assert (
        state(admin_conn, outbox_id)["status"] == "suppressed"
        and state(admin_conn, outbox_id)["sent_at"] is None
    )
    assert result.get("suppressed") == 1 and result.get("sent") == 0
    (message,) = dev.messages  # yerel arka uca yazıldı
    assert message.to == email_of(admin_conn, a.user_id)
    # Kapalıyken ikinci çalıştırma yeniden işlemez.
    again = await make(worker_engine, enabled=False, sender=real, dev=dev).dispatch()
    assert again.counts == {} and len(dev.messages) == 1


async def test_disabled_flag_writes_the_message_to_the_file_backend(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    tmp_path: Path,
) -> None:
    a = world.a
    seed(admin_conn, a)
    path = tmp_path / "out" / "outbox.jsonl"
    await make(
        worker_engine, enabled=False, sender=ExplodingSender(), dev=FileEmailSender(str(path))
    ).dispatch()
    (line,) = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["to"] == email_of(admin_conn, a.user_id) and record["subject"].startswith("NetKâr:")
    assert record["html"].startswith("<!doctype html>")
    assert set(record["headers"]) == {"List-Unsubscribe", "List-Unsubscribe-Post"}
    assert (path.stat().st_mode & 0o777) == 0o600  # dosya gizli veridir


async def test_disabled_flag_still_skips_unavailable_recipients_and_suppresses_push_rows(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    unverified = admin_conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('dogrulanmamis-kapali@example.com', 'x') RETURNING id"
    ).fetchone()
    assert unverified is not None
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'admin')",
        (unverified[0], a.tenant_id),
    )
    skipped = seed(admin_conn, a, user_id=unverified[0])
    push = seed(admin_conn, a, channel="push")
    real, dev = ExplodingSender(), InMemoryOutbox()
    result = await make(worker_engine, enabled=False, sender=real, dev=dev).dispatch()
    assert state(admin_conn, skipped)["status"] == "skipped"
    assert state(admin_conn, skipped)["last_error_class"] == "recipient_unavailable"
    assert state(admin_conn, push)["status"] == "suppressed"
    assert state(admin_conn, push)["last_error_class"] == "push_not_available"
    assert real.calls == 0 and dev.messages == [] and result.get("errors") == 0


async def test_enabled_flag_sends_through_the_configured_sender_and_marks_the_row_sent(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    box, dev = LiveBox(), InMemoryOutbox()
    result = await make(worker_engine, sender=box, dev=dev).dispatch()
    assert result.get("sent") == 1 and len(box.messages) == 1 and dev.messages == []
    current = state(admin_conn, outbox_id)
    assert (
        current["status"] == "sent" and current["sent_at"] is not None and current["last_error_class"] is None
    )
    assert box.messages[0].to == email_of(admin_conn, a.user_id)


# ===================================================================================== ADR 21: sıklık sınırı, sessiz saat


async def test_quiet_hours_hold_the_row_until_0800_istanbul_and_then_it_is_sent(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)  # varsayılan sessiz saat 22:00-08:00 (ayar satırı yok)
    box = LiveBox()
    first = await make(worker_engine, sender=box, now=NIGHT).dispatch()
    held = state(admin_conn, outbox_id)
    assert first.get("held") == 1 and box.messages == []
    assert held["status"] == "held" and held["last_error_class"] is None
    assert held["not_before"] == datetime(2026, 10, 11, 5, 0, tzinfo=UTC)  # 08:00 İstanbul

    still_night = await make(worker_engine, sender=box, now=NIGHT + timedelta(hours=1)).dispatch()
    assert box.messages == [] and state(admin_conn, outbox_id)["status"] == "held"
    assert still_night.get("released") == 1 and still_night.get("held") == 1  # bırakıldı, yine bekletildi

    sent = await make(worker_engine, sender=box, now=MORNING).dispatch()
    assert sent.get("sent") == 1 and len(box.messages) == 1
    assert state(admin_conn, outbox_id)["status"] == "sent"


async def test_user_quiet_hours_setting_overrides_the_default_window(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a, quiet=("14:00", "16:00"))  # İstanbul 15:00 bu pencerede
    outbox_id = seed(admin_conn, a)
    box = LiveBox()
    await make(worker_engine, sender=box, now=NOW).dispatch()
    held = state(admin_conn, outbox_id)
    assert held["status"] == "held" and held["not_before"] == datetime(2026, 10, 10, 13, 0, tzinfo=UTC)
    assert box.messages == []


async def test_a_held_row_whose_time_has_not_come_is_not_released(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a, status="held", not_before=datetime.now(UTC) + timedelta(days=1))
    box = LiveBox()
    result = await make(worker_engine, sender=box).dispatch()
    assert result.counts == {} and state(admin_conn, outbox_id)["status"] == "held" and box.messages == []


async def test_daily_limit_holds_the_fifth_instant_email_for_the_next_digest(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)  # sessiz saat kapalı
    now = datetime.now(UTC) + timedelta(hours=3)  # son gönderimler 30 dakikadan eski, 24 saat içinde
    mark_sent(admin_conn, a, 4)
    extra = seed(admin_conn, a)
    box = LiveBox()
    result = await make(worker_engine, sender=box, now=now).dispatch()
    assert box.messages == [] and result.get("held_rate_limited") == 1
    held = state(admin_conn, extra)
    assert held["status"] == "held" and held["last_error_class"] == "rate_limited"
    # Bırakma işlevi bu satırı almaz: sonraki çalıştırmada da gönderilmez (özete katlanır).
    await make(worker_engine, sender=box, now=now + timedelta(hours=1)).dispatch()
    assert box.messages == [] and state(admin_conn, extra)["status"] == "held"


async def test_limit_is_per_user_and_an_older_send_outside_the_window_does_not_count(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    user_settings(admin_conn, a, world.admin_id)
    now = datetime.now(UTC) + timedelta(hours=3)
    mark_sent(admin_conn, a, 4, user_id=world.admin_id)  # başka kullanıcının sınırı dolu
    mine = seed(admin_conn, a)
    box = LiveBox()
    await make(worker_engine, sender=box, now=now).dispatch()
    assert state(admin_conn, mine)["status"] == "sent"  # kendi sınırım dolu değil
    # 24 saat dışına itilen gönderimler sayılmaz.
    later = now + timedelta(hours=25)
    mark_sent(admin_conn, a, 3)
    seed_row = seed(admin_conn, a)
    await make(worker_engine, sender=box, now=later).dispatch()
    assert state(admin_conn, seed_row)["status"] == "sent"


async def test_minimum_gap_between_two_instant_emails_is_thirty_minutes(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    mark_sent(admin_conn, a, 1)
    waiting = seed(admin_conn, a)
    box = LiveBox()
    now = datetime.now(UTC) + timedelta(minutes=10)
    await make(worker_engine, sender=box, now=now).dispatch()
    assert state(admin_conn, waiting)["status"] == "held" and box.messages == []
    # 31 dakika sonra yeni bir anlık satır gönderilebilir.
    fresh = seed(admin_conn, a)
    await make(worker_engine, sender=box, now=datetime.now(UTC) + timedelta(minutes=31)).dispatch()
    assert state(admin_conn, fresh)["status"] == "sent"


async def test_digest_rows_are_exempt_from_the_instant_limit_and_quiet_hours(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    mark_sent(admin_conn, a, 4)
    digest = seed(admin_conn, a, kind="digest")
    box = LiveBox()
    await make(worker_engine, sender=box, now=NIGHT).dispatch()  # hem gece hem sınır dolu
    assert state(admin_conn, digest)["status"] == "sent" and len(box.messages) == 1
    assert box.messages[0].subject.startswith("NetKâr: günlük uyarı özeti")


async def test_pending_rows_of_one_user_merge_into_a_single_email(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    first = seed(admin_conn, a, payload=payload_of(LOSS, 1, "10.00"), not_before=NOW - timedelta(minutes=3))
    second = seed(admin_conn, a, payload=payload_of(LOSS, 2, "5.50"), not_before=NOW - timedelta(minutes=2))
    third = seed(
        admin_conn, a, payload=payload_of(DEDUCTION, 1, "7.25"), not_before=NOW - timedelta(minutes=1)
    )
    other_user = seed(admin_conn, a, user_id=world.admin_id)
    box = LiveBox()
    result = await make(worker_engine, sender=box).dispatch()
    mine = [m for m in box.messages if m.to == email_of(admin_conn, a.user_id)]
    assert len(mine) == 1 and result.get("merged") == 2  # kullanıcı başına tek ileti
    assert "- 3 üründe zararına satış" in mine[0].body and "Toplam zarar: 15,50 TL" in mine[0].body
    assert "- 1 sipariş satırında beklenmeyen kesinti" in mine[0].body
    # Birincil satır kimliğe göre en küçük kimliktir (grup sıralı); kimlikler rastgele olduğundan test bunu hesaplar.
    primary = min(first, second, third, key=str)
    assert state(admin_conn, primary)["status"] == "sent"
    for merged in (x for x in (first, second, third) if x != primary):
        assert (state(admin_conn, merged)["status"], state(admin_conn, merged)["last_error_class"]) == (
            "skipped",
            "merged",
        )
    assert state(admin_conn, other_user)["status"] == "sent"  # başka kullanıcının satırı ayrı gider


# ===================================================================================== ADR 22: özet


def digest_rows(conn: psycopg.Connection[Any], seller: Seller) -> list[dict[str, Any]]:
    """Satıcının (owner) özet satırları; admin kullanıcının özeti `user_digest_rows` ile bakılır."""
    return [r for r in rows(conn, seller, "digest") if r["user_id"] == seller.user_id]


async def test_digest_is_built_once_for_new_events_at_the_users_istanbul_hour(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    loss_one = event(admin_conn, a, amount="100.00")
    loss_two = event(admin_conn, a, amount="25.50", certainty="tahmini")
    deduction = event(
        admin_conn, a, rule=DEDUCTION, scope="order_line", subject=f"satir:{ORDER_NO}|1|1", amount="12.00"
    )
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    # Alıcılar üyelerden kurulur: A kiracısında owner ve admin (varsayılan özet), viewer (varsayılan e-posta off).
    assert result.get("digests") == 2 and result.get("users_due") == 4
    (digest,) = digest_rows(admin_conn, a)
    assert (digest["user_id"], digest["channel"], digest["status"]) == (a.user_id, "email", "pending")
    assert set(digest["alert_event_ids"]) == {loss_one, loss_two, deduction}
    payload = digest["payload"]
    assert payload["rule_counts"] == {LOSS: 2, DEDUCTION: 1} and payload["event_count"] == 3
    assert payload[LOSS] == {"event_count": 2, "window_days": 7, "total_amount": "125.50"}
    assert payload[DEDUCTION]["total_amount"] == "12.00" and payload["certainty"] == "tahmini"
    assert (payload["data_revision"], payload["settings_revision"]) == (3, 2)
    assert digest["dedupe_key"] == digest_dedupe_key(a.user_id, datetime(2026, 10, 10).date(), 8)
    # Aynı saatte ikinci çalıştırma hiçbir şey yazmaz.
    again = await make(worker_engine, now=DIGEST_AT + timedelta(minutes=20)).build_digests()
    assert again.get("digests") == 0 and len(digest_rows(admin_conn, a)) == 1


async def test_digest_time_matching_uses_istanbul_not_utc(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    event(admin_conn, a)
    # 08:13 UTC = 11:13 İstanbul: özet saati (08) değil.
    miss = await make(worker_engine, now=datetime(2026, 10, 10, 8, 13, tzinfo=UTC)).build_digests()
    assert miss.get("digests") == 0 and miss.get("users_due") == 0 and digest_rows(admin_conn, a) == []
    # 05:13 UTC = 08:13 İstanbul: eşleşir.
    hit = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert hit.get("digests") == 2  # owner ve admin (viewer varsayılanı off)
    # Kullanıcı özet saatini 11'e alırsa 08:13 UTC (11:13 İstanbul) eşleşir.
    admin_conn.execute("UPDATE notification_settings SET digest_hour = 11 WHERE user_id = %s", (a.user_id,))
    late = await make(worker_engine, now=datetime(2026, 10, 10, 8, 13, tzinfo=UTC)).build_digests()
    assert late.get("digests") == 1 and len(digest_rows(admin_conn, a)) == 2


async def test_no_new_events_means_no_digest_and_stale_resolved_or_muted_events_do_not_count(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    database: DatabaseInfo,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    empty = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert empty.get("digests") == 0 and digest_rows(admin_conn, a) == []  # olay yok: ileti yok

    old = event(admin_conn, a)
    admin_conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:
        admin_conn.execute(
            "UPDATE alert_events SET first_seen_at = %s WHERE id = %s", (SEEN - timedelta(hours=25), old)
        )
    finally:
        admin_conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")
    resolved = event(admin_conn, a)
    muted = event(admin_conn, a)
    silent = event(admin_conn, a, notify_mode="none")
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        transition(conn, a, resolved, "resolved")
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, muted, "muted", datetime.now(UTC) + timedelta(days=2))
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert result.get("digests") == 0, (
        silent
    )  # 24 saatten eski, çözülmüş, susturulmuş ve "none" olaylar sayılmaz
    digest_only = event(admin_conn, a, notify_mode="digest_only")
    final = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert final.get("digests") == 2 and digest_rows(admin_conn, a)[0]["alert_event_ids"] == [digest_only]


async def test_digest_follows_the_users_email_preferences_and_ignores_other_tenants(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a, b = world.a, world.b
    user_settings(admin_conn, a)
    user_settings(admin_conn, b)
    preference(admin_conn, a, a.user_id, DEDUCTION, "off")  # kapalı kural özete girmez
    preference(admin_conn, a, a.user_id, RETURNS, "instant")  # anlık kural özete girmez
    preference(
        admin_conn, a, a.user_id, "REKLAM_KARI_YIYOR", "instant", channel="push"
    )  # push tercihi etkilemez
    loss = event(admin_conn, a)
    event(admin_conn, a, rule=DEDUCTION, scope="order_line", subject="satir:1|1|1")
    event(admin_conn, a, rule=RETURNS, scope="account", subject="hesap:*")
    foreign = event(admin_conn, b, amount="999.00")
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert result.get("digests") == 3  # A: owner + admin, B: owner
    (mine,) = digest_rows(admin_conn, a)
    assert mine["alert_event_ids"] == [loss] and mine["payload"]["rule_counts"] == {LOSS: 1}
    (theirs,) = digest_rows(admin_conn, b)
    assert theirs["alert_event_ids"] == [foreign] and theirs["user_id"] == b.user_id


async def test_digest_suppresses_only_rules_whose_own_source_is_broken(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    loss = event(admin_conn, a)
    deduction = event(admin_conn, a, rule=DEDUCTION, scope="order_line", subject="satir:1|1|1")
    returns = event(admin_conn, a, rule=RETURNS, scope="account", subject="hesap:*")
    add_sync_run(admin_conn, a, "settlements", "failed", "2026-10-09")  # finans kaynağı bozuk
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert result.get("digests") == 2
    (digest,) = digest_rows(admin_conn, a)
    assert digest["alert_event_ids"] == [returns]  # iade kuralı etkilenmedi
    assert loss not in digest["alert_event_ids"] and deduction not in digest["alert_event_ids"]
    # Toparlanınca (sonraki saat/gün) kural yeniden özete girer.
    add_sync_run(admin_conn, a, "settlements", "succeeded", "2026-10-10")
    admin_conn.execute("DELETE FROM notification_outbox")
    again = await make(worker_engine, now=DIGEST_AT + timedelta(days=0, minutes=5)).build_digests()
    assert again.get("digests") == 2 and set(digest_rows(admin_conn, a)[0]["alert_event_ids"]) == {
        loss,
        deduction,
        returns,
    }


async def test_digest_is_not_built_for_an_account_that_is_not_active(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    revoked = make_seller(admin_conn, seller_id="5555", status="revoked")
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'owner')",
        (revoked.user_id, revoked.tenant_id),
    )
    user_settings(admin_conn, revoked)
    event(admin_conn, revoked)
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert result.get("digests") == 0 and digest_rows(admin_conn, revoked) == []  # etkin hesap yok


async def test_rate_limited_rows_fold_into_the_next_digest_and_are_closed(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    folded_event = event(admin_conn, a, amount="40.00")
    admin_conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:  # 24 saatten eski: yalnız katlanma yoluyla özete girer
        admin_conn.execute(
            "UPDATE alert_events SET first_seen_at = %s WHERE id = %s",
            (SEEN - timedelta(hours=30), folded_event),
        )
    finally:
        admin_conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")
    held = seed(admin_conn, a, events=[folded_event], status="held", payload=payload_of(LOSS, 1, "40.00"))
    admin_conn.execute(
        "UPDATE notification_outbox SET last_error_class = 'rate_limited' WHERE id = %s", (held,)
    )
    plain_held = seed(  # sessiz saat bekleyeni (aynı olay; katlanma yalnız rate_limited satırlar için)
        admin_conn, a, events=[folded_event], status="held", not_before=NOW + timedelta(days=30)
    )
    result = await make(worker_engine, now=DIGEST_AT).build_digests()
    assert result.get("digests") == 1 and result.get("folded") == 1
    (digest,) = digest_rows(admin_conn, a)
    assert digest["alert_event_ids"] == [folded_event] and digest["payload"]["rule_counts"] == {LOSS: 1}
    closed = state(admin_conn, held)
    assert (closed["status"], closed["last_error_class"]) == ("skipped", "folded_into_digest")
    assert state(admin_conn, plain_held)["status"] == "held"  # kural dışı bekleyen satıra dokunulmaz


async def test_unfoldable_rate_limited_rows_expire_after_two_days(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    held = seed(admin_conn, a, status="held")
    admin_conn.execute(
        "UPDATE notification_outbox SET last_error_class = 'rate_limited' WHERE id = %s", (held,)
    )
    admin_conn.execute("ALTER TABLE notification_outbox DISABLE TRIGGER notification_outbox_guard")
    try:
        admin_conn.execute(
            "UPDATE notification_outbox SET created_at = now() - interval '3 days' WHERE id = %s", (held,)
        )
    finally:
        admin_conn.execute("ALTER TABLE notification_outbox ENABLE ALWAYS TRIGGER notification_outbox_guard")
    result = await make(worker_engine, now=NOW).build_digests()
    assert result.get("expired") == 1
    assert (state(admin_conn, held)["status"], state(admin_conn, held)["last_error_class"]) == (
        "skipped",
        "held_expired",
    )


async def test_built_digest_is_dispatched_with_its_own_subject_and_never_resent(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    event(admin_conn, a, amount="321.00")
    await make(worker_engine, now=DIGEST_AT).build_digests()
    box = LiveBox()
    await make(worker_engine, sender=box, now=NOW).dispatch()
    (message,) = [m for m in box.messages if m.to == email_of(admin_conn, a.user_id)]
    assert len(box.messages) == 2  # owner ve admin (üye alıcılar)
    assert message.subject == "NetKâr: günlük uyarı özeti (1 uyarı)"
    assert "- 1 üründe zararına satış" in message.body and "Toplam zarar: 321,00 TL" in message.body
    await make(worker_engine, sender=box, now=NOW).dispatch()
    assert len(box.messages) == 2


# ===================================================================================== ADR 23: içerik


async def test_email_body_has_no_order_number_or_barcode_and_cleans_product_titles(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    barcode = "BC-TEMIZLE-1"
    product(admin_conn, a, barcode, "<b>Kırmızı</b>\r\nBcc: kotu@example.com‮ Tişört http://kotu.example")
    loss = event(admin_conn, a, subject=f"urun:{barcode}")
    line = event(
        admin_conn, a, rule=DEDUCTION, scope="order_line", subject=f"satir:{ORDER_NO}|5001|1", amount="12.00"
    )
    payload = {
        "rule_counts": {LOSS: 1, DEDUCTION: 1},
        "event_count": 2,
        "certainty": "kesin",
        "settings_revision": 3,
        LOSS: {"event_count": 1, "window_days": 7, "total_amount": "425.00"},
        DEDUCTION: {"event_count": 1, "window_days": 92, "total_amount": "12.00"},
    }
    seed(admin_conn, a, events=[loss, line], payload=payload)
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()
    (message,) = box.messages
    assert message.html is not None
    for part in (message.subject, message.body, message.html):
        assert ORDER_NO not in part and "5001" not in part and barcode not in part and "satir:" not in part
        assert "urun:" not in part
    # Başlık temizlendi: tek satır, kontrol karakteri yok, bağlantı şeması etkisiz.
    sample = next(ln for ln in message.body.splitlines() if ln.startswith("Örnek ürünler:"))
    assert "Bcc: kotu@example.com" in sample and "‮" not in message.body and "http://" not in message.body
    assert not any(ln.startswith("Bcc:") for ln in message.body.splitlines())
    assert "<b>" not in message.html and "&lt;b&gt;" in message.html  # HTML'de kaçışlı
    assert "Toplam zarar: 425,00 TL" in message.body and "Toplam fark: 12,00 TL" in message.body


async def test_amounts_are_absent_when_the_users_preference_is_off(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a, amounts=False)
    user_settings(admin_conn, a, world.admin_id, amounts=True)
    seed(admin_conn, a, payload=payload_of(LOSS, 1, "425.00"))
    seed(admin_conn, a, user_id=world.admin_id, payload=payload_of(LOSS, 1, "425.00"))
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()
    by_user = {m.to: m for m in box.messages}
    hidden = by_user[email_of(admin_conn, a.user_id)]
    shown = by_user[email_of(admin_conn, world.admin_id)]
    assert hidden.html is not None and shown.html is not None
    for part in (hidden.subject, hidden.body, hidden.html):
        # Kapatma bağlantısındaki rastgele token (base64url) "TL" ya da "425" içerebilir; tutar denetimi
        # yalnız insan okunur metne yapılır, token değeri denetimden önce çıkarılır.
        text_only = re.sub(r"token=[A-Za-z0-9_\-.]+", "token=", part)
        assert "425" not in text_only and "TL" not in text_only
    assert "425,00 TL" in shown.body and "425,00 TL" in shown.html


async def test_message_carries_verifiable_one_click_headers_and_per_rule_links(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    seed(admin_conn, a)
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()
    (message,) = box.messages
    url = message.headers["List-Unsubscribe"].strip("<>")
    assert url.startswith("https://app.test.invalid/api/v1/notifications/unsubscribe?token=")
    assert message.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    signer = UnsubscribeSigner(KEY)
    claim = signer.verify(url.split("token=", 1)[1], NOW)
    assert claim is not None and (claim.user_id, claim.tenant_id) == (a.user_id, a.tenant_id)
    assert claim.rule == LOSS and claim.channel == "email"  # tek kurallı anlık ileti: yalnız o kural (D1)
    link = next(ln for ln in message.body.splitlines() if ln.startswith("- Zararına satış: "))
    rule_claim = signer.verify(link.split("token=", 1)[1], NOW)
    assert rule_claim is not None and rule_claim.rule == LOSS and rule_claim.user_id == a.user_id
    assert "https://app.test.invalid/panel/uyarilar" in message.body


async def test_test_kind_rows_render_without_events(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a, kind="test", payload={"event_count": 0})
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()
    assert state(admin_conn, outbox_id)["status"] == "sent"
    assert box.messages[0].subject == "NetKâr: test bildirimi"


# ===================================================================================== ADR 24: alıcı


async def test_a_user_removed_from_the_tenant_or_unverified_gets_nothing(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    removed = world.admin_id
    unverified = admin_conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('dogrulanmamis@example.com', 'x') RETURNING id"
    ).fetchone()
    assert unverified is not None
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'admin')",
        (unverified[0], a.tenant_id),
    )
    removed_row = seed(admin_conn, a, user_id=removed)
    unverified_row = seed(admin_conn, a, user_id=unverified[0])
    stranger_row = seed(admin_conn, a, user_id=world.stranger_id)  # hiç üye değil
    ok_row = seed(admin_conn, a)
    admin_conn.execute("ALTER TABLE memberships DISABLE TRIGGER USER")
    try:
        admin_conn.execute("DELETE FROM memberships WHERE user_id = %s", (removed,))
    finally:
        admin_conn.execute("ALTER TABLE memberships ENABLE ALWAYS TRIGGER memberships_immutable_guard")
    box = LiveBox()
    result = await make(worker_engine, sender=box).dispatch()
    for outbox_id in (removed_row, unverified_row, stranger_row):
        current = state(admin_conn, outbox_id)
        assert (current["status"], current["last_error_class"]) == ("skipped", "recipient_unavailable")
    assert state(admin_conn, ok_row)["status"] == "sent"
    assert [m.to for m in box.messages] == [email_of(admin_conn, a.user_id)]  # yalnız üye ve doğrulanmış
    assert result.get("skipped") == 3 and result.get("sent") == 1


async def test_the_address_is_never_stored_in_the_outbox_or_the_error_class(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    address = email_of(admin_conn, a.user_id)
    seed(admin_conn, a)
    await make(worker_engine, sender=FailingSender()).dispatch()
    dump = admin_conn.execute("SELECT row_to_json(o)::text FROM notification_outbox o").fetchall()
    assert dump and all(address not in row[0] and "@" not in row[0] for row in dump)


# ===================================================================================== hata, yeniden deneme, idempotentlik


async def test_transient_failure_schedules_a_backoff_retry_and_the_retry_succeeds(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)
    failing = FailingSender()
    result = await make(worker_engine, sender=failing).dispatch()
    current = state(admin_conn, outbox_id)
    assert result.get("failed") == 1 and failing.calls == 1
    assert (current["status"], current["attempts"], current["last_error_class"]) == (
        "failed",
        1,
        "email_transient_error",
    )
    assert current["not_before"] == NOW + timedelta(seconds=BACKOFF_SECONDS[0])
    box = LiveBox()
    retry = await make(worker_engine, sender=box).dispatch()  # bekleme süresi geçmiş: bırakılır ve gönderilir
    assert retry.get("released") == 1 and retry.get("sent") == 1 and len(box.messages) == 1
    assert state(admin_conn, outbox_id)["status"] == "sent"


async def test_attempts_are_exhausted_after_six_failures_with_growing_backoff(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)
    failing = FailingSender()
    seen: list[tuple[str, int, timedelta | None]] = []
    for _ in range(MAX_ATTEMPTS):
        await make(worker_engine, sender=failing).dispatch()
        current = state(admin_conn, outbox_id)
        wait = (current["not_before"] - NOW) if current["status"] == "failed" else None
        seen.append((current["status"], current["attempts"], wait))
    assert [s[:2] for s in seen] == [("failed", n) for n in range(1, 6)] + [("failed_permanent", 6)]
    assert [s[2] for s in seen[:5]] == [timedelta(seconds=w) for w in BACKOFF_SECONDS]
    calls = failing.calls
    await make(worker_engine, sender=failing).dispatch()
    assert failing.calls == calls  # failed_permanent bir daha denenmez


async def test_permanent_failure_is_not_retried(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    failing = FailingSender(EmailPermanentError)
    await make(worker_engine, sender=failing, now=NOW).dispatch()
    current = state(admin_conn, outbox_id)
    assert (current["status"], current["attempts"], current["last_error_class"]) == (
        "failed_permanent",
        1,
        "email_permanent_error",
    )
    await make(worker_engine, sender=failing, now=NOW + timedelta(hours=1)).dispatch()
    assert failing.calls == 1


async def test_a_slow_backend_times_out_as_a_transient_failure(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    slow = SlowSender(delay=2.0)
    await make(worker_engine, sender=slow, send_timeout=0.05).dispatch()
    current = state(admin_conn, outbox_id)
    assert (current["status"], current["attempts"], current["last_error_class"]) == (
        "failed",
        1,
        "timeout_error",
    )
    assert slow.messages == []


async def test_two_concurrent_dispatchers_send_a_row_exactly_once(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    box = SlowSender(delay=0.3)
    first, second = make(worker_engine, sender=box), make(worker_engine, sender=box)
    await asyncio.gather(first.dispatch(), second.dispatch())
    assert len(box.messages) == 1 and state(admin_conn, outbox_id)["status"] == "sent"
    assert (await make(worker_engine, sender=box).dispatch()).counts == {}  # kapanmış satır yeniden işlenmez


async def test_a_database_failure_after_the_send_is_recorded_as_failed_and_the_retry_reuses_the_key(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)
    real = NotificationDispatcher._close
    box = LiveBox()

    async def broken(self: NotificationDispatcher, *args: Any, **kw: Any) -> int:
        if args[3] == "sent":
            raise RuntimeError("commit öncesi çökme")
        return await real(self, *args, **kw)

    monkeypatch.setattr(NotificationDispatcher, "_close", broken)
    result = await make(worker_engine, sender=box).dispatch()
    assert result.get("errors") == 1 and box.keys == [group_idempotency_key([outbox_id])]
    # D2: beklenmeyen hata AYRI işlemde attempts + 1 ve failed yazar; satır sınırsız pending kalmaz.
    current = state(admin_conn, outbox_id)
    assert (current["status"], current["attempts"], current["last_error_class"]) == (
        "failed",
        1,
        "runtime_error",
    )
    monkeypatch.undo()
    admin_conn.execute(
        "UPDATE notification_outbox SET not_before = now() - interval '1 minute' WHERE id = %s", (outbox_id,)
    )
    await make(worker_engine, sender=box).dispatch()  # yeniden deneme: aynı idempotency anahtarı
    assert (
        box.keys == [group_idempotency_key([outbox_id])] * 2
        and state(admin_conn, outbox_id)["status"] == "sent"
    )


async def test_unexpected_errors_exhaust_the_row_instead_of_retrying_forever(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)

    async def broken(*args: Any, **kw: Any) -> Any:
        raise RuntimeError("beklenmeyen")

    monkeypatch.setattr(NotificationDispatcher, "_compose", broken)
    for expected in range(1, MAX_ATTEMPTS + 1):
        admin_conn.execute(
            "UPDATE notification_outbox SET status = 'pending', not_before = now() - interval '1 minute' "
            "WHERE id = %s AND status = 'failed'",
            (outbox_id,),
        )
        await make(worker_engine).dispatch()
        assert state(admin_conn, outbox_id)["attempts"] == expected
    assert state(admin_conn, outbox_id)["status"] == "failed_permanent"


async def test_send_happens_outside_any_database_transaction_with_a_lease_and_the_row_id_as_key(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)
    observed: dict[str, Any] = {}

    class Probe(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            # Gönderim sırasında satır kilitli DEĞİL (işlem kapalı) ve kiralanmış (gelecekte not_before).
            with psycopg.connect(
                admin_conn.info.dsn, autocommit=True, password=admin_conn.info.password
            ) as other:
                locked = other.execute(
                    "SELECT id FROM notification_outbox WHERE id = %s FOR UPDATE SKIP LOCKED", (outbox_id,)
                ).fetchone()
                lease = other.execute(
                    "SELECT status, not_before > now() + interval '5 minutes' FROM notification_outbox WHERE id = %s",
                    (outbox_id,),
                ).fetchone()
            observed.update(locked=locked, lease=lease)
            await super().send(message, idempotency_key=idempotency_key)

    probe = Probe()
    await make(worker_engine, sender=probe).dispatch()
    assert observed["locked"] == (outbox_id,)  # satır kilitli değildi
    assert observed["lease"] == ("pending", True)  # kiralanmıştı: ikinci dağıtıcı onu görmez
    assert (
        probe.keys == [group_idempotency_key([outbox_id])]
        and state(admin_conn, outbox_id)["status"] == "sent"
    )


async def test_a_crash_between_claim_and_result_leaves_a_leased_pending_row_that_is_retried_later(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)

    class Crash(BaseException):
        pass

    class Dies(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            raise Crash

    with pytest.raises(Crash):
        await make(worker_engine, sender=Dies()).dispatch()
    assert state(admin_conn, outbox_id)["status"] == "pending"  # sonuç yazılamadı
    assert (
        await make(worker_engine, sender=LiveBox()).dispatch()
    ).counts == {}  # kira sürerken yeniden alınmaz
    admin_conn.execute(
        "UPDATE notification_outbox SET not_before = now() - interval '1 minute' WHERE id = %s", (outbox_id,)
    )
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()  # kira doldu: yeniden denenir, aynı anahtar
    assert (
        box.keys == [group_idempotency_key([outbox_id])] and state(admin_conn, outbox_id)["status"] == "sent"
    )


async def test_the_total_runtime_budget_stops_the_run_and_leaves_the_rest_for_the_next_tick(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    first = seed(admin_conn, a, user_id=a.user_id)
    second = seed(admin_conn, a, user_id=world.admin_id)
    box = LiveBox()
    result = await make(worker_engine, sender=box, max_runtime=0.0).dispatch()
    assert result.get("budget_exhausted") == 1 and box.messages == []
    assert {state(admin_conn, first)["status"], state(admin_conn, second)["status"]} == {"pending"}
    await make(worker_engine, sender=box).dispatch()
    assert len(box.messages) == 2


async def test_a_release_failure_for_one_row_does_not_block_the_others(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    user_settings(admin_conn, a, world.admin_id)
    bad = seed(admin_conn, a, status="held", not_before=NOW - timedelta(minutes=9))
    good = seed(admin_conn, a, user_id=world.admin_id, status="held", not_before=NOW - timedelta(minutes=1))
    from app.services import notify as notify_module

    real = real_tenant_transaction
    calls = {"n": 0}

    def flaky(sessions: Any, tenant_id: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("serbest bırakma hatası")
        return real(sessions, tenant_id)

    monkeypatch.setattr(notify_module, "tenant_transaction", flaky)
    box = LiveBox()
    result = await make(worker_engine, sender=box).dispatch()
    assert result.get("errors") == 1 and state(admin_conn, bad)["status"] == "held"
    assert state(admin_conn, good)["status"] == "sent" and result.get("released") == 1


# ===================================================================================== ORTA-1: kararlı grup


async def test_a_result_write_failure_on_a_merged_group_retries_with_the_same_key_and_content(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    first = seed(admin_conn, a, payload=payload_of(LOSS, 1, "10.00"), not_before=NOW - timedelta(minutes=3))
    second = seed(
        admin_conn, a, payload=payload_of(DEDUCTION, 2, "7.25"), not_before=NOW - timedelta(minutes=2)
    )
    key = group_idempotency_key([first, second])
    assert key == group_idempotency_key([second, first])  # sıralamadan bağımsız
    real = NotificationDispatcher._close
    box = LiveBox()

    async def broken(self: NotificationDispatcher, *args: Any, **kw: Any) -> int:
        if args[3] == "sent":
            raise RuntimeError("sonuç yazımı hatası")
        return await real(self, *args, **kw)

    monkeypatch.setattr(NotificationDispatcher, "_close", broken)
    result = await make(worker_engine, sender=box).dispatch()
    # Hata grubun TÜM satırlarına yazıldı (yalnız birincil değil): ikisi de failed, deneme 1, aynı not_before.
    states = [state(admin_conn, i) for i in (first, second)]
    assert result.get("errors") == 1 and [s_["status"] for s_ in states] == ["failed", "failed"]
    assert [s_["attempts"] for s_ in states] == [1, 1] and states[0]["not_before"] == states[1]["not_before"]
    monkeypatch.undo()
    admin_conn.execute(
        "UPDATE notification_outbox SET not_before = now() - interval '1 minute' WHERE id = ANY(%s)",
        ([first, second],),
    )
    await make(worker_engine, sender=box).dispatch()
    # İki gönderim, AYNI anahtar ve AYNI içerik; kardeşler ayrı ayrı gönderilmedi.
    assert box.keys == [key, key] and box.messages[0] == box.messages[1] and len(box.messages) == 2
    assert {state(admin_conn, i)["status"] for i in (first, second)} == {"sent", "skipped"}
    assert sorted(
        (state(admin_conn, i)["status"], state(admin_conn, i)["last_error_class"]) for i in (first, second)
    ) == [
        ("sent", None),
        ("skipped", "merged"),
    ]


async def test_failure_result_on_a_merged_group_marks_every_row_with_one_backoff(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    rows_ = [seed(admin_conn, a, not_before=NOW - timedelta(minutes=n)) for n in (3, 2, 1)]
    admin_conn.execute("UPDATE notification_outbox SET attempts = 2 WHERE id = %s", (rows_[0],))
    await make(worker_engine, sender=FailingSender()).dispatch()
    states = [state(admin_conn, i) for i in rows_]
    assert {s_["status"] for s_ in states} == {"failed"} and len({s_["not_before"] for s_ in states}) == 1
    assert sorted(s_["attempts"] for s_ in states) == [1, 1, 3]
    assert states[0]["not_before"] == NOW + timedelta(seconds=BACKOFF_SECONDS[2])  # en yüksek denemeye göre


async def test_message_content_is_deterministic_for_a_group_across_retries_at_different_times(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    first = seed(admin_conn, a, not_before=NOW - timedelta(minutes=3))
    second = seed(admin_conn, a, not_before=NOW - timedelta(minutes=2))

    class CaptureFail(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            await super().send(message, idempotency_key=idempotency_key)
            raise EmailTransientError("geçici")

    capture = CaptureFail()
    await make(worker_engine, sender=capture, now=NOW).dispatch()
    admin_conn.execute(
        "UPDATE notification_outbox SET not_before = now() - interval '1 minute' WHERE id = ANY(%s)",
        ([first, second],),
    )
    await make(worker_engine, sender=capture, now=NOW + timedelta(days=3)).dispatch()  # çok sonra, başka saat
    # Token zamanı satırın `created_at`ıdır (şimdiki zaman değil): içerik ve anahtar birebir aynı.
    assert len(capture.messages) == 2 and capture.messages[0] == capture.messages[1]
    assert capture.keys[0] == capture.keys[1] == group_idempotency_key([first, second])


# ===================================================================================== D-a: kira sahipliği


async def test_a_result_write_is_ignored_when_the_lease_moved_to_someone_else(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)

    class Takeover(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            # Gönderim sürerken kira (kiralama zamanı) başka bir çalıştırmaya geçti.
            admin_conn.execute(
                "UPDATE notification_outbox SET not_before = now() + interval '20 minutes' WHERE id = %s",
                (outbox_id,),
            )
            await super().send(message, idempotency_key=idempotency_key)

    result = await make(worker_engine, sender=Takeover()).dispatch()
    current = state(admin_conn, outbox_id)
    assert current["status"] == "pending" and current["attempts"] == 0  # yazım etkisiz kaldı
    assert result.get("lease_lost") == 1 and result.get("sent") == 0


async def test_a_failure_write_is_also_ignored_when_the_lease_moved(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)

    class TakeoverFail(FailingSender):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            admin_conn.execute(
                "UPDATE notification_outbox SET not_before = now() + interval '20 minutes' WHERE id = %s",
                (outbox_id,),
            )
            await super().send(message, idempotency_key=idempotency_key)

    result = await make(worker_engine, sender=TakeoverFail()).dispatch()
    assert state(admin_conn, outbox_id)["status"] == "pending" and result.get("lease_lost") == 1


async def test_the_lease_guard_does_not_block_the_normal_result_write(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    outbox_id = seed(admin_conn, a)
    result = await make(worker_engine, sender=LiveBox()).dispatch()
    assert state(admin_conn, outbox_id)["status"] == "sent" and result.get("lease_lost") == 0


async def test_a_partial_lease_loss_rolls_the_whole_group_result_back(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    first = seed(admin_conn, a, not_before=NOW - timedelta(minutes=3))
    second = seed(admin_conn, a, not_before=NOW - timedelta(minutes=2))

    class Partial(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            # Yalnız grubun BİR satırının kirası başkasına geçti.
            admin_conn.execute(
                "UPDATE notification_outbox SET not_before = now() + interval '20 minutes' WHERE id = %s",
                (second,),
            )
            await super().send(message, idempotency_key=idempotency_key)

    result = await make(worker_engine, sender=Partial()).dispatch()
    states = [state(admin_conn, i) for i in (first, second)]
    # Tümü ya hiç: kısmi yazım (biri sent, biri pending) YOK; ikisi de kiralı pending kaldı.
    assert [s_["status"] for s_ in states] == ["pending", "pending"] and [
        s_["attempts"] for s_ in states
    ] == [0, 0]
    assert result.get("lease_lost") == 2 and result.get("sent") == 0 and result.get("merged") == 0


async def test_a_partial_lease_loss_also_rolls_back_a_group_failure_write(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    first = seed(admin_conn, a, not_before=NOW - timedelta(minutes=3))
    second = seed(admin_conn, a, not_before=NOW - timedelta(minutes=2))

    class PartialFail(FailingSender):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            admin_conn.execute(
                "UPDATE notification_outbox SET not_before = now() + interval '20 minutes' WHERE id = %s",
                (first,),
            )
            await super().send(message, idempotency_key=idempotency_key)

    result = await make(worker_engine, sender=PartialFail()).dispatch()
    assert {state(admin_conn, i)["status"] for i in (first, second)} == {"pending"} and result.get(
        "lease_lost"
    ) == 2


async def test_the_unexpected_error_record_respects_lease_ownership(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    outbox_id = seed(admin_conn, a)
    real = NotificationDispatcher._close

    async def broken(self: NotificationDispatcher, *args: Any, **kw: Any) -> int:
        if args[3] == "sent":
            raise RuntimeError("sonuç yazımı hatası")
        return await real(self, *args, **kw)

    class Takeover(LiveBox):
        async def send(self, message: EmailMessage, *, idempotency_key: str | None = None) -> None:
            admin_conn.execute(
                "UPDATE notification_outbox SET not_before = now() + interval '20 minutes' WHERE id = %s",
                (outbox_id,),
            )
            await super().send(message, idempotency_key=idempotency_key)

    monkeypatch.setattr(NotificationDispatcher, "_close", broken)
    result = await make(worker_engine, sender=Takeover()).dispatch()
    # Kira başkasına geçtiği için beklenmeyen hata kaydı da ETKİSİZ: satır başkasının, değişmedi.
    current = state(admin_conn, outbox_id)
    assert result.get("errors") == 1 and (current["status"], current["attempts"]) == ("pending", 0)


async def test_digest_window_is_half_open_so_a_boundary_event_enters_only_one_digest(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    boundary = event(admin_conn, a)  # tam `tik - 24 sa` anında görüldü
    admin_conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:
        admin_conn.execute(
            "UPDATE alert_events SET first_seen_at = %s WHERE id = %s",
            (DIGEST_AT - timedelta(hours=24), boundary),
        )
    finally:
        admin_conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")
    # Önceki günün tikinin penceresi (tik - 48 sa, tik - 24 sa] olayı alır; bugünün (tik - 24 sa, tik] almaz.
    await make(worker_engine, now=DIGEST_AT).build_digests()
    assert digest_rows(admin_conn, a) == []
    previous = DIGEST_AT - timedelta(days=1)
    await make(worker_engine, now=previous).build_digests(at=previous)
    assert [r["alert_event_ids"] for r in digest_rows(admin_conn, a)] == [[boundary]]


# ===================================================================================== D-c: özet penceresi


async def test_the_digest_window_ends_at_the_tick_parameter_not_the_database_clock(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    inside = event(admin_conn, a)  # tikten 2 saat önce
    after = event(admin_conn, a)
    admin_conn.execute("ALTER TABLE alert_events DISABLE TRIGGER alert_events_immutable_guard")
    try:  # tikten SONRA görülen olay (pencerenin dışında): sonraki günün özetine kalır
        admin_conn.execute(
            "UPDATE alert_events SET first_seen_at = %s WHERE id = %s",
            (DIGEST_AT + timedelta(minutes=30), after),
        )
    finally:
        admin_conn.execute("ALTER TABLE alert_events ENABLE ALWAYS TRIGGER alert_events_immutable_guard")
    await make(worker_engine, now=DIGEST_AT).build_digests()
    assert digest_rows(admin_conn, a)[0]["alert_event_ids"] == [inside]
    # Ertesi gün aynı saatte tikin penceresi o olayı alır (kayıp ve çift yok).
    nextday = DIGEST_AT + timedelta(days=1)
    await make(worker_engine, now=nextday).build_digests(at=nextday)
    assert digest_rows(admin_conn, a)[-1]["alert_event_ids"] == [after]


# ===================================================================================== O1: yapısal güvence


async def test_a_non_local_dev_sender_is_rejected_by_the_constructor(worker_engine: AsyncEngine) -> None:
    with pytest.raises(NotificationConfigError, match="yerel"):
        make(worker_engine, enabled=False, dev=ExplodingSender())
    make(worker_engine, enabled=False, dev=InMemoryOutbox())  # yerel olan kabul


async def test_an_enabled_flag_needs_a_real_backend_never_a_local_one(
    worker_engine: AsyncEngine, tmp_path: Path
) -> None:
    for local in (InMemoryOutbox(), FileEmailSender(str(tmp_path / "o.jsonl"))):
        with pytest.raises(NotificationConfigError, match="gerçek"):
            make(worker_engine, enabled=True, sender=local)
    with pytest.raises(NotificationConfigError, match="gerçek"):
        NotificationDispatcher(
            worker_engine,
            sender=None,
            enabled=True,
            product_name="NetKâr",
            web_base_url="https://app.test.invalid",
            signer=UnsubscribeSigner(KEY),
        )
    make(worker_engine, enabled=True, sender=LiveBox())  # yerel olmayan gönderici kabul


async def test_from_settings_with_the_flag_off_never_calls_a_network_sender(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    settings: Any,
) -> None:
    a = world.a
    seed(admin_conn, a)
    network = ExplodingSender()
    dispatcher = NotificationDispatcher.from_settings(
        worker_engine, settings, live_sender=network, now=lambda: NOW
    )
    result = await dispatcher.dispatch()
    assert network.calls == 0 and result.get("suppressed") == 1 and result.get("errors") == 0
    assert isinstance(dispatcher._dev_sender, InMemoryOutbox) and len(dispatcher._dev_sender.messages) == 1


async def test_from_settings_rejects_an_enabled_flag_without_a_real_backend(
    worker_engine: AsyncEngine, settings: Any
) -> None:
    on = settings.model_copy(update={"alert_notifications_enabled": True})
    with pytest.raises(NotificationConfigError):
        NotificationDispatcher.from_settings(worker_engine, on)
    assert NotificationDispatcher.from_settings(worker_engine, on, live_sender=LiveBox())._enabled is True


# ===================================================================================== O3: zamanlanmış tik saati


async def test_a_late_tick_builds_the_digest_of_its_own_scheduled_hour(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    event(admin_conn, a)
    late_clock = datetime(2026, 10, 10, 9, 40, tzinfo=UTC)  # worker 12:40 İstanbul'da uyandı (saat 8 geçti)
    miss = await make(worker_engine, now=late_clock).build_digests()
    assert miss.get("digests") == 0  # tik zamanı verilmezse o saatin kullanıcıları kaçardı
    tick = datetime(2026, 10, 10, 5, 13, tzinfo=UTC)  # zamanlanmış tik: 08:13 İstanbul
    hit = await make(worker_engine, now=late_clock).build_digests(at=tick)
    assert hit.get("digests") == 2 and len(digest_rows(admin_conn, a)) == 1
    assert digest_rows(admin_conn, a)[0]["dedupe_key"] == digest_dedupe_key(a.user_id, tick.date(), 8)


# ===================================================================================== O5: üyelerden alıcı


async def test_digest_recipients_are_the_verified_members_with_role_based_defaults(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    event(admin_conn, a)  # hiç ayar ya da tercih satırı yok
    await make(worker_engine, now=DIGEST_AT).build_digests()
    got = {r["user_id"] for r in rows(admin_conn, a, "digest")}
    assert got == {a.user_id, world.admin_id}  # owner ve admin: günlük özet; viewer: e-posta varsayılanı off
    # viewer kendisi açarsa özet alır; doğrulanmamış üye ve üye olmayan alır olmaz.
    preference(admin_conn, a, world.viewer_id, LOSS, "digest")
    unverified = admin_conn.execute(
        "INSERT INTO users (email, password_hash) VALUES ('uye-dogrulanmamis@example.com', 'x') RETURNING id"
    ).fetchone()
    assert unverified is not None
    admin_conn.execute(
        "INSERT INTO memberships (user_id, tenant_id, role) VALUES (%s, %s, 'admin')",
        (unverified[0], a.tenant_id),
    )
    admin_conn.execute("DELETE FROM notification_outbox")
    await make(worker_engine, now=DIGEST_AT).build_digests()
    assert {r["user_id"] for r in rows(admin_conn, a, "digest")} == {
        a.user_id,
        world.admin_id,
        world.viewer_id,
    }


def test_the_digest_defaults_come_from_the_single_d6_function() -> None:
    from app.services.alert_api import default_matrix

    assert default_matrix("viewer")["ZARARINA_SATIS"]["email"] == "off"
    assert (
        default_matrix("owner")["ZARARINA_SATIS"]["email"]
        == default_matrix("admin")["IADE_ORANI_ARTISI"]["email"]
        == "digest"
    )


# ===================================================================================== D1: başlık kapsamı


async def test_unsubscribe_header_scope_follows_the_message_kind(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    user_settings(admin_conn, a, world.admin_id)
    user_settings(admin_conn, a, world.viewer_id)
    multi = {
        "rule_counts": {LOSS: 1, DEDUCTION: 1},
        "event_count": 2,
        "certainty": "kesin",
        LOSS: {"event_count": 1, "window_days": 7, "total_amount": "1.00"},
        DEDUCTION: {"event_count": 1, "window_days": 92, "total_amount": "2.00"},
    }
    seed(admin_conn, a, payload=multi)  # owner: çok kurallı anlık
    seed(admin_conn, a, user_id=world.admin_id, kind="digest")  # admin: özet
    seed(
        admin_conn, a, user_id=world.viewer_id, payload=payload_of(DEDUCTION, 1, "2.00")
    )  # viewer: tek kural
    box = LiveBox()
    await make(worker_engine, sender=box).dispatch()
    by_user = {m.to: m for m in box.messages}
    signer = UnsubscribeSigner(KEY)

    def header_rule(message: EmailMessage) -> str | None:
        raw = message.headers.get("List-Unsubscribe")
        claim = None if raw is None else signer.verify(raw.strip("<>").split("token=", 1)[1], NOW)
        return None if claim is None else claim.rule

    assert header_rule(by_user[email_of(admin_conn, a.user_id)]) is None  # çok kurallı anlık: başlık yok
    assert "List-Unsubscribe-Post" not in by_user[email_of(admin_conn, a.user_id)].headers
    assert (
        "Zararına satış: https://" in by_user[email_of(admin_conn, a.user_id)].body
    )  # gövde bağlantıları kalır
    assert header_rule(by_user[email_of(admin_conn, world.admin_id)]) == "*"  # özet: tümü
    assert header_rule(by_user[email_of(admin_conn, world.viewer_id)]) == DEDUCTION  # tek kural: yalnız o


def test_error_class_names_are_snake_case_without_message_text() -> None:
    assert error_class_name(EmailTransientError("x@example.com")) == "email_transient_error"
    assert error_class_name(TimeoutError()) == "timeout_error"
    assert error_class_name(ValueError("a@b.c")) == "value_error"

    class Weird123Error(Exception):
        pass

    assert error_class_name(Weird123Error()) == "weird_error"

    class A1(Exception):
        pass

    name = error_class_name(A1())
    assert name and set(name) <= set("abcdefghijklmnopqrstuvwxyz_") and len(name) <= 40


# ===================================================================================== log gizliliği


async def test_logs_carry_no_email_barcode_amount_or_order_number(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = world.a
    user_settings(admin_conn, a, digest_hour=8)
    address = email_of(admin_conn, a.user_id)
    product(admin_conn, a, "BC-LOG-1", "Gizli Ürün Adı")
    loss = event(admin_conn, a, subject="urun:BC-LOG-1", amount="987654.32")
    line = event(
        admin_conn, a, rule=DEDUCTION, scope="order_line", subject=f"satir:{ORDER_NO}|5001|1", amount="333.33"
    )
    seed(admin_conn, a, events=[loss, line], payload=payload_of(LOSS, 1, "987654.32"))
    seed(admin_conn, a, kind="digest", events=[line], payload=payload_of(DEDUCTION, 1, "333.33"))
    caplog.set_level(logging.DEBUG)
    await make(worker_engine, sender=FailingSender()).dispatch()  # hata yolu: metinde adres var
    await make(worker_engine, sender=LiveBox()).dispatch()
    await make(worker_engine, now=DIGEST_AT).build_digests()
    records = [r for r in caplog.records if r.name == "netkar.notify"]
    assert records, "dağıtıcı log yazmalı"
    blob = " ".join(f"{r.getMessage()} {r.__dict__}" for r in records)
    for secret in (
        address,
        address.split("@")[0],
        "BC-LOG-1",
        "Gizli Ürün",
        "987654",
        "333.33",
        ORDER_NO,
        "urun:",
        "satir:",
    ):
        assert secret not in blob
    assert {r.getMessage() for r in records} >= {
        "notify_dispatch_done",
        "notify_send_failed",
        "notify_digests_done",
    }


# ===================================================================================== sayaçlar ve kenar durumlar


async def test_counters_summary_is_sorted_and_json_safe(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    user_settings(admin_conn, a)
    seed(admin_conn, a)
    result = await make(worker_engine).dispatch()
    summary = result.summary()
    assert list(summary) == sorted(summary) and json.loads(json.dumps(summary)) == summary
    assert result.get("yok") == 0


async def test_dispatch_returns_quietly_when_nothing_is_due(worker_engine: AsyncEngine) -> None:
    assert (await make(worker_engine).dispatch()).counts == {}
    assert (await make(worker_engine).build_digests()).counts == {}


def test_amount_helpers_match_the_evaluator_payload_shape() -> None:
    from app.alerts import AlertRule
    from app.profit.enums import Certainty
    from app.services import alert_evaluation as ae
    from app.services.notify import _AMOUNT_KEYS, _Event, digest_payload

    # Özet yükü, D4 outbox yüküyle aynı anahtar kümesini kullanır (CHECK izin listesi).
    events = [
        _Event(
            UUID(int=1),
            UUID(int=9),
            LOSS,
            "high",
            {"certainty": "kesin", "evidence": {"total_loss": "10.00"}},
            4,
            2,
        ),
        _Event(UUID(int=2), UUID(int=9), RETURNS, "medium", {"certainty": "tahmini", "evidence": {}}, 5, 3),
    ]
    mine = digest_payload(events)
    key = ae.EvaluationKey(NOW.date(), 5, 3, 0)
    theirs = ae._outbox_payload(
        key,
        [
            ae.Notifiable(AlertRule.LOSS_MAKING_SALE, UUID(int=1), Decimal("10.00"), Certainty.CERTAIN),
            ae.Notifiable(AlertRule.RETURN_RATE_INCREASE, UUID(int=2), None, Certainty.ESTIMATED),
        ],
    )
    assert mine == theirs
    assert set(_AMOUNT_KEYS) == {LOSS, DEDUCTION, "REKLAM_KARI_YIYOR"}
