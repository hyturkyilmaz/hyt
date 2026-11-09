"""Büyük dönemde rapor süresi: 5.000 sipariş satırı, 30 gün (süre ve bellek AYRI ölçülür).

Süre `tracemalloc` KAPALIYKEN ölçülür (izleme süreyi birkaç kat şişirir, CI'da ölçüm yanıltıcı olur); bellek
ayrı bir testte izlemeyle ölçülür. Eşikler kapsam (coverage) izleme yükünü ve paylaşımlı CI makinelerini
hesaba katarak GENİŞ tutulmuştur: yalnız ikinci dereceden bozulmayı (örn. satır başına tüm listeyi tarayan
döngü) yakalamak içindir; gerçek ölçümler test çıktısına yazılır (`-s`).
"""

from __future__ import annotations

import json
import time
import tracemalloc
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest

from tests.conftest import Api
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401

pytestmark = pytest.mark.usefixtures("fixed_today")

ORDERS = 5_000
BARCODES = 60  # ilk 50'sinin maliyeti var, 10'u maliyetsiz
FIRST_DAY = date(2026, 10, 10)  # 30 günlük dönem: 2026-10-10 .. 2026-11-08
PERIOD = {"start": "2026-10-10", "end": "2026-11-08"}
# Kapsam izlemeli CI'da bile çok altında kalması beklenir (yerel ölçüm rapor edilir); aşım ciddi bozulmadır.
SECONDS_LIMIT = 60.0
PEAK_MB_LIMIT = 800


def seed_large(conn: psycopg.Connection[Any], shop: Shop) -> None:
    barcodes = [f"86819{i:08d}" for i in range(BARCODES)]
    tenant, account = shop.tenant_id, shop.account_id
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO products (tenant_id, marketplace_account_id, barcode, title, vat_rate, commission_rate) "
            "VALUES (%s, %s, %s, %s, 20, 12)",
            [(tenant, account, b, f"Ürün {i}") for i, b in enumerate(barcodes)],
        )
        cur.executemany(
            "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, unit_cost_excl_vat, "
            "vat_rate, entered_by) VALUES (%s, %s, %s, '2026-01-01', %s, 20, %s)",
            [(tenant, account, b, f"{20 + i}.00", shop.user_id) for i, b in enumerate(barcodes[:50])],
        )
        orders, lines, sales = [], [], []
        for n in range(ORDERS):
            order_id = uuid.uuid4()
            day = FIRST_DAY + timedelta(days=n % 30)
            when = datetime(day.year, day.month, day.day, 6 + n % 12, tzinfo=UTC)
            number, barcode, qty = f"7{n:07d}", barcodes[n % BARCODES], 1 + n % 3
            gross = f"{80 + (n * 7) % 120}.50"
            orders.append(
                (order_id, tenant, account, number, 10_000 + n, when, "Delivered", "Trendyol Express", 2)
            )
            items = json.dumps(
                [{"id": f"{n}-{i}", "seller_discount": "0", "ty_discount": "0"} for i in range(qty)]
            )
            lines.append((tenant, account, order_id, 20_000 + n, barcode, qty, gross, 20, 12, items))
            if n % 5 < 3:  # %60'ı ekstreli
                sales.append((tenant, account, f"S{n}", number, barcode, gross, f"{n % 7 + 5}.00", when))
        cur.executemany(
            "INSERT INTO orders (id, tenant_id, marketplace_account_id, order_number, shipment_package_id, ordered_at, "
            "status, carrier, cargo_deci) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            orders,
        )
        cur.executemany(
            "INSERT INTO order_lines (tenant_id, marketplace_account_id, order_id, line_id, barcode, quantity, "
            "line_gross_amount, vat_rate, commission_rate, items) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            lines,
        )
        cur.executemany(
            "INSERT INTO financial_transactions (tenant_id, marketplace_account_id, source, request_type, "
            "request_sub_type, transaction_id, order_number, barcode, debt, credit, commission_amount, "
            "commission_rate, seller_revenue, transaction_date) "
            "VALUES (%s, %s, 'settlements', 'Sale', '', %s, %s, %s, 0, %s, %s, 12, 0, %s)",
            sales,
        )
    # Toplu yükleme sonrası istatistik: üretimde autovacuum yapar. İstatistiksiz taze tabloda planlayıcı
    # EXISTS yarı birleşimini iç içe döngüyle çalıştırır (7 milyon karşılaştırma, ~1,8 sn); ölçüm gerçekçi olsun.
    conn.execute("ANALYZE")


@pytest.fixture
def big_shop(make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]) -> Shop:
    shop = make_shop_factory(make_api, admin_conn)(
        "a@example.com", "Mağaza A", rate_limit_profit_report_tenant=1000
    )
    seed_large(admin_conn, shop)
    return shop


def timed(shop: Shop, suffix: str, **params: Any) -> tuple[float, Any]:
    started = time.perf_counter()
    r = shop.api.get(f"{shop.base}/profit/{suffix}", params={**PERIOD, **params})
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    return elapsed, r.json()


def test_five_thousand_lines_over_thirty_days_report_in_bounded_time(big_shop: Shop) -> None:
    assert not tracemalloc.is_tracing()  # süre ölçümü izleme KAPALIYKEN
    t_summary, summary = timed(big_shop, "summary")
    t_products, products = timed(big_shop, "products", limit=200)
    t_detail, detail = timed(big_shop, f"products/86819{0:08d}", limit=200)
    t_alerts, alerts = timed(big_shop, "alerts", limit=200)
    print(
        f"\nPERF 5.000 satir/30 gun: summary={t_summary:.2f}s products={t_products:.2f}s "
        f"product_detail={t_detail:.2f}s alerts={t_alerts:.2f}s"
    )
    assert summary["totals"]["satir_sayisi"] == ORDERS and summary["totals"]["siparis_sayisi"] == ORDERS
    assert summary["feed_notes"]["total"] == 0
    assert summary["status_counts"]["settled"] == 3000 and summary["status_counts"]["estimated"] == 2000
    assert products["total_count"] == BARCODES and len(products["items"]) == 60
    assert detail["total_lines"] == ORDERS // BARCODES + (1 if 0 < ORDERS % BARCODES else 0)
    assert alerts["total_count"] > ORDERS  # her tarifesiz satır uyarı verir
    assert max(t_summary, t_products, t_detail, t_alerts) < SECONDS_LIMIT


def test_peak_memory_of_a_large_report_is_bounded(big_shop: Shop) -> None:
    tracemalloc.start()
    try:
        r = big_shop.api.get(f"{big_shop.base}/profit/products", params={**PERIOD, "limit": 200})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert r.status_code == 200
    megabytes = peak / (1024 * 1024)
    print(f"\nPERF bellek tepe (products, 5.000 satir): {megabytes:.1f} MB")
    assert megabytes < PEAK_MB_LIMIT
