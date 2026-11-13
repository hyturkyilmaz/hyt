"""Dönem sonucu önbelleği (denetim 2026-11-11 SU-01, S4 O-01/YO-01) ve sipariş listesi düzeltmeleri (SU-02, SU-04, SU-05).

Önbellek testlerde varsayılan olarak KAPALIDIR (`tests/conftest.py`); burada `profit_report_cache_ttl_seconds`
ile açıkça açılır. Motor çalışma sayısı `profit_report.calculate_profit` sarmalayıcısıyla sayılır. Takvime bağlı
test yoktur (TTL sahte saatle, İstanbul bugünü `fixed_today` ile sabit).
"""

from __future__ import annotations

import asyncio
import dataclasses
import threading
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from app.profit import calculate_profit
from app.profit.enums import WarningCode
from app.services import profit_feed, profit_report
from app.services import profit_views as views
from app.services.report_cache import ReportCache, ReportKey
from app.services.report_gate import ReportGate
from tests.conftest import Api
from tests.leak_helpers import visible_text
from tests.product_cost_helpers import (
    B1,
    B2,
    Shop,
    csv_bytes,
    fixed_today,  # noqa: F401
    make_shop_factory,
    upload,
)
from tests.report_helpers import END, START, add_order, seed_basic, seller_of
from tests.test_denetim_s4_kapanis import BlockedEngine
from tests.test_report_units import all_results

pytestmark = pytest.mark.usefixtures("fixed_today")
PERIOD = {"start": START, "end": END}
CACHE_ON: dict[str, Any] = {
    "rate_limit_profit_report_tenant": 100_000,
    "profit_report_cache_ttl_seconds": 300,
}


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


@pytest.fixture
def engine_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []

    def counting(profit_input: Any) -> Any:
        calls.append(len(profit_input.orders))
        return calculate_profit(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", counting)
    return calls


@pytest.fixture
def shop(make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]) -> Shop:
    created = make_shop("a@example.com", "Mağaza A", **CACHE_ON)
    seed_basic(admin_conn, created)
    return created


def call(shop: Shop, path: str, **params: Any) -> Any:
    return shop.api.get(f"{shop.base}/profit/{path}", params={**PERIOD, **params})


def cache_of(shop: Shop) -> ReportCache:
    cache: ReportCache = shop.api.client.app.state.report_cache  # type: ignore[attr-defined]
    return cache


# =============================================================================== birim: ReportCache


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_cache(clock: FakeClock | None = None, **over: Any) -> ReportCache:
    params: dict[str, Any] = {"ttl_seconds": 60, "max_entries": 8, "max_lines": 100, "tenant_entries": 4}
    params.update(over)
    return ReportCache(clock=clock or FakeClock(), **params)


def report_of(lines: int = 1) -> Any:
    """Yalnız `result.lines` uzunluğu önemli: gerçek dönem raporu yerine aynı biçimde küçük sahte."""
    result = dataclasses.make_dataclass("R", [("lines", tuple)])((None,) * lines)
    return dataclasses.make_dataclass("P", [("result", object)])(result)


def key_of(tenant: UUID, account: UUID | None = None, revision: int = 0, version: int = 0) -> ReportKey:
    return ReportKey(tenant, account or tenant, date(2026, 10, 1), date(2026, 10, 31), revision, version)


def test_key_carries_tenant_and_account_so_nobody_can_reach_a_foreign_entry() -> None:
    cache = make_cache()
    a, b = uuid4(), uuid4()
    cache.put(key_of(a), report_of())
    assert cache.get(key_of(a)) is not None
    assert cache.get(key_of(b)) is None  # her şey aynı, yalnız kiracı farklı
    assert cache.get(key_of(a, account=uuid4())) is None  # aynı kiracı, başka hesap
    assert cache.get(key_of(a, revision=1)) is None  # ayar sürümü değişti
    assert cache.get(key_of(a, version=1)) is None  # veri sürümü değişti


def test_ttl_expires_entries_and_zero_ttl_disables_the_cache() -> None:
    clock = FakeClock()
    cache = make_cache(clock)
    key = key_of(uuid4())
    cache.put(key, report_of())
    clock.now += 59
    assert cache.get(key) is not None
    clock.now += 2
    assert cache.get(key) is None and len(cache) == 0 and cache.total_lines == 0
    off = make_cache(ttl_seconds=0)
    off.put(key, report_of())
    assert not off.enabled and len(off) == 0


def test_lru_entry_limit_line_weight_limit_and_oversized_entry() -> None:
    cache = make_cache(max_entries=3, tenant_entries=10)
    tenants = [uuid4() for _ in range(4)]
    for t in tenants[:3]:
        cache.put(key_of(t), report_of())
    assert cache.get(key_of(tenants[0])) is not None  # en eski olan yeniden kullanıldı
    cache.put(key_of(tenants[3]), report_of())
    assert cache.get(key_of(tenants[1])) is None  # en az kullanılan düştü
    assert cache.get(key_of(tenants[0])) is not None and len(cache) == 3
    by_lines = make_cache(max_lines=24, max_entries=16, tenant_entries=10, tenant_lines=6)
    tenants = [uuid4() for _ in range(5)]
    for t in tenants[:4]:
        by_lines.put(key_of(t), report_of(5))  # ağırlık 6: dört kiracı toplam tavana (24) tam sığar
    assert by_lines.total_lines == 24
    by_lines.put(key_of(tenants[4]), report_of(5))  # toplam 30 > 24: eşitlikte en eski kiracı düşer
    assert by_lines.get(key_of(tenants[0])) is None and by_lines.get(key_of(tenants[4])) is not None
    assert by_lines.total_lines == 24
    by_lines.put(key_of(uuid4()), report_of(50))  # tek başına kiracı tavanını aşar: hiç saklanmaz
    assert len(by_lines) == 4


def test_per_tenant_cap_stops_one_tenant_from_evicting_the_others() -> None:
    cache = make_cache(max_entries=8, tenant_entries=2)
    quiet, noisy = uuid4(), uuid4()
    cache.put(key_of(quiet), report_of())
    for revision in range(6):
        cache.put(key_of(noisy, revision=revision), report_of())
    assert cache.get(key_of(quiet)) is not None  # gürültülü kiracı sessizin girdisini dışarı itemedi
    assert sum(1 for k in cache._entries if k.tenant_id == noisy) == 2


