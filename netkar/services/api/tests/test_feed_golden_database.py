"""Altın senaryolar veritabanı yolundan: sahte Trendyol -> senkron -> DB -> besleyici -> motor.

Her senaryonun `girdi` bloğu Trendyol yanıt biçiminde sahte API'ye konur, GERÇEK senkron yürütücüyle
(worker rolü, RLS) veritabanına yazılır, besleyiciyle (API rolü, RLS) `ProfitInput` kurulur ve motor
çalıştırılır. Sonuç hem doğrudan motor yoluyla (`parse_input`) hem altın `beklenen` ile AYNI olmalıdır.
Yalnız reklam senaryoları (G24-G26) hariçtir: reklam kayıtları (`ad_spend`) sonraki turdadır.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.rls import tenant_transaction
from app.db.session import create_engine
from app.profit import calculate_profit
from app.profit.schema_v1 import parse_input, parse_settings, render_result
from app.services.profit_feed import build_profit_input
from app.services.sync.runner import SyncRunner
from tests.conftest import DatabaseInfo
from tests.sync_helpers import FakeTrendyol, client_factory, count, envelope_for_tests, make_seller
from tests.test_profit_golden import GOLDEN_FILES, assert_matches

# 2026-10 içindeki tüm siparişleri ve ekstre satırlarını kapsayan "şimdi" (89 günlük geriye bakış).
NOW = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
# Reklam kayıtları (ad_spend) bu turda veritabanına alınmaz: sonraki tur (ADR-0005 §9).
AD_SCENARIOS = {"G24", "G25", "G26"}


def scenario_param(path: Path) -> Any:
    marks = (
        [pytest.mark.skip(reason="reklam kayıtları (ad_spend) sonraki tur")]
        if path.stem[:3] in AD_SCENARIOS
        else []
    )
    return pytest.param(path, id=path.stem, marks=marks)


def fake_api_from(girdi: dict[str, Any]) -> FakeTrendyol:
    """Altın girdiyi Trendyol yanıt biçimine çevirir (netkar_ alanları API'de yoktur, atılır/ayrılır)."""
    api = FakeTrendyol()
    api.orders = [dict(o) for o in girdi["siparisler"]]
    api.claims = [dict(c) for c in girdi.get("iadeler", [])]
    for row in girdi.get("settlements", []):
        api.settlements.setdefault(row["netkar_istek_tipi"], []).append(row)
    for row in girdi.get("otherfinancials", []):
        api.other.setdefault((row["netkar_istek_tipi"], row.get("netkar_istek_alt_tipi") or ""), []).append(
            row
        )
    # Gerçek API alt tipsiz DeductionInvoices isteğinde hizmet bedeli satırlarını da döndürebilir (K13):
    # besleyici aynı kimlikli kopyayı tekilleştirmelidir.
    fee_rows = api.other.get(("DeductionInvoices", "PlatformServiceFee"), [])
    api.other.setdefault(("DeductionInvoices", ""), []).extend(fee_rows)
    for invoice in girdi.get("kargo_faturalari", []):
        api.cargo[invoice["invoiceSerialNumber"]] = invoice["items"]
    barcodes = {p["barcode"] for p in girdi.get("urunler", [])}
    barcodes |= {
        line["barcode"] for o in girdi["siparisler"] for line in o["lines"] if "netkar_urun_desi" in line
    }
    api.products = [
        {
            "contentId": index,
            "productMainId": f"M{index}",
            "title": f"Ürün {index}",
            "category": {"id": 1, "name": "Kategori"},
            "variants": [{"barcode": barcode, "vatRate": 20, "commission": 15}],
        }
        for index, barcode in enumerate(sorted(barcodes), start=1)
    ]
    return api


def add_user_data(
    conn: psycopg.Connection[Any], tenant_id: Any, account_id: Any, user_id: Any, girdi: dict[str, Any]
) -> None:
    """Kullanıcı verisi: maliyetler, ürün desisi ve iade kalemi 'satılamaz' işareti (Trendyol'dan gelmez)."""
    for cost in girdi.get("urun_maliyetleri", []):
        conn.execute(
            "INSERT INTO product_costs (tenant_id, marketplace_account_id, barcode, valid_from, "
            "unit_cost_excl_vat, vat_rate, entered_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                tenant_id,
                account_id,
                cost["barcode"],
                cost["gecerlilik_baslangic"],
                cost["birim_maliyet_kdv_haric"],
                cost["kdv_orani"],
                user_id,
            ),
        )
    for order in girdi["siparisler"]:
        for line in order["lines"]:
            if "netkar_urun_desi" in line:
                conn.execute(
                    "UPDATE products SET unit_desi = %s WHERE marketplace_account_id = %s AND barcode = %s",
                    (line["netkar_urun_desi"], account_id, line["barcode"]),
                )
    for claim in girdi.get("iadeler", []):
        for line in claim["items"]:
            for item in line["claimItems"]:
                if item.get("netkar_urun_durumu") == "satilamaz":
                    conn.execute(
                        "UPDATE returns SET returned_to_stock = false WHERE marketplace_account_id = %s "
                        "AND claim_item_id = %s",
                        (account_id, item["id"]),
                    )


