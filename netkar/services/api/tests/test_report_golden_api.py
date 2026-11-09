"""Altın senaryolar API üzerinden: sahte Trendyol -> senkron -> PostgreSQL -> /profit/* uçları.

Her senaryo (reklamsız 38 tanesi) gerçek senkron yürütücüyle bir kiracının hesabına yazılır, sonra GİRİŞ YAPMIŞ
kullanıcı olarak beş rapor ucu çağrılır. Yanıtlar (a) altın `beklenen` ile kuruşu kuruşuna ve (b) doğrudan
motor çıktısının kablo biçimiyle (`render_result`) BİREBİR aynı olmalıdır; yani API ne bir tutarı yuvarlar,
ne bir alanı düşürür, ne de uydurur. Kâr ayarları kiracı tablosu gelene dek `profit_settings_for` üzerinden
verilir (testte senaryonun `ayarlar` bloğu).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest

from app.api.v1 import profit as profit_module
from app.db.session import create_engine
from app.profit import calculate_profit
from app.profit.schema_v1 import parse_input, parse_settings, render_result
from app.services.sync.runner import SyncRunner
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.sync_helpers import client_factory, envelope_for_tests
from tests.test_feed_golden_database import NOW, add_user_data, fake_api_from, scenario_param
from tests.test_profit_golden import GOLDEN_FILES, assert_matches

pytestmark = pytest.mark.usefixtures("fixed_today")
PERIOD = {"start": "2026-10-01", "end": "2026-10-31"}


@pytest.fixture
async def worker_engine(database: DatabaseInfo) -> AsyncIterator[Any]:
    engine = create_engine(database.worker_url.render_as_string(hide_password=False))
    yield engine
    await engine.dispose()


@pytest.fixture
def scenario(path: Path) -> dict[str, Any]:
    """Parametreli senaryo dosyasını okur (senkron: async testte blokajlı dosya okuması olmasın)."""
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def line_order(line: dict[str, Any]) -> tuple[str, int, int]:
    return (line["orderNumber"], line["shipmentPackageId"], line["lineId"])


@pytest.mark.parametrize("path", [scenario_param(p) for p in GOLDEN_FILES])
async def test_golden_scenario_through_the_report_api(
    scenario: dict[str, Any],
    make_api: Callable[..., Api],
    admin_conn: psycopg.Connection[Any],
    worker_engine: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    girdi, expected = scenario["girdi"], scenario["beklenen"]
    shop: Shop = make_shop_factory(make_api, admin_conn)(
        "a@example.com", "Mağaza A", rate_limit_profit_report_tenant=100_000
    )
    outcome = await SyncRunner(
        worker_engine, client_factory(fake_api_from(girdi)), envelope_for_tests(), now=lambda: NOW
    ).run(shop.account_id, "backfill")
    assert outcome.status == "completed", outcome.summary()
    add_user_data(admin_conn, shop.tenant_id, shop.account_id, shop.user_id, girdi)
    settings = parse_settings(girdi.get("ayarlar", {}))
    monkeypatch.setattr(profit_module, "profit_settings_for", lambda tenant_id, account_id: settings)
    direct = render_result(calculate_profit(parse_input(girdi)))

    def get(suffix: str, **params: Any) -> Any:
        r = shop.api.get(f"{shop.base}/profit/{suffix}", params={**PERIOD, **params})
        assert r.status_code == 200, (suffix, r.text)
        return r.json()

    # 1. Özet: dönem toplamı altın beklenenle ve motorun kablo çıktısıyla aynı.
    summary = get("summary")
    assert summary["feed_notes"]["total"] == 0
    assert summary["totals"] == direct["donem_toplami"]
    assert_matches(expected["donem_toplami"], summary["totals"], f"{scenario['senaryo_id']}.donem")
    assert sum(summary["status_counts"].values()) == len(direct["siparis_satirlari"])
    assert summary["missing_cost_line_count"] == direct["donem_toplami"]["maliyet_eksik_satir_sayisi"]

    # 2. Ürün listesi: her ürün için altın ürün toplamının ana alanları.
    listing = get("products", limit=200)
    assert listing["total_count"] == len(expected["urun_toplamlari"]) and listing["next_cursor"] is None
    by_barcode = {item["barcode"]: item for item in listing["items"]}
    for product in expected["urun_toplamlari"]:
        item = by_barcode[product["barcode"]]
        assert item["net_profit"] == product["net_kar"] and item["quantity"] == product["adet"]
        assert item["net_sales_excl_vat"] == product["net_satis_kdv_haric"]
        assert item["net_margin_percent"] == product["net_kar_marji_yuzde"]
        assert item["cost_missing"] == product["maliyet_eksik"]
        assert item["advertising_spend"] == product["reklam_harcamasi"]
        if product["net_kar"] is not None:  # net satış - toplam gider = net kâr (görünüm özdeşliği)
            gap = float(item["net_sales_excl_vat"]) - float(item["total_expenses"])
            assert abs(gap - float(item["net_profit"])) < 0.005

    # 3. Ürün kırılımı: ürün toplamı ve satırlar motorun kablo çıktısıyla birebir.
    for product in direct["urun_toplamlari"]:
        detail = get(f"products/{product['barcode']}", limit=200)
        assert detail["product"] == product
        mine = sorted(
            (ln for ln in direct["siparis_satirlari"] if ln["barcode"] == product["barcode"]), key=line_order
        )
        assert detail["lines"] == mine and detail["total_lines"] == len(mine)

    # 4. Sipariş kırılımı: siparişin satırları birebir (dönemli ve dönemsiz).
    for number in sorted({ln["orderNumber"] for ln in direct["siparis_satirlari"]}):
        lines = sorted(
            (ln for ln in direct["siparis_satirlari"] if ln["orderNumber"] == number), key=line_order
        )
        order = get(f"orders/{number}")
        assert order["lines"] == lines
        own_days = shop.api.get(f"{shop.base}/profit/orders/{number}")
        assert own_days.status_code == 200 and own_days.json()["order_number"] == number

    # 5. Uyarılar: tam olarak motorun satır ve dönem uyarıları (iptal satırı hariç).
    alerts = get("alerts", limit=200)
    got = sorted((a["code"], a["scope"], a["line_id"]) for a in alerts["items"])
    want = sorted(
        [(c, "period", None) for c in direct["donem_toplami"]["uyarilar"]]
        + [
            (c, "line", ln["lineId"])
            for ln in direct["siparis_satirlari"]
            if ln["durum"] != "cancelled"
            for c in ln["uyarilar"]
        ]
    )
    assert got == want and alerts["total_count"] == len(want)
