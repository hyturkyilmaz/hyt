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
from app.services import profit_report
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


def key_of(tenant: UUID, account: UUID | None = None, revision: int = 0, version: Any = ()) -> ReportKey:
    return ReportKey(tenant, account or tenant, date(2026, 10, 1), date(2026, 10, 31), revision, version)


def test_key_carries_tenant_and_account_so_nobody_can_reach_a_foreign_entry() -> None:
    cache = make_cache()
    a, b = uuid4(), uuid4()
    cache.put(key_of(a), report_of())
    assert cache.get(key_of(a)) is not None
    assert cache.get(key_of(b)) is None  # her şey aynı, yalnız kiracı farklı
    assert cache.get(key_of(a, account=uuid4())) is None  # aynı kiracı, başka hesap
    assert cache.get(key_of(a, revision=1)) is None  # ayar sürümü değişti
    assert cache.get(key_of(a, version=(("orders", "x", 1),))) is None  # veri sürümü değişti


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
    by_lines = make_cache(max_lines=10, tenant_entries=10)
    first, second = uuid4(), uuid4()
    by_lines.put(key_of(first), report_of(5))  # ağırlık 6
    by_lines.put(key_of(second), report_of(5))  # toplam 12 > 10: ilk düşer
    assert by_lines.get(key_of(first)) is None and by_lines.get(key_of(second)) is not None
    assert by_lines.total_lines == 6
    by_lines.put(key_of(uuid4()), report_of(50))  # tek başına tavanı aşar: hiç saklanmaz
    assert len(by_lines) == 1


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


async def test_gate_reserves_the_last_process_slot_for_a_tenant_without_any_slot() -> None:
    gate = ReportGate(process_slots=4, tenant_slots=2, retry_after_seconds=1)
    a, b, c = uuid4(), uuid4(), uuid4()
    from app.core.errors import ProblemError

    async with gate.slot(a), gate.slot(a), gate.slot(b):
        with pytest.raises(ProblemError) as greedy:  # B ikinci yuvayı isterse son yuva C'ye ayrılmış
            async with gate.slot(b):
                pytest.fail("son yuva yuvasız kiracıya ayrılmalı")
        assert greedy.value.status == 429 and greedy.value.slug == "report-in-progress"
        async with gate.slot(c):  # üçüncü kiracı starve olmadı
            assert gate.active == 4
    assert gate.active == 0 and gate.active_tenants == 0


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
