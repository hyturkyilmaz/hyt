"""O-a daraltması (ADR-0009 D4 açık maddesi, D5): bildirim YALNIZ ilgili kuralın veri kaynağı bozuksa bastırılır.

Önceki davranış: HERHANGİ bir kaynağın son senkronu başarısızsa (ya da herhangi bir kaynağın yedeklemesi eksikse) tüm
bildirimler bastırılıyordu. Şimdi her kuralın kaynak kümesi (`RULE_SOURCES`) vardır; yalnız o kümedeki bir kaynak
başarısız ya da yedeklemesi eksikse o kuralın bildirimi bastırılır. Olay HER durumda açılır; yalnız outbox yazılmaz.

Kaynak adları koddan alınır (`SOURCE_ORDER`, `RULE_SOURCES`); testler yeni isim uydurmaz.
Değerlendirme günü 2026-12-01 (iade kohortu `test_return_rate_rule_opens_...` ile aynı kurulum); zarar satırı
2026-11-27'dedir (7 günlük pencerede).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from app.alerts import AlertRule
from app.services.alert_evaluation import (
    DEDUCTION_PERIOD_DAYS,
    RULE_SOURCES,
    AlertEvaluator,
    blocked_rules,
)
from app.services.sync.sources import SOURCE_ORDER
from tests.test_alert_cohort import add_line as add_cohort_line
from tests.test_alert_evaluation import (
    add_loss_sale,
    add_sync_run,
    events,
    mark_synced,
    outbox,
    set_preference,
)
from tests.test_alert_schema import World, make_world


@pytest.fixture
def world(admin_conn: psycopg.Connection[Any]) -> World:
    """İki kiracı (A: owner, admin, viewer; B: owner); tüm kaynakların yedeklemesi tamam."""
    made = make_world(admin_conn)
    mark_synced(admin_conn, made.a)
    mark_synced(admin_conn, made.b)
    return made


LOSS = AlertRule.LOSS_MAKING_SALE
DEDUCTION = AlertRule.UNEXPECTED_DEDUCTION
RETURNS = AlertRule.RETURN_RATE_INCREASE
ADS = AlertRule.AD_EATS_PROFIT
T = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
ALL_SOURCES = frozenset(SOURCE_ORDER)


# ---- saf eşleme ------------------------------------------------------------------------------------------------------


def test_rule_sources_use_only_real_source_names_and_every_rule_is_mapped() -> None:
    assert set(RULE_SOURCES) == set(AlertRule)
    for rule, sources in RULE_SOURCES.items():
        assert sources <= ALL_SOURCES, rule  # uydurma kaynak adı yok
    assert RULE_SOURCES[ADS] == frozenset()  # reklam verisi senkron kaynağı değil
    used = frozenset().union(*RULE_SOURCES.values())
    assert ALL_SOURCES - used == {"products"}  # katalog hiçbir kuralın bastırma girdisi değil


@pytest.mark.parametrize(
    ("failed", "expected"),
    [
        ((), set()),
        (("products",), set()),  # katalog hatası bildirim bastırmaz (önceden hepsini bastırırdı)
        (("settlements",), {LOSS, DEDUCTION}),  # finans kaynağı: zarar ve kesinti; iade etkilenmez
        (("other_financials",), {LOSS, DEDUCTION}),
        (("cargo_invoices",), {LOSS, DEDUCTION}),
        (("claims",), {LOSS, RETURNS}),  # iade kaynağı: iade kuralı (+ zararın iade adedi)
        (("orders",), {LOSS, DEDUCTION, RETURNS}),
        (("settlements", "claims"), {LOSS, DEDUCTION, RETURNS}),
        (tuple(SOURCE_ORDER), {LOSS, DEDUCTION, RETURNS}),  # reklam hiçbir zaman bastırılmaz
    ],
)
def test_a_rule_is_blocked_only_by_its_own_failed_sources(
    failed: tuple[str, ...], expected: set[AlertRule]
) -> None:
    assert blocked_rules(ALL_SOURCES, failed) == expected


@pytest.mark.parametrize(
    ("missing", "expected"),
    [
        ((), set()),
        (("products",), set()),
        (("cargo_invoices",), {LOSS, DEDUCTION}),
        (("claims",), {LOSS, RETURNS}),
        (("orders", "claims"), {LOSS, DEDUCTION, RETURNS}),
    ],
)
def test_a_rule_is_blocked_only_by_its_own_missing_backfill(
    missing: tuple[str, ...], expected: set[AlertRule]
) -> None:
    assert blocked_rules(ALL_SOURCES - set(missing), ()) == expected
    assert blocked_rules((), ()) == {LOSS, DEDUCTION, RETURNS}  # hiç yedekleme yok: kaynağı olan her kural


def test_failure_and_missing_backfill_combine() -> None:
    assert blocked_rules(ALL_SOURCES - {"claims"}, ("cargo_invoices",)) == {LOSS, DEDUCTION, RETURNS}


# ---- değerlendirme (gerçek DB) ---------------------------------------------------------------------------------------


def arrange(admin_conn: psycopg.Connection[Any], world: World) -> None:
    """Hem zarar hem iade olayı doğuran veri; kullanıcı iki kural için e-postayı ANLIK ister."""
    a = world.a
    add_loss_sale(admin_conn, a, ordered=datetime(2026, 11, 27, 9, 0, tzinfo=UTC))
    for n in range(60):
        claims = (("Accepted", "2026-10-25T00:00:00", "R1"),) if n < 18 else ()
        add_cohort_line(admin_conn, a, "2026-10-20T09:00:00", "COHORT-1", claims=claims)
    for n in range(100):
        claims = (("Accepted", "2026-08-20T00:00:00", "R2"),) if n < 5 else ()
        add_cohort_line(admin_conn, a, "2026-08-15T09:00:00", "COHORT-1", claims=claims)
    set_preference(admin_conn, a, a.user_id, LOSS.value, "email", "instant")
    set_preference(admin_conn, a, a.user_id, RETURNS.value, "email", "instant")


def notified_rules(admin_conn: psycopg.Connection[Any], world: World) -> set[str]:
    rules: set[str] = set()
    for row in outbox(admin_conn, world.a):
        rules |= set(row["payload"]["rule_counts"])
    return rules


@pytest.mark.parametrize(
    ("break_sources", "expected"),
    [
        ((), {"ZARARINA_SATIS", "IADE_ORANI_ARTISI"}),
        (("products",), {"ZARARINA_SATIS", "IADE_ORANI_ARTISI"}),  # önceden ikisi de bastırılırdı
        (("settlements",), {"IADE_ORANI_ARTISI"}),
        (("other_financials",), {"IADE_ORANI_ARTISI"}),
        (("cargo_invoices",), {"IADE_ORANI_ARTISI"}),
        (("claims",), set()),
        (("orders",), set()),
    ],
)
async def test_failed_last_sync_suppresses_only_the_rules_that_depend_on_that_source(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    break_sources: tuple[str, ...],
    expected: set[str],
) -> None:
    a = world.a
    arrange(admin_conn, world)
    for source in break_sources:
        add_sync_run(admin_conn, a, source, "failed", "2026-11-30")
    out = await AlertEvaluator(worker_engine, now=lambda: T).evaluate(a.account_id)
    assert out.status == "succeeded"
    # Olaylar HER durumda açılır.
    assert len(events(admin_conn, a, "ZARARINA_SATIS")) == 1
    assert len(events(admin_conn, a, "IADE_ORANI_ARTISI")) == 2
    # Yalnız bozuk kaynağa bağlı kuralların bildirimi (outbox) yazılmaz.
    assert notified_rules(admin_conn, world) == expected
    for event in events(admin_conn, a):
        if event["rule"] in expected:
            assert event["last_notified_at"] is not None
        else:
            assert event["last_notified_at"] is None and event["notified_amount"] is None


@pytest.mark.parametrize(
    ("missing_backfill", "expected"),
    [
        (("products",), {"ZARARINA_SATIS", "IADE_ORANI_ARTISI"}),
        (("cargo_invoices",), {"IADE_ORANI_ARTISI"}),
        (("claims",), set()),
    ],
)
async def test_missing_backfill_suppresses_only_the_rules_that_depend_on_that_source(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
    missing_backfill: tuple[str, ...],
    expected: set[str],
) -> None:
    a = world.a
    arrange(admin_conn, world)
    for source in missing_backfill:
        admin_conn.execute(
            "DELETE FROM sync_cursors WHERE marketplace_account_id = %s AND source = %s",
            (a.account_id, source),
        )
    await AlertEvaluator(worker_engine, now=lambda: T).evaluate(a.account_id)
    assert len(events(admin_conn, a)) == 3  # olaylar açıldı
    assert notified_rules(admin_conn, world) == expected


async def test_a_recovered_source_notifies_on_the_next_evaluation_without_losing_the_alert(
    world: World,
    admin_conn: psycopg.Connection[Any],
    worker_engine: AsyncEngine,
) -> None:
    a = world.a
    arrange(admin_conn, world)
    add_sync_run(admin_conn, a, "settlements", "failed", "2026-11-30")
    first = AlertEvaluator(worker_engine, now=lambda: T)
    await first.evaluate(a.account_id)
    assert notified_rules(admin_conn, world) == {"IADE_ORANI_ARTISI"}
    add_sync_run(admin_conn, a, "settlements", "succeeded", "2026-12-01")
    admin_conn.execute(  # senkron yeni veri yazdı: veri sürümü artar, yeni değerlendirme anahtarı
        "UPDATE product_costs SET unit_cost_excl_vat = unit_cost_excl_vat + 1 WHERE marketplace_account_id = %s",
        (a.account_id,),
    )
    await AlertEvaluator(worker_engine, now=lambda: T).evaluate(a.account_id)
    assert notified_rules(admin_conn, world) == {"ZARARINA_SATIS", "IADE_ORANI_ARTISI"}  # zarar kaybolmadı


def test_deduction_window_constant_is_unchanged() -> None:
    assert DEDUCTION_PERIOD_DAYS == 92  # O-a yalnız bastırmayı daraltır; pencereler değişmedi