def add_user_settings(
    conn: psycopg.Connection[Any], tenant_id: Any, account_id: Any, user_id: Any, ayarlar: dict[str, Any]
) -> None:
    """Altın `ayarlar` bloğundaki KULLANICI ayarlarını (tarife, hizmet bedeli, varsayılan desi, değişken gider)
    hesabın ayar tablolarına yazar (ADR-0006). Sistem parametreleri (KDV oranları, stopaj, eşikler) tabloda yoktur.
    Girişler KDV hariçtir; başlangıçsız sürüm `2000-01-01`'den (en eski) başlar."""
    base = (tenant_id, account_id, user_id)
    undated = "2000-01-01"
    # Ayar başlığı HER ZAMAN eklenir (revision 1): satırlar başlıktaki sürümle okunur (K44, denetim YT-01) ve
    # başlıksız satır gerçek veride olmaz (0008 taşıması da başlığı oluşturur, YT-03).
    conn.execute(
        "INSERT INTO profit_settings (tenant_id, marketplace_account_id, updated_by, default_desi) "
        "VALUES (%s, %s, %s, %s)",
        (*base, ayarlar.get("varsayilan_desi")),
    )
    for agreement, key in (("trendyol", "kargo_tarifesi"), ("seller", "satici_kargo_tarifesi")):
        for carrier, versions in (ayarlar.get(key) or {}).items():
            dated = (
                [(v.get("gecerlilik_baslangic") or undated, v["kademeler"]) for v in versions]
                if versions and isinstance(versions[0], dict)
                else [(undated, versions)]
            )
            for valid_from, brackets in dated:
                payload = json.dumps(
                    [{"max_desi": str(desi), "price": str(price)} for desi, price in brackets]
                )
                conn.execute(
                    "INSERT INTO cargo_tariffs (revision_from, tenant_id, marketplace_account_id, entered_by, agreement, carrier, "
                    "valid_from, price_includes_vat, brackets) VALUES (1, %s, %s, %s, %s, %s, %s, false, %s)",
                    (*base, agreement, carrier, valid_from, payload),
                )
    fee = ayarlar.get("platform_hizmet_bedeli_tahmini_siparis_basi_kdv_haric")
    fee_versions = (
        []
        if fee is None
        else [(v.get("gecerlilik_baslangic") or undated, v["tutar_kdv_haric"]) for v in fee]
        if isinstance(fee, list)
        else [(undated, fee)]
    )
    for valid_from, amount in fee_versions:
        conn.execute(
            "INSERT INTO service_fee_estimates (revision_from, tenant_id, marketplace_account_id, entered_by, valid_from, "
            "amount, amount_includes_vat) VALUES (1, %s, %s, %s, %s, %s, false)",
            (*base, valid_from, amount),
        )
    for expense in ayarlar.get("degisken_giderler", []):
        conn.execute(
            "INSERT INTO variable_expenses (revision_from, tenant_id, marketplace_account_id, entered_by, name, kind, "
            "amount_excl_vat, percent, vat_rate, valid_from, valid_to) VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                *base,
                expense["ad"],
                expense["tip"],
                expense.get("tutar_kdv_haric"),
                expense.get("oran_yuzde"),
                expense.get("kdv_orani", "20"),
                expense.get("gecerlilik_baslangic") or undated,
                expense.get("gecerlilik_bitis"),
            ),
        )


