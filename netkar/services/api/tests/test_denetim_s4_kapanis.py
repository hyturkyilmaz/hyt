"""S4 denetim kapanışı: Y-01 (havuz kilitlenmesi), O-01 (kısmi), D-01, D-02, B-01 ve panel alanları.

Eşzamanlılık testleri CI yüküne dayanıklıdır: süre eşikleri geniştir, sıra olaylarla (Event) kurulur ve
sabit pencereli sınırlayıcıyı kesin sayan testler `frozen_ratelimit_clock` kullanır. Motoru bekleten
testler `tracemalloc` altında süre ölçmez.
"""

from __future__ import annotations

import asyncio
import base64
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings
from app.core.crypto import derive_key
from app.core.errors import ProblemError
from app.core.ratelimit import RateLimiter
from app.profit import calculate_profit
from app.profit.enums import Status, WarningCode
from app.profit.results import MissingCounts
from app.services import product_costs as costs_service
from app.services import profit_report
from app.services import profit_views as views
from app.services.report_gate import ReportGate
from tests.conftest import Api
from tests.product_cost_helpers import Shop, add_account, fixed_today, make_shop_factory  # noqa: F401
from tests.report_helpers import B1, B2, B3, END, START, add_order, add_sale, seed_basic, seller_of
from tests.test_report_units import all_results, golden_result, synthetic_rows

pytestmark = pytest.mark.usefixtures("fixed_today")
D = Decimal
PERIOD = {"start": START, "end": END}


@pytest.fixture
def make_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    return make_shop_factory(make_api, admin_conn)


def call(shop: Shop, path: str, **params: Any) -> Any:
    return shop.api.get(f"{shop.base}/profit/{path}", params={**PERIOD, **params})


def burst(n: int, fn: Callable[[], Any]) -> tuple[list[Any], float]:
    """n iş parçacığı bir bariyerde bekleyip AYNI ANDA `fn` çağırır; (yanıtlar, toplam süre)."""
    out: list[Any] = []
    barrier = threading.Barrier(n)

    def one() -> None:
        barrier.wait()
        out.append(fn())

    threads = [threading.Thread(target=one) for _ in range(n)]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out, time.perf_counter() - started


def slug(response: Any) -> str:
    return str(response.json().get("type", "")).rsplit(":", 1)[-1]