async def test_single_flight_shares_one_computation_and_a_failure_is_not_shared() -> None:
    cache = make_cache()
    key = key_of(uuid4())
    started, release, runs, released = asyncio.Event(), asyncio.Event(), [], []

    async def compute() -> Any:
        runs.append(1)
        started.set()
        await release.wait()
        return report_of()

    async def noop() -> None:
        released.append(1)

    leader = asyncio.create_task(cache.get_or_compute(key, compute, noop))
    await started.wait()
    follower = asyncio.create_task(cache.get_or_compute(key, compute, noop))
    await asyncio.sleep(0.01)
    release.set()
    (_, leader_hit), (_, follower_hit) = await leader, await follower
    assert (leader_hit, follower_hit) == (False, True) and len(runs) == 1 and released == [1]

    failing = key_of(uuid4())
    attempts: list[int] = []

    async def boom() -> Any:
        attempts.append(1)
        await asyncio.sleep(0.01)
        raise RuntimeError("hesap hatası")

    results = await asyncio.gather(
        *(cache.get_or_compute(failing, boom, noop) for _ in range(2)), return_exceptions=True
    )
    assert all(isinstance(r, RuntimeError) for r in results) and len(attempts) == 2  # hata paylaşılmadı
    assert cache._inflight == {}  # bekleyen kalmadı


# ================================================================================= API: önbellek


def test_second_identical_request_runs_the_engine_zero_times_and_every_endpoint_shares_it(
    shop: Shop, engine_calls: list[int]
) -> None:
    first = call(shop, "products")
    assert first.status_code == 200 and len(engine_calls) == 1
    again = call(shop, "products")
    assert again.status_code == 200 and again.json() == first.json()
    assert len(engine_calls) == 1  # ikinci çağrıda motor çalışma sayısı 0
    for path in ("orders", "alerts", "summary", f"products/{B1}", "orders/1001"):
        assert call(shop, path).status_code == 200, path
    assert len(engine_calls) == 1  # ürün, sipariş, uyarı, özet ve detay uçları aynı önbelleği paylaştı
    cursor = call(shop, "products", limit=1).json()["next_cursor"]
    assert call(shop, "products", limit=1, cursor=cursor).status_code == 200  # sayfa değişimi de isabet
    assert len(engine_calls) == 1
    other_period = shop.api.get(f"{shop.base}/profit/summary", params={"start": START, "end": "2026-10-30"})
    assert other_period.status_code == 200 and len(engine_calls) == 2  # başka dönem başka anahtar


def test_cached_and_fresh_answers_are_identical(shop: Shop) -> None:
    cached = [call(shop, p).json() for p in ("summary", "orders", "alerts")]
    cache_of(shop).clear()
    fresh = [call(shop, p).json() for p in ("summary", "orders", "alerts")]
    assert cached == fresh


def test_settings_write_bumps_the_revision_and_the_old_result_is_not_served(
    shop: Shop, engine_calls: list[int]
) -> None:
    assert call(shop, "summary").json()["settings_revision"] == 0 and len(engine_calls) == 1
    put = shop.api.put(f"{shop.base}/profit-settings/defaults", {"default_desi": "3"})
    assert put.status_code == 200 and put.json()["revision"] == 1
    after = call(shop, "summary")
    assert after.json()["settings_revision"] == 1 and len(engine_calls) == 2  # yeniden hesaplandı
    assert call(shop, "orders").json()["settings_revision"] == 1 and len(engine_calls) == 2


