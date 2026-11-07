"""Trendyol salt okuma istemcisi.

TÜM Trendyol HTTP çağrıları bu sınıftan geçer (docs/40_ajan_promptlari.md §3.3); uygulamada
başka hiçbir yerde Trendyol'a doğrudan httpx çağrısı yapılmaz. İstemci şunları tek noktada uygular:

  - Basic Auth ve zorunlu User-Agent (`"{sellerId} - {entegratör}"`); geçersizse kurulmaz.
  - (satıcı, uç nokta grubu) başına token bucket (`ratelimit.py`).
  - 429 ve 5xx ile ağ hatalarında üstel geri çekilme + jitter + üst sınır; 401/403 yeniden
    denenmez ve anlamlı hata türüyle döner (`errors.py`).
  - Çağrı meta logu: yöntem, uç nokta, grup, durum, süre. Gövde, başlık, sorgu dizesi ve kimlik
    bilgisi loglanmaz.
  - PII atma noktası: ham JSON bu dosyada Decimal'li bir dict'e çevrilir ve HEMEN pydantic
    modellerine doğrulanır (`extra="ignore"`, `models.py`); yalnız modeller dışarı çıkar.

Uç nokta yolları, parametre adları ve sınırlar resmi dokümanlardan alınmıştır (her yöntemde kaynak
sayfa yazılıdır). Dokümanda net olmayan ayrıntılar "doğrulanmadı" ile işaretlidir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from app.integrations.trendyol.config import TrendyolConfig
from app.integrations.trendyol.errors import (
    TrendyolAuthError,
    TrendyolForbiddenError,
    TrendyolNetworkError,
    TrendyolProtocolError,
    TrendyolRateLimitedError,
    TrendyolRequestError,
    TrendyolServerError,
    TrendyolValidationError,
    TrendyolWindowTooLargeError,
)
from app.integrations.trendyol.identity import TrendyolCredentials, build_user_agent
from app.integrations.trendyol.models import (
    ApprovedProduct,
    CargoInvoiceItem,
    Claim,
    ConnectionCheck,
    FinancialTransaction,
    InventoryContent,
    PageResponse,
    PaymentOrder,
    Question,
    ShipmentPackage,
    StreamResponse,
)
from app.integrations.trendyol.ratelimit import EndpointGroup, RateLimiterRegistry
from app.integrations.trendyol.windows import check_order, check_span, split_window, to_epoch_ms

logger = logging.getLogger("app.integrations.trendyol")
# httpx/httpcore INFO kayıtları tam URL'yi (sorgu dizesi dahil) yazar. Çağrı meta logunu biz
# yazarız (gövdesiz, sorgusuz); kütüphane kayıtları uyarı seviyesine çekilir.
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# --- Dokümandan gelen sınırlar ---------------------------------------------------------------
# v2/orders: size en fazla 200; tarih verilirse en fazla 2 hafta; erişilebilir pencere 10.000 paket
# (page 0..49 @ size 200). Kaynak: docs__sipariş-paketlerini-çekme-getshipmentpackages.md
ORDERS_MAX_SIZE = 200
ORDERS_MAX_SPAN = timedelta(days=14)
ORDERS_WINDOW_RESULTS = 10_000
# orders/stream: size varsayılan 50, en fazla 200; lastModified aralığı en fazla 14 gün.
# Kaynak: docs__sipariş-paketlerini-akış-ile-çekme.md
STREAM_MAX_SIZE = 200
STREAM_MAX_SPAN = timedelta(days=14)
# claims: size en fazla 200 (research/01 §2.4b). Tarih aralığı üst sınırı dokümante değil.
CLAIMS_MAX_SIZE = 200
# Finans: startDate-endDate en fazla 15 gün; size 500 veya 1000. Kaynak: docs__cari-hesap-ekstresi-...
FINANCE_MAX_SPAN = timedelta(days=15)
FINANCE_SIZES = (500, 1000)
PAYMENT_ORDER_MAX_SIZE = 10
# Ürün: size en fazla 100; page x size en fazla 10.000, sonrası nextPageToken.
PRODUCT_MAX_SIZE = 100
PRODUCT_WINDOW_RESULTS = 10_000
# Müşteri soruları: size en fazla 50, aralık en fazla 2 hafta (docs__müşteri-sorularını-çekme.md).
QNA_MAX_SIZE = 50
QNA_MAX_SPAN = timedelta(days=14)

# Yeniden denenen durumlar. 501/505 gibi kalıcı sunucu hataları yeniden denenmez.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_ITER_PAGES = 100_000

_PATH_SEGMENT_SAFE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After saniye değerini okur; HTTP-date biçimi ve geçersiz değer yok sayılır."""
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def backoff_delay(attempt: int, base: float, cap: float, rng: Callable[[], float]) -> float:
    """ "Eşit jitter" ile üstel geri çekilme: yarısı sabit, yarısı rastgele; `cap` ile sınırlı.

    attempt 0 ilk yeniden denemedir. Dönen değer her zaman [min(cap, base*2^n)/2, min(cap, base*2^n)].
    """
    ceiling = min(cap, base * (2.0**attempt))
    half = ceiling / 2.0
    return half + rng() * half