class BlockedEngine:
    """Motoru bir olay gelene dek bekleten sahte: kapı, bağlantı ve işlem durumu bu sırada gözlenir."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, profit_input: Any) -> Any:
        self.calls += 1
        self.started.set()
        assert self.release.wait(30), "motor serbest bırakılmadı"
        return calculate_profit(profit_input)


def seeded_shop(make_shop: Callable[..., Shop], conn: psycopg.Connection[Any], **overrides: Any) -> Shop:
    shop = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=10_000, **overrides)
    seed_basic(conn, shop)
    return shop


# =========================================================================================== Y-01


async def test_y01_limiter_pool_timeout_is_503_with_retry_after_not_a_hang(settings: Settings) -> None:
    """Hız sınırı havuzu doluysa (zaman aşımı kısa) beklemeden 503 + Retry-After (RFC 9457)."""
    engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0, pool_timeout=0.2)
    try:
        limiter = RateLimiter(engine, busy_retry_after_seconds=3)
        async with engine.connect():  # tek bağlantıyı tut: havuz dolu
            started = time.perf_counter()
            with pytest.raises(ProblemError) as caught:
                await limiter.hit("unit:busy", 5, 60)
            assert time.perf_counter() - started < 5
        assert caught.value.status == 503
        assert caught.value.headers["Retry-After"] == "3"
        assert caught.value.slug == "rate-limit-busy"
        await limiter.hit("unit:busy", 5, 60)  # havuz boşalınca yine çalışır
    finally:
        await engine.dispose()


def test_y01_app_limiter_uses_its_own_small_pool_not_the_session_pool(make_api: Callable[..., Api]) -> None:
    api = make_api()
    state = api.client.app.state  # type: ignore[attr-defined]
    limiter_engine = state.rate_limiter._engine
    assert limiter_engine is not state.engine
    assert limiter_engine.pool.size() == state.settings.rate_limit_pool_size <= 10
    assert limiter_engine.pool._max_overflow == 0
    assert limiter_engine.pool._timeout == state.settings.rate_limit_pool_timeout_seconds <= 5
    assert state.engine.pool._timeout == state.settings.db_pool_timeout_seconds <= 10


def test_y01_settings_defaults_are_sane() -> None:
    fields = Settings.model_fields
    assert fields["db_pool_timeout_seconds"].default <= 10  # 30 sn bekleme kilitlenmeyi büyütüyordu
    assert fields["rate_limit_pool_size"].default <= 10
    assert fields["rate_limit_pool_timeout_seconds"].default <= 5
    assert fields["profit_report_tenant_concurrency"].default in (1, 2)
    assert fields["profit_report_process_concurrency"].default >= 2


def test_y01_tiny_session_pool_does_not_deadlock_the_limiter_template_endpoint(
    make_shop: Callable[..., Shop],
) -> None:
    """Eski kusur: oturum bağlantısını tutan her istek aynı havuzdan ikinci bağlantı isterdi (kilitlenme).

    Havuz 2 bağlantıya indirilir; 8 eşzamanlı istek (S3 maliyet şablonu ucu, kapısız) kilitlenmeden biter."""
    shop = make_shop(
        "a@example.com", "Mağaza A", db_pool_size=2, db_max_overflow=0, db_pool_timeout_seconds=8.0
    )
    responses, elapsed = burst(8, lambda: shop.api.get(f"{shop.base}/product-costs/template.csv"))
    codes = sorted(r.status_code for r in responses)
    assert 500 not in codes and set(codes) <= {200, 429, 503}, codes
    assert codes.count(200) >= 2
    assert elapsed < 25  # eski davranış: havuz zaman aşımına kadar kilitli


def test_y01_poc_report_burst_never_500_and_health_ready_stays_fast(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    """PoC: havuz (20) + 10 eşzamanlı rapor isteği. Hiçbiri 500 olmaz; /health/ready hızlı yanıtlar."""
    shop = seeded_shop(make_shop, admin_conn)
    ready: list[tuple[int, float]] = []

    def probe() -> None:
        time.sleep(0.1)
        started = time.perf_counter()
        r = shop.api.client.get("/v1/health/ready")
        ready.append((r.status_code, time.perf_counter() - started))

    prober = threading.Thread(target=probe)
    prober.start()
    responses, elapsed = burst(30, lambda: call(shop, "summary"))
    prober.join()
    codes = [r.status_code for r in responses]
    assert 500 not in codes and set(codes) <= {200, 429, 503}, sorted(codes)
    assert 200 in codes
    assert elapsed < 25
    status, took = ready[0]
    assert status == 200 and took < 4.0, ready  # eski davranış: 28,9 sn


def test_y01_every_request_that_reaches_the_limiter_is_counted(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], frozen_ratelimit_clock: float
) -> None:
    """Kilitlenen istekler sayılmıyordu (sınırsız tekrar). Artık sınırlayıcıya ulaşan her istek sayılır."""
    shop = seeded_shop(make_shop, admin_conn)
    responses, _ = burst(20, lambda: call(shop, "summary"))
    unreached = sum(
        1 for r in responses if r.status_code == 503 and slug(r) in {"db-busy", "rate-limit-busy"}
    )
    counted = admin_conn.execute(
        "SELECT coalesce(sum(count), 0) FROM rate_limits WHERE key LIKE 'profit-report:%'"
    ).fetchone()
    assert counted is not None and int(counted[0]) == 20 - unreached
    assert all(r.status_code in (200, 429, 503) for r in responses)


def test_y01_session_pool_timeout_is_503_with_retry_after_not_500(
    make_shop: Callable[..., Shop], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ana havuz tükenince SQLAlchemy zaman aşımı 500 yerine 503 + Retry-After (ayrıntı yanıtta yok)."""
    shop = make_shop(
        "a@example.com", "Mağaza A", db_pool_size=1, db_max_overflow=0, db_pool_timeout_seconds=0.5
    )
    hold = threading.Event()
    entered = threading.Event()

    async def slow(*args: Any, **kwargs: Any) -> tuple[list[Any], bool]:
        entered.set()
        await asyncio.to_thread(hold.wait, 30)  # oturum bağlantısı bu sırada tutulur
        return [], False

    monkeypatch.setattr(costs_service, "template_products", slow)
    first: list[Any] = []
    t = threading.Thread(target=lambda: first.append(shop.api.get(f"{shop.base}/product-costs/template.csv")))
    t.start()
    assert entered.wait(15)
    second = shop.api.get(f"{shop.base}/product-costs/template.csv")
    hold.set()
    t.join()
    assert second.status_code == 503 and slug(second) == "db-busy"
    assert second.headers["content-type"].startswith("application/problem+json")
    assert int(second.headers["retry-after"]) >= 1
    assert "QueuePool" not in second.text and "sqlalchemy" not in second.text.lower()
    assert first[0].status_code == 200