@pytest.fixture
async def engines(database: DatabaseInfo) -> AsyncIterator[tuple[Any, Any]]:
    worker = create_engine(database.worker_url.render_as_string(hide_password=False))
    app = create_engine(database.app_url.render_as_string(hide_password=False))
    yield worker, app
    await worker.dispose()
    await app.dispose()


@pytest.fixture
def scenario(path: Path) -> dict[str, Any]:
    """Parametreli senaryo dosyasını okur (senkron: async testte blokajlı dosya okuması olmasın)."""
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


async def through_database(
    scenario: dict[str, Any], admin_conn: psycopg.Connection[Any], engines: tuple[Any, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    girdi = scenario["girdi"]
    worker_engine, app_engine = engines
    seller = make_seller(admin_conn)
    api = fake_api_from(girdi)
    runner = SyncRunner(worker_engine, client_factory(api), envelope_for_tests(), now=lambda: NOW)
    outcome = await runner.run(seller.account_id, "backfill")
    assert outcome.status == "completed", outcome.summary()
    add_user_data(admin_conn, seller.tenant_id, seller.account_id, seller.user_id, girdi)

    period = girdi.get("donem") or {"baslangic": "2026-10-01", "bitis": "2026-10-31"}
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    # Besleyici API rolüyle (netkar_app, RLS'ye tabi, şifreli sütunları okuyamaz) çalışır.
    async with tenant_transaction(sessions, seller.tenant_id) as session:
        feed = await build_profit_input(
            session,
            seller.tenant_id,
            seller.account_id,
            date.fromisoformat(period["baslangic"]),
            date.fromisoformat(period["bitis"]),
            parse_settings(girdi.get("ayarlar", {})),
        )
    assert feed.notes.total == 0, feed.notes
    via_db = render_result(calculate_profit(feed.profit_input))
    direct = render_result(calculate_profit(parse_input(girdi)))
    return via_db, direct


@pytest.mark.parametrize("path", [scenario_param(p) for p in GOLDEN_FILES])
async def test_golden_scenario_through_database_matches_engine_and_expectation(
    path: Path, scenario: dict[str, Any], admin_conn: psycopg.Connection[Any], engines: tuple[Any, Any]
) -> None:
    via_db, direct = await through_database(scenario, admin_conn, engines)
    assert via_db == direct  # veritabanı yolu, doğrudan motor girdisiyle birebir aynı sonucu verir
    assert_matches(
        scenario["beklenen"], via_db, scenario["senaryo_id"]
    )  # ve altın beklenenle kuruşu kuruşuna


@pytest.mark.parametrize("path", [next(p for p in GOLDEN_FILES if p.stem.startswith("G16"))], ids=["G16"])
async def test_database_path_is_idempotent_across_repeated_syncs(
    path: Path, scenario: dict[str, Any], admin_conn: psycopg.Connection[Any], engines: tuple[Any, Any]
) -> None:
    """Aynı veri ikinci kez (örtüşen pencereler, yeniden deneme) senkronlanınca sonuç değişmez."""
    await through_database(scenario, admin_conn, engines)
    girdi = scenario["girdi"]
    worker_engine, _ = engines
    seller = admin_conn.execute("SELECT id, tenant_id FROM marketplace_accounts").fetchone()
    assert seller is not None
    before = {
        t: count(admin_conn, t)
        for t in ("orders", "financial_transactions", "returns", "cargo_invoice_items")
    }
    runner = SyncRunner(
        worker_engine, client_factory(fake_api_from(girdi)), envelope_for_tests(), now=lambda: NOW
    )
    again = await runner.run(seller[0], "backfill", force=True)
    assert again.status == "completed"
    assert {t: count(admin_conn, t) for t in before} == before
