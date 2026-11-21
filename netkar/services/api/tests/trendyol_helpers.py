"""Trendyol testleri için ortak yardımcılar: sahte taşıma, sahte zaman, fixture yükleme.

Hiçbir test gerçek ağa çıkmaz: tüm istemciler httpx.MockTransport ile kurulur. Fixture'lar resmi
dokümanın örnek yanıtlarından türetilmiştir ve içindeki tüm kişisel veri SAHTE sentinel
değerlerdir (aşağıdaki PII_SENTINELS); gerçek kişi verisi yoktur.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from app.integrations.trendyol import TrendyolClient, TrendyolConfig, TrendyolCredentials
from app.integrations.trendyol.ratelimit import RateLimiterRegistry

FIXTURES = Path(__file__).parent / "fixtures" / "trendyol"

SELLER_ID = "2738"
API_KEY = "AnahtarDegeri12345"
API_SECRET = "SirDegeriGizli67890"

# Fixture'lara bilerek yerleştirilmiş sahte kişisel veri değerleri: hiçbir model nesnesinde,
# repr'de, hata mesajında veya log kaydında bulunmamalıdır.
PII_SENTINELS = (
    "SahteAd",
    "SahteSoyad",
    "sahte.kisi@example.invalid",
    "5550001122",
    "99999999990",
    "SahteMahalle",
    "SahteSokak",
    "SahteDaire",
    "SahteIlce",
    "SahteVergiNo0001",
    "SahteVergiDairesi",
    "SahteSirketAdi",
    "888888888",
    "SahteKullaniciAdi",
    "SahteMusteriNotu",
    "SahteNot",
    "11.111111",
    "22.222222",
    "invoice.example.invalid",
    "sahte.kullanici@example.invalid",
)


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


class FakeTime:
    """Sahte monotonik saat; uyku süreleri kaydedilir ve saati ilerletir."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def credentials(seller_id: str = SELLER_ID) -> TrendyolCredentials:
    return TrendyolCredentials(
        seller_id=seller_id, api_key=SecretStr(API_KEY), api_secret=SecretStr(API_SECRET)
    )


Handler = Callable[[httpx.Request], httpx.Response]


def json_response(
    body: dict[str, Any], status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body).encode(), headers=headers)


def make_client(
    handler: Handler,
    *,
    fake: FakeTime | None = None,
    seller_id: str = SELLER_ID,
    config: TrendyolConfig | None = None,
    rng: Callable[[], float] = lambda: 0.5,
    limiter: RateLimiterRegistry | None = None,
) -> tuple[TrendyolClient, FakeTime]:
    """Sahte taşımalı, sahte saatli istemci. Gerçek bekleme yoktur."""
    fake = fake or FakeTime()
    client = TrendyolClient(
        credentials(seller_id),
        config or TrendyolConfig(max_retries=3),
        transport=httpx.MockTransport(handler),
        limiter=limiter or RateLimiterRegistry(clock=fake.monotonic, sleep=fake.sleep),
        sleep=fake.sleep,
        rng=rng,
        monotonic=fake.monotonic,
    )
    return client, fake