def test_y01_pool_timeout_handler_is_registered_for_sqlalchemy_timeouts(make_api: Callable[..., Api]) -> None:
    app: Any = make_api().client.app
    assert PoolTimeoutError in app.exception_handlers


# --------------------------------------------------------------------------- eşzamanlılık kapısı


async def test_gate_unit_tenant_full_is_429_process_full_is_503_and_slots_are_released() -> None:
    gate = ReportGate(process_slots=3, tenant_slots=2, retry_after_seconds=7)
    a, b = uuid4(), uuid4()
    async with gate.slot(a):
        async with gate.slot(a):
            with pytest.raises(ProblemError) as tenant_full:
                async with gate.slot(a):
                    pytest.fail("kapı dolu iken girilmemeli")
            assert tenant_full.value.status == 429 and tenant_full.value.headers["Retry-After"] == "7"
            assert tenant_full.value.slug == "report-in-progress"
            async with gate.slot(b):  # başka kiracı: süreç yuvası (3. yuva) var
                with pytest.raises(ProblemError) as process_full:
                    async with gate.slot(b):
                        pytest.fail("süreç kapısı dolu iken girilmemeli")
                assert process_full.value.status == 503 and process_full.value.headers["Retry-After"] == "7"
                assert process_full.value.slug == "report-busy"
    assert gate.active == 0 and gate.active_tenants == 0


async def test_gate_unit_releases_on_error_and_cancellation() -> None:
    gate = ReportGate(process_slots=1, tenant_slots=1, retry_after_seconds=1)
    tenant = uuid4()
    with pytest.raises(RuntimeError):
        async with gate.slot(tenant):
            raise RuntimeError("motor hatası")
    assert gate.active == 0

    async def hold() -> None:
        async with gate.slot(tenant):
            await asyncio.sleep(30)

    task = asyncio.create_task(hold())
    await asyncio.sleep(0.05)
    assert gate.active == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert gate.active == 0 and gate.active_tenants == 0
    async with gate.slot(tenant):  # yuva geri geldi
        assert gate.active == 1


def _start(shop: Shop, path: str, out: list[Any]) -> threading.Thread:
    t = threading.Thread(target=lambda: out.append(call(shop, path)))
    t.start()
    return t


def test_gate_api_tenant_slot_full_returns_429_immediately_and_counts_the_attempt(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    frozen_ratelimit_clock: float,
) -> None:
    shop = seeded_shop(make_shop, admin_conn, profit_report_tenant_concurrency=1)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    first: list[Any] = []
    t = _start(shop, "summary", first)
    try:
        assert engine.started.wait(15)
        second = call(shop, "summary")  # motor hâlâ bekliyor: kapı beklemez, hemen reddeder
        assert second.status_code == 429 and slug(second) == "report-in-progress"
        assert int(second.headers["retry-after"]) >= 1
        assert second.headers["content-type"].startswith("application/problem+json")
    finally:
        engine.release.set()
        t.join()
    assert first[0].status_code == 200
    assert call(shop, "summary").status_code == 200  # yuva geri verildi
    counted = admin_conn.execute(
        "SELECT sum(count) FROM rate_limits WHERE key LIKE 'profit-report:%'"
    ).fetchone()
    assert counted is not None and int(counted[0]) == 3  # reddedilen istek de sayıldı


