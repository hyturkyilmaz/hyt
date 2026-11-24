"""Ürün maliyeti testleri için ortak yardımcılar (kiracı + hesap + ürün kurucuları, dosya üreticileri)."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from openpyxl import Workbook
from pydantic import SecretStr

from app.core import clock as clock_module
from app.models import MarketplaceAccount
from app.profit.schema_v1 import ISTANBUL
from app.services.marketplace_accounts import encrypt_secret
from tests.conftest import Api
from tests.sync_helpers import envelope_for_tests

TODAY_ISO = "2026-11-08"
B1, B2, B3 = "8681000000011", "8681000000028", "8681000000035"


@dataclass
class Shop:
    """Giriş yapmış bir kiracı: oturum, kimlikler ve bağlı pazaryeri hesabı."""

    api: Api
    tenant_id: UUID
    user_id: UUID
    account_id: UUID

    @property
    def base(self) -> str:
        return f"/v1/marketplace-accounts/{self.account_id}"


def add_account(
    conn: psycopg.Connection[Any], tenant_id: UUID, user_id: UUID, seller_id: str = "2738"
) -> UUID:
    envelope = envelope_for_tests()
    account_id = uuid4()
    account = MarketplaceAccount(id=account_id, tenant_id=tenant_id, platform="trendyol", seller_id=seller_id)
    conn.execute(
        "INSERT INTO marketplace_accounts (id, tenant_id, platform, seller_id, status, created_by, "
        "api_key_encrypted, api_secret_encrypted, api_key_last4) VALUES (%s, %s, 'trendyol', %s, 'active', %s, %s, %s, 'abcd')",
        (
            account_id,
            tenant_id,
            seller_id,
            user_id,
            encrypt_secret(envelope, account, "api_key", SecretStr("AnahtarDegeri12345")),
            encrypt_secret(envelope, account, "api_secret", SecretStr("SirDegeriGizli67890")),
        ),
    )
    return account_id


def add_product(
    conn: psycopg.Connection[Any],
    shop: Shop,
    barcode: str,
    title: str | None = "Ürün",
    stock: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title, stock_code, vat_rate) "
        "VALUES (%s, %s, %s, %s, %s, 20)",
        (shop.tenant_id, shop.account_id, barcode, title, stock),
    )


def count_costs(conn: psycopg.Connection[Any], shop: Shop) -> int:
    row = conn.execute(
        "SELECT count(*) FROM product_costs WHERE marketplace_account_id = %s", (shop.account_id,)
    ).fetchone()
    assert row is not None
    return int(row[0])


def audit_actions(conn: psycopg.Connection[Any], shop: Shop) -> list[tuple[str, dict[str, Any]]]:
    rows = conn.execute(
        "SELECT action, meta FROM audit_log WHERE tenant_id = %s AND action LIKE 'product_cost.%%' ORDER BY id",
        (shop.tenant_id,),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


@pytest.fixture(autouse=False)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """İstanbul bugünü 2026-11-08'e sabitlenir (geçerlilik tarihi aralık denetimleri deterministik olur)."""
    moment = datetime(2026, 11, 8, 12, 0, tzinfo=ISTANBUL).timestamp()
    monkeypatch.setattr(clock_module, "unix_time", lambda: moment)
    yield


def make_shop_factory(make_api: Callable[..., Api], conn: psycopg.Connection[Any]) -> Callable[..., Shop]:
    def _make(email: str, tenant: str, seller_id: str = "2738", **overrides: Any) -> Shop:
        api = make_api(**overrides)
        api.signup_and_login(email, tenant=tenant)
        me = api.get("/v1/me").json()
        tenant_id, user_id = UUID(me["tenant"]["id"]), UUID(me["user_id"])
        return Shop(api, tenant_id, user_id, add_account(conn, tenant_id, user_id, seller_id))

    return _make


# --- dosya üreticileri -------------------------------------------------------------------------------

HEADER_TR = "barkod;birim_maliyet_kdv_haric;kdv_orani;gecerlilik_tarihi"


def csv_bytes(*lines: str, header: str = HEADER_TR, bom: bool = False) -> bytes:
    text = "\r\n".join([header, *lines]) + "\r\n"
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


def xlsx_bytes(rows: Sequence[Sequence[Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def rewrite_zip(data: bytes, edit: Callable[[str, bytes], bytes]) -> bytes:
    """Zip içindeki her girdiyi `edit(ad, içerik)` ile değiştirerek yeniden paketler."""
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            target.writestr(info.filename, edit(info.filename, source.read(info)))
    return out.getvalue()


def upload(
    shop: Shop,
    data: bytes,
    name: str = "maliyet.csv",
    *,
    dry_run: bool | None = None,
    allow_partial: bool | None = None,
) -> Any:
    params: dict[str, str] = {}
    if dry_run is not None:
        params["dry_run"] = str(dry_run).lower()
    if allow_partial is not None:
        params["allow_partial"] = str(allow_partial).lower()
    return shop.api.post(
        f"{shop.base}/product-costs/import",
        None,
        files={"file": (name, data, "application/octet-stream")},
        params=params,
    )
