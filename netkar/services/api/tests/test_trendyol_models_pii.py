"""PII: kişisel veri içeren Trendyol yanıtı modele girince hiçbir nesnede ve log'da kalmaz.

Fixture'lardaki tüm kişisel veriler SAHTE sentinel değerlerdir (tests/trendyol_helpers.PII_SENTINELS).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from app.integrations.trendyol import TrendyolError, TrendyolProtocolError, models
from tests.trendyol_helpers import PII_SENTINELS, json_response, load_fixture, make_client

T0 = datetime(2026, 10, 1, tzinfo=UTC)

# Yasaklı alan takma adları: hiçbir modelde (iç içe dahil) tanımlı olamaz.
FORBIDDEN_ALIASES = {
    "customerFirstName",
    "customerLastName",
    "customerEmail",
    "customerId",
    "customerTckn",
    "identityNumber",
    "invoiceAddress",
    "firstName",
    "lastName",
    "fullName",
    "fullAddress",
    "address1",
    "address2",
    "addressLines",
    "phone",
    "email",
    "latitude",
    "longitude",
    "taxNumber",
    "taxOffice",
    "company",
    "userName",
    "customerNote",
    "note",
    "invoiceLink",
    "district",
    "neighborhood",
    "postalCode",
    "lastModifiedBy",
    "imageUrl",
    "webUrl",
}


def _all_models() -> Iterator[type[BaseModel]]:
    for value in vars(models).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value.__module__ == models.__name__:
            yield value


def test_no_model_declares_a_pii_field() -> None:
    found: dict[str, set[str]] = {}
    for model in _all_models():
        aliases = {f.alias or name for name, f in model.model_fields.items()}
        aliases |= {name for name in model.model_fields}
        bad = aliases & FORBIDDEN_ALIASES
        if bad:
            found[model.__name__] = bad
    assert found == {}


def test_all_models_ignore_unknown_fields() -> None:
    for model in _all_models():
        if model is models.ConnectionCheck:
            continue
        assert model.model_config.get("extra") == "ignore", model.__name__


def test_shipment_address_keeps_only_province() -> None:
    assert set(models.ProvinceOnly.model_fields) == {"city", "city_code"}
    package = models.ShipmentPackage.model_validate(load_fixture("shipment_packages_v2.json")["content"][0])
    assert package.shipment_province is not None
    assert package.shipment_province.city == "İstanbul" and package.shipment_province.city_code == 34


def _dump(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return (
            obj.model_dump_json()
            + repr(obj)
            + str(obj)
            + json.dumps(obj.model_dump(mode="json"), default=str)
        )
    return repr(obj)


async def _fetch_everything(handler_map: dict[str, str]) -> list[Any]:
    """Tüm uç noktaları PII'li fixture'larla çağırır; dönen tüm nesneleri toplar."""

    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, fixture in handler_map.items():
            if request.url.path.endswith(suffix):
                return json_response(load_fixture(fixture))
        raise AssertionError(request.url.path)

    client, _ = make_client(handler)
    end = T0 + timedelta(days=1)
    out: list[Any] = []
    async with client:
        out.append(await client.get_shipment_packages(start=T0, end=end))
        out.append(await client.get_shipment_packages_stream(last_modified_start=T0, last_modified_end=end))
        out.append(await client.get_claims(start=T0, end=end))
        out.append(await client.get_settlements(["Sale"], start=T0, end=end))
        out.append(await client.get_other_financials(["DeductionInvoices"], start=T0, end=end))
        out.append(await client.get_payment_orders())
        out.append(await client.get_cargo_invoice_items("F1"))
        out.append(await client.filter_approved_products())
        out.append(await client.filter_inventory_and_price())
        out.append(await client.get_questions())
        out.append(await client.get_question(77001))
    return out


ROUTES = {
    "/v2/orders": "shipment_packages_v2.json",
    "/orders/stream": "shipment_packages_stream_p1.json",
    "/claims": "claims.json",
    "/settlements": "settlements.json",
    "/otherfinancials": "other_financials.json",
    "/payment-order": "payment_orders.json",
    "/cargo-invoice/F1/items": "cargo_invoice_items.json",
    "/products/approved": "approved_products.json",
    "/inventory-and-price": "inventory_and_price.json",
    "/questions/filter": "questions.json",
    "/questions/77001": "questions_single.json",
}


async def test_fixtures_really_contain_the_sentinels() -> None:
    """Testin anlamlı olması için: ham fixture'larda sentinel değerler gerçekten var."""
    raw = " ".join(
        json.dumps(load_fixture(name), ensure_ascii=False)
        for name in {fixture for fixture in ROUTES.values()}
    )
    for sentinel in PII_SENTINELS:
        assert sentinel in raw, sentinel


async def test_pii_never_reaches_any_model_object(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        results = await _fetch_everything(ROUTES)
    dumped = " ".join(_dump(obj) for obj in results)
    for sentinel in PII_SENTINELS:
        assert sentinel not in dumped, f"{sentinel} modele sızdı"
    # Fixture gerçekten ayrıştırıldı (boş sonuç testi yanıltmasın)
    assert len(dumped) > 2000
    assert results[0].content[0].order_number == "10654411111"


async def test_pii_never_reaches_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        await _fetch_everything(ROUTES)
    assert caplog.records, "log yakalayıcı çalışmıyor"
    text = " ".join(
        f"{record.getMessage()} {record.__dict__} {record.exc_text or ''}" for record in caplog.records
    )
    for sentinel in PII_SENTINELS:
        assert sentinel not in text, f"{sentinel} log'a sızdı"


async def test_pii_never_reaches_error_objects_or_logs_on_protocol_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = load_fixture("shipment_packages_v2.json")
    body["content"][0]["shipmentPackageId"] = "sayı-değil-SahteAd-5550001122"
    client, _ = make_client(lambda request: json_response(body))
    with caplog.at_level(logging.DEBUG):
        async with client:
            with pytest.raises(TrendyolProtocolError) as info:
                await client.get_shipment_packages()
    error = info.value
    text = f"{error} {error.args} {error.__cause__} {error.__context__}"
    text += " ".join(str(r.__dict__) + r.getMessage() for r in caplog.records)
    for sentinel in PII_SENTINELS:
        assert sentinel not in text
    assert error.__context__ is None


def _reply_with(body: dict[str, Any], status: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(body, status)

    return handler


async def test_pii_never_reaches_error_objects_on_http_errors(caplog: pytest.LogCaptureFixture) -> None:
    leaky = {"customerFirstName": "SahteAd", "phone": "5550001122", "message": "SahteSoyad"}
    for status in (400, 401, 403, 429, 500):
        client, _ = make_client(_reply_with(leaky, status))
        with caplog.at_level(logging.DEBUG):
            async with client:
                with pytest.raises(TrendyolError) as info:
                    await client.get_payment_orders()
        assert "SahteAd" not in f"{info.value!r} {info.value.args}"
    assert "SahteAd" not in " ".join(str(r.__dict__) for r in caplog.records)
