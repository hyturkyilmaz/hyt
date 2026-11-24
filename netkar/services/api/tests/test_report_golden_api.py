"""Altın senaryolar API üzerinden: sahte Trendyol -> senkron -> PostgreSQL -> /profit/* uçları.

Her senaryo (reklamsız 46 tanesi) gerçek senkron yürütücüyle bir kiracının hesabına yazılır, sonra GİRİŞ YAPMIŞ
kullanıcı olarak beş rapor ucu çağrılır. Yanıtlar (a) altın `beklenen` ile kuruşu kuruşuna ve (b) doğrudan
motor çıktısının kablo biçimiyle (`render_result`) BİREBİR aynı olmalıdır; yani API ne bir tutarı yuvarlar,
ne bir alanı düşürür, ne de uydurur. Kâr ayarları GERÇEK yoldan okunur (ADR-0006): senaryonun `ayarlar` bloğundaki
kullanıcı ayarları (tarife, hizmet bedeli, varsayılan desi, değişken gider) hesabın ayar tablolarına yazılır ve
`load_profit_settings` onları okur; yalnız tabloda olmayan SİSTEM parametreleri (KDV oranları, komisyon KDV varsayımı,
stopaj, eşikler) senaryodan üstüne bindirilir.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
import pytest

from app.api.v1 import profit as profit_module
from app.db.session import create_engine
from app.profit import ProfitSettings, calculate_profit
from app.profit.schema_v1 import parse_input, parse_settings, render_result
from app.services.profit_settings import LoadedSettings
from app.services.profit_settings import load_profit_settings as real_load_settings
from app.services.sync.runner import SyncRunner
from tests.conftest import Api, DatabaseInfo
from tests.product_cost_helpers import Shop, fixed_today, make_shop_factory  # noqa: F401
from tests.sync_helpers import client_factory, envelope_for_tests
from tests.test_feed_golden_database import (
    NOW,
    add_user_data,
    add_user_settings,
    fake_api_from,
    scenario_param,
)
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
    add_user_settings(admin_conn, shop.tenant_id, shop.account_id, shop.user_id, girdi.get("ayarlar", {}))
    golden = parse_settings(girdi.get("ayarlar", {}))

    async def settings_from_database(db: Any, tenant_id: UUID, account_id: UUID) -> LoadedSettings:
        """Kullanıcı ayarları veritabanından; sistem parametreleri (tabloda yok) senaryodan."""
        loaded = await real_load_settings(db, tenant_id, account_id)
        stored: ProfitSettings = loaded.settings
        merged = dataclasses.replace(
            stored,
            commission_includes_vat=golden.commission_includes_vat,
            commission_vat_rate=golden.commission_vat_rate,
            shipping_vat_rate=golden.shipping_vat_rate,
            service_fee_vat_rate=golden.service_fee_vat_rate,
            ad_vat_rate=golden.ad_vat_rate,
            withholding_rate=golden.withholding_rate,
            cargo_invoice_vat_tolerance=golden.cargo_invoice_vat_tolerance,
            thresholds=golden.thresholds,
        )
        return LoadedSettings(merged, loaded.revision, loaded.bundle)

    monkeypatch.setattr(profit_module, "load_profit_settings", settings_from_database)
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
    # K37-K40 ve ADR-0006 §5: eksik kalem sayısı, kesinlik ve tamlık motor/ayar durumundan gelir.
    assert (
        summary["tariff_missing_line_count"]
        == expected["donem_toplami"]["eksik_kalem_satir_sayilari"]["kargo_gonderi"]
    )
    assert summary["totals"]["kesinlik"] == expected["donem_toplami"]["kesinlik"]
    ayarlar = girdi.get("ayarlar", {})
    fee = ayarlar.get("platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric")
    assert summary["completeness"] == {
        "cargo_tariff_defined": bool(ayarlar.get("kargo_tarifesi")),
        "seller_cargo_tariff_defined": bool(ayarlar.get("satici_kargo_tarifesi")),
        "service_fee_estimate_defined": fee is not None and fee != [],
        "variable_expenses_defined": any(
            e.get("gecerlilik_bitis") is None for e in ayarlar.get("degisken_giderler", [])
        ),
        "default_desi_defined": ayarlar.get("varsayilan_desi") is not None,
    }
    assert summary["settings_configured"] == (
        summary["completeness"]["cargo_tariff_defined"]
        and summary["completeness"]["service_fee_estimate_defined"]
    )

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
        # ADR-0006 §5: kesinlik motordan, eksik kalemler ve eksik giderler hariç kâr ürün toplamından.
        assert item["certainty"] == product["kesinlik"]
        assert item["contribution_excl_missing"] == product["eksik_giderler_haric_kar"]
        assert item["missing_items"] == [k for k, n in product["eksik_kalem_satir_sayilari"].items() if n > 0]
        assert item["statement_basis"] == item["basis"]
        # K37 kesin zarar: net kâr varsa o, yoksa bilinen giderlerle kâr negatifse zarar (neden ayrı).
        if product["net_kar"] is not None:
            assert (item["loss_reason"] == "net_profit") == (float(product["net_kar"]) < 0)
        else:
            assert (item["loss_reason"] is not None) == (float(product["eksik_giderler_haric_kar"]) < 0)
        if product["net_kar"] is not None:  # net satış - toplam gider = net kâr (görünüm özdeşliği)
            gap = float(item["net_sales_excl_vat"]) - float(item["total_expenses"])
            assert abs(gap - float(item["net_profit"])) < 0.005

    losses = get("products", limit=200, filter="loss")
    assert {i["barcode"] for i in losses["items"]} == {
        i["barcode"] for i in listing["items"] if i["loss_reason"] is not None
    }

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