def test_cost_write_and_cost_import_invalidate_the_cached_result(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    def b2_cost_missing() -> bool:
        rows = {r["barcode"]: r for r in call(shop, "products").json()["items"]}
        return bool(rows[B2]["cost_missing"])

    assert b2_cost_missing() is True and len(engine_calls) == 1  # seed_basic: B2'nin maliyeti yok
    imported = upload(shop, csv_bytes(f"{B2};30,00;20;2026-01-01"), dry_run=False)
    assert imported.status_code == 200 and imported.json()["committed"] is True
    assert b2_cost_missing() is False and len(engine_calls) == 2  # içe aktarma sonrası eski sonuç dönmedi
    put = shop.api.put(
        f"{shop.base}/products/{B2}/costs",
        {"valid_from": "2026-01-01", "unit_cost_excl_vat": "35.00", "vat_rate": 20},
    )
    assert put.status_code == 200
    rows = {r["barcode"]: r for r in call(shop, "products").json()["items"]}
    assert len(engine_calls) == 3 and Decimal(rows[B2]["product_cost"]) == Decimal("35.00")


def test_sync_writes_new_and_updated_rows_invalidate_the_cached_result(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    assert call(shop, "orders").json()["total_count"] == 4 and len(engine_calls) == 1
    # Senkron yazımı (store.py): yeni paket eklenir ya da var olan satır `updated_at = now()` ile güncellenir.
    add_order(
        admin_conn, seller_of(shop), "3333", 33, datetime(2026, 10, 20, 9, tzinfo=UTC),
        lines=[{"line_id": 33, "barcode": B1, "gross": "80.00"}],
    )  # fmt: skip
    assert call(shop, "orders").json()["total_count"] == 5 and len(engine_calls) == 2
    admin_conn.execute(
        "UPDATE order_lines SET line_gross_amount = 999, updated_at = now() "
        "WHERE marketplace_account_id = %s AND line_id = 33",
        (shop.account_id,),
    )
    items = {i["order_number"]: i for i in call(shop, "orders").json()["items"]}
    assert len(engine_calls) == 3 and Decimal(items["3333"]["net_sales_excl_vat"]) > Decimal("500")
    admin_conn.execute(
        "UPDATE financial_transactions SET updated_at = now() WHERE marketplace_account_id = %s",
        (shop.account_id,),
    )
    call(shop, "summary")
    assert len(engine_calls) == 4  # ekstre satırı güncellemesi de sürümü değiştirir


def test_ttl_expiry_recomputes(shop: Shop, engine_calls: list[int]) -> None:
    clock = FakeClock()
    cache_of(shop)._clock = clock
    call(shop, "summary")
    call(shop, "alerts")
    assert len(engine_calls) == 1
    clock.now += 301
    call(shop, "summary")
    assert len(engine_calls) == 2


def test_other_tenant_never_gets_the_cached_result_of_this_tenant(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    """Aynı uygulama (aynı önbellek), aynı dönem ve aynı ayar sürümü: B kendi hesabında kendi sonucunu görür."""
    mine = call(shop, "orders").json()
    assert mine["total_count"] == 4 and len(engine_calls) == 1
    api = shop.api
    api.signup_and_login("b@example.com", tenant="Mağaza B")
    me = api.get("/v1/me").json()
    from tests.product_cost_helpers import add_account

    b_account = add_account(admin_conn, UUID(me["tenant"]["id"]), UUID(me["user_id"]), "9999")
    b_path = f"/v1/marketplace-accounts/{b_account}/profit/orders"
    theirs = api.get(b_path, params=PERIOD)
    assert theirs.status_code == 200 and theirs.json()["total_count"] == 0 and theirs.json()["items"] == []
    assert len(engine_calls) == 2  # B önbellek isabeti almadı
    # A'nın hesabı B'nin oturumuyla yine 404: önbellek yetkilendirmeyi atlamaz.
    foreign = api.get(f"{shop.base}/profit/orders", params=PERIOD)
    assert foreign.status_code == 404 and "1001" not in visible_text(foreign) and len(engine_calls) == 2


def test_cache_hit_skips_the_gate_and_the_rate_limited_gate_still_protects_misses(
    shop: Shop, engine_calls: list[int]
) -> None:
    assert call(shop, "summary").status_code == 200
    gate: ReportGate = shop.api.client.app.state.report_gate  # type: ignore[attr-defined]
    gate._active = gate.process_slots  # süreç yuvaları dolu gibi
    try:
        assert call(shop, "products").status_code == 200  # isabet kapıya girmez
        miss = shop.api.get(f"{shop.base}/profit/summary", params={"start": START, "end": "2026-10-30"})
        assert miss.status_code == 503  # ıska kapıya girer
    finally:
        gate._active = 0
    assert len(engine_calls) == 1


def test_concurrent_identical_requests_share_one_engine_run_without_holding_gate_slots(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_tenant_concurrency=1, **CACHE_ON
    )  # tek yuva: ikinci istek yuva alamazdı
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: list[Any] = []
    first = threading.Thread(target=lambda: out.append(call(shop, "summary")))
    first.start()
    assert engine.started.wait(15)
    second = threading.Thread(target=lambda: out.append(call(shop, "alerts")))
    second.start()
    second.join(0.5)
    assert second.is_alive()  # bekliyor, 429 almadı
    engine.release.set()
    first.join()
    second.join()
    assert [r.status_code for r in out] == [200, 200] and engine.calls == 1


# ================================================================================ YO-01: kapı adaleti


class _Tick:
    """Kapı için sahte saat (süre penceresi testte deterministik)."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def _rejected(gate: ReportGate, tenant: UUID) -> Any:
    from app.core.errors import ProblemError

    with pytest.raises(ProblemError) as caught:
        async with gate.slot(tenant):
            pytest.fail("yuva verilmemeliydi")
    return caught.value


async def test_gate_reserves_the_last_slot_only_while_a_tenant_without_a_slot_is_actually_waiting() -> None:
    tick = _Tick()
    gate = ReportGate(process_slots=4, tenant_slots=2, retry_after_seconds=2, clock=tick)
    a, b, c = uuid4(), uuid4(), uuid4()
    async with gate.slot(a), gate.slot(a), gate.slot(b):
        # OS-06: kimse beklemiyor: B ikinci yuvayı alır (eskiden 429 verirdi).
        async with gate.slot(b):
            assert gate.active == 4
            full = await _rejected(gate, c)  # C yuvasız, süreç dolu: 503 ve artık "bekleyen"
            assert full.status == 503 and full.slug == "report-busy"
        # B bıraktı (3 aktif): son yuva C'ye ayrılmış, B ikinciyi alamaz
        greedy = await _rejected(gate, b)
        assert greedy.status == 429 and greedy.slug == "report-in-progress"
        async with gate.slot(c):  # C yeniden denedi: bekleyen kayıt silinir, üçüncü kiracı starve olmadı
            assert gate.active == 4
        assert gate._starved == {}
        async with gate.slot(b):  # C bitti ve kimse beklemiyor: B yine alabilir
            assert gate.active == 4
    assert gate.active == 0 and gate.active_tenants == 0


async def test_gate_waiting_mark_expires_after_two_retry_after_windows() -> None:
    tick = _Tick()
    gate = ReportGate(process_slots=2, tenant_slots=2, retry_after_seconds=3, clock=tick)
    a, b = uuid4(), uuid4()
    async with gate.slot(a), gate.slot(a):
        await _rejected(gate, b)  # B bekleyen sayıldı
        tick.now += 5.9  # 2 x 3 sn penceresi içinde
        assert gate._other_tenant_waiting(a) is True
        tick.now += 0.2  # pencere aşıldı: B artık gelmiyor, yuva boşuna ayrılmaz
        assert gate._other_tenant_waiting(a) is False
    async with gate.slot(a):  # A tek başına, yuva ayrımı yok
        async with gate.slot(a):
            assert gate.active == 2


async def test_gate_a_lone_tenant_can_use_all_its_slots_even_when_process_slots_equal_tenant_slots() -> None:
    gate = ReportGate(process_slots=2, tenant_slots=2, retry_after_seconds=1)
    only = uuid4()
    async with gate.slot(only), gate.slot(only):  # eskiden ikinci yuva hiç alınamazdı (1 + 1 >= 2)
        assert gate.active == 2
        assert (await _rejected(gate, only)).status == 429  # kiracı yuvaları dolu
    one = ReportGate(process_slots=1, tenant_slots=2, retry_after_seconds=1)
    async with one.slot(only):  # süreç yuvası tek: ikinci istek 503, kendi kendini 429'a kilitlemez
        refused = await _rejected(one, only)
        assert refused.status == 503 and refused.slug == "report-busy"
    assert one.active == 0


# ================================================================================ SU-02, SU-04


def add_split_order(conn: psycopg.Connection[Any], shop: Shop) -> None:
    """Sipariş 3001: paket 31 dönem DIŞI (20 Eylül), paket 32 dönem içi (14 Ekim)."""
    seller = seller_of(shop)
    add_order(conn, seller, "3001", 31, datetime(2026, 9, 20, 9, tzinfo=UTC), lines=[{"line_id": 31, "barcode": B1, "gross": "50.00"}])  # fmt: skip
    add_order(conn, seller, "3001", 32, datetime(2026, 10, 14, 9, tzinfo=UTC), lines=[{"line_id": 32, "barcode": B1, "gross": "70.00"}])  # fmt: skip


def test_su02_ordered_on_and_date_sort_come_from_the_in_period_package(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_split_order(admin_conn, shop)
    items = call(shop, "orders").json()["items"]
    by = {i["order_number"]: i for i in items}
    assert by["3001"]["ordered_on"] == "2026-10-14"  # dönem dışı 2026-09-20 görünmez
    assert by["3001"]["line_count"] == 1  # kart yalnız dönem içi paket
    assert [i["order_number"] for i in items][:2] == ["3001", "1004"]  # yeni önce: 14 Ekim, sonra 8 Ekim
    asc = [i["order_number"] for i in call(shop, "orders", order="asc").json()["items"]]
    assert asc[-1] == "3001"  # eski davranış (Eylül tarihi) onu başa koyardı


def test_su02_period_that_only_contains_the_outside_package_has_no_card(
    shop: Shop, admin_conn: psycopg.Connection[Any]
) -> None:
    add_split_order(admin_conn, shop)
    september = shop.api.get(
        f"{shop.base}/profit/orders", params={"start": "2026-09-15", "end": "2026-09-25", "q": "3001"}
    ).json()
    assert [i["order_number"] for i in september["items"]] == ["3001"]
    assert september["items"][0]["ordered_on"] == "2026-09-20" and september["items"][0]["line_count"] == 1


def test_su04_nonexistent_or_out_of_period_or_foreign_search_does_not_run_the_engine(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    add_split_order(admin_conn, shop)
    body = call(shop, "orders", q="NOYOK-1").json()
    assert body["total_count"] == 0 and body["items"] == [] and body["next_cursor"] is None
    assert body["q"] == "NOYOK-1" and body["settings_revision"] == 0 and len(engine_calls) == 0
    assert call(shop, "orders", q="3001", start="2026-08-01", end="2026-08-31").json()["items"] == []
    assert len(engine_calls) == 0  # sipariş var ama bu dönemde paketi yok
    # Başka kiracının sipariş numarası: kiracı/hesap süzgeci nedeniyle "yok" ve motor yok.
    other = shop.api  # aynı oturum, başka hesap kimliği (var olmayan) 404; sipariş numarası sızmaz
    assert (
        other.get(
            f"/v1/marketplace-accounts/{uuid4()}/profit/orders", params={**PERIOD, "q": "1001"}
        ).status_code
        == 404
    )
    hit = call(shop, "orders", q="1001").json()
    assert [i["order_number"] for i in hit["items"]] == ["1001"] and len(
        engine_calls
    ) == 1  # var olan arama motor çalıştırır


def test_su04_net_profit_sort_fetches_dates_only_for_the_page(
    shop: Shop, monkeypatch: pytest.MonkeyPatch
) -> None:
    sizes: list[int] = []
    real = views.order_dates

    async def spy(db: Any, tenant: Any, account: Any, numbers: Any, lower: Any, upper: Any) -> Any:
        sizes.append(len(numbers))
        return await real(db, tenant, account, numbers, lower, upper)

    monkeypatch.setattr(views, "order_dates", spy)
    page = call(shop, "orders", sort="net_profit", limit=2).json()
    assert len(page["items"]) == 2 and page["total_count"] == 4 and sizes == [2]
    sizes.clear()
    call(shop, "orders", sort="date", limit=2)
    assert sizes == [4]  # tarih sıralaması tüm satırların anını ister


# ======================================================================= SU-05: kalem dökümü


def test_su05_unexpected_deduction_breakdown_is_derived_from_the_engine_comparison() -> None:
    seen = 0
    for name, result in all_results():
        lines = {(line.order_number, line.line_id): line for line in result.lines}
        for alert in views.build_alerts(result):
            if alert.code is not WarningCode.UNEXPECTED_DEDUCTION:
                assert alert.breakdown is None and alert.default_desi_used is None, name
                continue
            seen += 1
            line = lines[(alert.order_number or "", alert.line_id or 0)]
            comparison = line.comparison
            assert comparison is not None and alert.breakdown is not None, name
            assert [b.item for b in alert.breakdown] == [
                "commission",
                "outbound_shipping",
                "platform_service_fee",
            ]
            compared = [b for b in alert.breakdown if b.compared]
            assert (
                sum(b.difference or Decimal(0) for b in compared) == alert.difference == comparison.difference
            )
            assert sum(b.estimated or Decimal(0) for b in compared) == comparison.compared_estimated_total
            assert sum(b.actual or Decimal(0) for b in compared) == comparison.compared_actual_total
            for b in alert.breakdown:
                if not b.compared:
                    assert b.difference is None
            assert alert.default_desi_used is comparison.shipping_estimate_default_desi, name
    assert seen > 0, "altın senaryolarda BEKLENMEYEN_KESINTI yok: test boş geçmemeli"


def test_su05_alert_schema_fields_are_optional_and_additive() -> None:
    from app.api.v1.profit_schemas import AlertOut

    legacy = AlertOut(code=WarningCode.LOSS, scope="line", message="m")
    assert legacy.breakdown is None and legacy.default_desi_used is None
    body = AlertOut.model_validate(
        {
            "code": WarningCode.UNEXPECTED_DEDUCTION,
            "scope": "line",
            "message": "m",
            "difference": Decimal("12.5"),
            "default_desi_used": True,
            "breakdown": [
                {
                    "item": "commission",
                    "estimated": Decimal("10"),
                    "actual": Decimal("22.5"),
                    "compared": True,
                    "difference": Decimal("12.5"),
                }
            ],
        }
    ).model_dump(mode="json")
    assert body["breakdown"][0] == {
        "item": "commission", "estimated": "10.00", "actual": "22.50", "compared": True, "difference": "12.50",
    }  # fmt: skip
    assert body["default_desi_used"] is True


# =========================================================== OS-01, OS-02, OS-10: birim (ReportCache)


async def _three_concurrent(cache: ReportCache, key: ReportKey, lines: int) -> tuple[list[Any], list[int]]:
    runs: list[int] = []
    gate = asyncio.Event()

    async def compute() -> Any:
        runs.append(1)
        await gate.wait()
        return report_of(lines)

    async def noop() -> None:
        return None

    tasks = [asyncio.create_task(cache.get_or_compute(key, compute, noop)) for _ in range(3)]
    await asyncio.sleep(0.02)
    gate.set()
    return list(await asyncio.gather(*tasks)), runs


async def test_os01_unstored_oversized_result_is_still_shared_by_single_flight() -> None:
    cache = make_cache(max_lines=100, tenant_lines=10)  # 50 satırlık sonuç kiracı tavanını aşar: saklanmaz
    key = key_of(uuid4())
    results, runs = await _three_concurrent(cache, key, 50)
    assert len(runs) == 1  # motor 1 kez (eskiden 3 kez, sırayla)
    assert results[0][0] is results[1][0] is results[2][0]  # üçü de aynı sonuç nesnesi
    assert sorted(hit for _, hit in results) == [False, True, True]
    assert len(cache) == 0 and cache.get(key) is None  # sonuç saklanmadı
    assert cache._inflight == {}
    again, _ = await cache.get_or_compute(key, lambda: _async(report_of(50)), _noop)
    assert again is not results[0][0]  # sonraki istek saklanmadığı için yeniden hesaplar


async def _async(value: Any) -> Any:
    return value


async def _noop() -> None:
    return None


async def test_os01_leader_failure_is_not_shared_waiters_retry_on_their_own_even_when_nothing_is_stored() -> (
    None
):
    cache = make_cache()
    key = key_of(uuid4())
    attempts: list[int] = []
    release = asyncio.Event()

    async def flaky() -> Any:
        attempts.append(1)
        if len(attempts) == 1:
            await release.wait()
            raise RuntimeError("ilk hesap düştü")
        return report_of(2)

    leader = asyncio.create_task(cache.get_or_compute(key, flaky, _noop))
    await asyncio.sleep(0.01)
    follower = asyncio.create_task(cache.get_or_compute(key, flaky, _noop))
    await asyncio.sleep(0.01)
    release.set()
    with pytest.raises(RuntimeError):
        await leader  # hata yalnız hesaplayana gider
    report, shared = await follower  # bekleyen hatayı almaz, kendi hesabını yapar
    assert len(attempts) == 2 and shared is False and report is not None and cache._inflight == {}


async def test_os01_cancelled_leader_does_not_wedge_waiters() -> None:
    cache = make_cache()
    key = key_of(uuid4())
    started = asyncio.Event()

    async def hang() -> Any:
        started.set()
        await asyncio.Event().wait()

    leader = asyncio.create_task(cache.get_or_compute(key, hang, _noop))
    await started.wait()
    follower = asyncio.create_task(cache.get_or_compute(key, lambda: _async(report_of(1)), _noop))
    await asyncio.sleep(0.01)
    leader.cancel()
    report, shared = await asyncio.wait_for(follower, 5)
    assert report is not None and shared is False  # bekleyen devraldı, kilitlenmedi


async def test_os10_waiter_gives_up_with_503_after_the_wait_limit_while_the_leader_finishes() -> None:
    from app.core.errors import ProblemError

    cache = make_cache(wait_seconds=0.05)
    key = key_of(uuid4())
    started, release = asyncio.Event(), asyncio.Event()

    async def slow() -> Any:
        started.set()
        await release.wait()
        return report_of(1)

    leader = asyncio.create_task(cache.get_or_compute(key, slow, _noop))
    await started.wait()
    with pytest.raises(ProblemError) as caught:
        await cache.get_or_compute(key, slow, _noop)
    assert caught.value.status == 503 and caught.value.slug == "report-wait-timeout"
    assert int(caught.value.headers["Retry-After"]) >= 1
    assert not leader.done() and key in cache._inflight  # bekleyenin zaman aşımı ortak hesabı iptal etmedi
    release.set()
    await leader
    hit, was_hit = await cache.get_or_compute(key, slow, _noop)
    assert was_hit is True and hit is not None  # yeniden deneyen isabet alır


def test_os02_one_tenant_with_four_big_periods_cannot_evict_the_others_poc_scenario() -> None:
    """Denetim PoC 2: varsayılan ayarlar (16 girdi, 40.000 satır, kiracı başına 4 girdi)."""
    cache = ReportCache(ttl_seconds=60, max_entries=16, max_lines=40_000, tenant_entries=4)
    assert cache.tenant_lines == 10_000  # varsayılan: toplamın dörtte biri
    victims = [uuid4() for _ in range(5)]
    for v in victims:
        cache.put(key_of(v), report_of(999))  # 1.000'er satır
    noisy = uuid4()
    for revision in range(4):  # tek kiracı, tek hesap, 4 dönem x 9.998 satır
        cache.put(key_of(noisy, revision=revision), report_of(9_997))
    assert all(cache.get(key_of(v)) is not None for v in victims)  # kurbanların 5'i de yerinde
    assert cache.tenant_weight(noisy) <= cache.tenant_lines
    assert sum(1 for k in cache._entries if k.tenant_id == noisy) == 1  # kendi eski girdilerini düşürdü
    assert cache.get(key_of(noisy, revision=3)) is not None  # en yenisi kaldı
    assert cache.total_lines <= cache.max_lines


def test_os02_tenant_evicts_only_its_own_entries_and_oversized_single_result_is_not_stored() -> None:
    cache = make_cache(max_lines=1000, tenant_lines=100, tenant_entries=10)
    a, b = uuid4(), uuid4()
    cache.put(key_of(b), report_of(30))
    for revision in range(5):
        cache.put(
            key_of(a, revision=revision), report_of(39)
        )  # ağırlık 40: kiracı tavanı 100'e 2 girdi sığar
    assert cache.get(key_of(b)) is not None
    assert [k.settings_revision for k in cache._entries if k.tenant_id == a] == [3, 4]
    cache.put(key_of(a, revision=9), report_of(100))  # ağırlık 101 > 100: saklanmaz, başkasına dokunmaz
    assert cache.get(key_of(a, revision=9)) is None and cache.get(key_of(b)) is not None
    assert cache.get(key_of(a, revision=4)) is not None  # kendi girdileri de düşmedi


def test_os02_when_the_global_cap_is_full_the_tenant_with_the_most_lines_loses_an_entry() -> None:
    cache = make_cache(max_lines=100, tenant_lines=25, tenant_entries=10)  # kiracı tavanı 100 // 4 = 25
    heavy, mid, mid2, mid3, small, newcomer = (uuid4() for _ in range(6))
    cache.put(key_of(small), report_of(4))  # ağırlık 5, en eski girdi
    cache.put(key_of(heavy), report_of(24))  # 25
    for t in (mid, mid2, mid3):
        cache.put(key_of(t), report_of(19))  # 20 x 3: toplam 90
    cache.put(key_of(newcomer), report_of(14))  # 15: toplam 105 > 100 -> en çok tutan (heavy) düşer
    assert cache.get(key_of(heavy)) is None
    for kept in (
        small,
        mid,
        mid2,
        mid3,
        newcomer,
    ):  # en eski olan küçük kiracı korundu (eskiden ilk o düşerdi)
        assert cache.get(key_of(kept)) is not None
    assert cache.total_lines == 80


def test_os05_expired_entries_are_swept_on_put_and_do_not_evict_live_ones() -> None:
    clock = FakeClock()
    cache = make_cache(clock, max_lines=40, tenant_lines=10, tenant_entries=10)
    live = uuid4()
    for _ in range(4):
        cache.put(key_of(uuid4()), report_of(9))  # 10 x 4: toplam tavan (40) dolu
    clock.now += 61  # süresi doldu ama kimse okumadı
    cache.put(key_of(live), report_of(9))
    assert cache.total_lines == 10 and len(cache) == 1 and cache.get(key_of(live)) is not None


def test_ok03_lowering_max_lines_still_keeps_one_tenant_from_evicting_the_others() -> None:
    """OK-03: `max_lines=8000` ve eski varsayılan `tenant_lines=10_000` iken kiracı tavanı 8000 olup tek kiracı
    önbelleğin tamamını doldurabiliyordu. Etkin kiracı tavanı her zaman `max_lines // 4`tür."""
    cache = ReportCache(
        ttl_seconds=60, max_entries=16, max_lines=8_000, tenant_entries=4, tenant_lines=10_000
    )
    assert cache.tenant_lines == 2_000
    assert (
        ReportCache(ttl_seconds=60, max_entries=16, max_lines=8_000, tenant_entries=4).tenant_lines == 2_000
    )
    victims = [uuid4() for _ in range(3)]
    for v in victims:
        cache.put(key_of(v), report_of(999))  # 1.000'er satır
    noisy = uuid4()
    for revision in range(6):  # tek kiracı, 6 dönem x 1.999 satır: tavanı (2.000) aşan kendi eskisini düşürür
        cache.put(key_of(noisy, revision=revision), report_of(1_998))
    assert all(cache.get(key_of(v)) is not None for v in victims)
    assert cache.tenant_weight(noisy) <= 2_000
    assert sum(1 for k in cache._entries if k.tenant_id == noisy) == 1
    cache.put(key_of(noisy, revision=99), report_of(2_000))  # 2.001 > 2.000: hiç saklanmaz
    assert cache.get(key_of(noisy, revision=99)) is None
    assert all(cache.get(key_of(v)) is not None for v in victims)
    assert cache.total_lines <= cache.max_lines


def test_ok03_default_settings_keep_the_10000_line_tenant_cap() -> None:
    cache = ReportCache(
        ttl_seconds=60, max_entries=16, max_lines=40_000, tenant_entries=4, tenant_lines=10_000
    )
    assert cache.tenant_lines == 10_000


async def test_ok05_a_stuck_compute_is_cancelled_and_frees_the_inflight_entry_and_the_gate_slot() -> None:
    from app.core.errors import ProblemError

    gate = ReportGate(process_slots=2, tenant_slots=1, retry_after_seconds=7)
    cache = make_cache(wait_seconds=0.05, compute_timeout_seconds=0.1, retry_after_seconds=7)
    tenant = uuid4()
    key = key_of(tenant)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def stuck() -> Any:
        async with gate.slot(tenant):
            started.set()
            try:
                await asyncio.Event().wait()  # hiç bitmeyen hesap
            except asyncio.CancelledError:
                cancelled.set()
                raise

    with pytest.raises(ProblemError) as caught:
        await asyncio.wait_for(cache.get_or_compute(key, stuck, _noop), 5)
    assert started.is_set() and cancelled.is_set()
    assert caught.value.status == 503 and caught.value.slug == "report-compute-timeout"
    assert caught.value.headers["Retry-After"] == "7"  # OK-11: sabit değil, ayardan
    assert cache._inflight == {} and gate.active == 0 and gate.active_tenants == 0
    assert cache.get(key) is None  # hata saklanmaz
    report, hit = await cache.get_or_compute(
        key, lambda: _async(report_of(1)), _noop
    )  # yeniden deneme çalışır
    assert report is not None and hit is False


async def test_ok05_compute_timeout_does_not_translate_foreign_timeouts_and_can_be_disabled() -> None:
    cache = make_cache(compute_timeout_seconds=5)

    async def foreign() -> Any:
        raise TimeoutError("başka yerden")

    with pytest.raises(TimeoutError, match="başka yerden"):
        await cache.get_or_compute(key_of(uuid4()), foreign, _noop)
    unlimited = make_cache()  # None = sınırsız (birim testleri)
    report, _ = await unlimited.get_or_compute(key_of(uuid4()), lambda: _async(report_of(1)), _noop)
    assert report is not None


async def test_ok11_wait_timeout_retry_after_comes_from_the_setting() -> None:
    from app.core.errors import ProblemError

    cache = make_cache(wait_seconds=0.05, retry_after_seconds=9)
    key = key_of(uuid4())
    started, release = asyncio.Event(), asyncio.Event()

    async def slow() -> Any:
        started.set()
        await release.wait()
        return report_of(1)

    leader = asyncio.create_task(cache.get_or_compute(key, slow, _noop))
    await started.wait()
    with pytest.raises(ProblemError) as caught:
        await cache.get_or_compute(key, slow, _noop)
    assert caught.value.slug == "report-wait-timeout" and caught.value.headers["Retry-After"] == "9"
    release.set()
    await leader


async def test_ok11_starved_records_are_swept_on_the_503_branch_too() -> None:
    from app.core.errors import ProblemError

    clock = FakeClock()
    gate = ReportGate(process_slots=1, tenant_slots=1, retry_after_seconds=2, clock=clock)
    holder, gone, newcomer = uuid4(), uuid4(), uuid4()
    async with gate.slot(holder):
        with pytest.raises(ProblemError):
            async with gate.slot(gone):
                pass
        assert set(gate._starved) == {gone}
        clock.now += 100  # `gone` yeniden denemedi: kaydı bayatladı
        with pytest.raises(ProblemError):
            async with gate.slot(newcomer):  # yalnız 503 dalı çalışır; eski kayıt orada temizlenir
                pass
        assert set(gate._starved) == {newcomer}


# ======================================================================= OS-01/02, YO-01: HTTP


def _threads_started(*threads: threading.Thread) -> None:
    for t in threads:
        t.start()


def test_os01_http_three_concurrent_requests_share_one_engine_run_even_when_the_result_is_not_stored(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_cache_tenant_lines=1, **CACHE_ON
    )  # tavan 1 satır: hiçbir sonuç saklanmaz
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: list[Any] = []
    threads = [
        threading.Thread(target=lambda p=p: out.append(call(shop, p)))
        for p in ("summary", "products", "alerts")
    ]
    threads[0].start()
    assert engine.started.wait(15)
    _threads_started(*threads[1:])
    threads[1].join(0.5)
    assert threads[1].is_alive() and threads[2].is_alive()  # bekliyorlar: 429/503 almadılar, ayrı motor yok
    engine.release.set()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in out) == [200, 200, 200] and engine.calls == 1
    assert len(cache_of(shop)) == 0  # sonuç saklanmadı
    assert call(shop, "summary").status_code == 200 and engine.calls == 2  # saklanmadığı için yeniden hesap


def _extra_client(shop: Shop, email: str, tenant: str, seller: str, conn: psycopg.Connection[Any]) -> Shop:
    """Aynı uygulamaya (aynı kapı ve önbellek) bağlı İKİNCİ kiracı: ayrı çerez kavanozlu istemci."""
    from fastapi.testclient import TestClient

    from tests.product_cost_helpers import add_account

    client = TestClient(shop.api.client.app, base_url="https://testserver", client=("testclient", 50001))
    api = Api(client)
    api.signup_and_login(email, tenant=tenant)
    me = api.get("/v1/me").json()
    tenant_id, user_id = UUID(me["tenant"]["id"]), UUID(me["user_id"])
    account = add_account(conn, tenant_id, user_id, seller)
    return Shop(api, tenant_id, user_id, account)


def test_os02_http_noisy_tenant_walking_periods_does_not_evict_another_tenants_cached_result(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    cache = cache_of(shop)
    other = _extra_client(shop, "b@example.com", "Mağaza B", "9999", admin_conn)
    add_order(
        admin_conn, seller_of(other), "9001", 9001, datetime(2026, 10, 12, 9, tzinfo=UTC),
        lines=[{"line_id": 9001, "barcode": B1, "gross": "60.00"}],
    )  # fmt: skip
    ends = ("2026-10-31", "2026-10-30", "2026-10-29", "2026-10-28", "2026-10-27")

    def a_summary(end: str) -> Any:
        return shop.api.get(f"{shop.base}/profit/summary", params={"start": START, "end": end})

    weights = []
    for end in ends:  # her dönemin gerçek ağırlığı (boş önbellekte tek girdi)
        cache.clear()
        assert a_summary(end).status_code == 200
        weights.append(cache.total_lines)
    cache.clear()
    assert call(other, "orders").status_code == 200
    b_weight = cache.total_lines
    w_max = max(weights)
    # Genel tavan B + A'nın iki girdisi; kiracı tavanı A'ya üç girdi tanır: A'nın üçüncüsü GENEL taşma yaratır.
    # Eski kural en eski girdiyi (B'nin) düşürürdü; adil kural en çok tutan kiracıyı (A) kendi içinden düşürür.
    cache.tenant_entries = 10
    cache.tenant_lines = 3 * w_max
    cache.max_lines = b_weight + 2 * w_max
    runs = len(engine_calls)
    for end in ends:
        assert a_summary(end).status_code == 200
    assert len(engine_calls) == runs + len(ends)  # A'nın her dönemi ilk kez hesaplandı
    assert cache.tenant_weight(shop.tenant_id) <= cache.max_lines - b_weight
    before = len(engine_calls)
    assert call(other, "orders").status_code == 200
    assert len(engine_calls) == before  # B'nin sonucu hâlâ önbellekte: A onu düşüremedi


def _wait_for(predicate: Callable[[], bool], seconds: float = 15.0) -> bool:
    import time

    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_os06_http_lone_tenant_gets_its_second_slot_when_process_slots_equal_tenant_slots(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_tenant_concurrency=2, profit_report_process_concurrency=2,
        **CACHE_ON,
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: list[Any] = []
    first = threading.Thread(target=lambda: out.append(call(shop, "summary")))
    second = threading.Thread(  # farklı dönem: farklı anahtar, tek uçuş birleştirmez, kapıdan geçer
        target=lambda: out.append(
            shop.api.get(f"{shop.base}/profit/summary", params={"start": START, "end": "2026-10-30"})
        )
    )
    first.start()
    assert engine.started.wait(15)
    second.start()
    assert _wait_for(lambda: engine.calls == 2)  # ikisi de motorda: ikinci istek 429 almadı
    engine.release.set()
    first.join()
    second.join()
    assert sorted(r.status_code for r in out) == [200, 200]


def test_yo01_http_last_slot_is_reserved_only_for_a_tenant_that_was_actually_turned_away(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop_a = make_shop(
        "a@example.com", "Mağaza A", profit_report_tenant_concurrency=2, profit_report_process_concurrency=2,
        profit_report_retry_after_seconds=60, **CACHE_ON,
    )  # fmt: skip
    seed_basic(admin_conn, shop_a)
    shop_b = _extra_client(shop_a, "b@example.com", "Mağaza B", "9999", admin_conn)
    shop_c = _extra_client(shop_a, "c@example.com", "Mağaza C", "8888", admin_conn)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: dict[str, Any] = {}

    def run(name: str, shop: Shop, end: str) -> threading.Thread:
        return threading.Thread(
            target=lambda: out.__setitem__(
                name, shop.api.get(f"{shop.base}/profit/summary", params={"start": START, "end": end})
            )
        )

    a1, b1 = run("a1", shop_a, "2026-10-31"), run("b1", shop_b, "2026-10-31")
    a1.start()
    assert engine.started.wait(15)
    b1.start()
    assert _wait_for(lambda: engine.calls == 2)  # süreç dolu (2/2)
    c_first = shop_c.api.get(f"{shop_c.base}/profit/summary", params={"start": START, "end": END})
    assert c_first.status_code == 503  # C yuvasız ve süreç dolu: bekleyen sayıldı
    gate: ReportGate = shop_a.api.client.app.state.report_gate  # type: ignore[attr-defined]
    assert shop_c.tenant_id in gate._starved
    engine.release.set()
    a1.join()
    b1.join()
    assert out["a1"].status_code == out["b1"].status_code == 200
    gate._active = 1  # A bir yuva tutuyormuş gibi (yalnız kapı durumu): son yuva C'ye ayrılmış olmalı
    gate._per_tenant[shop_a.tenant_id] = 1
    try:
        greedy = shop_a.api.get(f"{shop_a.base}/profit/summary", params={"start": START, "end": "2026-10-29"})
        assert greedy.status_code == 429 and greedy.json()["type"].endswith("report-in-progress")
        retry = shop_c.api.get(f"{shop_c.base}/profit/summary", params={"start": START, "end": END})
        assert retry.status_code == 200  # C'nin yeniden denemesi ayrılmış yuvayı buldu
    finally:
        gate._active = 0
        gate._per_tenant.clear()
    assert gate._starved == {}


# ================================================================================ OS-07: boşluklar


def test_os07_removed_at_flag_invalidates_the_cached_result(
    shop: Shop, admin_conn: psycopg.Connection[Any], engine_calls: list[int]
) -> None:
    """Senkron `removed_at` ile yalnız işaretler (satır silinmez, `updated_at` ayrıca yazılmasa da sürüm değişir)."""
    before = call(shop, "orders").json()
    assert before["total_count"] == 4 and len(engine_calls) == 1
    assert call(shop, "orders").json() == before and len(engine_calls) == 1  # isabet
    flagged = admin_conn.execute(
        "UPDATE order_lines SET removed_at = now() WHERE marketplace_account_id = %s AND line_id = 1",
        (shop.account_id,),
    ).rowcount
    assert flagged == 1
    after = call(shop, "orders").json()
    assert len(engine_calls) == 2  # yeniden hesaplandı
    assert after != before and "1001" not in {
        i["order_number"] for i in after["items"] if i["line_count"] > 0
    }


def test_os07_waiters_that_hit_the_cache_after_waiting_can_still_touch_the_database(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bekleyen, bekleme öncesi bağlantıyı iade eder; isabet sonrası orders, products ve detay uçları RLS bağlamını
    yeniden kurup veritabanına (başlık, tarih) dokunur: sonuç, önbelleksiz sıralı çağrıyla aynıdır."""
    shop = make_shop("a@example.com", "Mağaza A", **CACHE_ON)
    seed_basic(admin_conn, shop)
    paths = ["summary", "orders", "products", f"products/{B1}", "orders/1001", "alerts"]
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: dict[str, Any] = {}
    threads = {p: threading.Thread(target=lambda p=p: out.__setitem__(p, call(shop, p))) for p in paths}
    threads["summary"].start()
    assert engine.started.wait(15)
    for p in paths[1:]:
        threads[p].start()
    threads["orders"].join(0.5)
    assert all(threads[p].is_alive() for p in paths[1:])  # hepsi tek uçuşu bekliyor
    engine.release.set()
    for t in threads.values():
        t.join()
    assert engine.calls == 1 and all(r.status_code == 200 for r in out.values())
    cache_of(shop).clear()
    for p in paths:  # önbelleksiz sıralı sonuçla aynı gövde
        assert call(shop, p).json() == out[p].json(), p
    assert (
        "Ürün Bir" in out["products"].text and "Ürün Bir" in out[f"products/{B1}"].text
    )  # başlık DB'den geldi


# ======================================================================= OK-05: HTTP hesap zaman aşımı


def test_ok05_http_stuck_engine_times_out_with_503_and_keeps_the_slot_until_the_thread_really_ends(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DK-01: istek zamanında 503 alır ve uçuş kaydı silinir, ama kapı yuvası terk edilen motor iş parçacığı
    bitene dek DOLU kalır: yeni hesap kapasiteyi aşamaz (503 report-busy), motor bitince yuva serbest kalır."""
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_compute_timeout_seconds=1.0,
        profit_report_cache_wait_seconds=0.5, profit_report_retry_after_seconds=3,
        profit_report_process_concurrency=1, profit_report_tenant_concurrency=2, **CACHE_ON,
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    gate: ReportGate = shop.api.client.app.state.report_gate  # type: ignore[attr-defined]
    try:
        stuck = call(shop, "summary")
        assert engine.started.is_set() and engine.calls == 1
        assert stuck.status_code == 503 and stuck.json()["type"].endswith("report-compute-timeout")
        assert stuck.headers["Retry-After"] == "3"
        assert (
            cache_of(shop)._inflight == {} and len(cache_of(shop)) == 0
        )  # uçuş kaydı silindi, hata saklanmadı
        assert gate.active == 1 and gate.active_tenants == 1  # motor hâlâ bloke: yuva tutuluyor
        busy = call(shop, "summary")  # ikinci hesap kapasiteyi aşamaz, yeni motor başlamaz
        assert busy.status_code == 503 and busy.json()["type"].endswith("report-busy")
        assert engine.calls == 1
    finally:
        engine.release.set()  # takılan iş parçacığı biter
    assert _wait_for(lambda: gate.active == 0)  # bitince yuva serbest kaldı
    assert gate.active_tenants == 0
    ok = call(shop, "summary")
    assert ok.status_code == 200 and engine.calls == 2


def test_ok05_http_report_transaction_gets_a_database_side_statement_timeout(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_compute_timeout_seconds=7.0,
        profit_report_cache_wait_seconds=1.0, **CACHE_ON,
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    seen: list[str] = []
    original = profit_feed.build_profit_input

    async def spying(db: Any, *args: Any, **kwargs: Any) -> Any:
        from sqlalchemy import text

        seen.append((await db.execute(text("SHOW statement_timeout"))).scalar_one())
        return await original(db, *args, **kwargs)

    monkeypatch.setattr(profit_report, "build_profit_input", spying)
    assert call(shop, "summary").status_code == 200
    assert (
        seen == ["2s"]
    )  # compute 7 sn, deyim sınırı 5 sn kısa (DK-05); işlem yerel: besleyici okumaları sınırlı oturumda çalıştı


def test_ok05_http_statement_timeout_in_the_feed_becomes_the_same_503(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = make_shop(
        "a@example.com", "Mağaza A", profit_report_compute_timeout_seconds=30.0, **CACHE_ON
    )  # fmt: skip
    seed_basic(admin_conn, shop)
    gate: ReportGate = shop.api.client.app.state.report_gate  # type: ignore[attr-defined]

    async def slow_query(db: Any, *args: Any, **kwargs: Any) -> Any:
        from sqlalchemy import text

        await db.execute(text("SET LOCAL statement_timeout = 100"))  # sınır küçültülüp sorgu uyutulur
        await db.execute(text("SELECT pg_sleep(5)"))
        raise AssertionError("deyim sınırı çalışmadı")

    monkeypatch.setattr(profit_report, "build_profit_input", slow_query)
    resp = call(shop, "summary")
    assert resp.status_code == 503 and resp.json()["type"].endswith("report-compute-timeout")
    assert int(resp.headers["Retry-After"]) >= 1
    assert gate.active == 0 and cache_of(shop)._inflight == {}


async def test_dk01_deferred_slot_is_released_only_by_the_handle_and_release_is_idempotent() -> None:
    gate = ReportGate(process_slots=2, tenant_slots=2, retry_after_seconds=2)
    tenant = uuid4()
    async with gate.slot(tenant) as handle:
        handle.defer()
    assert gate.active == 1  # çıkış bırakmadı (iş parçacığına devredildi)
    handle.release()
    handle.release()
    assert gate.active == 0 and gate.active_tenants == 0


def test_dk04_statement_timeout_in_the_settings_read_becomes_the_same_503(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import profit as profit_api

    shop = make_shop("a@example.com", "Mağaza A", **CACHE_ON)
    seed_basic(admin_conn, shop)

    async def slow_settings(db: Any, *args: Any, **kwargs: Any) -> Any:
        from sqlalchemy import text

        await db.execute(text("SET LOCAL statement_timeout = 100"))
        await db.execute(text("SELECT pg_sleep(5)"))
        raise AssertionError("deyim sınırı çalışmadı")

    monkeypatch.setattr(profit_api, "load_profit_settings", slow_settings)
    resp = call(shop, "summary")
    assert resp.status_code == 503 and resp.json()["type"].endswith("report-compute-timeout")
    assert int(resp.headers["Retry-After"]) >= 1
