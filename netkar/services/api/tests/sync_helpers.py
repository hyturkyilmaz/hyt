"""Senkron testleri için ortak yardımcılar: sahte Trendyol API'si, hesap kurucu, istemci fabrikası.

Hiçbir test gerçek ağa çıkmaz: tüm istemciler httpx.MockTransport ile kurulur. Yanıt gövdeleri
resmi doküman biçimindedir; kişisel veri yalnız SAHTE sentinel değerlerdir (trendyol_helpers).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs
from uuid import UUID, uuid4

import httpx
import psycopg
from pydantic import SecretStr

from app.core.envelope import EnvelopeCipher, KeyRing
from app.integrations.trendyol import TrendyolClient, TrendyolConfig, TrendyolCredentials
from app.integrations.trendyol.ratelimit import RateLimiterRegistry
from app.models import MarketplaceAccount
from app.services.marketplace_accounts import TrendyolClientFactory, encrypt_secret
from tests.conftest import TEST_KEK
from tests.trendyol_helpers import API_KEY, API_SECRET, FakeTime

SELLER_ID = "2738"
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
DAY_MS = 86_400_000


def ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def envelope_for_tests() -> EnvelopeCipher:
    """Test KEK'iyle zarf şifreleyici (conftest.settings ile aynı halka)."""
    return EnvelopeCipher(KeyRing.parse(f"kek1:{TEST_KEK}", "kek1"))


@dataclass(frozen=True)
class Seller:
    """Test satıcısı: kiracı, kullanıcı ve hesap kimlikleri."""

    tenant_id: UUID
    user_id: UUID
    account_id: UUID
    seller_id: str


def make_seller(
    conn: psycopg.Connection[Any],
    *,
    seller_id: str = SELLER_ID,
    status: str = "active",
    envelope: EnvelopeCipher | None = None,
    name: str = "Test Mağaza",
) -> Seller:
    """Yönetici bağlantısıyla kiracı + kullanıcı + şifreli anahtarlı pazaryeri hesabı ekler."""
    envelope = envelope or envelope_for_tests()
    tenant_id, user_id, account_id = uuid4(), uuid4(), uuid4()
    conn.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (tenant_id, name))
    conn.execute(
        "INSERT INTO users (id, email, password_hash) VALUES (%s, %s, 'x')",
        (user_id, f"{user_id.hex[:8]}@example.com"),
    )
    account = MarketplaceAccount(id=account_id, tenant_id=tenant_id, platform="trendyol", seller_id=seller_id)
    key = encrypt_secret(envelope, account, "api_key", SecretStr(API_KEY))
    secret = encrypt_secret(envelope, account, "api_secret", SecretStr(API_SECRET))
    conn.execute(
        "INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, created_by, "
        "api_key_encrypted, api_secret_encrypted, api_key_last4, revoked_at) "
        "VALUES (%s, %s, 'trendyol', %s, %s, %s, %s, %s, %s, %s)",
        (
            account_id,
            tenant_id,
            seller_id,
            status,
            user_id,
            None if status == "revoked" else key,
            None if status == "revoked" else secret,
            API_KEY[-4:],
            NOW if status == "revoked" else None,
        ),
    )
    return Seller(tenant_id, user_id, account_id, seller_id)


# --- sahte Trendyol API'si --------------------------------------------------------------------------


