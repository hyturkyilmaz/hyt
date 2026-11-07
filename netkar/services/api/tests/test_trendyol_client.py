"""TrendyolClient sözleşme testleri: httpx.MockTransport, gerçek ağ yok.

Kapsam: User-Agent ve Basic Auth, ortam seçimi, 429/5xx geri çekilme ve yeniden deneme sayısı,
401/403'te yeniden deneme olmaması, uç nokta yolları ve parametre adları, sayfalama, pencere
bölme, akış imleci, çağrı meta logu.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.integrations.trendyol import (
    TrendyolAuthError,
    TrendyolConfig,
    TrendyolEnvironment,
    TrendyolError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolRequestError,
    TrendyolServerError,
    TrendyolValidationError,
    TrendyolWindowTooLargeError,
)
from tests.trendyol_helpers import (
    API_KEY,
    API_SECRET,
    SELLER_ID,
    json_response,
    load_fixture,
    make_client,
)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


async def collect[T](iterator: AsyncIterator[T]) -> list[T]:
    return [item async for item in iterator]


def ms(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000))


# --- Kimlik ve ortam -------------------------------------------------------------------------


async def test_user_agent_and_basic_auth_are_sent_on_every_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("payment_orders.json"))

    client, _ = make_client(handler)
    async with client:
        await client.get_payment_orders()
        await client.get_payment_orders(page=1)
    expected_auth = "Basic " + base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
    assert len(seen) == 2
    for request in seen:
        assert request.headers["User-Agent"] == f"{SELLER_ID} - NetKar"
        assert request.headers["Authorization"] == expected_auth
        assert request.headers["Accept"] == "application/json"


@pytest.mark.parametrize(
    ("environment", "host"),
    [
        (TrendyolEnvironment.STAGE, "stageapigw.trendyol.com"),
        (TrendyolEnvironment.LIVE, "apigw.trendyol.com"),
    ],
)
async def test_environment_selects_base_url(environment: TrendyolEnvironment, host: str) -> None:
    hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return json_response(load_fixture("payment_orders.json"))

    client, _ = make_client(handler, config=TrendyolConfig(environment=environment))
    async with client:
        await client.get_payment_orders()
    assert hosts == [host]


# --- Yeniden deneme ve geri çekilme ----------------------------------------------------------


async def test_429_is_retried_with_exponential_backoff_then_raises() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response({"error": "too.many.requests"}, 429)

    client, fake = make_client(handler, config=TrendyolConfig(max_retries=3))
    async with client:
        with pytest.raises(TrendyolRateLimitedError) as info:
            await client.get_payment_orders()
    assert calls == 4  # ilk deneme + 3 yeniden deneme
    assert info.value.status == 429 and info.value.endpoint_group == "finance"
    # rng=0.5 -> gecikme = tavanın %75'i; tavan 1, 2, 4 sn (üstel)
    assert fake.sleeps == pytest.approx([0.75, 1.5, 3.0])


async def test_backoff_is_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response({}, 503)

    config = TrendyolConfig(max_retries=6, backoff_base=1.0, backoff_cap=4.0)
    client, fake = make_client(handler, config=config, rng=lambda: 1.0)
    async with client:
        with pytest.raises(TrendyolServerError):
            await client.get_payment_orders()
    assert fake.sleeps == [1.0, 2.0, 4.0, 4.0, 4.0, 4.0]
    assert max(fake.sleeps) <= 4.0


async def test_429_honours_retry_after_and_caps_it() -> None:
    replies = iter(
        [
            json_response({}, 429, {"Retry-After": "7"}),
            json_response({}, 429, {"Retry-After": "99999"}),
            json_response(load_fixture("payment_orders.json")),
        ]
    )
    client, fake = make_client(
        lambda request: next(replies), config=TrendyolConfig(max_retries=3, retry_after_cap=60)
    )
    async with client:
        result = await client.get_payment_orders()
    assert result.content[0].id == 112360
    assert fake.sleeps == [7.0, 60.0]


async def test_429_blocks_parallel_calls_of_same_seller_and_group() -> None:
    replies = iter(
        [json_response({}, 429, {"Retry-After": "5"}), json_response(load_fixture("payment_orders.json"))]
    )
    client, fake = make_client(lambda request: next(replies))
    async with client:
        await client.get_payment_orders()
    # Geri çekilme uykusu (5 sn) bittikten sonra kova da serbesttir: ek bekleme yok.
    assert fake.sleeps == [5.0]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_5xx_is_retried_and_can_recover(status: int) -> None:
    replies = iter([json_response({}, status), json_response(load_fixture("payment_orders.json"))])
    client, fake = make_client(lambda request: next(replies))
    async with client:
        result = await client.get_payment_orders()
    assert result.total_elements == 1
    assert len(fake.sleeps) == 1


async def test_persistent_5xx_raises_server_error_with_retry_budget() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response({}, 502)

    client, _ = make_client(handler, config=TrendyolConfig(max_retries=2))
    async with client:
        with pytest.raises(TrendyolServerError) as info:
            await client.get_payment_orders()
    assert calls == 3 and info.value.status == 502


async def test_max_retries_zero_means_single_attempt() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response({}, 503)

    client, fake = make_client(handler, config=TrendyolConfig(max_retries=0))
    async with client:
        with pytest.raises(TrendyolServerError):
            await client.get_payment_orders()
    assert calls == 1 and fake.sleeps == []


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, TrendyolAuthError),
        (403, TrendyolForbiddenError),
        (400, TrendyolRequestError),
        (404, TrendyolRequestError),
        (302, TrendyolRequestError),
    ],
)
async def test_auth_and_client_errors_are_never_retried(status: int, error: type[TrendyolError]) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(
            {"exception": "ClientApiAuthenticationException", "mesaj": "gizli ayrıntı"}, status
        )

    client, fake = make_client(handler)
    async with client:
        with pytest.raises(error) as info:
            await client.get_payment_orders()
    assert calls == 1 and fake.sleeps == []
    assert info.value.status == status
    assert "gizli" not in str(info.value)  # yanıt gövdesi hataya taşınmaz


async def test_transport_errors_are_retried_and_do_not_leak_details() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError(f"bağlantı kurulamadı {request.url}")

    client, fake = make_client(handler, config=TrendyolConfig(max_retries=2))
    async with client:
        with pytest.raises(TrendyolNetworkError) as info:
            await client.get_payment_orders()
    assert calls == 3 and len(fake.sleeps) == 2
    assert "ConnectError" in str(info.value) and SELLER_ID not in str(info.value)
    assert info.value.__cause__ is None and info.value.__context__ is None


async def test_transport_error_then_success() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ReadTimeout("zaman aşımı")
        return json_response(load_fixture("payment_orders.json"))

    client, _ = make_client(handler)
    async with client:
        assert (await client.get_payment_orders()).total_elements == 1


@pytest.mark.parametrize("body", [b"<html>bakim</html>", b"[1, 2]", b""])
async def test_non_object_or_invalid_json_is_protocol_error(body: bytes) -> None:
    client, _ = make_client(lambda request: httpx.Response(200, content=body))
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.get_payment_orders()
    assert info.value.__context__ is None and info.value.__cause__ is None


async def test_schema_mismatch_is_protocol_error_without_input_values() -> None:
    bad = {"content": "SahteAd SahteSoyad", "page": "x"}
    client, _ = make_client(lambda request: json_response(bad))
    async with client:
        with pytest.raises(TrendyolProtocolError) as info:
            await client.get_payment_orders()
    assert "SahteAd" not in str(info.value) and info.value.__context__ is None


async def test_money_is_parsed_as_exact_decimal() -> None:
    client, _ = make_client(lambda request: json_response(load_fixture("settlements.json")))
    # json_response float yazar; istemci parse_float=Decimal ile okur.
    async with client:
        page = await client.get_settlements(["Sale"], start=T0, end=T0 + timedelta(days=1))
    row = page.content[0]
    assert row.commission_amount == Decimal("67.4985") and isinstance(row.commission_amount, Decimal)
    assert row.seller_revenue == Decimal("382.4915") and row.credit == Decimal("449.99")


# --- Çağrı meta logu -------------------------------------------------------------------------


async def test_call_log_has_meta_only(caplog: pytest.LogCaptureFixture) -> None:
    replies = iter([json_response({}, 429), json_response(load_fixture("claims.json"))])
    client, _ = make_client(lambda request: next(replies))
    with caplog.at_level(logging.DEBUG):
        async with client:
            await client.get_claims(start=T0, end=T0 + timedelta(days=1), order_number="65745805")
    records = [r for r in caplog.records if r.name.startswith("app.integrations.trendyol")]
    calls = [r for r in records if r.getMessage() == "trendyol_call"]
    assert [c.status for c in calls] == [429, 200]  # type: ignore[attr-defined]
    assert {c.endpoint_group for c in calls} == {"claims"}  # type: ignore[attr-defined]
    assert all(c.http_method == "GET" and c.duration_ms >= 0 for c in calls)  # type: ignore[attr-defined]
    everything = " ".join(str(r.__dict__) for r in caplog.records)
    for forbidden in (
        API_KEY,
        API_SECRET,
        "Basic ",
        "65745805",
        "SahteAd",
        "SahteMusteriNotu",
        "orderNumber",
    ):
        assert forbidden not in everything


async def test_call_log_marks_transport_failure_with_status_zero(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x")

    client, _ = make_client(handler, config=TrendyolConfig(max_retries=0))
    with caplog.at_level(logging.INFO):
        async with client:
            with pytest.raises(TrendyolNetworkError):
                await client.get_payment_orders()
    assert [r.status for r in caplog.records if r.getMessage() == "trendyol_call"] == [0]  # type: ignore[attr-defined]


# --- Siparişler ------------------------------------------------------------------------------


async def test_get_shipment_packages_uses_v2_path_and_documented_params() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("shipment_packages_v2.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.get_shipment_packages(
            start=T0,
            end=T0 + timedelta(days=2),
            page=1,
            size=50,
            status="Delivered",
            order_number="10654411111",
        )
    request = seen[0]
    assert request.url.path == f"/integration/order/sellers/{SELLER_ID}/v2/orders"
    params = dict(request.url.params)
    assert params == {
        "startDate": ms(T0),
        "endDate": ms(T0 + timedelta(days=2)),
        "page": "1",
        "size": "50",
        "status": "Delivered",
        "orderNumber": "10654411111",
        "orderByField": "PackageLastModifiedDate",
        "orderByDirection": "ASC",
    }
    assert page.total_elements == 2 and page.content[0].shipment_package_id == 3330111111
    line = page.content[0].lines[0]
    assert line.commission == Decimal("13.5") and line.vat_rate == Decimal("20.0") and line.quantity == 2
    assert page.content[0].package_total_price == Decimal("498.90")


async def test_shipment_package_ids_are_joined() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("shipment_packages_v2.json"))

    client, _ = make_client(handler)
    async with client:
        await client.get_shipment_packages(shipment_package_ids=[1, 2, 3])
    assert seen[0].url.params["shipmentPackageIds"] == "1,2,3"
    assert "startDate" not in seen[0].url.params  # tarihsiz çağrı: sunucu son 1 haftayı verir


@pytest.mark.parametrize(
    "kwargs",
    [
        {"size": 201},
        {"size": 0},
        {"page": -1},
        {"page": 50, "size": 200},  # 10.000 penceresinin dışı
        {"start": T0},  # tek uçlu aralık
        {"start": T0, "end": T0 + timedelta(days=14, seconds=1)},
        {"start": T0, "end": T0 - timedelta(days=1)},
        {"start": datetime(2026, 10, 1), "end": datetime(2026, 10, 2)},  # naive
        {"shipment_package_ids": list(range(51))},
    ],
)
async def test_shipment_package_validation_rejects_before_any_request(kwargs: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("istek gönderilmemeliydi")

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_shipment_packages(**kwargs)


async def test_page_49_with_size_200_is_the_last_allowed_page() -> None:
    client, _ = make_client(lambda request: json_response(load_fixture("shipment_packages_v2.json")))
    async with client:
        await client.get_shipment_packages(page=49, size=200)


async def test_iter_shipment_packages_splits_window_and_pages() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        page = int(params["page"])
        body = load_fixture("shipment_packages_v2.json")
        body.update(page=page, totalPages=2, totalElements=4)
        body["content"] = [dict(body["content"][0], shipmentPackageId=1000 + page)]
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        packages = await collect(client.iter_shipment_packages(T0, T0 + timedelta(days=20)))
    # 20 gün -> 2 pencere (14 gün sınırı); her pencere 2 sayfa
    assert len(seen) == 4
    assert [p["page"] for p in seen] == ["0", "1", "0", "1"]
    assert len(packages) == 4
    windows = {(p["startDate"], p["endDate"]) for p in seen}
    assert len(windows) == 2
    for start, end in windows:
        assert int(end) - int(start) < 14 * 86400 * 1000


async def test_iter_shipment_packages_raises_when_window_exceeds_10000() -> None:
    body = load_fixture("shipment_packages_v2.json")
    body.update(totalElements=12540, totalPages=63)
    client, _ = make_client(lambda request: json_response(body))
    async with client:
        with pytest.raises(TrendyolWindowTooLargeError) as info:
            await collect(client.iter_shipment_packages(T0, T0 + timedelta(days=1)))
    assert info.value.total_elements == 12540


async def test_stream_follows_cursor_until_has_more_is_false() -> None:
    seen: list[dict[str, str]] = []
    pages = iter(
        [load_fixture("shipment_packages_stream_p1.json"), load_fixture("shipment_packages_stream_p2.json")]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/integration/order/sellers/{SELLER_ID}/orders/stream"
        seen.append(dict(request.url.params))
        return json_response(next(pages))

    client, fake = make_client(handler)
    async with client:
        result = await collect(
            client.iter_shipment_packages_stream(
                T0, T0 + timedelta(days=3), statuses=["Delivered", "Returned"], size=1
            )
        )
    assert [p.shipment_package_id for p in result] == [3330111111, 3330111112]
    assert "nextCursor" not in seen[0]
    assert seen[1]["nextCursor"] == "609ca79b-1fdf-4c4e-a814-498ce9c1c039"
    assert seen[0]["packageItemStatuses"] == "Delivered,Returned"
    assert seen[0]["lastModifiedStartDate"] == ms(T0)
    assert seen[0]["lastModifiedEndDate"] == ms(T0 + timedelta(days=3))
    assert seen[0]["size"] == "1"
    # Akış için "en az 5 sn aralık" önerisi: ikinci istek öncesi bekleme (burst 1, 12/dk).
    assert fake.sleeps and fake.sleeps[0] == pytest.approx(5.0)


async def test_stream_splits_into_14_day_windows_each_with_fresh_cursor() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return json_response({"hasMore": False, "size": 50, "content": []})

    client, _ = make_client(handler)
    async with client:
        await collect(client.iter_shipment_packages_stream(T0, T0 + timedelta(days=30)))
    assert len(seen) == 3
    assert all("nextCursor" not in p for p in seen)
    for params in seen:
        assert int(params["lastModifiedEndDate"]) - int(params["lastModifiedStartDate"]) < 14 * 86400 * 1000


@pytest.mark.parametrize("cursor", [None, "1"])
async def test_stream_stuck_cursor_is_protocol_error(cursor: str | None) -> None:
    body: dict[str, Any] = {"hasMore": True, "nextCursor": cursor, "size": 1, "content": []}
    client, _ = make_client(lambda request: json_response(body))
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await collect(client.iter_shipment_packages_stream(T0, T0 + timedelta(days=1)))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"size": 201},
        {"last_modified_start": T0},
        {"last_modified_start": T0, "last_modified_end": T0 + timedelta(days=15)},
    ],
)
async def test_stream_validation(kwargs: dict[str, Any]) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_shipment_packages_stream(**kwargs)


async def test_stream_schema_mismatch_is_protocol_error() -> None:
    client, _ = make_client(lambda request: json_response({"hasMore": "belki", "content": "x"}))
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await client.get_shipment_packages_stream()


# --- İadeler ---------------------------------------------------------------------------------


async def test_claims_params_and_model() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("claims.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.get_claims(start=T0, end=T0 + timedelta(days=30), status="Created", size=50)
    request = seen[0]
    assert request.url.path == f"/integration/order/sellers/{SELLER_ID}/claims"
    assert dict(request.url.params) == {
        "startDate": ms(T0),
        "endDate": ms(T0 + timedelta(days=30)),
        "page": "0",
        "size": "50",
        "claimItemStatus": "Created",
    }
    claim = page.content[0]
    assert claim.claim_id.startswith("f9da2317") and claim.order_shipment_package_id == 3853354
    item = claim.items[0].claim_items[0]
    assert item.customer_claim_item_reason is not None and item.customer_claim_item_reason.code == "UNFIT"
    assert item.claim_item_status is not None and item.claim_item_status.name == "Created"
    assert claim.items[0].order_line is not None and claim.items[0].order_line.price == Decimal("12.95")


async def test_iter_claims_pages_until_total_pages() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        seen.append(page)
        body = load_fixture("claims.json")
        body.update(page=int(page), totalPages=3)
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        claims = await collect(client.iter_claims())
    assert seen == ["0", "1", "2"] and len(claims) == 3


@pytest.mark.parametrize(
    "kwargs",
    [{"size": 201}, {"page": -1}, {"start": T0, "end": T0 - timedelta(days=1)}],
)
async def test_claims_validation(kwargs: dict[str, Any]) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_claims(**kwargs)


# --- Finans ----------------------------------------------------------------------------------


async def test_settlements_request_shape() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("settlements.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.get_settlements(
            ["Sale", "Return"], start=T0, end=T0 + timedelta(days=15), size=1000
        )
    request = seen[0]
    assert request.url.path == f"/integration/finance/che/sellers/{SELLER_ID}/settlements"
    assert dict(request.url.params) == {
        "transactionTypes": "Sale,Return",
        "startDate": ms(T0),
        "endDate": ms(T0 + timedelta(days=15)),
        "page": "0",
        "size": "1000",
    }
    row = page.content[0]
    assert row.id == "725041340" and row.order_number == "501915861" and row.shipment_package_id == 1111111111
    assert row.commission_rate == Decimal("15.0") and row.payment_order_id == 112360


async def test_settlements_by_payment_date_and_payment_order_id() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return json_response(load_fixture("settlements.json"))

    client, _ = make_client(handler)
    async with client:
        await client.get_settlements(["Sale"], payment_date="2026-10-07")
        await client.get_settlements(["Sale"], payment_order_id=112360)
    assert seen[0]["paymentDate"] == "2026-10-07" and "startDate" not in seen[0]
    assert seen[1]["paymentOrderId"] == "112360" and "startDate" not in seen[1]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"transaction_types": []},
        {"transaction_types": ["Sale"]},  # tarih kipi yok
        {"transaction_types": ["Sale"], "payment_date": "2026-10-07", "payment_order_id": 1},  # iki kip
        {"transaction_types": ["Sale"], "start": T0},  # tek uçlu
        {"transaction_types": ["Sale"], "start": T0, "end": T0 + timedelta(days=15, seconds=1)},
        {"transaction_types": ["Sale"], "payment_date": "2026-10-07", "size": 100},
        {"transaction_types": ["Sale"], "payment_date": "2026-10-07", "page": -1},
    ],
)
async def test_settlements_validation(kwargs: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("istek gönderilmemeliydi")

    client, _ = make_client(handler)
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_settlements(**kwargs)


async def test_iter_settlements_splits_40_days_into_15_day_windows() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        page = int(params["page"])
        body = load_fixture("settlements.json")
        body.update(page=page, totalPages=2 if params["startDate"] == seen[0]["startDate"] else 1)
        return json_response(body)

    client, _ = make_client(handler)
    end = T0 + timedelta(days=40)
    async with client:
        rows = await collect(client.iter_settlements(["Sale"], T0, end))
    windows: list[tuple[int, int]] = []
    for params in seen:
        window = (int(params["startDate"]), int(params["endDate"]))
        if window not in windows:
            windows.append(window)
    assert len(windows) == 3
    assert windows[0][0] == int(T0.timestamp() * 1000) and windows[-1][1] == int(end.timestamp() * 1000)
    for (_, finish), (begin, _) in pairwise(windows):
        assert finish == begin  # boşluk yok
    assert all(finish - begin < 15 * 86400 * 1000 for begin, finish in windows)
    # ilk pencere 2 sayfa, diğer ikisi 1 sayfa: toplam 4 istek, 4 sayfa x 2 satır
    assert len(seen) == 4 and len(rows) == 8


async def test_other_financials_platform_service_fee_filter() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/otherfinancials")
        seen.append(dict(request.url.params))
        return json_response(load_fixture("other_financials.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.get_other_financials(
            ["DeductionInvoices"], sub_type="PlatformServiceFee", start=T0, end=T0 + timedelta(days=5)
        )
        rows = await collect(
            client.iter_other_financials(
                ["DeductionInvoices"], T0, T0 + timedelta(days=5), sub_type="PlatformServiceFee"
            )
        )
    assert seen[0]["transactionSubType"] == "PlatformServiceFee"
    assert seen[0]["transactionTypes"] == "DeductionInvoices"
    assert page.content[0].transaction_type == "Kargo Faturası" and page.content[0].debt == Decimal("1250.5")
    assert len(rows) == 2


async def test_sub_type_requires_deduction_invoices() -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_other_financials(
                ["Stoppage"], sub_type="PlatformServiceFee", payment_date="2026-10-07"
            )


async def test_payment_orders_and_validation() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("payment_orders.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.get_payment_orders(page=2, size=5)
        with pytest.raises(TrendyolValidationError):
            await client.get_payment_orders(size=11)
        with pytest.raises(TrendyolValidationError):
            await client.get_payment_orders(page=-1)
    assert seen[0].url.path.endswith("/finance/che/sellers/2738/payment-order")
    assert dict(seen[0].url.params) == {"page": "2", "size": "5"}
    order = page.content[0]
    assert order.status == "PAID" and order.amount == Decimal("8754732.06") and order.region_code == "TR"


async def test_cargo_invoice_items_path_and_pagination() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = load_fixture("cargo_invoice_items.json")
        page = int(request.url.params["page"])
        body.update(page=page, totalPages=2)
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        items = await collect(client.iter_cargo_invoice_items("FAT2026000123"))
    assert (
        seen[0].url.path == f"/integration/finance/che/sellers/{SELLER_ID}/cargo-invoice/FAT2026000123/items"
    )
    assert len(seen) == 2 and len(items) == 4
    assert items[0].shipment_package_type == "Gönderi Kargo Bedeli" and items[0].amount == Decimal("34.24")
    assert items[1].shipment_package_type == "İade Kargo Bedeli" and items[1].desi == 1


@pytest.mark.parametrize("serial", ["", "../admin", "a/b", "a b", "a?x=1", "a%2Fb", "fatura\n"])
async def test_cargo_invoice_serial_cannot_inject_path(serial: str) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_cargo_invoice_items(serial)


# --- Ürünler ---------------------------------------------------------------------------------


async def test_approved_products_params_and_model() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("approved_products.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.filter_approved_products(
            size=100,
            barcodes=["a", "b"],
            date_query_type="VARIANT_MODIFIED_DATE",
            start=T0,
            end=T0 + timedelta(days=1),
        )
    request = seen[0]
    assert request.url.path == f"/integration/product/sellers/{SELLER_ID}/products/approved"
    assert (
        request.url.params["barcodes"] == "a,b"
        and request.url.params["dateQueryType"] == "VARIANT_MODIFIED_DATE"
    )
    product = page.content[0]
    assert product.content_id == 12715815 and product.category is not None and product.category.id == 91266
    variant = product.variants[0]
    assert variant.commission == Decimal("7.83") and variant.vat_rate == Decimal("20")
    assert variant.price is not None and variant.price.price_seen_by_customer == Decimal("169")
    assert variant.stock is not None and variant.stock.quantity == 5 and variant.channels == ["CORE", "LUXE"]


@pytest.mark.parametrize(
    "kwargs",
    [{"size": 101}, {"page": -1}, {"page": 100, "size": 100}, {"barcodes": [str(i) for i in range(51)]}],
)
async def test_approved_products_validation(kwargs: dict[str, Any]) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.filter_approved_products(**kwargs)


async def test_iter_approved_products_pages_then_stops() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        body = load_fixture("approved_products.json")
        body.update(page=int(params["page"]), totalPages=3, totalElements=250)
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        products = await collect(client.iter_approved_products())
    assert [p["page"] for p in seen] == ["0", "1", "2"] and len(products) == 3


async def test_iter_approved_products_switches_to_next_page_token_after_10000() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        body = load_fixture("approved_products.json")
        token_mode = "nextPageToken" in params
        body.update(
            page=0 if token_mode else int(params["page"]),
            totalPages=102,
            totalElements=10_150,
            nextPageToken=None if token_mode else "TOKEN-1",
        )
        if not token_mode and int(params["page"]) < 99:
            body["nextPageToken"] = None  # pencere içinde token zorunlu değil
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        products = await collect(client.iter_approved_products())
    assert len(seen) == 101  # 100 sayfa + 1 token isteği
    assert [p["page"] for p in seen[:100]] == [str(i) for i in range(100)]
    assert seen[100] == {"size": "100", "nextPageToken": "TOKEN-1"}  # token ile page gönderilmez
    assert len(products) == 101


async def test_iter_approved_products_stops_at_exactly_10000_without_token() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["page"])
        body = load_fixture("approved_products.json")
        body.update(totalPages=100, totalElements=10_000, nextPageToken="BOS")
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        products = await collect(client.iter_approved_products())
    assert len(seen) == 100 and len(products) == 100  # token isteği yok


async def test_iter_approved_products_stops_on_repeated_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = load_fixture("approved_products.json")
        body.update(totalPages=500, totalElements=50_000, nextPageToken="AYNI")
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        products = await collect(client.iter_approved_products(size=100))
    # 100 sayfa + token modunda aynı token ikinci kez gelince durur (sonsuz döngü yok)
    assert 101 <= len(products) <= 102


async def test_iter_approved_products_stops_on_empty_page() -> None:
    client, _ = make_client(lambda request: json_response({"content": [], "totalPages": 5}))
    async with client:
        assert await collect(client.iter_approved_products()) == []


async def test_inventory_and_price_lightweight_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("inventory_and_price.json"))

    client, _ = make_client(handler)
    async with client:
        page = await client.filter_inventory_and_price(size=1)
        with pytest.raises(TrendyolValidationError):
            await client.filter_inventory_and_price(size=101)
        with pytest.raises(TrendyolValidationError):
            await client.filter_inventory_and_price(page=-1)
    assert seen[0].url.path.endswith("/products/approved/inventory-and-price")
    variant = page.content[0].variants[0]
    assert (
        variant.sale_price == Decimal("699.99") and variant.quantity == 50 and variant.barcode == "60506560"
    )


# --- Müşteri soruları ------------------------------------------------------------------------


async def test_questions_params_model_and_pagination() -> None:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/integration/qna/sellers/{SELLER_ID}/questions/filter"
        params = dict(request.url.params)
        seen.append(params)
        body = load_fixture("questions.json")
        body.update(page=int(params["page"]), totalPages=2)
        return json_response(body)

    client, _ = make_client(handler)
    async with client:
        questions = await collect(
            client.iter_questions(T0, T0 + timedelta(days=20), status="WAITING_FOR_ANSWER", size=20)
        )
    # 20 gün -> 2 pencere x 2 sayfa
    assert len(seen) == 4 and len(questions) == 4
    assert seen[0]["status"] == "WAITING_FOR_ANSWER" and seen[0]["orderByField"] == "CreatedDate"
    question = questions[0]
    assert question.id == 77001 and question.text == "Bu ürün stokta var mı?"
    assert question.answer is not None and question.answer.text == "Stokta var, yarın kargoda."


@pytest.mark.parametrize(
    "kwargs",
    [
        {"size": 51},
        {"page": -1},
        {"start": T0},
        {"start": T0, "end": T0 + timedelta(days=15)},
    ],
)
async def test_questions_validation(kwargs: dict[str, Any]) -> None:
    client, _ = make_client(lambda request: json_response({}))
    async with client:
        with pytest.raises(TrendyolValidationError):
            await client.get_questions(**kwargs)


async def test_get_question_by_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("questions.json")["content"][0])

    client, _ = make_client(handler)
    async with client:
        question = await client.get_question(77001)
        with pytest.raises(TrendyolValidationError):
            await client.get_question(0)
    assert seen[0].url.path == f"/integration/qna/sellers/{SELLER_ID}/questions/77001"
    assert question.status == "ANSWERED"


async def test_get_question_schema_mismatch() -> None:
    client, _ = make_client(lambda request: json_response({"id": "değil-sayı"}))
    async with client:
        with pytest.raises(TrendyolProtocolError):
            await client.get_question(1)


# --- Bağlantı doğrulama ----------------------------------------------------------------------


async def test_verify_connection_uses_lightest_call() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(load_fixture("inventory_and_price.json"))

    client, _ = make_client(handler)
    async with client:
        check = await client.verify_connection()
    assert len(seen) == 1
    assert (
        seen[0].url.path == f"/integration/product/sellers/{SELLER_ID}/products/approved/inventory-and-price"
    )
    assert dict(seen[0].url.params) == {"page": "0", "size": "1"}
    assert check.ok and check.total_products == 4321


@pytest.mark.parametrize(("status", "error"), [(401, TrendyolAuthError), (403, TrendyolForbiddenError)])
async def test_verify_connection_maps_rejections(status: int, error: type[Exception]) -> None:
    client, _ = make_client(lambda request: json_response({}, status))
    async with client:
        with pytest.raises(error):
            await client.verify_connection()


# --- Tek istemci kuralı ----------------------------------------------------------------------


def test_only_the_client_module_imports_httpx_for_trendyol() -> None:
    """Trendyol'a HTTP çağrısı yalnız TrendyolClient'tan yapılır (docs/40 §3.3)."""
    app_root = Path(__file__).resolve().parent.parent / "app"
    allowed = {
        app_root / "integrations" / "trendyol" / "client.py",
        app_root / "core" / "pwned.py",  # HIBP (Trendyol dışı) istemcisi
    }
    offenders = [
        str(path.relative_to(app_root))
        for path in app_root.rglob("*.py")
        if path not in allowed and "httpx" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