def test_gate_api_process_slots_full_returns_503_immediately(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    shop = seeded_shop(
        make_shop, admin_conn, profit_report_tenant_concurrency=5, profit_report_process_concurrency=1
    )
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    first: list[Any] = []
    t = _start(shop, "products", first)
    try:
        assert engine.started.wait(15)
        second = call(shop, "alerts")
        assert second.status_code == 503 and slug(second) == "report-busy"
        assert int(second.headers["retry-after"]) >= 1
    finally:
        engine.release.set()
        t.join()
    assert first[0].status_code == 200
    assert engine.calls == 1  # reddedilen istek motoru çalıştırmadı


# --------------------------------------------------------------------------- O-01 (kısmi)


@pytest.mark.parametrize("path", ["summary", "products", "alerts", f"products/{B1}", "orders/1001"])
def test_o01_no_idle_in_transaction_connection_while_the_engine_runs(
    make_shop: Callable[..., Shop],
    admin_conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    engine = BlockedEngine()
    monkeypatch.setattr(profit_report, "calculate_profit", engine)
    out: list[Any] = []
    t = _start(shop, path, out)
    try:
        assert engine.started.wait(15)
        rows = admin_conn.execute(
            "SELECT state FROM pg_stat_activity WHERE usename = 'netkar_app' AND state = 'idle in transaction'"
        ).fetchall()
        assert rows == [], f"motor çalışırken işlem açık: {rows}"
    finally:
        engine.release.set()
        t.join()
    assert out[0].status_code == 200, out[0].text


def test_o01_titles_still_load_after_the_connection_was_released(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    """Bağlantı iade edilince RLS bağlamı yeniden kurulur: başlık sorgusu kiracı verisini görmeye devam eder."""
    shop = seeded_shop(make_shop, admin_conn)
    items = {i["barcode"]: i for i in call(shop, "products").json()["items"]}
    assert items[B1]["title"] == "Ürün Bir" and items[B2]["title"] == "Ürün İki"
    assert call(shop, f"products/{B1}").json()["title"] == "Ürün Bir"


# --------------------------------------------------------------------------- D-01


def test_d01_order_without_period_over_92_days_is_422(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    seller = seller_of(shop)
    for package, day in (
        (31, datetime(2026, 1, 5, 11, 0, tzinfo=UTC)),
        (32, datetime(2026, 10, 5, 11, 0, tzinfo=UTC)),
    ):
        add_order(
            admin_conn,
            seller,
            "3001",
            package,
            day,
            lines=[{"line_id": package, "barcode": B1, "gross": "10.00"}],
        )
    r = shop.api.get(f"{shop.base}/profit/orders/3001")
    assert r.status_code == 422
    assert {"field": "end", "code": "period_too_long"} in r.json()["errors"]
    # Açık dönem verilirse sınır yine 92 gün; dar dönem kabul edilir.
    ok = shop.api.get(f"{shop.base}/profit/orders/3001", params={"start": "2026-10-01", "end": "2026-10-31"})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    ("second_day", "expected"), [(5, 200), (6, 422)]
)  # 6 Ağu - 5 Kas tam 92 gün, ertesi gün 93
def test_d01_order_period_boundary_is_92_days_inclusive(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], second_day: int, expected: int
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    seller = seller_of(shop)
    add_order(admin_conn, seller, "3002", 41, datetime(2026, 8, 6, 11, 0, tzinfo=UTC), lines=[{"line_id": 41, "barcode": B1}])  # fmt: skip
    add_order(admin_conn, seller, "3002", 42, datetime(2026, 11, second_day, 11, 0, tzinfo=UTC), lines=[{"line_id": 42, "barcode": B1}])  # fmt: skip
    r = shop.api.get(f"{shop.base}/profit/orders/3002")
    assert r.status_code == expected
    if expected == 200:
        assert r.json()["period"]["days"] == 92


def test_d01_default_order_period_helper_boundaries() -> None:
    from datetime import date

    assert views.default_order_period((date(2026, 8, 1), date(2026, 10, 31))) == (
        date(2026, 8, 1),
        date(2026, 10, 31),
    )
    with pytest.raises(views.PeriodError) as caught:
        views.default_order_period((date(2026, 8, 1), date(2026, 11, 1)))
    assert (caught.value.field, caught.value.code) == ("end", "period_too_long")


# --------------------------------------------------------------------------- D-02


def test_d02_loss_reason_unit_cases() -> None:
    import dataclasses

    base = synthetic_rows()[0].totals
    known_loss = dataclasses.replace(base, net_profit=D("-1.00"), cost_missing=False)
    known_profit = dataclasses.replace(base, net_profit=D("1.00"), cost_missing=False)
    only_cost = MissingCounts(product_cost=1, outbound_shipping=0, platform_service_fee=0)
    everything = MissingCounts(product_cost=1, outbound_shipping=1, platform_service_fee=1)

    def unknown_net(profit: str, counts: MissingCounts) -> Any:
        # K37: net kâr null iken zarar kararı "eksik giderler hariç kâr"a (known_expenses_profit) bakar.
        return dataclasses.replace(
            base,
            net_profit=None,
            cost_missing=True,
            known_expenses_profit=D(profit),
            missing_line_counts=counts,
        )

    certain_loss = unknown_net("-0.01", only_cost)
    unknown = unknown_net("0.00", only_cost)
    positive_unknown = unknown_net("5.00", only_cost)
    known_expenses_loss = unknown_net("-3.00", everything)
    rows = [
        views.ProductRow(t, None, "estimated", 0, 0, 0)
        for t in (known_loss, known_profit, certain_loss, unknown, positive_unknown, known_expenses_loss)
    ]
    assert [r.loss_reason for r in rows] == [
        "net_profit", None, "contribution_before_cost", None, None, "known_expenses",
    ]  # fmt: skip
    assert [r for r in views.filter_rows(rows, "loss")] == [rows[0], rows[2], rows[5]]
    assert views.filter_rows(rows, "missing_cost") == rows[2:]


def test_d02_loss_filter_includes_costless_product_with_negative_contribution(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    seller = seller_of(shop)
    # Maliyeti girilmemiş ürün; ekstredeki komisyon satıştan büyük olduğundan maliyetsiz bile kesin zarar.
    other = "8681000000099"
    add_order(
        admin_conn, seller, "5001", 51, datetime(2026, 10, 9, 11, 0, tzinfo=UTC),
        lines=[{"line_id": 51, "barcode": other, "gross": "100.00"}],
    )  # fmt: skip
    add_sale(admin_conn, seller, "5001", other, "100.00", "150.00")
    everything = {i["barcode"]: i for i in call(shop, "products").json()["items"]}
    item = everything[other]
    assert item["net_profit"] is None and item["cost_missing"] is True
    # Hesapta kâr ayarı yok: kargo ve hizmet bedeli de eksik; bilinen giderlerle zarar yine kesin (K37).
    assert item["loss_reason"] == "known_expenses" and D(item["contribution_excl_missing"]) < 0
    # Ayar tanımlanınca (kargo tarifesi, varsayılan desi, hizmet bedeli 0) yalnız maliyet eksik kalır.
    base = f"{shop.base}/profit-settings"
    assert shop.api.put(f"{base}/defaults", {"default_desi": "1"}).status_code == 200
    brackets = [{"max_desi": "1000", "price": "0"}]
    tariff = {
        "agreement": "trendyol",
        "carrier": "*",
        "valid_from": "2026-01-01",
        "price_includes_vat": False,
    }
    assert shop.api.put(f"{base}/cargo-tariffs", {**tariff, "brackets": brackets}).status_code == 200
    fee = {"valid_from": "2026-01-01", "amount": "0", "amount_includes_vat": False}
    assert shop.api.put(f"{base}/service-fee-estimates", fee).status_code == 200
    everything = {i["barcode"]: i for i in call(shop, "products").json()["items"]}
    item = everything[other]
    assert item["net_profit"] is None and item["cost_missing"] is True
    assert item["loss_reason"] == "contribution_before_cost"
    assert item["missing_items"] == ["urun_maliyeti"]
    assert everything[B1]["loss_reason"] in ("net_profit", None)
    assert everything[B2]["loss_reason"] is None  # maliyetsiz ama katkısı pozitif
    losses = call(shop, "products", filter="loss").json()
    barcodes = {i["barcode"] for i in losses["items"]}
    assert other in barcodes and B2 not in barcodes
    assert losses["total_count"] == len(barcodes)
    for i in losses["items"]:
        assert i["loss_reason"] in ("net_profit", "contribution_before_cost", "known_expenses")
        if i["loss_reason"] == "net_profit":
            assert D(i["net_profit"]) < 0
    # missing_cost süzgeci değişmedi: kesin zararlı maliyetsiz ürün orada da durur.
    assert other in {i["barcode"] for i in call(shop, "products", filter="missing_cost").json()["items"]}


# --------------------------------------------------------------------------- B-01


MASTER = b"0123456789abcdef0123456789abcdef"


def codec(
    tenant: UUID | None = None, account: UUID | None = None, master: bytes = MASTER
) -> views.CursorCodec:
    return views.CursorCodec(master, tenant or UUID(int=1), account or UUID(int=2))


def test_b01_codec_round_trip_is_opaque_and_bound_to_everything() -> None:
    c = codec()
    cursor = c.encode("fp", ["0", "-10.00", "8681000000011"])
    assert c.decode(cursor, "fp", 3) == ["0", "-10.00", "8681000000011"]
    assert "=" not in cursor and cursor.replace("-", "").replace("_", "").isalnum()
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    assert b"8681000000011" not in raw and b"-10.00" not in raw and b"fp" not in raw  # düz metin yok
    assert c.encode("fp", ["0", "-10.00", "8681000000011"]) != cursor  # rastgele nonce
    for other, fingerprint in (
        (codec(tenant=UUID(int=9)), "fp"),  # başka kiracı
        (codec(account=UUID(int=9)), "fp"),  # başka hesap
        (codec(master=b"x" * 32), "fp"),  # başka anahtar
        (c, "other"),  # başka sorgu
    ):
        with pytest.raises(views.CursorError):
            other.decode(cursor, fingerprint, 3)
    with pytest.raises(views.CursorError):
        c.decode(cursor, "fp", 2)  # parça sayısı
    flipped = cursor[:-2] + ("A" if cursor[-2] != "A" else "B") + cursor[-1]
    for bad in (flipped, "!!!", "", cursor[:10], cursor + "AAAA"):
        with pytest.raises(views.CursorError):
            c.decode(bad, "fp", 3)


def test_b01_codec_uses_a_purpose_specific_key_and_rejects_oversized_parts() -> None:
    assert derive_key(MASTER, "report-cursor") != derive_key(MASTER, "aes-gcm-field")
    c = codec()
    with pytest.raises(views.CursorError):
        c.decode(c.encode("fp", ["x" * 201]), "fp", 1)
    with pytest.raises(views.CursorError):
        c.decode(c.encode("fp", [1, 2, 3]), "fp", 3)  # type: ignore[list-item]


def _walk_once(shop: Shop) -> str:
    cursor = call(shop, "products", limit=1).json()["next_cursor"]
    assert cursor
    return str(cursor)


def test_b01_cursor_carries_no_plaintext_net_profit_or_barcode(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    page = call(shop, "products", limit=1).json()
    cursor = page["next_cursor"]
    raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    assert page["items"][0]["barcode"].encode() not in raw
    assert str(page["items"][0]["net_profit"]).encode() not in raw
    assert "net_profit" not in raw.decode(errors="ignore")


def test_b01_foreign_tenant_and_foreign_account_and_tampered_cursors_are_422_without_running_the_engine(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    a = make_shop("a@example.com", "Mağaza A", rate_limit_profit_report_tenant=10_000)
    b = make_shop("b@example.com", "Mağaza B", seller_id="9999", rate_limit_profit_report_tenant=10_000)
    seed_basic(admin_conn, a)
    seed_basic(admin_conn, b)
    cursor = _walk_once(a)
    assert call(a, "products", limit=1, cursor=cursor).status_code == 200
    calls: list[int] = []

    def counting(profit_input: Any) -> Any:
        calls.append(1)
        return calculate_profit(profit_input)

    monkeypatch.setattr(profit_report, "calculate_profit", counting)
    assert call(b, "products", limit=1, cursor=cursor).status_code == 422  # başka kiracı
    sibling = add_account(admin_conn, a.tenant_id, a.user_id, "5555")
    r = a.api.get(
        f"/v1/marketplace-accounts/{sibling}/profit/products", params={**PERIOD, "limit": 1, "cursor": cursor}
    )
    assert r.status_code == 422  # aynı kiracının başka hesabı
    flipped = cursor[:-3] + ("A" if cursor[-3] != "A" else "B") + cursor[-2:]
    tampered = call(a, "products", limit=1, cursor=flipped)
    assert tampered.status_code == 422
    assert {"field": "cursor", "code": "cursor_invalid"} in tampered.json()["errors"]
    assert calls == []  # hiçbiri motoru çalıştırmadı


# --------------------------------------------------------------------------- panel alanları


def test_panel_summary_fields_are_derived_from_engine_output(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    body = call(shop, "summary").json()
    assert body["settings_configured"] is False  # hesapta kâr ayarı kaydı yok: motor "tanımsız" çalışır
    assert body["completeness"] == dict.fromkeys(
        (
            "cargo_tariff_defined",
            "seller_cargo_tariff_defined",
            "service_fee_estimate_defined",
            "variable_expenses_defined",
            "default_desi_defined",
        ),
        False,
    )
    lines = [line for o in ("1001", "1002", "1003") for line in call(shop, f"orders/{o}").json()["lines"]]
    tariff_missing = sum(1 for line in lines if "KARGO_TARIFESI_EKSIK" in line["uyarilar"])
    assert body["tariff_missing_line_count"] == tariff_missing > 0
    assert body["estimated_line_count"] == body["status_counts"]["estimated"] > 0
    alert_counts = {c["code"]: c["count"] for c in call(shop, "alerts").json()["counts"]}
    assert body["tariff_missing_line_count"] == alert_counts["KARGO_TARIFESI_EKSIK"]


def test_panel_product_rows_flag_shipping_missing_like_the_summary_counts(
    make_shop: Callable[..., Shop], admin_conn: psycopg.Connection[Any]
) -> None:
    shop = seeded_shop(make_shop, admin_conn)
    items = {i["barcode"]: i for i in call(shop, "products").json()["items"]}
    for barcode in (B1, B2):
        lines = call(shop, f"products/{barcode}", limit=200).json()["lines"]
        expected = any(
            "KARGO_TARIFESI_EKSIK" in line["uyarilar"] and line["durum"] != "cancelled" for line in lines
        )
        assert items[barcode]["shipping_missing"] is expected
    assert items[B1]["shipping_missing"] is True
    assert B3 not in items or items[B3]["shipping_missing"] is False


def test_panel_helpers_match_engine_output_for_every_golden_scenario() -> None:
    for name, result in all_results():
        active = [line for line in result.lines if line.status is not Status.CANCELLED]
        expected = sum(1 for line in active if WarningCode.CARGO_TARIFF_MISSING in line.warnings)
        # Sayım artık motorun `eksik_kalem_satir_sayilari.kargo_gonderi` alanından gelir (ADR-0006 §5); uyarıdan
        # sayılan değerle aynı olmalıdır.
        assert result.period.missing_line_counts.outbound_shipping == expected, name
        rows = {r.totals.barcode: r for r in views.build_product_rows(result)}
        for barcode, row in rows.items():
            has = any(
                WarningCode.CARGO_TARIFF_MISSING in line.warnings
                for line in active
                if line.barcode == barcode
            )
            assert row.shipping_missing is has, (name, barcode)
    assert golden_result("G01").period.missing_line_counts.outbound_shipping == 0
