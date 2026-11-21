"""Uyarı değerlendirme işi (ADR-0009 D4): gerçek PostgreSQL, `netkar_worker` rolü, elle kurulmuş veri.

Kapsam: idempotentlik (aynı anahtarla ikinci çalıştırma yeni olay ya da outbox üretmez), açılış, güncelleme, çözülme,
yeniden açılma, bastırma (zarar 2 kat bir kez, sessiz yeniden açılma, susturma), outbox yazımı ve izin listeli yük,
sessiz saat, kiracı yalıtımı, işlem bütünlüğü (hata olursa kısmi yazım yok, `failed` kaydı), veri sürüm döngüsünün
olmaması, reklam verisi yokken uyarı üretilmemesi, kiracı eşik ezmesi, tetikleyiciler (senkron sonrası, ayar ve maliyet
yazımı, günlük) ve log'da kişisel veri olmaması. Saf yardımcılar (anahtar, sessiz saat, bastırma matrisi) ayrıca sınanır.

Dosya adı bilerek `test_alerts_*` değildir: `make test-alerts` (DB'siz, saf kural kapsamı) bunu toplamaz.
Değerlendirme günü `NOW` = 2026-10-10 12:00 UTC (İstanbul 15:00). Zarar satırı 2026-10-06'dadır (7 günlük pencerede).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import procrastinate
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from procrastinate import testing
from psycopg.types.json import Jsonb
from sqlalchemy.ext.asyncio import AsyncEngine

from app.alerts import AlertCandidate, AlertRule, AlertScope, NotifyMode, Severity
from app.core.config import Settings
from app.db.rls import tenant_transaction as real_tenant_transaction
from app.profit.enums import Certainty
from app.services import alert_evaluation as ae
from app.services.alert_evaluation import (
    AlertEvaluationFailed,
    AlertEvaluationTransient,
    AlertEvaluator,
    EvaluationKey,
    ExistingEvent,
    composite_settings_revision,
    decide_notification,
    is_transient,
    quiet_until,
    thresholds_digest,
)
from app.services.profit_report import period_profit as real_period_profit
from app.services.sync.runner import SourceOutcome, SyncOutcome
from app.worker.queue import defer_alert_evaluation, defer_backfill, request_alert_evaluation
from app.worker.runtime import WorkerRuntime
from app.worker.tasks import (
    CRON_ALERTS_DAILY,
    CRON_ALERTS_RECOVER,
    defer_alerts_after_sync,
    plan_alert_evaluations,
    recover_stalled_alerts,
    register_tasks,
)
from tests.conftest import Api, DatabaseInfo, RecordingJobQueue
from tests.product_cost_helpers import B1, B2, Shop, csv_bytes, fixed_today, make_shop_factory, upload  # noqa: F401
from tests.report_helpers import add_cost
from tests.sync_fixtures import full_api
from tests.sync_helpers import Seller, client_factory, make_seller
from tests.test_alert_cohort import add_line as add_cohort_line
from tests.test_alert_schema import (
    World,
    immutable_guard_disabled,
    make_world,
    role_tx,
    transition,
)
from tests.test_feed_database import add_order

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
ORDERED = datetime(2026, 10, 6, 9, 0, tzinfo=UTC)
DIGEST = "ab" * 32
EVALUATION_KEYS = {
    "opened",
    "updated",
    "resolved",
    "reopened",
    "notified",
    "outbox_rows",
    "candidates",
    "rules_evaluated",
    "rules_no_data",
    "duration_ms",
    "dropped",
    "rule_counts",
}


# ---- yardımcılar ---------------------------------------------------------------------------------------------------


def mark_synced(conn: psycopg.Connection[Any], seller: Seller) -> None:
    """Tüm kaynakların yedeklemesi tamam (bildirim kapısı açık); aksi halde olay açılır ama outbox yazılmaz."""
    for source in ("orders", "claims", "products", "settlements", "other_financials", "cargo_invoices"):
        conn.execute(
            "INSERT INTO sync_cursors (tenant_id, marketplace_account_id, source, watermark, "
            "backfill_completed_at) VALUES (%s, %s, %s, now(), now())",
            (seller.tenant_id, seller.account_id, source),
        )


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    world = make_world(admin_conn)
    mark_synced(admin_conn, world.a)
    mark_synced(admin_conn, world.b)
    return world


def evaluator(engine: AsyncEngine, now: datetime = NOW) -> AlertEvaluator:
    return AlertEvaluator(engine, now=lambda: now)


def add_loss_sale(
    conn: psycopg.Connection[Any],
    seller: Seller,
    barcode: str = B1,
    *,
    order_no: str = "5001",
    package: int = 5001,
    line: int = 1,
    cost: str | None = "500.00",
    ordered: datetime = ORDERED,
) -> None:
    """100 TL brüt satış; maliyet 500 TL olduğundan iade etkisi olmayan zarar satırı (ZARAR uyarısı)."""
    conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title, vat_rate) "
        "VALUES (%s, %s, %s, 'Ürün', 20) ON CONFLICT DO NOTHING",
        (seller.tenant_id, seller.account_id, barcode),
    )
    if cost is not None:
        add_cost(conn, seller, barcode, cost)  # type: ignore[arg-type]
    add_order(
        conn,
        seller,
        order_no,
        package,
        ordered,
        lines=[{"line_id": line, "barcode": barcode, "gross": "100.00"}],
    )


def set_cost(conn: psycopg.Connection[Any], seller: Seller, cost: str) -> None:
    conn.execute(
        "UPDATE product_costs SET unit_cost_excl_vat = %s WHERE marketplace_account_id = %s",
        (cost, seller.account_id),
    )


def add_push(
    conn: psycopg.Connection[Any], seller: Seller, user_id: UUID | None = None, digest: str = DIGEST
) -> None:
    conn.execute(
        "INSERT INTO push_subscriptions (tenant_id, user_id, endpoint_host, endpoint_digest, endpoint_enc, "
        "p256dh_enc, auth_enc, vapid_key_id) VALUES (%s, %s, 'fcm.googleapis.com', %s, 'e', 'p', 'a', 'k1')",
        (seller.tenant_id, user_id or seller.user_id, digest),
    )


def set_preference(
    conn: psycopg.Connection[Any], seller: Seller, user_id: UUID, rule: str, channel: str, mode: str
) -> None:
    conn.execute(
        "INSERT INTO notification_preferences (tenant_id, user_id, rule, channel, mode) VALUES (%s, %s, %s, %s, %s)",
        (seller.tenant_id, user_id, rule, channel, mode),
    )


def events(conn: psycopg.Connection[Any], seller: Seller, rule: str | None = None) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, rule, subject, status, occurrence_count, severity, payload, data_revision, settings_revision, "
        "last_notified_at, notified_amount, renotified, notify_mode, resolved_at FROM alert_events "
        "WHERE marketplace_account_id = %s AND (%s::text IS NULL OR rule = %s) ORDER BY subject",
        (seller.account_id, rule, rule),
    )
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def outbox(conn: psycopg.Connection[Any], seller: Seller) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, user_id, channel, kind, status, not_before, alert_event_ids, payload, dedupe_key "
        "FROM notification_outbox WHERE tenant_id = %s ORDER BY channel, user_id",
        (seller.tenant_id,),
    )
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def evaluations(conn: psycopg.Connection[Any], seller: Seller) -> list[dict[str, Any]]:
    cur = conn.execute(
        "SELECT id, as_of_date, data_revision, settings_revision, rules_version, status, counts, finished_at, attempt "
        "FROM alert_evaluations WHERE marketplace_account_id = %s ORDER BY started_at",
        (seller.account_id,),
    )
    names = [d.name for d in cur.description or ()]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def table_counts(conn: psycopg.Connection[Any], seller: Seller) -> tuple[int, int, int, int]:
    def count(table: str) -> int:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        return int(row[0])

    return (
        count("alert_events"),
        count("alert_event_transitions"),
        count("notification_outbox"),
        count("alert_evaluations"),
    )


def data_revision(conn: psycopg.Connection[Any], seller: Seller) -> int:
    row = conn.execute(
        "SELECT revision FROM report_data_revisions WHERE marketplace_account_id = %s", (seller.account_id,)
    ).fetchone()
    return 0 if row is None else int(row[0])


def transitions_of(conn: psycopg.Connection[Any], event_id: UUID) -> list[tuple[str, str, str]]:
    return [
        (r[0], r[1], r[2])
        for r in conn.execute(
            "SELECT from_status, to_status, actor FROM alert_event_transitions WHERE alert_event_id = %s "
            "ORDER BY created_at, id",
            (event_id,),
        )
    ]


# ===================================================================================== saf yardımcılar


def test_composite_settings_revision_packs_both_parts_without_collision() -> None:
    assert composite_settings_revision(0, 0) == 0
    assert composite_settings_revision(1, 0) == 2**31
    assert composite_settings_revision(3, 5) == (3 << 31) + 5
    assert composite_settings_revision(2, 2**31 - 1) < composite_settings_revision(3, 0)
    for profit, digest in ((-1, 0), (0, -1), (0, 2**31)):
        with pytest.raises(ValueError, match="aralık"):
            composite_settings_revision(profit, digest)
    assert EvaluationKey(NOW.date(), 7, 3, 5).stored_settings_revision == (3 << 31) + 5


def test_thresholds_digest_is_content_based_and_zero_without_a_row() -> None:
    base = {"loss_min_amount": Decimal("5.00"), "ad_min_spend": Decimal("50.00")}
    assert thresholds_digest(None, None) == 0
    one = thresholds_digest(base, ["A", "B"])
    assert one == thresholds_digest(dict(reversed(base.items())), ["B", "A"])  # sıra ve kopya fark etmez
    assert 0 <= one < 2**31
    assert one != thresholds_digest({**base, "loss_min_amount": Decimal("6.00")}, ["A", "B"])
    assert one != thresholds_digest(base, ["A"])
    assert thresholds_digest({}, None) == thresholds_digest({}, None)


def test_quiet_until_handles_overnight_same_day_and_empty_windows() -> None:
    night = (time(22, 0), time(8, 0))
    # İstanbul UTC+3: 20:00Z = 23:00 (içeride), 04:00Z = 07:00 (içeride), 05:00Z = 08:00 (dışarıda), 12:00Z = 15:00.
    assert quiet_until(datetime(2026, 10, 10, 20, 0, tzinfo=UTC), *night) == datetime(
        2026, 10, 11, 5, 0, tzinfo=UTC
    )
    assert quiet_until(datetime(2026, 10, 10, 4, 0, tzinfo=UTC), *night) == datetime(
        2026, 10, 10, 5, 0, tzinfo=UTC
    )
    assert quiet_until(datetime(2026, 10, 10, 19, 0, tzinfo=UTC), *night) == datetime(
        2026, 10, 11, 5, 0, tzinfo=UTC
    )
    assert quiet_until(datetime(2026, 10, 10, 5, 0, tzinfo=UTC), *night) is None
    assert quiet_until(NOW, *night) is None
    day = (time(13, 0), time(15, 0))
    assert quiet_until(datetime(2026, 10, 10, 11, 0, tzinfo=UTC), *day) == datetime(
        2026, 10, 10, 12, 0, tzinfo=UTC
    )
    assert quiet_until(datetime(2026, 10, 10, 13, 0, tzinfo=UTC), *day) is None
    assert quiet_until(NOW, time(9, 0), time(9, 0)) is None


def candidate(
    rule: AlertRule,
    evidence: dict[str, Any],
    notify: NotifyMode = NotifyMode.NORMAL,
    certainty: Certainty = Certainty.CERTAIN,
) -> AlertCandidate:
    scope = AlertScope.ORDER_LINE if rule is AlertRule.UNEXPECTED_DEDUCTION else AlertScope.PRODUCT
    return AlertCandidate(
        rule=rule,
        scope=scope,
        subject="urun:X",
        dedupe_key=DIGEST,
        severity=Severity.HIGH,
        certainty=certainty,
        notify=notify,
        evidence=evidence,
    )


def existing(
    rule: AlertRule,
    status: str = "open",
    *,
    notified: str | None = None,
    renotified: bool = False,
    last: datetime | None = None,
    resolved_at: datetime | None = None,
    muted_until: datetime | None = None,
) -> ExistingEvent:
    return ExistingEvent(
        uuid4(),
        DIGEST,
        rule.value,
        status,
        muted_until,
        resolved_at,
        last,
        None if notified is None else Decimal(notified),
        renotified,
    )


LOSS = AlertRule.LOSS_MAKING_SALE


def loss(total: str, **kw: Any) -> AlertCandidate:
    return candidate(LOSS, {"total_loss": Decimal(total)}, **kw)


def test_loss_notification_is_first_once_then_doubling_exactly_once() -> None:
    first = decide_notification(loss("100.00"), None, NOW, None)
    assert first == ae.NotifyDecision(True, NOW, Decimal("100.00"), False)
    open_event = existing(LOSS, notified="100.00", last=NOW)
    assert not decide_notification(loss("199.99"), open_event, NOW, None).notify  # 1,9 kat: yok
    doubled = decide_notification(loss("200.00"), open_event, NOW, None)
    assert doubled == ae.NotifyDecision(True, NOW, Decimal("200.00"), True)
    done = existing(LOSS, notified="200.00", renotified=True, last=NOW)
    again = decide_notification(loss("900.00"), done, NOW, None)  # 4 kat, 8 kat için ek bildirim yok
    assert again == ae.NotifyDecision(False, NOW, Decimal("200.00"), True)


def test_loss_reopen_is_silent_within_seven_days_and_fresh_afterwards() -> None:
    resolved = existing(LOSS, "resolved", notified="100.00", renotified=True, last=NOW, resolved_at=NOW)
    assert not decide_notification(loss("100.00"), resolved, NOW + timedelta(days=6), "resolved").notify
    later = decide_notification(loss("100.00"), resolved, NOW + timedelta(days=8), "resolved")
    # 7 günden sonra yeniden açılan olay yeni olay gibidir: ilk bildirim, yeniden bildirim bayrağı sıfırlanır.
    assert later == ae.NotifyDecision(True, NOW + timedelta(days=8), Decimal("100.00"), False)


def test_other_rules_follow_their_own_noise_policy() -> None:
    ad = candidate(AlertRule.AD_EATS_PROFIT, {"ad_spend": Decimal("80.00")})
    assert decide_notification(ad, None, NOW, None).notify
    recent = existing(AlertRule.AD_EATS_PROFIT, last=NOW)
    assert not decide_notification(ad, recent, NOW + timedelta(days=13), None).notify
    assert decide_notification(ad, recent, NOW + timedelta(days=14), None).notify
    returns = candidate(AlertRule.RETURN_RATE_INCREASE, {})
    assert decide_notification(returns, None, NOW, None).notify
    assert not decide_notification(
        returns, existing(AlertRule.RETURN_RATE_INCREASE, last=NOW), NOW, None
    ).notify
    deduction = candidate(AlertRule.UNEXPECTED_DEDUCTION, {"difference": Decimal("20.00")})
    assert decide_notification(deduction, None, NOW, None).notify
    seen = existing(AlertRule.UNEXPECTED_DEDUCTION, last=NOW)
    assert not decide_notification(
        deduction, seen, NOW + timedelta(days=400), None
    ).notify  # aynı satır bir kez
    never = existing(AlertRule.UNEXPECTED_DEDUCTION)  # özetteyken sonradan eşiği geçti
    assert decide_notification(deduction, never, NOW, None).notify


def test_digest_only_none_and_muted_events_never_notify() -> None:
    for mode in (NotifyMode.DIGEST_ONLY, NotifyMode.NONE):
        assert not decide_notification(loss("100.00", notify=mode), None, NOW, None).notify
    muted = existing(LOSS, "muted", muted_until=NOW + timedelta(days=1))
    assert not decide_notification(loss("100.00"), muted, NOW, None).notify
    expired = existing(LOSS, "muted", muted_until=NOW - timedelta(days=1))
    assert not decide_notification(
        loss("100.00"), expired, NOW, "muted"
    ).notify  # susturma bitti: yalnız panel


def test_event_and_outbox_payloads_use_text_amounts_and_no_personal_fields() -> None:
    cand = loss("12.50")
    assert ae.event_payload(cand) == {"certainty": "kesin", "evidence": {"total_loss": "12.50"}}
    assert ae.candidate_amount(cand) == Decimal("12.50")
    assert ae.candidate_amount(candidate(AlertRule.RETURN_RATE_INCREASE, {})) is None
    key = EvaluationKey(NOW.date(), 4, 2, 0)
    chosen = [
        ae.Notifiable(LOSS, uuid4(), Decimal("10.00"), Certainty.CERTAIN),
        ae.Notifiable(LOSS, uuid4(), Decimal("2.50"), Certainty.ESTIMATED),
        ae.Notifiable(AlertRule.RETURN_RATE_INCREASE, uuid4(), None, Certainty.ESTIMATED),
    ]
    payload = ae._outbox_payload(key, chosen)
    assert payload["rule_counts"] == {"ZARARINA_SATIS": 2, "IADE_ORANI_ARTISI": 1}
    assert payload["event_count"] == 3 and payload["certainty"] == "tahmini"
    assert payload["ZARARINA_SATIS"] == {"event_count": 2, "window_days": 7, "total_amount": "12.50"}
    assert payload["IADE_ORANI_ARTISI"] == {"event_count": 1, "window_days": 28}
    assert (payload["data_revision"], payload["settings_revision"]) == (4, 2)


# ===================================================================================== değerlendirme (gerçek DB)


async def test_first_run_opens_the_event_writes_outbox_rows_and_second_run_writes_nothing(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    set_preference(admin_conn, a, world.admin_id, "ZARARINA_SATIS", "email", "instant")
    ev = evaluator(worker_engine)

    first = await ev.evaluate(a.account_id)

    assert first.status == "succeeded"
    (event,) = events(admin_conn, a)
    assert (event["rule"], event["subject"], event["status"], event["occurrence_count"]) == (
        "ZARARINA_SATIS",
        f"urun:{B1}",
        "open",
        1,
    )
    assert event["severity"] == "high" and event["notify_mode"] == "normal" and not event["renotified"]
    assert event["notified_amount"] == Decimal("425.00") and event["last_notified_at"] == NOW
    assert event["payload"]["certainty"] == "tahmini"
    assert event["payload"]["evidence"]["total_loss"] == "425.00"
    assert event["data_revision"] == data_revision(admin_conn, a) and event["settings_revision"] == 0
    rows = outbox(admin_conn, a)
    assert [(r["channel"], r["user_id"], r["kind"], r["status"]) for r in rows] == [
        ("email", world.admin_id, "instant", "pending"),
        ("push", a.user_id, "instant", "pending"),
    ]
    for row in rows:
        assert row["alert_event_ids"] == [event["id"]] and row["not_before"] == NOW
        assert row["payload"]["rule_counts"] == {"ZARARINA_SATIS": 1}
        assert row["payload"]["ZARARINA_SATIS"] == {
            "event_count": 1,
            "window_days": 7,
            "total_amount": "425.00",
        }
        assert (
            row["payload"]["data_revision"] == event["data_revision"]
            and row["payload"]["certainty"] == "tahmini"
        )
    (evaluation,) = evaluations(admin_conn, a)
    assert evaluation["status"] == "succeeded" and evaluation["finished_at"] is not None
    assert evaluation["as_of_date"] == NOW.date() and evaluation["rules_version"] == 1
    counts = evaluation["counts"]
    assert set(counts) <= EVALUATION_KEYS
    assert (counts["opened"], counts["notified"], counts["outbox_rows"], counts["candidates"]) == (1, 1, 2, 1)
    assert (
        counts["rules_evaluated"] == 2 and counts["rules_no_data"] == 2
    )  # reklam (veri yok) ve iade (kohort yok)
    assert counts["rule_counts"] == {"ZARARINA_SATIS": 1, "BEKLENMEYEN_KESINTI": 0}
    assert table_counts(admin_conn, a) == (1, 0, 2, 1)

    second = await ev.evaluate(a.account_id)  # aynı gün, aynı veri sürümü, aynı ayar sürümü

    assert second.status == "skipped"
    assert table_counts(admin_conn, a) == (1, 0, 2, 1)
    assert events(admin_conn, a)[0]["occurrence_count"] == 1
    assert [r["id"] for r in outbox(admin_conn, a)] == [r["id"] for r in rows]


async def test_event_lifecycle_update_renotify_once_resolve_and_silent_reopen(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    ev = evaluator(worker_engine)
    assert (await ev.evaluate(a.account_id)).counts["opened"] == 1
    assert len(outbox(admin_conn, a)) == 1

    # Zarar 2 katını aştı: GÜNCELLEME ve yalnız bir kez daha bildirim.
    set_cost(admin_conn, a, "1000.00")
    out = await ev.evaluate(a.account_id)
    assert (out.counts["updated"], out.counts["opened"], out.counts["notified"]) == (1, 0, 1)
    (event,) = events(admin_conn, a)
    assert event["occurrence_count"] == 2 and event["renotified"] is True
    assert event["notified_amount"] == Decimal(event["payload"]["evidence"]["total_loss"]) > Decimal("850.00")
    assert len(outbox(admin_conn, a)) == 2

    # 4 kat, 8 kat için ek bildirim yok.
    set_cost(admin_conn, a, "5000.00")
    out = await ev.evaluate(a.account_id)
    assert (out.counts["updated"], out.counts["notified"], out.counts["outbox_rows"]) == (1, 0, 0)
    assert events(admin_conn, a)[0]["occurrence_count"] == 3 and len(outbox(admin_conn, a)) == 2

    # Koşul kalktı: ÇÖZÜLDÜ (geçiş yalnız defter satırıyla, sistem aktörü).
    set_cost(admin_conn, a, "10.00")
    out = await ev.evaluate(a.account_id)
    assert (out.counts["resolved"], out.counts["updated"], out.counts["candidates"]) == (1, 0, 0)
    (event,) = events(admin_conn, a)
    assert event["status"] == "resolved" and event["resolved_at"] is not None
    assert transitions_of(admin_conn, event["id"]) == [("open", "resolved", "system")]

    # Yeniden görüldü: YENİDEN AÇILDI; 7 gün içinde olduğundan bildirim gitmez (yalnız panel).
    set_cost(admin_conn, a, "500.00")
    out = await ev.evaluate(a.account_id)
    assert (out.counts["reopened"], out.counts["opened"], out.counts["notified"]) == (1, 0, 0)
    (event,) = events(admin_conn, a)
    assert event["status"] == "open" and event["resolved_at"] is None
    assert transitions_of(admin_conn, event["id"]) == [
        ("open", "resolved", "system"),
        ("resolved", "open", "system"),
    ]
    assert len(outbox(admin_conn, a)) == 2
    assert [e["status"] for e in evaluations(admin_conn, a)] == ["succeeded"] * 5


async def test_muted_event_stays_muted_expires_to_open_silently_and_resolves_when_cleared(
    database: DatabaseInfo, world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    ev = evaluator(worker_engine)
    await ev.evaluate(a.account_id)
    event_id = events(admin_conn, a)[0]["id"]
    until = datetime.now(UTC) + timedelta(days=30)
    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "muted", until)

    set_cost(admin_conn, a, "1000.00")  # zarar 2 katını aşsa da susturulmuş olay bildirim üretmez
    out = await ev.evaluate(a.account_id)
    assert (out.counts["updated"], out.counts["notified"], out.counts["reopened"]) == (1, 0, 0)
    (event,) = events(admin_conn, a)
    assert event["status"] == "muted" and event["renotified"] is False and event["occurrence_count"] == 2
    assert len(outbox(admin_conn, a)) == 1

    with immutable_guard_disabled(admin_conn):
        admin_conn.execute("UPDATE alert_events SET muted_until = now() - interval '1 hour'")
    set_cost(admin_conn, a, "3000.00")
    out = await ev.evaluate(a.account_id)  # süre doldu: sistem yeniden açar, bildirim yok
    assert (out.counts["reopened"], out.counts["notified"]) == (1, 0)
    assert events(admin_conn, a)[0]["status"] == "open" and len(outbox(admin_conn, a)) == 1
    assert transitions_of(admin_conn, event_id)[-1] == ("muted", "open", "system")

    with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
        transition(conn, a, event_id, "muted", datetime.now(UTC) + timedelta(days=5))
    set_cost(admin_conn, a, "10.00")  # koşul kalktı: susturulmuş olay da çözülür
    out = await ev.evaluate(a.account_id)
    assert out.counts["resolved"] == 1 and events(admin_conn, a)[0]["status"] == "resolved"
    assert transitions_of(admin_conn, event_id)[-1] == ("muted", "resolved", "system")


async def test_quiet_hours_hold_the_outbox_row_until_the_window_ends(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    night = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)  # İstanbul 23:00: varsayılan sessiz saat (22:00-08:00)
    await evaluator(worker_engine, night).evaluate(a.account_id)
    (row,) = outbox(admin_conn, a)
    assert row["status"] == "held" and row["not_before"] == datetime(2026, 10, 11, 5, 0, tzinfo=UTC)


async def test_user_quiet_hours_setting_overrides_the_default_window(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    # NOW = İstanbul 15:00; kullanıcı 14:00-16:00 sessiz saat seçmiş: tutulur, 16:00 İstanbul = 13:00 UTC.
    admin_conn.execute(
        "INSERT INTO notification_settings (tenant_id, user_id, quiet_start, quiet_end) VALUES (%s, %s, '14:00', '16:00')",
        (a.tenant_id, a.user_id),
    )
    await evaluator(worker_engine).evaluate(a.account_id)
    (row,) = outbox(admin_conn, a)
    assert row["status"] == "held" and row["not_before"] == datetime(2026, 10, 10, 13, 0, tzinfo=UTC)


async def test_explicit_preferences_override_the_default_matrix(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    add_push(admin_conn, a, world.admin_id, "cd" * 32)
    set_preference(admin_conn, a, a.user_id, "ZARARINA_SATIS", "push", "off")  # varsayılan anlık, kapatılmış
    set_preference(admin_conn, a, world.admin_id, "ZARARINA_SATIS", "push", "digest")  # özet: anlık satır yok
    set_preference(admin_conn, a, world.viewer_id, "ZARARINA_SATIS", "email", "digest")
    await evaluator(worker_engine).evaluate(a.account_id)
    assert outbox(admin_conn, a) == []
    assert evaluations(admin_conn, a)[0]["counts"]["notified"] == 1  # olay bildirime uygun, alıcı seçmedi


async def test_tenant_threshold_override_changes_the_key_and_resolves_below_the_threshold(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    ev = evaluator(worker_engine)
    await ev.evaluate(a.account_id)
    assert events(admin_conn, a)[0]["status"] == "open"

    admin_conn.execute(
        "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, loss_min_amount, updated_by) "
        "VALUES (%s, %s, 10000.00, %s)",
        (a.tenant_id, a.account_id, a.user_id),
    )
    out = await ev.evaluate(a.account_id)  # veri ve gün aynı; eşik özeti anahtarı değiştirdi
    assert out.status == "succeeded" and (out.counts["resolved"], out.counts["candidates"]) == (1, 0)
    assert events(admin_conn, a)[0]["status"] == "resolved"
    first, second = evaluations(admin_conn, a)
    assert first["data_revision"] == second["data_revision"] and first["settings_revision"] == 0
    assert (
        second["settings_revision"] > 0 and second["settings_revision"] < 2**31
    )  # K44 sürümü 0, yalnız özet
    assert events(admin_conn, a)[0]["settings_revision"] == 0  # olay damgası yalnız K44 sürümüdür
    assert (await ev.evaluate(a.account_id)).status == "skipped"  # içerik aynı: yeniden değerlendirme yok


async def test_rules_enabled_limits_which_rules_run(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    admin_conn.execute(
        "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, rules_enabled, updated_by) "
        "VALUES (%s, %s, ARRAY['BEKLENMEYEN_KESINTI']::text[], %s)",
        (a.tenant_id, a.account_id, a.user_id),
    )
    calls: list[int] = []
    real = real_period_profit

    async def spy(db: Any, tenant: Any, account: Any, start: Any, end: Any, *rest: Any, **kw: Any) -> Any:
        calls.append((end - start).days + 1)
        return await real(db, tenant, account, start, end, *rest, **kw)

    monkeypatch.setattr("app.services.alert_evaluation.period_profit", spy)
    out = await evaluator(worker_engine).evaluate(a.account_id)
    assert events(admin_conn, a) == [] and calls == [92]  # zarar kuralı kapalı: 7 günlük motor çalışmaz
    assert out.counts["rules_evaluated"] == 1 and out.counts["rule_counts"] == {"BEKLENMEYEN_KESINTI": 0}


async def test_no_ad_data_means_no_ad_alert_and_no_30_day_engine_run(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    periods: list[int] = []
    real = real_period_profit

    async def spy(db: Any, tenant: Any, account: Any, start: Any, end: Any, *rest: Any, **kw: Any) -> Any:
        periods.append((end - start).days + 1)
        return await real(db, tenant, account, start, end, *rest, **kw)

    monkeypatch.setattr("app.services.alert_evaluation.period_profit", spy)
    out = await evaluator(worker_engine).evaluate(a.account_id)
    assert events(admin_conn, a, "REKLAM_KARI_YIYOR") == []
    assert periods == [7, 92]
    assert "REKLAM_KARI_YIYOR" not in out.counts["rule_counts"] and out.counts["rules_no_data"] == 2


async def test_tenants_are_isolated_and_a_foreign_push_subscription_is_never_used(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a, b = world.a, world.b
    add_loss_sale(admin_conn, a)
    add_loss_sale(admin_conn, b, B2, order_no="6001", package=6001)
    add_push(admin_conn, a)
    add_push(admin_conn, b)
    ev = evaluator(worker_engine)

    await ev.evaluate(a.account_id)

    assert [e["subject"] for e in events(admin_conn, a)] == [f"urun:{B1}"]
    assert events(admin_conn, b) == [] and outbox(admin_conn, b) == [] and evaluations(admin_conn, b) == []
    assert [r["user_id"] for r in outbox(admin_conn, a)] == [a.user_id]
    tenants = admin_conn.execute("SELECT DISTINCT tenant_id FROM alert_events").fetchall()
    assert tenants == [(a.tenant_id,)]

    await ev.evaluate(b.account_id)
    assert [e["subject"] for e in events(admin_conn, b)] == [f"urun:{B2}"]
    assert [r["user_id"] for r in outbox(admin_conn, b)] == [b.user_id]
    assert [e["subject"] for e in events(admin_conn, a)] == [f"urun:{B1}"]  # A etkilenmedi
    assert len(outbox(admin_conn, a)) == 1 and len(evaluations(admin_conn, a)) == 1


async def test_failure_rolls_back_every_write_and_records_a_failed_evaluation(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)

    async def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("gizli-ayrinti-9f3")  # olaylar yazıldıktan SONRA düşer

    monkeypatch.setattr(ae, "_write_outbox", boom)
    caplog.set_level(logging.INFO, logger="netkar.alerts")
    with pytest.raises(AlertEvaluationFailed):
        await evaluator(worker_engine).evaluate(a.account_id)

    assert events(admin_conn, a) == [] and outbox(admin_conn, a) == []
    assert table_counts(admin_conn, a)[:3] == (0, 0, 0)
    (failed,) = evaluations(admin_conn, a)
    assert failed["status"] == "failed" and failed["finished_at"] is not None
    assert set(failed["counts"]) == {"duration_ms"}
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "alert_evaluation_failed" in text and "RuntimeError" in text and "gizli-ayrinti-9f3" not in text

    assert failed["counts"].keys() == {"duration_ms"} and failed["attempt"] == 1
    monkeypatch.undo()
    # `failed` anahtar yeniden denenir (attempt 2); başarılı olunca anahtar kapanır.
    retried = await evaluator(worker_engine).evaluate(a.account_id)
    assert retried.status == "succeeded"
    assert [(e["status"], e["attempt"]) for e in evaluations(admin_conn, a)] == [
        ("failed", 1),
        ("succeeded", 2),
    ]
    assert len(events(admin_conn, a)) == 1 and len(outbox(admin_conn, a)) == 1
    again = await evaluator(worker_engine).evaluate(a.account_id)
    assert (again.status, again.reason) == ("skipped", "completed")


async def test_three_failed_attempts_exhaust_the_key_until_the_data_changes(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)

    async def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("x")

    monkeypatch.setattr(ae, "_write_outbox", boom)
    for _ in range(3):
        with pytest.raises(AlertEvaluationFailed):
            await evaluator(worker_engine).evaluate(a.account_id)
    assert [(e["status"], e["attempt"]) for e in evaluations(admin_conn, a)] == [
        ("failed", n) for n in (1, 2, 3)
    ]
    monkeypatch.undo()
    out = await evaluator(worker_engine).evaluate(a.account_id)
    assert (out.status, out.reason) == ("skipped", "exhausted") and events(admin_conn, a) == []
    set_cost(admin_conn, a, "600.00")  # yeni veri sürümü yeni anahtardır
    assert (await evaluator(worker_engine).evaluate(a.account_id)).status == "succeeded"


def test_transient_classification_covers_operational_errors_and_retryable_sqlstates() -> None:
    from sqlalchemy import exc as sa_exc
    from sqlalchemy.exc import DBAPIError, OperationalError

    assert is_transient(psycopg.OperationalError("x"))
    assert is_transient(OperationalError("s", {}, psycopg.OperationalError("x")))
    assert is_transient(psycopg.errors.SerializationFailure("x"))
    assert is_transient(DBAPIError("s", {}, psycopg.errors.DeadlockDetected("x")))
    assert is_transient(sa_exc.TimeoutError("havuz"))  # bağlantı havuzu zaman aşımı
    assert not is_transient(psycopg.errors.CheckViolation("x"))
    assert not is_transient(RuntimeError("x"))


async def test_failure_before_the_key_is_known_leaves_no_evaluation_row(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("okuma hatası")

    monkeypatch.setattr(ae, "load_profit_settings", broken)
    with pytest.raises(AlertEvaluationFailed) as raised:
        await evaluator(worker_engine).evaluate(world.a.account_id)
    assert raised.value.error_class == "ConnectionError" and not isinstance(
        raised.value, AlertEvaluationTransient
    )
    assert table_counts(admin_conn, world.a) == (0, 0, 0, 0)


async def test_unrecordable_failure_is_logged_and_the_original_error_still_propagates(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    add_loss_sale(admin_conn, world.a)

    async def boom(*args: Any, **kwargs: Any) -> int:
        raise RuntimeError("asıl hata")

    def broken_transaction(*args: Any, **kwargs: Any) -> Any:
        raise OSError("kayıt da düştü")

    real = real_tenant_transaction
    state = {"calls": 0}

    def flaky(sessions: Any, tenant: UUID) -> Any:
        state["calls"] += 1
        return real(sessions, tenant) if state["calls"] == 1 else broken_transaction()

    monkeypatch.setattr(ae, "_write_outbox", boom)
    monkeypatch.setattr("app.services.alert_evaluation.tenant_transaction", flaky)
    caplog.set_level(logging.ERROR, logger="netkar.alerts")
    with pytest.raises(AlertEvaluationFailed, match="RuntimeError") as raised:
        await evaluator(worker_engine).evaluate(world.a.account_id)
    assert "asıl hata" not in str(raised.value) and raised.value.__cause__ is None
    assert "alert_evaluation_failure_not_recorded" in caplog.text
    assert table_counts(admin_conn, world.a) == (0, 0, 0, 0)


async def test_evaluation_never_bumps_the_data_revision_so_there_is_no_loop(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_push(admin_conn, a)
    before = data_revision(admin_conn, a)
    ev = evaluator(worker_engine)
    first = await ev.evaluate(a.account_id)
    set_cost(admin_conn, a, "1000.00")
    mid = data_revision(admin_conn, a)
    await ev.evaluate(a.account_id)  # olay güncellemesi, geçişler ve outbox yazıldı
    assert first.status == "succeeded" and mid == before + 1
    assert data_revision(admin_conn, a) == mid  # alarm tabloları sayacı artırmadı
    assert (
        await ev.evaluate(a.account_id)
    ).status == "skipped"  # kendi yazımı yeni değerlendirme tetiklemedi
    assert len(evaluations(admin_conn, a)) == 2 and data_revision(admin_conn, a) == mid


async def test_daily_new_event_cap_drops_the_excess_and_warns(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    add_loss_sale(admin_conn, a, B2, order_no="5002", package=5002, line=2, cost=None)
    add_cost(admin_conn, a, B2, "500.00")  # type: ignore[arg-type]
    monkeypatch.setattr(ae, "MAX_NEW_EVENTS_PER_DAY", 1)
    caplog.set_level(logging.WARNING, logger="netkar.alerts")
    out = await evaluator(worker_engine).evaluate(a.account_id)
    assert out.counts["opened"] == 1 and out.counts["candidates"] == 2 and len(events(admin_conn, a)) == 1
    assert "alert_event_cap_reached" in caplog.text


async def test_revoked_account_is_inactive_and_writes_nothing(
    admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    seller = make_seller(admin_conn, status="revoked")
    out = await evaluator(worker_engine).evaluate(seller.account_id)
    assert out.status == "inactive" and out.counts == {}
    assert out.summary() == {"account_id": str(seller.account_id), "status": "inactive"}
    assert table_counts(admin_conn, seller) == (0, 0, 0, 0)


async def test_logs_carry_no_barcode_order_number_amount_or_email(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a, order_no="SIPARIS-GIZLI-7", package=7001)
    add_push(admin_conn, a)
    email = admin_conn.execute("SELECT email FROM users WHERE id = %s", (a.user_id,)).fetchone()
    assert email is not None
    caplog.set_level(logging.DEBUG)
    await evaluator(worker_engine).evaluate(a.account_id)
    await evaluator(worker_engine).evaluate(a.account_id)  # atlanan çalıştırma da loglanır
    records = [r for r in caplog.records if r.name == "netkar.alerts"]
    assert {r.getMessage() for r in records} == {"alert_evaluation_done", "alert_evaluation_skipped"}
    text = " ".join(f"{r.getMessage()} {r.__dict__}" for r in records)
    for secret in (B1, "SIPARIS-GIZLI-7", email[0], "425.00", "urun:"):
        assert secret not in text
    done = next(r for r in records if r.getMessage() == "alert_evaluation_done")
    assert done.opened == 1 and done.unmatched_returns == 0  # type: ignore[attr-defined]
    assert done.orphan_returns == 0 and done.ambiguous_returns == 0  # type: ignore[attr-defined]


async def test_return_rate_rule_opens_product_and_account_events_from_the_cohort_query(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_push(admin_conn, a)
    set_preference(admin_conn, a, a.user_id, "IADE_ORANI_ARTISI", "push", "instant")
    # T = 2026-12-01: güncel kohort sipariş günü [2026-10-13, 2026-11-10), taban [2026-07-21, 2026-10-13).
    # Güncel kohort: 60 satır, 18 iadeli (%30); taban: 100 satır, 5 iadeli (%5).
    for n in range(60):
        claims = (("Accepted", "2026-10-25T00:00:00", "R1"),) if n < 18 else ()
        add_cohort_line(admin_conn, a, "2026-10-20T09:00:00", B1, claims=claims)
    for n in range(100):
        claims = (("Accepted", "2026-08-20T00:00:00", "R2"),) if n < 5 else ()
        add_cohort_line(admin_conn, a, "2026-08-15T09:00:00", B1, claims=claims)
    out = await evaluator(worker_engine, datetime(2026, 12, 1, 9, 0, tzinfo=UTC)).evaluate(a.account_id)
    assert out.status == "succeeded"
    found = events(admin_conn, a, "IADE_ORANI_ARTISI")
    assert [(e["subject"], e["severity"]) for e in found] == [("hesap:*", "medium"), (f"urun:{B1}", "medium")]
    product = next(e for e in found if e["subject"] != "hesap:*")
    evidence = product["payload"]["evidence"]
    assert (evidence["current_lines"], evidence["current_returned"]) == (60, 18)
    assert (evidence["base_lines"], evidence["base_returned"]) == (100, 5)
    assert evidence["reason_codes"] == "R1" and product["payload"]["certainty"] == "tahmini"
    (row,) = outbox(admin_conn, a)
    assert row["channel"] == "push" and row["payload"]["rule_counts"] == {"IADE_ORANI_ARTISI": 2}
    assert row["payload"]["IADE_ORANI_ARTISI"] == {"event_count": 2, "window_days": 28}
    assert out.counts["rule_counts"]["IADE_ORANI_ARTISI"] == 2
    assert out.counts["rules_no_data"] == 1  # yalnız reklam


async def test_losing_the_insert_race_for_the_evaluation_key_writes_nothing(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    real = AlertEvaluator._read_inputs

    async def raced(
        self: AlertEvaluator, tenant_id: UUID, account_id: UUID, as_of: Any, scope: str, backfill_done: bool
    ) -> Any:
        inputs = await real(self, tenant_id, account_id, as_of, scope, backfill_done)
        assert isinstance(inputs, ae._Inputs)
        # Başka bir çalıştırma okuma ile yazma arasında aynı anahtarı kapattı.
        admin_conn.execute(
            "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
            "settings_revision, rules_version, attempt) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                a.tenant_id,
                a.account_id,
                inputs.key.as_of,
                inputs.key.data_revision,
                inputs.key.stored_settings_revision,
                inputs.key.rules_version,
                inputs.attempt,
            ),
        )
        return inputs

    monkeypatch.setattr(AlertEvaluator, "_read_inputs", raced)
    out = await evaluator(worker_engine).evaluate(a.account_id)
    assert (out.status, out.reason) == ("skipped", "raced")
    assert table_counts(admin_conn, a) == (0, 0, 0, 1)


async def test_outbox_rows_are_idempotent_by_their_own_dedupe_key(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    a = world.a
    add_push(admin_conn, a)
    key = EvaluationKey(NOW.date(), 4, 0, 0)
    chosen = [ae.Notifiable(LOSS, uuid4(), Decimal("10.00"), Certainty.CERTAIN)]
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    written = []
    for _ in range(2):
        async with real_tenant_transaction(sessions, a.tenant_id) as session:
            written.append(await ae._write_outbox(session, a.tenant_id, a.account_id, key, chosen, NOW))
    assert written == [1, 0]
    assert len(outbox(admin_conn, a)) == 1
    async with real_tenant_transaction(sessions, a.tenant_id) as session:
        assert await ae._write_outbox(session, a.tenant_id, a.account_id, key, [], NOW) == 0


def test_default_clock_is_utc_now(worker_engine: AsyncEngine) -> None:
    moment = AlertEvaluator(worker_engine)._now()
    assert moment.tzinfo is UTC and abs((datetime.now(UTC) - moment).total_seconds()) < 5


def add_sync_run(
    conn: psycopg.Connection[Any], seller: Seller, source: str, status: str, started: str = "2026-10-09"
) -> None:
    conn.execute(
        "INSERT INTO sync_runs (tenant_id, marketplace_account_id, run_group_id, kind, source, status, "
        "error_class, started_at) VALUES (%s, %s, %s, 'incremental', %s, %s, %s, %s)",
        (
            seller.tenant_id,
            seller.account_id,
            uuid4(),
            source,
            status,
            "timeout" if status == "failed" else None,
            started,
        ),
    )


async def test_notifications_are_suppressed_until_backfill_is_complete_and_the_last_sync_is_clean(
    admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    seller = make_seller(admin_conn, seller_id="7777")
    add_loss_sale(admin_conn, seller)
    add_push(admin_conn, seller)
    ev = evaluator(worker_engine)

    out = await ev.evaluate(seller.account_id)  # yedekleme eksik: olay açılır, outbox yok
    assert (out.counts["opened"], out.counts["notified"], out.counts["outbox_rows"]) == (1, 0, 0)
    (event,) = events(admin_conn, seller)
    assert (
        event["last_notified_at"] is None
        and event["notified_amount"] is None
        and outbox(admin_conn, seller) == []
    )

    mark_synced(admin_conn, seller)
    add_sync_run(admin_conn, seller, "orders", "failed", "2026-10-09")  # son senkron kısmi (kaynak başarısız)
    out = await ev.evaluate(seller.account_id)
    assert (out.counts["updated"], out.counts["notified"]) == (1, 0) and outbox(admin_conn, seller) == []

    add_sync_run(admin_conn, seller, "orders", "succeeded", "2026-10-10")  # toparlandı
    set_cost(admin_conn, seller, "501.00")  # senkron yeni veri yazar: veri sürümü artar, yeni anahtar
    out = await ev.evaluate(seller.account_id)
    assert (out.counts["updated"], out.counts["notified"], out.counts["outbox_rows"]) == (1, 1, 1)
    assert events(admin_conn, seller)[0]["last_notified_at"] == NOW  # bildirim kaybolmadı, ertelendi
    assert len(outbox(admin_conn, seller)) == 1


async def test_more_than_500_notifications_are_split_into_chunks_without_loss(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    a = world.a
    add_push(admin_conn, a)
    key = EvaluationKey(NOW.date(), 4, 0, 0)
    ids = [uuid4() for _ in range(1203)]
    chosen = [ae.Notifiable(LOSS, event_id, Decimal("1.50"), Certainty.CERTAIN) for event_id in ids]
    sessions = async_sessionmaker(worker_engine, expire_on_commit=False)
    async with real_tenant_transaction(sessions, a.tenant_id) as session:
        assert await ae._write_outbox(session, a.tenant_id, a.account_id, key, chosen, NOW) == 3
    rows = sorted(outbox(admin_conn, a), key=lambda r: -len(r["alert_event_ids"]))
    assert [len(r["alert_event_ids"]) for r in rows] == [500, 500, 203]
    assert [r["payload"]["event_count"] for r in rows] == [500, 500, 203]
    assert [r["payload"]["ZARARINA_SATIS"]["total_amount"] for r in rows] == ["750.00", "750.00", "304.50"]
    assert {i for r in rows for i in r["alert_event_ids"]} == set(ids)  # hiçbir olay kesilmedi
    assert len({r["dedupe_key"] for r in rows}) == 3
    async with real_tenant_transaction(
        sessions, a.tenant_id
    ) as session:  # aynı değerlendirme: tekrar yazılmaz
        assert await ae._write_outbox(session, a.tenant_id, a.account_id, key, chosen, NOW) == 0


async def test_a_job_failure_never_leaks_database_detail_into_logs_or_the_job_record(
    runtime: WorkerRuntime,
    world: World,
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from sqlalchemy import text

    a = world.a
    add_loss_sale(admin_conn, a)

    async def leaky(session: Any, tenant_id: UUID, account_id: UUID, *args: Any, **kwargs: Any) -> int:
        # CHECK ihlali: psycopg DETAIL ("Failing row contains ...") satır değerlerini (konu) içerir.
        await session.execute(
            text(
                "INSERT INTO alert_events (tenant_id, marketplace_account_id, rule, scope, subject, dedupe_key, "
                "severity, payload, payload_version, data_revision, settings_revision) VALUES "
                "(:t, :a, 'ZARARINA_SATIS', 'product', 'urun:GIZLI-BARKOD-77', :k, 'high', "
                "CAST(:p AS jsonb), 1, 1, 1)"
            ),
            {"t": tenant_id, "a": account_id, "k": "ab" * 32, "p": '{"email": "gizli@ornek.com"}'},
        )
        return 0

    monkeypatch.setattr(ae, "_write_outbox", leaky)
    app, connector = memory_app(runtime)
    caplog.set_level(logging.DEBUG)
    async with app.open_async():
        await defer_alert_evaluation(app, a.account_id)
        await app.run_worker_async(wait=False)
    (job,) = alert_jobs(connector)
    assert job["status"] == "failed"  # kalıcı hata: yeniden denenmez
    everything = " ".join(f"{r.getMessage()} {r.exc_text} {r.__dict__}" for r in caplog.records)
    everything += caplog.text + str(job)
    assert "alert evaluation failed" in everything or "alert_evaluation_failed" in everything
    for secret in ("GIZLI-BARKOD-77", "gizli@ornek.com", "Failing row"):
        assert secret not in everything
    assert table_counts(admin_conn, a)[:3] == (0, 0, 0)


def _job_with_attempts(attempts: int) -> Any:
    return procrastinate.jobs.Job(
        id=1, queue="alerts", lock=None, queueing_lock=None, task_name="alerts.evaluate", attempts=attempts
    )


async def test_transient_errors_are_retried_with_backoff_and_permanent_ones_are_not(
    runtime: WorkerRuntime, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, connector = memory_app(runtime)
    strategy = app.tasks["alerts.evaluate"].retry_strategy
    assert strategy is not None and getattr(strategy, "max_attempts", None) == 3
    assert (
        strategy.get_retry_exception(  # type: ignore[union-attr]
            AlertEvaluationTransient("x"), _job_with_attempts(0)
        )
        is not None
    )
    assert strategy.get_retry_exception(AlertEvaluationFailed("x"), _job_with_attempts(0)) is None  # type: ignore[union-attr]

    async def transient(self: AlertEvaluator, account_id: UUID, scope: str = "all") -> Any:
        raise AlertEvaluationTransient("OperationalError")

    monkeypatch.setattr(AlertEvaluator, "evaluate", transient)
    async with app.open_async():
        await defer_alert_evaluation(app, world.a.account_id)
        await app.run_worker_async(wait=False)
    (job,) = alert_jobs(connector)
    assert job["status"] == "todo" and job["attempts"] == 1 and job["scheduled_at"] > datetime.now(UTC)

    async def permanent(self: AlertEvaluator, account_id: UUID, scope: str = "all") -> Any:
        raise AlertEvaluationFailed("CheckViolation")

    monkeypatch.setattr(AlertEvaluator, "evaluate", permanent)
    app2, connector2 = memory_app(runtime)
    async with app2.open_async():
        await defer_alert_evaluation(app2, world.b.account_id)
        await app2.run_worker_async(wait=False)
    (job2,) = alert_jobs(connector2)
    assert job2["status"] == "failed"


async def test_fast_scope_skips_the_92_day_engine_run_and_leaves_deduction_events_alone(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    periods: list[int] = []
    real = real_period_profit

    async def spy(db: Any, tenant: Any, account: Any, start: Any, end: Any, *rest: Any, **kw: Any) -> Any:
        periods.append((end - start).days + 1)
        return await real(db, tenant, account, start, end, *rest, **kw)

    monkeypatch.setattr("app.services.alert_evaluation.period_profit", spy)
    ev = evaluator(worker_engine)
    fast = await ev.evaluate(a.account_id, "fast")
    assert periods == [7] and fast.counts["rules_evaluated"] == 1  # zarar; iade kohortu yok
    assert fast.counts["rule_counts"] == {"ZARARINA_SATIS": 1}
    full = await ev.evaluate(a.account_id, "all")  # aynı gün ve veri: `fast` anahtarı `all`ı kapatmaz
    assert full.status == "succeeded" and periods == [7, 7, 92]
    assert (await ev.evaluate(a.account_id, "fast")).reason == "completed"
    with pytest.raises(ValueError, match="kapsam"):
        await ev.evaluate(a.account_id, "bilinmeyen")


async def test_deferral_with_delay_keeps_one_pending_job_per_account_and_scope(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    async with app.open_async():
        assert await defer_alert_evaluation(app, seller.account_id, scope="fast", delay_minutes=10) is True
        assert await defer_alert_evaluation(app, seller.account_id, scope="fast", delay_minutes=10) is False
        assert await defer_alert_evaluation(app, seller.account_id, scope="all", delay_minutes=10) is True
    assert sorted(j["args"]["scope"] for j in alert_jobs(connector)) == ["all", "fast"]


async def test_stalled_alert_jobs_are_recovered_but_other_queues_are_left_alone(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_alert_evaluation(app, seller.account_id)
        await defer_backfill(app, seller.account_id)
        for job in connector.jobs.values():
            job["status"] = "doing"  # worker'ı ölmüş (heartbeat yok)
        assert await recover_stalled_alerts(app) == 1
    statuses = {j["task_name"]: j["status"] for j in connector.jobs.values()}
    assert statuses == {"alerts.evaluate": "todo", "sync.backfill": "doing"}


def test_stalled_recovery_is_scheduled_periodically_off_the_half_hour() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)
    crons = {name: task.cron for (name, _), task in app.periodic_registry.periodic_tasks.items()}
    assert crons["alerts.recover_stalled"] == CRON_ALERTS_RECOVER
    minutes = {int(m) for m in "5 15 25 35 45 55".split()}
    assert minutes.isdisjoint({0, 30}) and app.tasks["alerts.recover_stalled"].queue == "alerts"


async def test_user_transition_in_flight_blocks_the_evaluation_which_then_sees_the_new_status(
    database: DatabaseInfo, world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    import asyncio

    a = world.a
    add_loss_sale(admin_conn, a)
    ev = evaluator(worker_engine)
    await ev.evaluate(a.account_id)
    event_id = events(admin_conn, a)[0]["id"]
    set_cost(admin_conn, a, "10.00")  # koşul kalktı: sonraki değerlendirme çözecek
    user = psycopg.connect(database.app_dsn())
    try:
        user.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a.tenant_id),))
        user.execute("SELECT set_config('app.user_id', %s, true)", (str(a.user_id),))
        transition(user, a, event_id, "read")  # işlem açık: olay satırı kilitli
        task = asyncio.create_task(ev.evaluate(a.account_id))
        await asyncio.sleep(1.0)
        assert not task.done()  # değerlendirme olay satırında bekliyor (FOR UPDATE)
        user.commit()
    finally:
        user.close()
    out = await task  # eski durumu okuyup 40001 almaz: kullanıcının `read` durumunu görür
    assert out.status == "succeeded" and out.counts["resolved"] == 1
    assert transitions_of(admin_conn, event_id) == [("open", "read", "user"), ("read", "resolved", "system")]


async def test_threshold_aba_is_re_evaluated_because_updated_at_is_part_of_the_key(
    database: DatabaseInfo, world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    admin_conn.execute(
        "INSERT INTO alert_rule_settings (tenant_id, marketplace_account_id, updated_by) VALUES (%s, %s, %s)",
        (a.tenant_id, a.account_id, a.user_id),
    )
    ev = evaluator(worker_engine)
    assert (await ev.evaluate(a.account_id)).counts["opened"] == 1

    def set_threshold(value: str) -> None:
        with role_tx(database.app_dsn(), a.tenant_id, a.user_id, commit=True) as conn:
            conn.execute(
                "UPDATE alert_rule_settings SET loss_min_amount = %s WHERE marketplace_account_id = %s",
                (value, a.account_id),
            )

    set_threshold("10000.00")  # B
    assert (await ev.evaluate(a.account_id)).counts["resolved"] == 1
    set_threshold("5.00")  # A'ya dönüş: içerik ilk anahtarla AYNI, `updated_at` farklı
    third = await ev.evaluate(a.account_id)
    assert third.status == "succeeded" and third.counts["reopened"] == 1
    assert events(admin_conn, a)[0]["status"] == "open"
    assert len({e["settings_revision"] for e in evaluations(admin_conn, a)}) == 3


async def test_a_held_advisory_lock_blocks_the_write_phase_until_released(
    world: World, admin_conn: psycopg.Connection[Any], worker_engine: AsyncEngine, database: DatabaseInfo
) -> None:
    import asyncio

    a = world.a
    add_loss_sale(admin_conn, a)
    holder = psycopg.connect(database.admin_dsn())
    try:
        holder.execute("SELECT pg_advisory_xact_lock(hashtext('alerts:' || %s::text))", (str(a.account_id),))
        task = asyncio.create_task(evaluator(worker_engine).evaluate(a.account_id))
        await asyncio.sleep(1.0)
        assert not task.done() and events(admin_conn, a) == []  # yazma aşaması kilitte bekliyor
        holder.commit()
    finally:
        holder.close()
    assert (await task).status == "succeeded" and len(events(admin_conn, a)) == 1


# ---- migrasyon 0026 ------------------------------------------------------------------------------------------------


def test_migration_0026_schema_attempt_key_dropped_count_and_immutability(
    database: DatabaseInfo, world: World, admin_conn: psycopg.Connection[Any]
) -> None:
    a = world.a
    insert = (
        "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
        "settings_revision, rules_version, attempt) VALUES (%s, %s, '2026-11-20', 4, 2, 1, %s) RETURNING id"
    )
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:
        first = conn.execute(insert, (a.tenant_id, a.account_id, 1)).fetchone()
        assert first is not None
        conn.execute("UPDATE alert_evaluations SET status = 'failed' WHERE id = %s", (first[0],))
        conn.execute(insert, (a.tenant_id, a.account_id, 2))
    for bad in (0, 4):
        with (
            role_tx(database.worker_dsn(), a.tenant_id) as conn,
            pytest.raises(psycopg.errors.CheckViolation),
        ):
            conn.execute(insert, (a.tenant_id, a.account_id, bad))
    with role_tx(database.worker_dsn(), a.tenant_id) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(insert, (a.tenant_id, a.account_id, 2))  # (anahtar, attempt) tekil
    with admin_conn.transaction(force_rollback=True), pytest.raises(psycopg.errors.CheckViolation):
        admin_conn.execute("UPDATE alert_evaluations SET attempt = 3 WHERE attempt = 2")  # kimlik sütunu
    with role_tx(database.worker_dsn(), a.tenant_id, commit=True) as conn:  # `dropped` izin listesinde
        conn.execute(
            "UPDATE alert_evaluations SET status = 'succeeded', counts = %s WHERE attempt = 2",
            (Jsonb({"dropped": 3}),),
        )
    with role_tx(database.worker_dsn(), a.tenant_id) as conn, pytest.raises(psycopg.errors.CheckViolation):
        third = conn.execute(insert, (a.tenant_id, a.account_id, 3)).fetchone()
        assert third is not None
        conn.execute(
            "UPDATE alert_evaluations SET status = 'failed', counts = %s WHERE id = %s",
            (Jsonb({"bilinmeyen": 1}), third[0]),
        )


def test_migration_0026_downgrade_guard_counts_only_retry_rows_and_prod_always_refuses(
    alembic_cfg: Config,
    world: World,
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = world.a
    insert = (
        "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
        "settings_revision, rules_version, attempt) VALUES (%s, %s, '2026-11-20', 4, 2, 1, %s)"
    )
    for attempt in (1, 2, 3):
        admin_conn.execute(insert, (a.tenant_id, a.account_id, attempt))
    admin_conn.execute(  # `dropped` anahtarlı dolu counts: downgrade sonrası CHECK ihlali olmamalı
        "UPDATE alert_evaluations SET status = 'succeeded', counts = %s WHERE attempt = 1",
        (Jsonb({"dropped": 2}),),
    )
    monkeypatch.delenv("NETKAR_ALLOW_ALERT_DATA_LOSS", raising=False)
    try:
        monkeypatch.setenv("ENVIRONMENT", "prod")
        with pytest.raises(RuntimeError, match="ENVIRONMENT=prod"):
            command.downgrade(alembic_cfg, "0025")
        monkeypatch.setenv("ENVIRONMENT", "test")
        for wrong in ("", "3", "1", "attempt=2"):
            monkeypatch.setenv("NETKAR_ALLOW_ALERT_DATA_LOSS", wrong)
            with pytest.raises(RuntimeError, match="NETKAR_ALLOW_ALERT_DATA_LOSS=2"):
                command.downgrade(alembic_cfg, "0025")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0026",)
        assert admin_conn.execute("SELECT count(*) FROM alert_evaluations").fetchone() == (3,)
        monkeypatch.setenv("NETKAR_ALLOW_ALERT_DATA_LOSS", "2")
        command.downgrade(alembic_cfg, "0025")
        assert admin_conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0025",)
        assert admin_conn.execute("SELECT count(*) FROM alert_evaluations").fetchone() == (
            1,
        )  # yalnız attempt 1
        assert admin_conn.execute("SELECT counts FROM alert_evaluations").fetchone() == ({"dropped": 2},)
        # Genişletilmiş izin listesi geri alınmadı: yeni `dropped` yazımı CHECK ihlali vermez.
        admin_conn.execute(
            "INSERT INTO alert_evaluations (tenant_id, marketplace_account_id, as_of_date, data_revision, "
            "settings_revision, rules_version) VALUES (%s, %s, '2026-11-21', 1, 1, 1)",
            (a.tenant_id, a.account_id),
        )
        admin_conn.execute(
            "UPDATE alert_evaluations SET status = 'succeeded', counts = %s WHERE as_of_date = '2026-11-21'",
            (Jsonb({"dropped": 5}),),
        )
        assert (
            admin_conn.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'alert_evaluations' AND column_name = 'attempt'"
            ).fetchone()
            is None
        )
        forced = admin_conn.execute(
            "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'alert_evaluations'"
        ).fetchone()
        assert forced == (True,)
    finally:
        monkeypatch.delenv("NETKAR_ALLOW_ALERT_DATA_LOSS", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "test")
        command.upgrade(alembic_cfg, "head")
    assert sorted(admin_conn.execute("SELECT attempt FROM alert_evaluations").fetchall()) == [(1,), (1,)]


# ===================================================================================== tetikleyiciler


@pytest.fixture
async def runtime(settings: Settings) -> AsyncIterator[WorkerRuntime]:
    rt = WorkerRuntime(settings, client_factory=client_factory(full_api()), now=lambda: NOW)
    yield rt
    await rt.aclose()


def memory_app(rt: WorkerRuntime) -> tuple[procrastinate.App, testing.InMemoryConnector]:
    connector = testing.InMemoryConnector()
    app = procrastinate.App(connector=connector)
    register_tasks(app, rt)
    app.periodic_registry.periodic_tasks.clear()  # periyodik işler açılışta kendiliğinden girer; testler açıkça ekler
    return app, connector


def alert_jobs(connector: testing.InMemoryConnector) -> list[dict[str, Any]]:
    return [j for j in connector.jobs.values() if j["task_name"] == "alerts.evaluate"]


def test_alert_tasks_are_registered_on_their_own_queue_and_the_daily_plan_is_periodic() -> None:
    app = procrastinate.App(connector=testing.InMemoryConnector())
    register_tasks(app)
    assert app.tasks["alerts.evaluate"].queue == "alerts" and app.tasks["alerts.plan_daily"].queue == "alerts"
    crons = {name: task.cron for (name, _), task in app.periodic_registry.periodic_tasks.items()}
    assert (
        crons["alerts.plan_daily"] == CRON_ALERTS_DAILY == "47 3 * * *"
    )  # 06:47 İstanbul, dakika 0/30 değil
    assert "alerts.evaluate" not in crons  # değerlendirme yalnız hesap başına ve talep üzerine


async def test_deferral_uses_a_per_account_lock_and_one_pending_job(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    async with app.open_async():
        assert await defer_alert_evaluation(app, seller.account_id) is True
        assert await defer_alert_evaluation(app, seller.account_id) is False  # bekleyen iş varken eklenmez
    (job,) = alert_jobs(connector)
    assert (
        job["lock"] == f"alerts:{seller.account_id}"
        and job["queueing_lock"] == f"alerts-eval:{seller.account_id}:all"
    )
    assert job["queue_name"] == "alerts"
    assert job["args"] == {"account_id": str(seller.account_id), "scope": "all"}


async def test_worker_runs_the_evaluation_job_end_to_end(
    runtime: WorkerRuntime, world: World, admin_conn: psycopg.Connection[Any]
) -> None:
    a = world.a
    add_loss_sale(admin_conn, a)
    app, connector = memory_app(runtime)
    async with app.open_async():
        await defer_alert_evaluation(app, a.account_id)
        await app.run_worker_async(wait=False)
    (job,) = alert_jobs(connector)
    assert job["status"] == "succeeded"
    assert [e["status"] for e in events(admin_conn, a)] == ["open"]
    assert evaluations(admin_conn, a)[0]["status"] == "succeeded"


def sync_outcome(status: str, *upserted: int) -> SyncOutcome:
    account = uuid4()
    return SyncOutcome(
        account,
        "incremental",
        status,  # type: ignore[arg-type]
        [SourceOutcome(f"s{n}", "succeeded", upserted=count) for n, count in enumerate(upserted)],
    )


async def test_alerts_are_deferred_after_sync_only_when_something_was_written(
    runtime: WorkerRuntime,
) -> None:
    app, connector = memory_app(runtime)
    async with app.open_async():
        assert await defer_alerts_after_sync(app, sync_outcome("completed", 0, 3)) is True
        assert await defer_alerts_after_sync(app, sync_outcome("partial", 1)) is True
        assert await defer_alerts_after_sync(app, sync_outcome("completed", 0, 0)) is False  # upserted = 0
        assert await defer_alerts_after_sync(app, sync_outcome("completed")) is False  # kaynak yok
        for status in ("invalid", "credentials_error", "inactive", "locked"):
            assert await defer_alerts_after_sync(app, sync_outcome(status, 5)) is False
    assert len(alert_jobs(connector)) == 2
    # Aynı hesap için bekleyen iş varken ikinci erteleme eklenmez (AlreadyEnqueued).
    same = sync_outcome("completed", 2)
    async with app.open_async():
        assert await defer_alerts_after_sync(app, same) is True
        assert await defer_alerts_after_sync(app, same) is False
    assert len(alert_jobs(connector)) == 3


async def test_sync_scope_is_all_only_when_a_finance_source_wrote_and_fast_otherwise(
    runtime: WorkerRuntime,
) -> None:
    def outcome(**written: int) -> SyncOutcome:
        return SyncOutcome(
            uuid4(),
            "incremental",
            "completed",
            [SourceOutcome(name, "succeeded", upserted=count) for name, count in written.items()],
        )

    app, connector = memory_app(runtime)
    async with app.open_async():
        for written, scope in (
            ({"orders": 2}, "fast"),
            ({"orders": 1, "claims": 1, "products": 4}, "fast"),
            ({"orders": 2, "settlements": 1}, "all"),
            ({"other_financials": 1}, "all"),
            ({"cargo_invoices": 3}, "all"),
        ):
            assert await defer_alerts_after_sync(app, outcome(**written)) is True
            assert alert_jobs(connector)[-1]["args"]["scope"] == scope
    assert all(j["status"] == "todo" and j["scheduled_at"] is not None for j in alert_jobs(connector))


async def test_a_deferral_failure_never_breaks_the_sync_job(
    runtime: WorkerRuntime, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import app.worker.tasks as tasks

    async def broken(*args: Any, **kwargs: Any) -> bool:
        raise OSError("kuyruk yok")

    monkeypatch.setattr(tasks, "defer_alert_evaluation", broken)
    app, _ = memory_app(runtime)
    caplog.set_level(logging.WARNING, logger="netkar.worker")
    assert await defer_alerts_after_sync(app, sync_outcome("completed", 4)) is False
    (record,) = caplog.records
    assert "ertelenemedi" in record.getMessage() and record.error_class == "OSError"  # type: ignore[attr-defined]
    assert "kuyruk yok" not in f"{record.getMessage()} {record.__dict__}"


async def test_sync_tasks_defer_an_alert_evaluation_when_records_were_written(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    seller = make_seller(admin_conn)
    app, connector = memory_app(runtime)
    from app.worker.queue import defer_backfill

    async with app.open_async():
        await defer_backfill(app, seller.account_id)
        await app.run_worker_async(wait=False)
    (job,) = alert_jobs(connector)
    # Senkron sonrası değerlendirme 10 dakika ertelenir (kapsam birim testinde ayrıca sınanır).
    assert job["args"]["account_id"] == str(seller.account_id) and job["status"] == "todo"
    assert job["queueing_lock"] == f"alerts-eval:{seller.account_id}:{job['args']['scope']}"
    delay = job["scheduled_at"] - datetime.now(UTC)
    assert timedelta(minutes=9) < delay <= timedelta(minutes=10)


async def test_daily_plan_defers_one_evaluation_per_active_account(
    runtime: WorkerRuntime, admin_conn: psycopg.Connection[Any]
) -> None:
    active = make_seller(admin_conn)
    make_seller(admin_conn, seller_id="9999", status="revoked")
    other = make_seller(admin_conn, seller_id="8888")
    app, connector = memory_app(runtime)
    async with app.open_async():
        assert await plan_alert_evaluations(app, runtime) == {"deferred": 2}
        assert await plan_alert_evaluations(app, runtime) == {"deferred": 0}  # bekleyenler varken eklenmez
    assert {j["args"]["account_id"] for j in alert_jobs(connector)} == {
        str(active.account_id),
        str(other.account_id),
    }


# ---- API tetikleyicileri (kâr ayarı ve maliyet yazımı) ------------------------------------------------------------


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.mark.usefixtures("fixed_today")
def test_cost_and_settings_writes_request_an_evaluation_after_commit(
    make_shop: Callable[..., Shop], job_queue: RecordingJobQueue
) -> None:
    shop = make_shop("a@example.com", "Mağaza A")
    cost = {"valid_from": "2026-10-01", "unit_cost_excl_vat": "50.00", "vat_rate": 20}
    assert shop.api.put(f"{shop.base}/products/{B1}/costs", cost).status_code == 200
    assert job_queue.alert_evaluations == [shop.account_id]
    assert shop.api.put(f"{shop.base}/profit-settings/defaults", {"default_desi": "3"}).status_code == 200
    assert job_queue.alert_evaluations == [shop.account_id] * 2
    # Değişiklik yoksa (aynı içerik) hiçbir şey yazılmaz ve değerlendirme istenmez.
    assert shop.api.put(f"{shop.base}/profit-settings/defaults", {"default_desi": "3"}).status_code == 200
    assert len(job_queue.alert_evaluations) == 2
    # Kuru deneme yazmaz: istek yok; gerçek içe aktarma yazar: istek var.
    data = csv_bytes(f"{B1};60,00;20;2026-10-02")
    assert upload(shop, data, dry_run=True).status_code == 200
    assert len(job_queue.alert_evaluations) == 2
    assert upload(shop, data, dry_run=False).status_code == 200
    assert len(job_queue.alert_evaluations) == 3


@pytest.mark.usefixtures("fixed_today")
def test_a_queue_failure_never_breaks_the_write(
    make_shop: Callable[..., Shop], job_queue: RecordingJobQueue, admin_conn: psycopg.Connection[Any]
) -> None:
    shop = make_shop("a@example.com", "Mağaza A")
    job_queue.fail = True
    cost = {"valid_from": "2026-10-01", "unit_cost_excl_vat": "50.00", "vat_rate": 20}
    assert shop.api.put(f"{shop.base}/products/{B1}/costs", cost).status_code == 200
    assert shop.api.put(f"{shop.base}/profit-settings/defaults", {"default_desi": "4"}).status_code == 200
    row = admin_conn.execute(
        "SELECT count(*) FROM product_costs WHERE marketplace_account_id = %s", (shop.account_id,)
    ).fetchone()
    assert row == (1,) and job_queue.alert_evaluations == []


async def test_request_alert_evaluation_swallows_queue_errors_and_logs_only_the_class(
    caplog: pytest.LogCaptureFixture,
) -> None:
    queue = RecordingJobQueue()
    queue.fail = True
    caplog.set_level(logging.WARNING, logger="netkar.worker")
    await request_alert_evaluation(queue, uuid4())
    (record,) = caplog.records
    assert "kuyruğa eklenemedi" in record.getMessage() and record.error_class == "RuntimeError"  # type: ignore[attr-defined]
    assert "kuyruk erişilemez" not in f"{record.getMessage()} {record.__dict__}"
    queue.fail = False
    account = uuid4()
    await request_alert_evaluation(queue, account)
    assert queue.alert_evaluations == [account]
