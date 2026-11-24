"""PII: senkron yolu boyunca son müşteri verisi hiçbir tabloya ve hiçbir loga YAZILMAZ (KVKK, EK-6).

Fixture'lardaki ad, soyad, adres, telefon, TCKN, e-posta, müşteri kimliği vb. SAHTE sentinel
değerlerdir (`tests.trendyol_helpers.PII_SENTINELS`). Tüm Trendyol uç noktaları (sipariş stream'i, iade,
ekstre, kargo faturası, ürün) bu değerleri taşıyan yanıtlarla sürülür; sonra `public` şemadaki HER tablonun
HER satırı (JSON olarak) ve yakalanan tüm loglar taranır. Yalnız il adı ("İstanbul") tutulabilir.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import psycopg
import pytest

from app.db.session import create_engine
from app.services.sync.runner import SyncRunner
from tests.conftest import DatabaseInfo
from tests.sync_helpers import (
    NOW,
    FakeTrendyol,
    client_factory,
    envelope_for_tests,
    make_seller,
    status_response,
)
from tests.trendyol_helpers import PII_SENTINELS, load_fixture


@pytest.fixture
async def worker_engine(database: DatabaseInfo) -> AsyncIterator[Any]:
    engine = create_engine(database.worker_url.render_as_string(hide_password=False))
    yield engine
    await engine.dispose()


def pii_api() -> FakeTrendyol:
    """Her uç noktada kişisel veri içeren gerçekçi (doküman biçimli) sahte yanıtlar."""
    api = FakeTrendyol(ignore_windows=True)
    api.orders = [
        *load_fixture("shipment_packages_stream_p1.json")["content"],
        *load_fixture("shipment_packages_stream_p2.json")["content"],
    ]
    api.claims = load_fixture("claims.json")["content"]
    api.settlements["Sale"] = load_fixture("settlements.json")["content"]
    other = load_fixture("other_financials.json")["content"]
    api.other[("DeductionInvoices", "")] = other
    api.cargo = {other[0]["id"]: load_fixture("cargo_invoice_items.json")["content"]}
    api.products = load_fixture("approved_products.json")["content"]
    return api


def dump_database(conn: psycopg.Connection[Any]) -> str:
    """`public` şemadaki her tablonun her satırı (JSON) tek metinde: sentinel taraması için."""
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
    ]
    parts = []
    for table in tables:
        for (row,) in conn.execute(f'SELECT row_to_json(t)::text FROM "{table}" t').fetchall():
            parts.append(f"{table}: {row}")
    return "\n".join(parts)


def assert_no_pii(text: str, where: str) -> None:
    leaked = [s for s in PII_SENTINELS if s in text]
    assert leaked == [], f"{where}: kişisel veri sızdı: {leaked}"


def test_fixtures_really_carry_every_sentinel() -> None:
    """Kendini doğrulama: tarama anlamlı olsun diye fixture'lar tüm sentinel değerlerini taşır."""
    raw = "".join(
        json.dumps(load_fixture(name), ensure_ascii=False)
        for name in (
            "shipment_packages_stream_p1.json",
            "shipment_packages_stream_p2.json",
            "claims.json",
            "approved_products.json",
        )
    )
    # fixture'larda bulunan sentinel değerlerin büyük çoğunluğu (soru uç noktası bu testte yok)
    present = [s for s in PII_SENTINELS if s in raw]
    assert len(present) >= len(PII_SENTINELS) - 3, set(PII_SENTINELS) - set(present)


async def test_sync_writes_no_customer_data_to_any_table_or_log(
    worker_engine: Any,
    admin_conn: psycopg.Connection[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    seller = make_seller(admin_conn)
    api = pii_api()
    runner = SyncRunner(worker_engine, client_factory(api), envelope_for_tests(), now=lambda: NOW)
    outcome = await runner.run(seller.account_id, "backfill")
    assert outcome.status == "completed", outcome.summary()

    # Veri gerçekten yazıldı (aksi halde tarama boş bir veritabanını tarar)...
    orders = admin_conn.execute(
        "SELECT order_number, province, province_code, customer_key FROM orders ORDER BY order_number"
    ).fetchall()
    assert len(orders) >= 2 and {o[1] for o in orders} == {"İstanbul"}  # ...ve yalnız il adı tutulur
    assert all(o[3] is None for o in orders)  # takma adlı müşteri anahtarı da yok
    assert admin_conn.execute("SELECT count(*) FROM returns").fetchone() != (0,)
    assert admin_conn.execute("SELECT count(*) FROM financial_transactions").fetchone() != (0,)
    assert admin_conn.execute("SELECT count(*) FROM cargo_invoice_items").fetchone() != (0,)
    assert admin_conn.execute("SELECT count(*) FROM products").fetchone() != (0,)

    assert_no_pii(dump_database(admin_conn), "veritabanı")
    assert_no_pii("\n".join(f"{r.name} {r.getMessage()} {r.__dict__}" for r in caplog.records), "log")
    assert_no_pii(json.dumps(outcome.summary()), "görev sonucu")
    assert caplog.records  # log gerçekten yakalandı (boş log taraması anlamsız olurdu)


@pytest.mark.parametrize(
    "inject",
    [
        pytest.param(
            lambda api: api.overrides.update({"/orders/stream": status_response(500)}), id="sunucu_hatasi"
        ),
        pytest.param(lambda api: api.overrides.update({"/claims": status_response(401)}), id="yetki_hatasi"),
        pytest.param(
            lambda api: api.overrides.update(
                {
                    "/orders/stream": lambda r: httpx.Response(
                        200, content=b'{"hasMore": "SahteAd SahteSoyad", "content": 5}'
                    )
                }
            ),
            id="bozuk_govde",
        ),
    ],
)
async def test_failure_paths_do_not_leak_customer_data_either(
    inject: Any,
    worker_engine: Any,
    admin_conn: psycopg.Connection[Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    seller = make_seller(admin_conn)
    api = pii_api()
    inject(api)
    runner = SyncRunner(worker_engine, client_factory(api), envelope_for_tests(), now=lambda: NOW)
    outcome = await runner.run(seller.account_id, "backfill")
    assert outcome.status in {"partial", "invalid"}
    assert_no_pii(dump_database(admin_conn), "veritabanı")
    assert_no_pii(
        "\n".join(f"{r.name} {r.getMessage()} {r.__dict__} {r.exc_text}" for r in caplog.records), "log"
    )
    # hata yolunda yalnız sınıf adı yazılır
    classes = {r[0] for r in admin_conn.execute("SELECT error_class FROM sync_runs WHERE status = 'failed'")}
    assert classes and classes <= {"server_error", "unauthorized", "protocol", "validation"}


def test_no_text_column_could_hold_a_customer_name_by_design(admin_conn: psycopg.Connection[Any]) -> None:
    """Metin sütunları: yalnız katalog (kategori adı) ve ekstre (işlem türü, açıklama; satıcının kendi hesap hareketi)."""
    rows = admin_conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name IN ('products', 'orders', 'order_lines', 'returns', 'financial_transactions', "
        "'cargo_invoice_items', 'sync_runs', 'sync_cursors') AND data_type = 'text' "
        "AND (column_name LIKE '%name%' OR column_name LIKE '%note%' OR column_name LIKE '%text%' "
        "OR column_name LIKE '%comment%' OR column_name LIKE '%description%')"
    ).fetchall()
    # ürün başlığı/kategori adı katalog verisidir; müşteri adı sütunu yoktur
    assert {(t, c) for t, c in rows} == {
        ("products", "category_name"),
        ("financial_transactions", "description"),
        ("financial_transactions", "type_text"),
    }