def package(
    number: str = "1001",
    package_id: int = 3_001,
    *,
    ordered: datetime | None = None,
    status: str = "Delivered",
    lines: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Doküman biçiminde bir sipariş paketi (il dışında müşteri verisi yok)."""
    ordered = ordered or datetime(2026, 10, 5, 11, 30, tzinfo=UTC)
    return {
        "orderNumber": number,
        "shipmentPackageId": package_id,
        "orderDate": ms(ordered),
        "lastModifiedDate": ms(ordered),
        "status": status,
        "cargoProviderName": "Trendyol Express",
        "cargoTrackingNumber": 7_280_000_000_000_000 + package_id,
        "cargoDeci": 2,
        "commercial": False,
        "shipmentAddress": {"city": "İstanbul", "cityCode": 34},
        "packageGrossAmount": 299.9,
        "lines": lines if lines is not None else [order_line(package_id * 10)],
        **extra,
    }


def order_line(
    line_id: int = 30_010,
    barcode: str = "8681000000011",
    quantity: int = 1,
    gross: str = "299.90",
    vat: int = 20,
    commission: int = 15,
    seller_discount: str = "0.00",
    ty_discount: str = "0.00",
) -> dict[str, Any]:
    return {
        "lineId": line_id,
        "barcode": barcode,
        "stockCode": f"STK-{barcode[-3:]}",
        "quantity": quantity,
        "lineGrossAmount": gross,
        "lineSellerDiscount": seller_discount,
        "lineTyDiscount": ty_discount,
        "vatRate": vat,
        "commission": commission,
        "discountDetails": [
            {
                "lineItemId": f"{line_id}{i}",
                "lineItemPrice": gross,
                "lineItemSellerDiscount": seller_discount,
                "lineItemTyDiscount": ty_discount,
            }
            for i in range(quantity)
        ],
    }


def settlement_row(
    row_id: str,
    order_number: str = "1001",
    barcode: str = "8681000000011",
    *,
    debt: str = "0",
    credit: str = "299.90",
    when: datetime | None = None,
    payment_order_id: int = 7_001,
    **extra: Any,
) -> dict[str, Any]:
    when = when or datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    return {
        "id": row_id,
        "transactionDate": ms(when),
        "barcode": barcode,
        "transactionType": "Satış",
        "description": "Satış",
        "debt": debt,
        "credit": credit,
        "commissionRate": 15,
        "commissionAmount": "44.985",
        "sellerRevenue": "254.915",
        "orderNumber": order_number,
        "paymentOrderId": payment_order_id,
        "shipmentPackageId": 3_001,
        **extra,
    }


Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


@dataclass
class FakeTrendyol:
    """Yol bazlı sahte API: veri listeleri doldurulur, çağrılar kaydedilir, hata enjekte edilir."""

    orders: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    settlements: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    other: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    cargo: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    products: list[dict[str, Any]] = field(default_factory=list)
    calls: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    # (yol parçası) -> yanıt kurucu; ilk eşleşen kullanılır. Örn. {"/orders/stream": lambda r: 500 yanıtı}
    overrides: dict[str, Callable[[httpx.Request], httpx.Response]] = field(default_factory=dict)
    gate: Callable[[httpx.Request], Awaitable[None]] | None = None
    # (yol parçası) -> (kaç çağrı normal yanıtlanır, sonrasında dönen durum kodu): yarım kalan senkron için.
    fail_after: dict[str, tuple[int, int]] = field(default_factory=dict)
    # True ise zaman damgası süzgeci uygulanmaz (eski tarihli fixture'ları her pencerede döndürür).
    ignore_windows: bool = False
    _counts: dict[str, int] = field(default_factory=dict)

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]

    def calls_to(self, fragment: str) -> list[dict[str, str]]:
        return [q for path, q in self.calls if fragment in path]

    @staticmethod
    def _page(rows: list[dict[str, Any]]) -> httpx.Response:
        body = {"page": 0, "size": 500, "totalPages": 1, "totalElements": len(rows), "content": rows}
        return httpx.Response(200, content=json.dumps(body).encode())

    def _within(
        self, rows: list[dict[str, Any]], key: str, query: dict[str, str], lo: str, hi: str
    ) -> list[dict[str, Any]]:
        """Satırın zaman damgası (`key`) pencere içindeyse döndürür; damgası olmayan satır hep döner."""
        if self.ignore_windows:
            return list(rows)
        start = int(query[lo]) if lo in query else None
        end = int(query[hi]) if hi in query else None
        out = []
        for row in rows:
            stamp = row.get(key)
            if stamp is None or ((start is None or stamp >= start) and (end is None or stamp <= end)):
                out.append(row)
        return out

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.calls.append((path, query))
        if self.gate is not None:
            await self.gate(request)
        for fragment, (ok_calls, status) in self.fail_after.items():
            if fragment in path:
                self._counts[fragment] = self._counts.get(fragment, 0) + 1
                if self._counts[fragment] > ok_calls:
                    return httpx.Response(status, content=b"{}")
        for fragment, build in self.overrides.items():
            if fragment in path:
                return build(request)
        if path.endswith("/orders/stream"):
            rows = self._within(
                self.orders, "lastModifiedDate", query, "lastModifiedStartDate", "lastModifiedEndDate"
            )
            return httpx.Response(
                200, content=json.dumps({"hasMore": False, "size": 50, "content": rows}).encode()
            )
        if path.endswith("/claims"):
            return self._page(self._within(self.claims, "lastModifiedDate", query, "startDate", "endDate"))
        if path.endswith("/settlements"):
            rows = self.settlements.get(query["transactionTypes"], [])
            return self._page(self._within(rows, "transactionDate", query, "startDate", "endDate"))
        if path.endswith("/otherfinancials"):
            rows = self.other.get((query["transactionTypes"], query.get("transactionSubType", "")), [])
            return self._page(self._within(rows, "transactionDate", query, "startDate", "endDate"))
        match = re.search(r"/cargo-invoice/([^/]+)/items$", path)
        if match:
            return self._page(self.cargo.get(match.group(1), []))
        if path.endswith("/products/approved"):
            return self._page(self.products)
        return httpx.Response(404, content=b"{}")


def status_response(
    status: int, headers: dict[str, str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    """Gövdesiz sabit durum yanıtı kurucusu (hata enjeksiyonu için)."""
    return lambda request: httpx.Response(status, content=b"{}", headers=headers)


def client_factory(
    handler: Handler, fake: FakeTime | None = None, *, retries: int = 1
) -> TrendyolClientFactory:
    """Sahte taşımalı, sahte saatli istemci fabrikası (gerçek bekleme yok)."""
    fake = fake or FakeTime()
    limiter = RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep)

    def _factory(
        credentials: TrendyolCredentials, *, max_retries: int | None = None, max_wait: float | None = None
    ) -> TrendyolClient:
        return TrendyolClient(
            credentials,
            TrendyolConfig(max_retries=retries),
            transport=httpx.MockTransport(cast(Any, handler)),
            limiter=limiter,
            sleep=fake.sleep,
            rng=lambda: 0.5,
            monotonic=fake.monotonic,
        )

    return _factory


def count(conn: psycopg.Connection[Any], table: str, where: str = "true") -> int:
    row = conn.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()
    assert row is not None
    return int(row[0])
