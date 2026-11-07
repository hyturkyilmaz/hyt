"""Senkron testleri için ortak fixture'lar (tests/conftest.py `pytest_plugins` ile yüklenir)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from app.core.config import Settings, get_settings
from app.core.envelope import EnvelopeCipher
from app.db.session import create_engine
from app.services.sync.runner import SyncRunner
from tests.conftest import DatabaseInfo
from tests.sync_helpers import (
    NOW,
    FakeTrendyol,
    Seller,
    client_factory,
    envelope_for_tests,
    make_seller,
    ms,
    order_line,
    package,
    settlement_row,
)


@dataclass
class Env:
    seller: Seller
    api: FakeTrendyol
    runner: SyncRunner
    conn: psycopg.Connection[Any]


@pytest.fixture
async def worker_engine(database: DatabaseInfo) -> AsyncIterator[Any]:
    engine = create_engine(database.worker_url.render_as_string(hide_password=False))
    yield engine
    await engine.dispose()


@pytest.fixture
def worker_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """app.worker.app içe aktarılırken ortamdan ayar okunur (worker rolü dahil)."""
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    assert settings.worker_database_url is not None
    monkeypatch.setenv("WORKER_DATABASE_URL", settings.worker_database_url)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", settings.data_encryption_key.get_secret_value())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def full_api() -> FakeTrendyol:
    """Her kaynağında bir kayıt olan sahte API (tarihler NOW'a göre pencere içinde)."""
    api = FakeTrendyol()
    ordered = NOW - timedelta(days=20)
    api.orders = [
        package(
            "1001", 3001, ordered=ordered, lines=[order_line(30_010), order_line(30_011, "8681000000028")]
        )
    ]
    api.claims = [
        {
            "claimId": "C-1",
            "orderNumber": "1001",
            "orderShipmentPackageId": 3001,
            "claimDate": ms(ordered),
            "lastModifiedDate": ms(ordered + timedelta(days=2)),
            "items": [
                {
                    "orderLine": {"id": 30_010, "barcode": "8681000000011"},
                    "claimItems": [
                        {"id": "I-1", "orderLineItemId": 300_100, "claimItemStatus": {"name": "Accepted"}}
                    ],
                }
            ],
        }
    ]
    api.settlements["Sale"] = [settlement_row("S1", when=ordered + timedelta(days=5))]
    api.other[("DeductionInvoices", "")] = [
        {
            "id": "KRG1",
            "transactionDate": ms(ordered + timedelta(days=6)),
            "transactionType": "Kargo Faturası",
            "debt": "34.24",
            "credit": "0",
            "paymentOrderId": 7001,
        }
    ]
    api.other[("Stoppage", "")] = [
        {
            "id": "ST1",
            "transactionDate": ms(ordered + timedelta(days=6)),
            "transactionType": "E-ticaret Stopajı",
            "debt": "3.00",
            "credit": "0",
            "paymentOrderId": 7001,
        }
    ]
    api.cargo["KRG1"] = [
        {
            "shipmentPackageType": "Gönderi Kargo Bedeli",
            "parcelUniqueId": 1,
            "orderNumber": "1001",
            "amount": "34.24",
            "desi": 2,
        }
    ]
    api.products = [
        {
            "contentId": 1,
            "productMainId": "M1",
            "title": "Tişört",
            "category": {"id": 5, "name": "Tişört"},
            "variants": [
                {"barcode": "8681000000011", "stockCode": "S1", "vatRate": 20, "commission": 15},
                {"barcode": "8681000000028", "stockCode": "S2", "vatRate": 20, "commission": 15},
            ],
        }
    ]
    return api


@pytest.fixture
def make_env(admin_conn: psycopg.Connection[Any], worker_engine: Any) -> Any:
    def _make(
        api: FakeTrendyol | None = None, *, envelope: EnvelopeCipher | None = None, **seller_kw: Any
    ) -> Env:
        seller = make_seller(admin_conn, **seller_kw)
        the_api = api if api is not None else full_api()
        runner = SyncRunner(
            worker_engine, client_factory(the_api), envelope or envelope_for_tests(), now=lambda: NOW
        )
        return Env(seller, the_api, runner, admin_conn)

    return _make


@pytest.fixture
def env(make_env: Any) -> Env:
    return make_env()  # type: ignore[no-any-return]