def _csv(values: Iterable[str]) -> str:
    return ",".join(values)


def _clean(params: Mapping[str, Any]) -> dict[str, Any]:
    """None değerleri atar."""
    return {key: value for key, value in params.items() if value is not None}


def _check_size(size: int, maximum: int) -> None:
    if not 1 <= size <= maximum:
        raise TrendyolValidationError(f"size 1 ile {maximum} arasında olmalı")


def _check_page(page: int) -> None:
    if page < 0:
        raise TrendyolValidationError("page negatif olamaz")


class TrendyolClient:
    """Tek satıcı için salt okuma Trendyol istemcisi (async context manager olarak kullanılır)."""

    def __init__(
        self,
        credentials: TrendyolCredentials,
        config: TrendyolConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: RateLimiterRegistry | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: Callable[[], float] = random.random,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._config = config or TrendyolConfig()
        # Geçersiz satıcı kimliği veya entegratör adı burada TrendyolConfigError fırlatır:
        # User-Agent geçerli değilse istemci kurulmaz (403'ü Trendyol'a bırakmayız).
        self._user_agent = build_user_agent(credentials.seller_id, self._config.integrator_name)
        self._seller_id = credentials.seller_id
        self._limiter = limiter or RateLimiterRegistry()
        self._sleep = sleep
        self._rng = rng
        self._monotonic = monotonic
        timeout = httpx.Timeout(
            connect=self._config.connect_timeout,
            read=self._config.read_timeout,
            write=self._config.write_timeout,
            pool=self._config.pool_timeout,
        )
        self._http = httpx.AsyncClient(
            base_url=self._config.base_url,
            auth=httpx.BasicAuth(
                credentials.api_key.get_secret_value(), credentials.api_secret.get_secret_value()
            ),
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    @property
    def user_agent(self) -> str:
        """Gönderilen User-Agent değeri (sır içermez)."""
        return self._user_agent

    async def __aenter__(self) -> TrendyolClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Bağlantı havuzunu kapatır."""
        await self._http.aclose()

    # --- Düşük seviye istek ------------------------------------------------------------------

    def _log_call(
        self, group: EndpointGroup, endpoint: str, status: int, started: float, attempt: int
    ) -> None:
        logger.info(
            "trendyol_call",
            extra={
                "http_method": "GET",
                "endpoint_group": group.value,
                "endpoint": endpoint,
                "status": status,
                "duration_ms": int((self._monotonic() - started) * 1000),
                "attempt": attempt,
            },
        )

    async def _get_json(
        self, group: EndpointGroup, endpoint: str, path: str, params: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Hız sınırı, yeniden deneme ve hata eşlemesiyle GET; ayrıştırılmış JSON (Decimal'li) döner."""
        query = _clean(params or {})
        attempt = 0
        while True:
            await self._limiter.acquire(self._seller_id, group, endpoint)
            started = self._monotonic()
            response: httpx.Response | None = None
            failure: str | None = None
            try:
                response = await self._http.get(path, params=query)
            except httpx.TransportError as exc:
                failure = type(exc).__name__
            if response is None:
                self._log_call(group, endpoint, 0, started, attempt)
                if attempt >= self._config.max_retries:
                    # Özgün istisna taşınmaz (URL ve başlık ayrıntısı içerebilir); except bloğunun
                    # dışında fırlatılır ki __context__ de boş kalsın.
                    raise TrendyolNetworkError(f"bağlantı hatası ({failure})", endpoint_group=group.value)
                await self._sleep(self._retry_delay(attempt, None))
                attempt += 1
                continue

            status = response.status_code
            self._log_call(group, endpoint, status, started, attempt)
            if 200 <= status < 300:
                return self._parse_body(response, group)
            if status in _RETRY_STATUSES:
                retry_after = parse_retry_after(response.headers.get("Retry-After"))
                delay = self._retry_delay(attempt, retry_after)
                if status == 429:
                    # Aynı satıcı ve grup için paralel çağrılar da beklesin.
                    self._limiter.penalize(self._seller_id, group, endpoint, delay)
                if attempt >= self._config.max_retries:
                    if status == 429:
                        raise TrendyolRateLimitedError(
                            "istek sınırı aşıldı (429)", status=status, endpoint_group=group.value
                        )
                    raise TrendyolServerError(
                        f"sunucu hatası ({status})", status=status, endpoint_group=group.value
                    )
                logger.warning(
                    "trendyol_retry",
                    extra={
                        "endpoint_group": group.value,
                        "endpoint": endpoint,
                        "status": status,
                        "attempt": attempt,
                        "delay_s": round(delay, 3),
                    },
                )
                await self._sleep(delay)
                attempt += 1
                continue
            if status == 401:
                raise TrendyolAuthError(
                    "kimlik doğrulama başarısız (401)", status=status, endpoint_group=group.value
                )
            if status == 403:
                raise TrendyolForbiddenError(
                    "erişim reddedildi (403)", status=status, endpoint_group=group.value
                )
            raise TrendyolRequestError(
                f"istek reddedildi ({status})", status=status, endpoint_group=group.value
            )

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float:
        delay = backoff_delay(attempt, self._config.backoff_base, self._config.backoff_cap, self._rng)
        if retry_after is not None:
            delay = max(delay, min(retry_after, self._config.retry_after_cap))
        return delay

    @staticmethod
    def _parse_body(response: httpx.Response, group: EndpointGroup) -> dict[str, Any]:
        data: Any = None
        valid = True
        try:
            # parse_float=Decimal: parasal alanlarda ikili kayan nokta hatası olmaz.
            data = json.loads(response.content, parse_float=Decimal)
        except ValueError:
            valid = False
        # JSONDecodeError ham gövdeyi taşır: hata except bloğunun dışında fırlatılır (__context__ boş).
        if not valid:
            raise TrendyolProtocolError("yanıt geçerli JSON değil", endpoint_group=group.value)
        if not isinstance(data, dict):
            raise TrendyolProtocolError("yanıt bir JSON nesnesi değil", endpoint_group=group.value)
        return data

    @staticmethod
    def _validate[T: BaseModel](model: type[T], data: dict[str, Any], group: EndpointGroup) -> T:
        """Yanıtı modele doğrular. Bu çağrı PII atma noktasıdır (`extra="ignore"`).

        ValidationError girdi değerlerini taşır: zincirlenmez, yalnız hata türü bildirilir.
        """
        try:
            return model.model_validate(data)
        except ValidationError:
            pass
        raise TrendyolProtocolError("yanıt beklenen şemaya uymuyor", endpoint_group=group.value)

    def _page[T: BaseModel](
        self, model: type[T], data: dict[str, Any], group: EndpointGroup
    ) -> PageResponse[T]:
        return self._validate(PageResponse[model], data, group)  # type: ignore[valid-type]

    # --- Siparişler --------------------------------------------------------------------------

    async def get_shipment_packages(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 0,
        size: int = ORDERS_MAX_SIZE,
        status: str | None = None,
        order_number: str | None = None,
        shipment_package_ids: Sequence[int] | None = None,
    ) -> PageResponse[ShipmentPackage]:
        """getShipmentPackages (v2): GET /integration/order/sellers/{id}/v2/orders.

        Kaynak: docs__sipariş-paketlerini-çekme-getshipmentpackages.md. Tarih verilmezse son 1
        hafta döner; verilirse aralık en fazla 14 gün. page x size en fazla 10.000.
        """
        _check_size(size, ORDERS_MAX_SIZE)
        _check_page(page)
        if (page + 1) * size > ORDERS_WINDOW_RESULTS:
            raise TrendyolValidationError("v2/orders yalnız ilk 10000 pakete erişim verir (page x size)")
        if (start is None) != (end is None):
            raise TrendyolValidationError("startDate ve endDate birlikte verilmeli")
        if start is not None and end is not None:
            check_span(start, end, ORDERS_MAX_SPAN, "v2/orders")
        if shipment_package_ids is not None and len(shipment_package_ids) > 50:
            raise TrendyolValidationError("shipmentPackageIds en fazla 50 olabilir")
        params = {
            "startDate": to_epoch_ms(start) if start else None,
            "endDate": to_epoch_ms(end) if end else None,
            "page": page,
            "size": size,
            "status": status,
            "orderNumber": order_number,
            "orderByField": "PackageLastModifiedDate",
            "orderByDirection": "ASC",
            # Dizi gösterimi (virgülle ayrılmış) doğrulanmadı.
            "shipmentPackageIds": _csv(str(i) for i in shipment_package_ids)
            if shipment_package_ids
            else None,
        }
        data = await self._get_json(
            EndpointGroup.ORDERS,
            "getShipmentPackages",
            f"/integration/order/sellers/{self._seller_id}/v2/orders",
            params,
        )
        return self._page(ShipmentPackage, data, EndpointGroup.ORDERS)

    async def iter_shipment_packages(
        self,
        start: datetime,
        end: datetime,
        *,
        status: str | None = None,
        size: int = ORDERS_MAX_SIZE,
    ) -> AsyncIterator[ShipmentPackage]:
        """v2/orders ile [start, end] aralığını 14 günlük pencerelere bölüp sayfa sayfa gezer.

        Bir pencerede totalElements 10.000'i aşarsa sessizce kırpmak yerine
        TrendyolWindowTooLargeError fırlatır (stream kullanılmalı veya aralık daraltılmalı).
        Pencere sınırında yinelenen paketler olabilir: `shipment_package_id` ile tekilleştirin.
        """
        for window_start, window_end in split_window(start, end, ORDERS_MAX_SPAN):
            page = 0
            while True:
                result = await self.get_shipment_packages(
                    start=window_start, end=window_end, page=page, size=size, status=status
                )
                if (result.total_elements or 0) > ORDERS_WINDOW_RESULTS:
                    raise TrendyolWindowTooLargeError(result.total_elements or 0)
                for package in result.content:
                    yield package
                page += 1
                if not result.content or page >= (result.total_pages or 0):
                    break

    async def get_shipment_packages_stream(
        self,
        *,
        last_modified_start: datetime | None = None,
        last_modified_end: datetime | None = None,
        statuses: Sequence[str] | None = None,
        size: int = 50,
        next_cursor: str | None = None,
    ) -> StreamResponse[ShipmentPackage]:
        """getShipmentPackagesStream: GET /integration/order/sellers/{id}/orders/stream (cursor).

        Kaynak: docs__sipariş-paketlerini-akış-ile-çekme.md. Son 3 ay erişilir; aralık en fazla 14
        gün; `nextCursor` opak değerdir ve filtreler değişmeden kullanılmalıdır.
        """
        _check_size(size, STREAM_MAX_SIZE)
        if (last_modified_start is None) != (last_modified_end is None):
            raise TrendyolValidationError("lastModifiedStartDate ve lastModifiedEndDate birlikte verilmeli")
        if last_modified_start is not None and last_modified_end is not None:
            check_span(last_modified_start, last_modified_end, STREAM_MAX_SPAN, "orders/stream")
        params = {
            "size": size,
            "nextCursor": next_cursor,
            "packageItemStatuses": _csv(statuses) if statuses else None,
            "lastModifiedStartDate": to_epoch_ms(last_modified_start) if last_modified_start else None,
            "lastModifiedEndDate": to_epoch_ms(last_modified_end) if last_modified_end else None,
        }
        data = await self._get_json(
            EndpointGroup.ORDERS_STREAM,
            "getShipmentPackagesStream",
            f"/integration/order/sellers/{self._seller_id}/orders/stream",
            params,
        )
        return self._validate(StreamResponse[ShipmentPackage], data, EndpointGroup.ORDERS_STREAM)

    async def iter_shipment_packages_stream(
        self,
        start: datetime,
        end: datetime,
        *,
        statuses: Sequence[str] | None = None,
        size: int = 50,
    ) -> AsyncIterator[ShipmentPackage]:
        """Stream ile [start, end] (lastModified) aralığını 14 günlük pencerelere bölüp gezer.

        Her pencere yeni bir akıştır (imleç filtre değişince geçersizdir). Pencere sınırında
        yinelenen paketler olabilir: `shipment_package_id` ile tekilleştirin.
        """
        for window_start, window_end in split_window(start, end, STREAM_MAX_SPAN):
            cursor: str | None = None
            seen: set[str] = set()
            for _ in range(_MAX_ITER_PAGES):
                result = await self.get_shipment_packages_stream(
                    last_modified_start=window_start,
                    last_modified_end=window_end,
                    statuses=statuses,
                    size=size,
                    next_cursor=cursor,
                )
                for package in result.content:
                    yield package
                if not result.has_more:
                    break
                if not result.next_cursor or result.next_cursor in seen:
                    # Sonsuz döngü koruması: devam ediyor denip imleç ilerlemiyorsa dur.
                    raise TrendyolProtocolError(
                        "akış imleci ilerlemiyor", endpoint_group=EndpointGroup.ORDERS_STREAM.value
                    )
                seen.add(result.next_cursor)
                cursor = result.next_cursor

    # --- İadeler -----------------------------------------------------------------------------

    async def get_claims(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 0,
        size: int = CLAIMS_MAX_SIZE,
        status: str | None = None,
        order_number: str | None = None,
    ) -> PageResponse[Claim]:
        """getClaims: GET /integration/order/sellers/{id}/claims (tarih lastModifiedDate'e göre).

        Kaynak: docs__i̇adesi-oluşturulan-siparişleri-çekme-getclaims.md. Tarih aralığı üst sınırı
        dokümante değildir (doğrulanmadı).
        """
        _check_size(size, CLAIMS_MAX_SIZE)
        _check_page(page)
        if start is not None and end is not None:
            check_order(start, end, "claims")
        params = {
            "startDate": to_epoch_ms(start) if start else None,
            "endDate": to_epoch_ms(end) if end else None,
            "page": page,
            "size": size,
            "claimItemStatus": status,
            "orderNumber": order_number,
        }
        data = await self._get_json(
            EndpointGroup.CLAIMS, "getClaims", f"/integration/order/sellers/{self._seller_id}/claims", params
        )
        return self._page(Claim, data, EndpointGroup.CLAIMS)

    async def iter_claims(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        *,
        status: str | None = None,
        size: int = CLAIMS_MAX_SIZE,
    ) -> AsyncIterator[Claim]:
        """İadeleri sayfa sayfa gezer."""
        page = 0
        for _ in range(_MAX_ITER_PAGES):
            result = await self.get_claims(start=start, end=end, page=page, size=size, status=status)
            for claim in result.content:
                yield claim
            page += 1
            if not result.content or page >= (result.total_pages or 0):
                return

    # --- Finans ------------------------------------------------------------------------------

    def _finance_params(
        self,
        *,
        transaction_types: Sequence[str],
        start: datetime | None,
        end: datetime | None,
        payment_date: str | None,
        payment_order_id: int | None,
        page: int,
        size: int,
    ) -> dict[str, Any]:
        if not transaction_types:
            raise TrendyolValidationError("transactionType veya transactionTypes gerekli")
        _check_page(page)
        if size not in FINANCE_SIZES:
            raise TrendyolValidationError("size 500 veya 1000 olmalı")
        has_range = start is not None or end is not None
        modes = [has_range, payment_date is not None, payment_order_id is not None]
        if sum(modes) != 1:
            raise TrendyolValidationError(
                "startDate+endDate, paymentDate veya paymentOrderId'den biri verilmeli"
            )
        if has_range:
            if start is None or end is None:
                raise TrendyolValidationError("startDate ve endDate birlikte verilmeli")
            check_span(start, end, FINANCE_MAX_SPAN, "finans")
        return {
            # Çoklu tür gösterimi (virgülle ayrılmış) dokümandaki "Type1, Type2" örneğine göredir;
            # boşluksuz virgül doğrulanmadı.
            "transactionTypes": _csv(transaction_types),
            "startDate": to_epoch_ms(start) if start else None,
            "endDate": to_epoch_ms(end) if end else None,
            "paymentDate": payment_date,
            "paymentOrderId": payment_order_id,
            "page": page,
            "size": size,
        }

    async def get_settlements(
        self,
        transaction_types: Sequence[str],
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        payment_date: str | None = None,
        payment_order_id: int | None = None,
        page: int = 0,
        size: int = 500,
    ) -> PageResponse[FinancialTransaction]:
        """settlements: GET /integration/finance/che/sellers/{id}/settlements (en fazla 15 gün)."""
        params = self._finance_params(
            transaction_types=transaction_types,
            start=start,
            end=end,
            payment_date=payment_date,
            payment_order_id=payment_order_id,
            page=page,
            size=size,
        )
        data = await self._get_json(
            EndpointGroup.FINANCE,
            "getSettlements",
            f"/integration/finance/che/sellers/{self._seller_id}/settlements",
            params,
        )
        return self._page(FinancialTransaction, data, EndpointGroup.FINANCE)

    async def get_other_financials(
        self,
        transaction_types: Sequence[str],
        *,
        sub_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        payment_date: str | None = None,
        payment_order_id: int | None = None,
        page: int = 0,
        size: int = 500,
    ) -> PageResponse[FinancialTransaction]:
        """otherfinancials: GET .../finance/che/sellers/{id}/otherfinancials (en fazla 15 gün).

        `sub_type="PlatformServiceFee"` yalnız DeductionInvoices ile birlikte kullanılabilir.
        """
        if sub_type is not None and "DeductionInvoices" not in transaction_types:
            raise TrendyolValidationError("transactionSubType yalnız DeductionInvoices ile kullanılabilir")
        params = self._finance_params(
            transaction_types=transaction_types,
            start=start,
            end=end,
            payment_date=payment_date,
            payment_order_id=payment_order_id,
            page=page,
            size=size,
        )
        params["transactionSubType"] = sub_type
        data = await self._get_json(
            EndpointGroup.FINANCE,
            "getOtherFinancials",
            f"/integration/finance/che/sellers/{self._seller_id}/otherfinancials",
            params,
        )
        return self._page(FinancialTransaction, data, EndpointGroup.FINANCE)

    async def _iter_finance(
        self,
        fetch: Callable[..., Awaitable[PageResponse[FinancialTransaction]]],
        transaction_types: Sequence[str],
        start: datetime,
        end: datetime,
        size: int,
        extra: Mapping[str, Any],
    ) -> AsyncIterator[FinancialTransaction]:
        for window_start, window_end in split_window(start, end, FINANCE_MAX_SPAN):
            page = 0
            for _ in range(_MAX_ITER_PAGES):
                result = await fetch(
                    transaction_types, start=window_start, end=window_end, page=page, size=size, **extra
                )
                for item in result.content:
                    yield item
                page += 1
                if not result.content or page >= (result.total_pages or 0):
                    break

    def iter_settlements(
        self, transaction_types: Sequence[str], start: datetime, end: datetime, *, size: int = 500
    ) -> AsyncIterator[FinancialTransaction]:
        """Ekstre (settlements) kayıtlarını 15 günlük pencerelere otomatik bölerek gezer.

        Pencere sınırında yinelenen kayıtlar olabilir: `id` ile tekilleştirin.
        """
        return self._iter_finance(self.get_settlements, transaction_types, start, end, size, {})

    def iter_other_financials(
        self,
        transaction_types: Sequence[str],
        start: datetime,
        end: datetime,
        *,
        sub_type: str | None = None,
        size: int = 500,
    ) -> AsyncIterator[FinancialTransaction]:
        """otherfinancials kayıtlarını 15 günlük pencerelerle gezer (`id` ile tekilleştirin)."""
        return self._iter_finance(
            self.get_other_financials, transaction_types, start, end, size, {"sub_type": sub_type}
        )

    async def get_payment_orders(
        self, *, page: int = 0, size: int = PAYMENT_ORDER_MAX_SIZE
    ) -> PageResponse[PaymentOrder]:
        """payment-order: GET .../finance/che/sellers/{id}/payment-order (sayfa başına en fazla 10)."""
        _check_page(page)
        _check_size(size, PAYMENT_ORDER_MAX_SIZE)
        data = await self._get_json(
            EndpointGroup.FINANCE,
            "getPaymentOrders",
            f"/integration/finance/che/sellers/{self._seller_id}/payment-order",
            {"page": page, "size": size},
        )
        return self._page(PaymentOrder, data, EndpointGroup.FINANCE)

    async def get_cargo_invoice_items(
        self, invoice_serial_number: str, *, page: int = 0, size: int = 500
    ) -> PageResponse[CargoInvoiceItem]:
        """getCargoInvoiceItems: GET .../finance/che/sellers/{id}/cargo-invoice/{seri}/items.

        Seri numarası, otherfinancials DeductionInvoices satırlarından transactionType "Kargo
        Faturası" olanın `id` değeridir (docs__kargo-faturası-detayları.md).
        """
        _check_page(page)
        _check_size(size, 1000)
        if not invoice_serial_number or not set(invoice_serial_number) <= _PATH_SEGMENT_SAFE:
            raise TrendyolValidationError("fatura seri numarası geçersiz")
        data = await self._get_json(
            EndpointGroup.FINANCE,
            "getCargoInvoiceItems",
            f"/integration/finance/che/sellers/{self._seller_id}/cargo-invoice/"
            f"{quote(invoice_serial_number, safe='')}/items",
            {"page": page, "size": size},
        )
        return self._page(CargoInvoiceItem, data, EndpointGroup.FINANCE)

    async def iter_cargo_invoice_items(
        self, invoice_serial_number: str, *, size: int = 500
    ) -> AsyncIterator[CargoInvoiceItem]:
        """Bir kargo faturasının tüm kalemlerini gezer."""
        page = 0
        for _ in range(_MAX_ITER_PAGES):
            result = await self.get_cargo_invoice_items(invoice_serial_number, page=page, size=size)
            for item in result.content:
                yield item
            page += 1
            if not result.content or page >= (result.total_pages or 0):
                return

    # --- Ürünler -----------------------------------------------------------------------------

    async def filter_approved_products(
        self,
        *,
        page: int = 0,
        size: int = PRODUCT_MAX_SIZE,
        barcode: str | None = None,
        barcodes: Sequence[str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        date_query_type: str | None = None,
        next_page_token: str | None = None,
    ) -> PageResponse[ApprovedProduct]:
        """Onaylı ürün filtreleme v2: GET /integration/product/sellers/{id}/products/approved.

        Kaynak: docs__ürün-filtreleme-onaylı-ürün-v2.md. size en fazla 100; page x size en fazla
        10.000, sonrası `nextPageToken` (token ile page gönderilmez).
        """
        _check_size(size, PRODUCT_MAX_SIZE)
        _check_page(page)
        if next_page_token is None and (page + 1) * size > PRODUCT_WINDOW_RESULTS:
            raise TrendyolValidationError("10000'den sonrası için nextPageToken kullanılmalı")
        if barcodes is not None and len(barcodes) > 50:
            raise TrendyolValidationError("barcodes en fazla 50 olabilir")
        params = {
            "barcode": barcode,
            "barcodes": _csv(barcodes) if barcodes else None,
            "startDate": to_epoch_ms(start) if start else None,
            "endDate": to_epoch_ms(end) if end else None,
            "dateQueryType": date_query_type,
            "size": size,
            "page": page if next_page_token is None else None,
            "nextPageToken": next_page_token,
        }
        data = await self._get_json(
            EndpointGroup.PRODUCT_READ,
            "filterApprovedProducts",
            f"/integration/product/sellers/{self._seller_id}/products/approved",
            params,
        )
        return self._page(ApprovedProduct, data, EndpointGroup.PRODUCT_READ)

    async def iter_approved_products(self, *, size: int = PRODUCT_MAX_SIZE) -> AsyncIterator[ApprovedProduct]:
        """Tüm onaylı ürünleri gezer: ilk 10.000 content sayfa ile, sonrası nextPageToken ile.

        Token geçişinin ayrıntıları (ilk 10.000'den sonra token yanıtı) doğrulanmadı; sözleşme
        testi sahte yanıtla yapılır.
        """
        page = 0
        token: str | None = None
        seen_tokens: set[str] = set()
        for _ in range(_MAX_ITER_PAGES):
            result = await self.filter_approved_products(page=page, size=size, next_page_token=token)
            for product in result.content:
                yield product
            if not result.content:
                return
            if token is None:
                if (page + 2) * size <= PRODUCT_WINDOW_RESULTS:
                    # Pencere içinde: sayfa numarasıyla ilerle, toplam sayfa bitince dur.
                    page += 1
                    if page >= (result.total_pages or 0):
                        return
                    continue
                if (result.total_elements or 0) <= (page + 1) * size:
                    return
            # Pencere doldu (veya token modunda): sonraki sayfa için token şart.
            if not result.next_page_token or result.next_page_token in seen_tokens:
                return
            seen_tokens.add(result.next_page_token)
            token = result.next_page_token

    async def filter_inventory_and_price(
        self, *, page: int = 0, size: int = PRODUCT_MAX_SIZE
    ) -> PageResponse[InventoryContent]:
        """Stok ve fiyat odaklı v2: GET .../products/approved/inventory-and-price (hafif yanıt)."""
        _check_size(size, PRODUCT_MAX_SIZE)
        _check_page(page)
        data = await self._get_json(
            EndpointGroup.PRODUCT_READ,
            "filterApprovedProductsInventoryAndPrice",
            f"/integration/product/sellers/{self._seller_id}/products/approved/inventory-and-price",
            {"page": page, "size": size},
        )
        return self._page(InventoryContent, data, EndpointGroup.PRODUCT_READ)

    # --- Müşteri soruları (yalnız çekme) -----------------------------------------------------

    async def get_questions(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        status: str | None = None,
        barcode: str | None = None,
        page: int = 0,
        size: int = 20,
    ) -> PageResponse[Question]:
        """questionsFilter: GET /integration/qna/sellers/{id}/questions/filter.

        Kaynak: docs__müşteri-sorularını-çekme.md. size en fazla 50; tarih verilirse aralık en
        fazla 2 hafta (verilmezse son 1 hafta).
        """
        _check_size(size, QNA_MAX_SIZE)
        _check_page(page)
        if (start is None) != (end is None):
            raise TrendyolValidationError("startDate ve endDate birlikte verilmeli")
        if start is not None and end is not None:
            check_span(start, end, QNA_MAX_SPAN, "questions")
        params = {
            "startDate": to_epoch_ms(start) if start else None,
            "endDate": to_epoch_ms(end) if end else None,
            "status": status,
            "barcode": barcode,
            "orderByField": "CreatedDate",
            "orderByDirection": "DESC",
            "page": page,
            "size": size,
        }
        data = await self._get_json(
            EndpointGroup.QNA,
            "questionsFilter",
            f"/integration/qna/sellers/{self._seller_id}/questions/filter",
            params,
        )
        return self._page(Question, data, EndpointGroup.QNA)

    async def iter_questions(
        self, start: datetime, end: datetime, *, status: str | None = None, size: int = QNA_MAX_SIZE
    ) -> AsyncIterator[Question]:
        """Soruları 14 günlük pencerelere bölerek ve sayfa sayfa gezer (`id` ile tekilleştirin)."""
        for window_start, window_end in split_window(start, end, QNA_MAX_SPAN):
            page = 0
            for _ in range(_MAX_ITER_PAGES):
                result = await self.get_questions(
                    start=window_start, end=window_end, status=status, page=page, size=size
                )
                for question in result.content:
                    yield question
                page += 1
                if not result.content or page >= (result.total_pages or 0):
                    break

    async def get_question(self, question_id: int) -> Question:
        """questionsFilterById: GET /integration/qna/sellers/{id}/questions/{id}."""
        if question_id <= 0:
            raise TrendyolValidationError("soru kimliği pozitif olmalı")
        data = await self._get_json(
            EndpointGroup.QNA,
            "questionsFilterById",
            f"/integration/qna/sellers/{self._seller_id}/questions/{question_id}",
        )
        return self._validate(Question, data, EndpointGroup.QNA)

    # --- Bağlantı doğrulama ------------------------------------------------------------------

    async def verify_connection(self) -> ConnectionCheck:
        """Anahtarların çalıştığını en hafif çağrıyla doğrular.

        Seçilen çağrı: stok ve fiyat odaklı onaylı ürün v2, `size=1` (ADR-0003 §4). Gerekçe: salt
        okuma; yanıtta müşteri kişisel verisi YOK (sipariş, iade ve soru uç noktalarında var);
        yalnız barkod/fiyat/stok döndüğü için yük en küçük; en yüksek limit grubunda (Product
        Integration Read, 1000-2000/dk); 401 ve 403 ayrımı net.
        """
        result = await self.filter_inventory_and_price(page=0, size=1)
        return ConnectionCheck(ok=True, total_products=result.total_elements)
