"""Demo veri tohumu (app.tools.seed_demo): koruma, idempotency, RLS, KVKK ve doğru cevap kartı.

Tohum gerçek test veritabanına, uygulamanın kendi rolleriyle yazılır (kayıt: auth_gate; ayar ve maliyet:
netkar_app; Trendyol verisi: netkar_worker). Doğrulama sayımları yönetici bağlantısıyla (yalnız okuma) yapılır.
Cevap kartı değerleri, aynı veriyi okuyan RAPOR API uçlarının yanıtlarıyla karşılaştırılır.
"""

from __future__ import annotations

import io
import ipaddress
import re
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.envelope import EnvelopeCipher
from app.db.rls import tenant_transaction
from app.db.session import create_engine, create_sessionmaker
from app.models import MarketplaceAccount, Order, OrderLine, Product
from app.profit.enums import WarningCode
from app.services.marketplace_accounts import decrypt_credentials
from app.tools import demo_data, seed_demo
from app.tools.demo_card import AccountFacts, compute_facts, render_card, write_card
from app.tools.seed_demo import DemoGuardError, SeedOptions, SeedResult, check_guard, seed
from tests.conftest import Api, DatabaseInfo, FakePwned

AS_OF = date(2026, 11, 14)
ENV = {"NETKAR_ENV": "test"}
TABLES = (
    "tenants",
    "users",
    "marketplace_accounts",
    "products",
    "product_costs",
    "orders",
    "order_lines",
    "financial_transactions",
    "cargo_invoice_items",
    "profit_settings",
    "cargo_tariffs",
    "service_fee_estimates",
    "variable_expenses",
)


@pytest.fixture(autouse=True)
def _non_production_mark(admin_conn: psycopg.Connection[Any]) -> None:
    """Test veritabanı üretim dışıdır: işareti süper kullanıcıyla yazar (tohum betiği yalnız okur)."""
    admin_conn.execute(
        "INSERT INTO deployment_marks (key, value) VALUES ('non_production', 'true') ON CONFLICT DO NOTHING"
    )


def with_db(url: str, name: str) -> str:
    return make_url(url).set(database=name).render_as_string(hide_password=False)


def counts(conn: psycopg.Connection[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in TABLES:
        row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
        assert row is not None
        out[table] = int(row[0])
    return out


@pytest.fixture
async def sessions(settings: Settings) -> Any:
    engine = create_engine(settings.database_url)
    yield create_sessionmaker(engine)
    await engine.dispose()


@pytest.fixture
async def seeded(settings: Settings) -> SeedResult:
    return await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=ENV)


def by_key(result: SeedResult, key: str) -> Any:
    return next(acc for acc in result.accounts if acc.data.key == key)


# --------------------------------------------------------------------------------------------- koruma


def guard(settings: Settings, **kw: Any) -> None:
    args: dict[str, Any] = {"demo_flag": True, "environ": ENV, "settings": settings}
    args.update(kw)
    check_guard(**args)


def test_guard_passes_for_test_database(settings: Settings) -> None:
    guard(settings)
    guard(settings, environ={"NETKAR_ENV": "local"})  # test kümesi unix soketi: yerel sayılır
    guard(settings, environ={"NETKAR_ENV": "staging"})


def test_guard_requires_demo_flag(settings: Settings) -> None:
    with pytest.raises(DemoGuardError, match="--demo"):
        guard(settings, demo_flag=False)


@pytest.mark.parametrize(
    "env",
    [{}, {"NETKAR_ENV": ""}, {"NETKAR_ENV": "prod"}, {"NETKAR_ENV": "production"}, {"NETKAR_ENV": "dev"}],
)
def test_guard_requires_non_production_netkar_env(settings: Settings, env: dict[str, str]) -> None:
    with pytest.raises(DemoGuardError, match="NETKAR_ENV"):
        guard(settings, environ=env)


def test_guard_refuses_prod_environment_and_live_trendyol(settings: Settings) -> None:
    with pytest.raises(DemoGuardError, match="prod"):
        guard(settings.model_copy(update={"environment": "prod"}))
    with pytest.raises(DemoGuardError, match="live"):
        guard(settings.model_copy(update={"trendyol_environment": "live"}))


@pytest.mark.parametrize("name", ["netkar_prod", "netkar-production", "canli_veri", "NetKar_LIVE"])
def test_guard_refuses_production_database_names(settings: Settings, name: str) -> None:
    app_url = with_db(settings.database_url, name)
    worker_url = with_db(settings.worker_database_url or "", name)
    with pytest.raises(DemoGuardError, match="üretim"):
        guard(settings.model_copy(update={"database_url": app_url, "worker_database_url": worker_url}))


def test_guard_local_requires_local_host(settings: Settings) -> None:
    remote = "postgresql+psycopg://u:p@db.example.org:5432/netkar_demo"
    remote_settings = settings.model_copy(update={"database_url": remote, "worker_database_url": remote})
    with pytest.raises(DemoGuardError, match="yerel"):
        guard(remote_settings, environ={"NETKAR_ENV": "local"})
    guard(
        remote_settings, environ={"NETKAR_ENV": "staging"}
    )  # staging uzak sunucuya izin verir, ad kuralı geçerli


def test_guard_requires_worker_url_on_same_database(settings: Settings) -> None:
    with pytest.raises(DemoGuardError, match="WORKER_DATABASE_URL"):
        guard(settings.model_copy(update={"worker_database_url": None}))
    other = with_db(settings.worker_database_url or "", "baska_veritabani")
    with pytest.raises(DemoGuardError, match="aynı sunucu"):
        guard(settings.model_copy(update={"worker_database_url": other}))


async def test_refused_seed_writes_nothing(settings: Settings, admin_conn: psycopg.Connection[Any]) -> None:
    for bad_env in ({}, {"NETKAR_ENV": "prod"}):
        with pytest.raises(DemoGuardError):
            await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=bad_env)
    with pytest.raises(DemoGuardError):
        await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=False, environ=ENV)
    with pytest.raises(DemoGuardError, match="as-of"):
        await seed(settings, SeedOptions(as_of=date(2026, 1, 1)), demo_flag=True, environ=ENV)
    with pytest.raises(DemoGuardError, match="instance"):
        await seed(settings, SeedOptions(as_of=AS_OF, instance=0), demo_flag=True, environ=ENV)
    assert counts(admin_conn) == dict.fromkeys(TABLES, 0)


# ------------------------------------------------------------------------------------- idempotency


async def test_seed_is_idempotent_and_shifts_dates(
    settings: Settings, seeded: SeedResult, admin_conn: psycopg.Connection[Any]
) -> None:
    first = counts(admin_conn)
    assert first["tenants"] == 3 and first["marketplace_accounts"] == 3
    assert first["orders"] > 150 and first["product_costs"] > 40
    assert all(acc.password for acc in seeded.accounts)  # ilk çalıştırma: parolalar üretildi
    # Demo kullanıcıları doğrulanmış açılır (yoksa yazma uçlarında 403 email-not-verified alırlar).
    assert admin_conn.execute(
        "SELECT count(*) FILTER (WHERE email_verified_at IS NULL) FROM users"
    ).fetchone() == (0,)

    again = await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=ENV)
    assert counts(admin_conn) == first
    assert [a.password for a in again.accounts] == [
        None,
        None,
        None,
    ]  # var olan hesap: parola sorulmaz, değişmez
    assert [a.account_id for a in again.accounts] == [a.account_id for a in seeded.accounts]

    row = admin_conn.execute("SELECT min(ordered_at), max(ordered_at) FROM orders").fetchone()
    assert row is not None
    shifted = await seed(settings, SeedOptions(as_of=AS_OF + timedelta(days=1)), demo_flag=True, environ=ENV)
    assert counts(admin_conn) == first  # tarih kaydı çoğaltmaz
    moved = admin_conn.execute("SELECT min(ordered_at), max(ordered_at) FROM orders").fetchone()
    assert (
        moved is not None
        and moved[0] - row[0] == timedelta(days=1)
        and moved[1] - row[1] == timedelta(days=1)
    )
    assert shifted.accounts[0].tenant_id == seeded.accounts[0].tenant_id


async def test_instances_are_separate_tenants(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    one = await seed(settings, SeedOptions(as_of=AS_OF, datasets=("x",)), demo_flag=True, environ=ENV)
    two = await seed(
        settings, SeedOptions(as_of=AS_OF, instance=2, datasets=("x",)), demo_flag=True, environ=ENV
    )
    assert {a.tenant_id for a in one.accounts}.isdisjoint({a.tenant_id for a in two.accounts})
    assert counts(admin_conn)["tenants"] == 4


async def test_refuses_other_seed_version(
    settings: Settings, seeded: SeedResult, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed_demo, "SEED_VERSION", "999")
    with pytest.raises(DemoGuardError, match="sürümü"):
        await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=ENV)


async def test_password_env_and_reset(settings: Settings, make_api: Callable[..., Api]) -> None:
    fixed = "demo-ortam-parolasi-123"
    first = await seed(
        settings,
        SeedOptions(as_of=AS_OF, datasets=("x",)),
        demo_flag=True,
        environ={**ENV, seed_demo.PASSWORD_ENV: fixed},
    )
    assert {a.password_source for a in first.accounts} == {"env"}
    assert make_api().login(first.accounts[0].email, fixed).status_code == 200
    out = seed_demo.format_credentials(first)
    assert fixed not in out  # ortamdan gelen parola ekrana yazılmaz

    reset = await seed(
        settings, SeedOptions(as_of=AS_OF, datasets=("x",), reset_passwords=True), demo_flag=True, environ=ENV
    )
    new = reset.accounts[0].password
    assert new and new != fixed and reset.accounts[0].password_source == "generated"
    assert make_api().login(first.accounts[0].email, fixed).status_code == 401
    assert make_api().login(first.accounts[0].email, new).status_code == 200

    with pytest.raises(DemoGuardError, match="arasında"):
        await seed(
            settings,
            SeedOptions(as_of=AS_OF),
            demo_flag=True,
            environ={**ENV, seed_demo.PASSWORD_ENV: "kisa"},
        )


# --------------------------------------------------------------------------------------- RLS ve KVKK


async def test_rls_tenant_cannot_see_other_tenant(
    seeded: SeedResult, sessions: async_sessionmaker[AsyncSession]
) -> None:
    a, bx = by_key(seeded, "a"), by_key(seeded, "bx")
    async with tenant_transaction(sessions, a.tenant_id) as db:
        own = (await db.execute(select(func.count()).select_from(Order))).scalar_one()
        foreign = (
            await db.execute(
                select(func.count()).select_from(Order).where(Order.marketplace_account_id == bx.account_id)
            )
        ).scalar_one()
        accounts = (await db.execute(select(MarketplaceAccount.id))).scalars().all()
        products = (await db.execute(select(func.count()).select_from(Product))).scalar_one()
    assert own == len(a.data.orders) and foreign == 0
    assert accounts == [a.account_id] and products == len(a.data.products)
    async with tenant_transaction(sessions, bx.tenant_id) as db:
        assert (await db.execute(select(func.count()).select_from(Order))).scalar_one() == len(bx.data.orders)
        assert (
            await db.execute(
                select(func.count()).select_from(Order).where(Order.marketplace_account_id == a.account_id)
            )
        ).scalar_one() == 0
    async with sessions() as db:  # kiracı bağlamı yok: hiçbir satır görünmez
        assert (await db.execute(select(func.count()).select_from(OrderLine))).scalar_one() == 0
        assert (await db.execute(text("SELECT count(*) FROM tenants"))).scalar_one() == 0


async def test_no_customer_personal_data_and_fake_secrets(
    seeded: SeedResult, admin_conn: psycopg.Connection[Any]
) -> None:
    row = admin_conn.execute(
        "SELECT count(*) FILTER (WHERE province IS NOT NULL OR province_code IS NOT NULL OR customer_key IS NOT NULL "
        "OR cargo_tracking_number IS NOT NULL) FROM orders"
    ).fetchone()
    assert row is not None and row[0] == 0
    titles = [r[0] for r in admin_conn.execute("SELECT title FROM products").fetchall()]
    assert titles and all(t.startswith("Demo Ürün: ") for t in titles)
    names = [r[0] for r in admin_conn.execute("SELECT name FROM tenants").fetchall()]
    assert all(n.startswith("Demo Mağaza") for n in names)
    emails = [r[0] for r in admin_conn.execute("SELECT email FROM users").fetchall()]
    assert all(re.fullmatch(r"demo-(a|bx|by)-1@example\.com", e) for e in emails)
    for acc in seeded.accounts:
        assert re.fullmatch(r"9[0-9]{6}", acc.seller_id)
    # Parola ve özeti depoda sabit değildir: her çalıştırmada farklı.
    assert len({a.password for a in seeded.accounts}) == 3


async def test_stored_keys_decrypt_to_fake_placeholders(settings: Settings, seeded: SeedResult) -> None:
    """Zarf şifreli anahtarlar işçi rolüyle çözülünce sahte yer tutucudur (gerçek sır değil)."""
    from sqlalchemy.orm import undefer

    engine = create_engine(settings.worker_database_url or "")
    envelope = EnvelopeCipher(settings.key_ring)
    try:
        for acc in seeded.accounts:
            async with tenant_transaction(create_sessionmaker(engine), acc.tenant_id) as db:
                account = (
                    await db.execute(
                        select(MarketplaceAccount)
                        .options(
                            undefer(MarketplaceAccount.api_key_encrypted),
                            undefer(MarketplaceAccount.api_secret_encrypted),
                        )
                        .where(MarketplaceAccount.id == acc.account_id)
                    )
                ).scalar_one()
                creds = decrypt_credentials(envelope, account)
            assert creds.api_key.get_secret_value().startswith("demo-sahte-")
            assert creds.api_secret.get_secret_value().startswith("demo-sahte-")
    finally:
        await engine.dispose()


def test_no_personal_data_in_financial_returns_and_cargo_tables(
    seeded: SeedResult, admin_conn: psycopg.Connection[Any]
) -> None:
    """Ekstre, kargo faturası, iade ve satır tablolarında kişisel veri yok: metinler beyaz listeden, '@' yok."""
    assert admin_conn.execute("SELECT count(*) FROM returns").fetchone() == (0,)
    texts = {r[0] for r in admin_conn.execute("SELECT DISTINCT type_text FROM financial_transactions")}
    assert texts <= {"Satış", "İade", "Platform Hizmet Bedeli", "Kargo Faturası"}
    descriptions = {
        r[0] for r in admin_conn.execute("SELECT DISTINCT description FROM financial_transactions")
    }
    assert descriptions <= {"Satış", "İade", "Platform Hizmet Bedeli", "Kargo Faturası"}
    kinds = {
        r[0] for r in admin_conn.execute("SELECT DISTINCT shipment_package_type FROM cargo_invoice_items")
    }
    assert kinds <= {"Gönderi Kargo Bedeli", "İade Kargo Bedeli"}
    assert admin_conn.execute(
        "SELECT count(*) FROM financial_transactions WHERE commission_invoice_serial_number IS NOT NULL "
        "OR receipt_id IS NOT NULL"
    ).fetchone() == (0,)
    for table in ("financial_transactions", "cargo_invoice_items", "order_lines", "orders", "products"):
        rows = admin_conn.execute(f"SELECT t::text FROM {table} t").fetchall()
        assert rows and not any("@" in r[0] for r in rows), table
    keys = {k for (items,) in admin_conn.execute("SELECT items FROM order_lines") for i in items for k in i}
    assert keys == {"id", "seller_discount", "ty_discount"}


def test_seed_modules_contain_no_credentials_or_forbidden_dashes() -> None:
    for module in (seed_demo, demo_data):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        assert chr(0x2014) not in source and chr(0x2015) not in source
    # Çalışma anında verilen parola dışında sabit bir giriş parolası yok.
    assert not re.search(
        r"password\s*=\s*[\"'][^\"']{8,}[\"']", Path(seed_demo.__file__ or "").read_text(encoding="utf-8")
    )


# ---------------------------------------------------------------------------------- senaryo ve kart


@pytest.fixture
async def facts(settings: Settings, seeded: SeedResult) -> list[AccountFacts]:
    engine = create_engine(settings.database_url)
    try:
        return await compute_facts(create_sessionmaker(engine), seeded.accounts, AS_OF)
    finally:
        await engine.dispose()


def facts_for(facts: list[AccountFacts], key: str) -> AccountFacts:
    return next(f for f in facts if f.key == key)


def test_account_a_is_partial_with_positive_known_profit(facts: list[AccountFacts]) -> None:
    a = facts_for(facts, "a")
    assert a.period_net_profit is None and a.net_profit_partial
    assert a.period_known_profit > 0 and not a.loss_products
    assert a.missing_shipping_lines == a.missing_fee_lines == a.line_count > 0 and a.missing_cost_lines == 0
    # Bilgi kartı girilince net kâr görünür ve pozitiftir; G3 değişikliği kârı azaltır.
    assert a.after_g2 is not None and a.after_g2[0] is not None and a.after_g2[0] > 0 and not a.after_g2[1]
    assert a.after_g3 is not None and a.after_g3[0] is not None and a.after_g3[0] < a.after_g2[0]
    assert a.after_g2[0] < a.period_known_profit


@pytest.mark.parametrize("key", ["bx", "by"])
def test_account_b_has_every_scenario(facts: list[AccountFacts], key: str) -> None:
    b = facts_for(facts, key)
    roles = b.roles
    assert {p.reason for p in b.loss_products} == {"net_profit", "contribution_before_cost", "known_expenses"}
    assert len(b.loss_products) == 3
    top = b.loss_products[0]
    assert top.barcode == roles["loss_net"] and top.reason == "net_profit"
    assert top.value <= 3 * b.loss_products[1].value  # kesin farkla en çok zarar eden (en az 3 kat)
    assert top.top_expense_excl_cost == "Kargo (gönderi)"
    assert sorted(b.cost_missing_products) == sorted([roles["loss_nocost"], roles["nocost_other"]])
    assert len(b.awaiting_orders) >= 2 and {roles["old_awaiting_1"], roles["old_awaiting_2"]} <= set(
        b.awaiting_orders
    )
    assert roles["unexpected_commission"] in {u.order_number for u in b.unexpected}
    assert b.alert_counts[WarningCode.LOSS.value] > 0 and b.alert_counts[WarningCode.MISSING_COST.value] > 0
    assert b.alert_counts[WarningCode.REFUND_RECORD_PENDING.value] == 1
    assert b.multi_order is not None and len(b.multi_order.lines) == 2
    assert any(line.pending_refund_quantity == 1 for line in b.multi_order.lines)
    # Dolgu ürünlerin hepsi kârlı: zarar yalnız kurgulanmış üç üründedir.
    assert {p.barcode for p in b.loss_products} == {
        roles["loss_net"],
        roles["loss_known"],
        roles["loss_nocost"],
    }


def test_datasets_x_and_y_differ(facts: list[AccountFacts]) -> None:
    x, y = facts_for(facts, "bx"), facts_for(facts, "by")
    assert x.loss_products[0].barcode != y.loss_products[0].barcode
    assert x.loss_products[0].title != y.loss_products[0].title
    assert x.roles["multi_order"] != y.roles["multi_order"]
    assert {u.order_number for u in x.unexpected}.isdisjoint({u.order_number for u in y.unexpected})
    assert len(x.unexpected) != len(y.unexpected)


async def test_card_matches_report_api(
    seeded: SeedResult, facts: list[AccountFacts], make_api: Callable[..., Api]
) -> None:
    """Kartın her rakamı, aynı veriyi okuyan rapor API uçlarının yanıtıyla birebir aynıdır."""
    for acc in seeded.accounts:
        f = facts_for(facts, acc.data.key)
        assert acc.password is not None
        api = make_api()
        assert api.login(acc.email, acc.password).status_code == 200
        base = f"/v1/marketplace-accounts/{acc.account_id}/profit"
        period = f"start={f.start.isoformat()}&end={f.end.isoformat()}"
        body = api.get(f"{base}/summary?{period}").json()
        totals = body["totals"]
        known = f"{f.period_known_profit:.2f}"
        assert totals["donem_eksik_giderler_haric_kar"] == known
        assert totals["donem_net_kar"] == (
            None if f.period_net_profit is None else f"{f.period_net_profit:.2f}"
        )
        assert totals["net_kar_kismi"] is f.net_profit_partial
        assert totals["siparis_sayisi"] == f.order_count and totals["satir_sayisi"] == f.line_count
        assert totals["tam_satirlar"]["satir_sayisi"] == f.full_lines_count
        assert totals["eksik_kalem_satir_sayilari"]["kargo_gonderi"] == f.missing_shipping_lines

        listing = api.get(f"{base}/products?{period}&filter=loss&sort=net_profit&order=asc&limit=200").json()
        assert listing["total_count"] == len(f.loss_products)
        assert {i["barcode"]: i["loss_reason"] for i in listing["items"]} == {
            p.barcode: p.reason for p in f.loss_products
        }
        if f.loss_products:
            top = f.loss_products[0]
            first = listing["items"][0]
            assert first["barcode"] == top.barcode and first["title"] == top.title
            assert first["net_profit"] == f"{top.net_profit:.2f}"
        missing = api.get(f"{base}/products?{period}&filter=missing_cost&limit=200").json()
        assert sorted(i["barcode"] for i in missing["items"]) == f.cost_missing_products

        awaiting = api.get(f"{base}/orders?{period}&filter=awaiting_payout&limit=200").json()
        assert awaiting["total_count"] == len(f.awaiting_orders)
        assert sorted(i["order_number"] for i in awaiting["items"]) == f.awaiting_orders
        unexpected = api.get(f"{base}/orders?{period}&filter=unexpected_deduction&limit=200").json()
        assert sorted(i["order_number"] for i in unexpected["items"]) == [
            u.order_number for u in f.unexpected
        ]

        alerts = api.get(f"{base}/alerts?{period}").json()
        assert {c["code"]: c["count"] for c in alerts["counts"]} == f.alert_counts

        if f.multi_order is not None:
            detail = api.get(f"{base}/orders/{f.multi_order.number}?{period}").json()
            assert len(detail["lines"]) == len(f.multi_order.lines)
            net = None if f.multi_order.net_profit is None else f"{f.multi_order.net_profit:.2f}"
            assert detail["totals"]["net_profit"] == net


async def test_card_a_after_info_card_matches_real_settings_write(
    seeded: SeedResult, facts: list[AccountFacts], make_api: Callable[..., Api]
) -> None:
    """Katılımcı bilgi kartını gerçekten girince API'nin dönem net kârı kartın G2 ve G3 değerleriyle aynıdır."""
    a, f = by_key(seeded, "a"), facts_for(facts, "a")
    api = make_api()
    assert api.login(a.email, a.password).status_code == 200
    base = f"/v1/marketplace-accounts/{a.account_id}"
    brackets = [{"max_desi": str(d), "price": str(p)} for d, p in demo_data.INFO_CARD_TARIFF]
    tariff = {
        "agreement": "trendyol",
        "carrier": "Trendyol Express",
        "valid_from": "2026-01-01",
        "price_includes_vat": True,
        "brackets": brackets,
    }
    put = api.put(f"{base}/profit-settings/cargo-tariffs", tariff)
    assert put.status_code == 200, put.text  # ilk giriş: onay penceresi (409) çıkmaz
    fee = {"valid_from": "2026-01-01", "amount": "10.00", "amount_includes_vat": True}
    assert api.put(f"{base}/profit-settings/service-fee-estimates", fee).status_code == 200
    period = f"start={f.start.isoformat()}&end={f.end.isoformat()}"
    summary = api.get(f"{base}/profit/summary?{period}").json()
    assert f.after_g2 is not None and f.after_g2[0] is not None
    assert (
        summary["totals"]["donem_net_kar"] == f"{f.after_g2[0]:.2f}"
        and not summary["totals"]["net_kar_kismi"]
    )
    # G3: mevcut tarifeyi düzenlemek geçmişi etkiler ve açık onay ister.
    edited = {
        **tariff,
        "brackets": [{"max_desi": str(d), "price": str(p)} for d, p in demo_data.INFO_CARD_TARIFF_AFTER_G3],
    }
    refused = api.put(f"{base}/profit-settings/cargo-tariffs", edited)
    assert refused.status_code == 409
    confirmed = api.put(
        f"{base}/profit-settings/cargo-tariffs", {**edited, "confirm_affects_from": "2026-01-01"}
    )
    assert confirmed.status_code == 200, confirmed.text
    after = api.get(f"{base}/profit/summary?{period}").json()
    assert f.after_g3 is not None and f.after_g3[0] is not None
    assert after["totals"]["donem_net_kar"] == f"{f.after_g3[0]:.2f}"


def test_rendered_card_content(facts: list[AccountFacts], seeded: SeedResult) -> None:
    card = render_card(facts, AS_OF, 1)
    assert f"Tohum sürümü: **{demo_data.SEED_VERSION}**" in card
    assert "2026-10-16 - 2026-11-14" in card and "2026-11-14" in card
    for heading in ("G1", "G2", "G3", "G4 / G8a", "G5", "G6 / G8b", "G7"):
        assert heading in card
    b = facts_for(facts, "bx")
    assert b.loss_products[0].barcode in card and b.multi_order is not None and b.multi_order.number in card
    assert f"**{len(b.awaiting_orders)}**" in card
    for acc in seeded.accounts:
        assert acc.password is not None and acc.password not in card
    assert chr(0x2014) not in card and chr(0x2015) not in card


# ----------------------------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    values = {
        "DATABASE_URL": settings.database_url,
        "WORKER_DATABASE_URL": settings.worker_database_url or "",
        "DATA_ENCRYPTION_KEY": settings.data_encryption_key.get_secret_value(),
        "DATA_KEKS": settings.data_keks.get_secret_value() if settings.data_keks else "",
        "DATA_KEK_ACTIVE": settings.data_kek_active or "",
        "ENVIRONMENT": "test",
        "EMAIL_BACKEND": "memory",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    yield


def test_cli_end_to_end(cli_env: None, tmp_path: Path, admin_conn: psycopg.Connection[Any]) -> None:
    card = tmp_path / "karti.md"
    out = io.StringIO()
    code = seed_demo.main(["--demo", "--as-of", AS_OF.isoformat(), "--card-path", str(card)], ENV, out)
    assert code == 0
    text_out = out.getvalue()
    assert "Demo girişleri" in text_out and "demo-a-1@example.com" in text_out and "Tohum sürümü" in text_out
    password = text_out.split("demo-a-1@example.com")[1].split()[0]
    assert len(password) >= 20
    written = card.read_text(encoding="utf-8")
    assert password not in written and "Demo doğru cevap kartı" in written
    first = counts(admin_conn)

    out2 = io.StringIO()
    assert seed_demo.main(["--demo", "--as-of", AS_OF.isoformat(), "--card-path", str(card)], ENV, out2) == 0
    assert "parola değişmedi" in out2.getvalue() and password not in out2.getvalue()
    assert counts(admin_conn) == first
    assert card.read_text(encoding="utf-8") == written  # kart deterministik


@pytest.mark.parametrize(
    ("argv", "env"),
    [
        (["--as-of", AS_OF.isoformat()], ENV),  # --demo yok
        (["--demo", "--as-of", AS_OF.isoformat()], {}),  # NETKAR_ENV yok
        (["--demo", "--as-of", AS_OF.isoformat()], {"NETKAR_ENV": "prod"}),
    ],
)
def test_cli_guard_exit_code(
    cli_env: None,
    argv: list[str],
    env: dict[str, str],
    tmp_path: Path,
    admin_conn: psycopg.Connection[Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = seed_demo.main([*argv, "--card-path", str(tmp_path / "k.md")], env, io.StringIO())
    assert code == 3
    assert "Reddedildi" in capsys.readouterr().err
    assert counts(admin_conn)["tenants"] == 0 and not (tmp_path / "k.md").exists()


def test_cli_prod_environment_setting_refused(
    cli_env: None, monkeypatch: pytest.MonkeyPatch, database: DatabaseInfo, capsys: pytest.CaptureFixture[str]
) -> None:
    # ENVIRONMENT=prod için ayar doğrulaması DATA_KEKS ister (cli_env verir) ve e-posta arka ucu file/memory olamaz.
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("EMAIL_BACKEND", "smtp-yok")
    assert seed_demo.main(["--demo"], ENV, io.StringIO()) == 3  # ayar doğrulaması zaten reddeder
    assert capsys.readouterr().err


async def test_write_card_returns_facts(settings: Settings, seeded: SeedResult, tmp_path: Path) -> None:
    facts = await write_card(settings, seeded, tmp_path / "alt" / "k.md")
    assert {f.key for f in facts} == {"a", "bx", "by"} and (tmp_path / "alt" / "k.md").is_file()
    assert Decimal(0) < facts_for(facts, "a").period_known_profit


# ------------------------------------------------------------------ bağlantı hedefi koruması (DT-01)


@pytest.mark.parametrize(
    "tail",
    ["?dbname=baska", "?hostaddr=10.0.0.5", "?service=uretim", "?servicefile=/x/y"],
)
def test_guard_refuses_query_that_redirects_the_target(settings: Settings, tail: str) -> None:
    base = "postgresql+psycopg://netkar_app:x@localhost:5432/netkar_demo"
    for field in ("database_url", "worker_database_url"):
        other = {"database_url": base, "worker_database_url": base}
        other[field] = base + tail
        with pytest.raises(DemoGuardError, match="hedefini değiştiren"):
            guard(settings.model_copy(update=other), environ={"NETKAR_ENV": "staging"})


def test_guard_refuses_ambiguous_empty_and_remote_socket_hosts(settings: Settings) -> None:
    def urls(url: str) -> Settings:
        return settings.model_copy(update={"database_url": url, "worker_database_url": url})

    with pytest.raises(DemoGuardError, match="açık bir sunucu"):  # boş sunucu PGHOST'a düşer
        guard(urls("postgresql+psycopg://u:p@/netkar_demo"), environ={"NETKAR_ENV": "staging"})
    with pytest.raises(DemoGuardError, match="belirsiz"):  # URL'de de sorguda da sunucu
        guard(
            urls("postgresql+psycopg://u:p@localhost/netkar_demo?host=/tmp"),
            environ={"NETKAR_ENV": "staging"},
        )
    with pytest.raises(DemoGuardError, match="yerel"):  # uzak unix soketi (Cloud SQL vekili)
        guard(
            urls("postgresql+psycopg://u:p@/netkar_demo?host=/cloudsql/proje:bolge:ornek"),
            environ={"NETKAR_ENV": "local"},
        )
    with pytest.raises(DemoGuardError, match="yerel"):
        guard(
            urls("postgresql+psycopg://u:p@/netkar_demo?host=/tmp/../cloudsql/x"),
            environ={"NETKAR_ENV": "local"},
        )
    with pytest.raises(DemoGuardError, match="birden çok"):
        guard(urls("postgresql+psycopg://u:p@a,b/netkar_demo"), environ={"NETKAR_ENV": "staging"})
    guard(
        urls("postgresql+psycopg://u:p@/netkar_demo?host=/var/run/postgresql&port=5433"),
        environ={"NETKAR_ENV": "local"},
    )
    guard(urls("postgresql+psycopg://u:p@127.0.0.1:5432/netkar_demo"), environ={"NETKAR_ENV": "local"})


def test_parse_target_rejects_port_in_both_url_and_query_like_the_driver_would_override() -> None:
    """DT-13: psycopg sorgudaki `port`'u URL'dekinin üstüne yazar; ikisi birlikte belirsiz hedeftir."""
    from app.tools.seed_demo import parse_target

    with pytest.raises(DemoGuardError, match="hem URL'de hem sorguda port"):
        parse_target("DATABASE_URL", "postgresql+psycopg://u:p@:5432/netkar?host=/tmp&port=6543")
    with pytest.raises(DemoGuardError, match="hem URL'de hem sorguda port"):
        parse_target("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/netkar?port=5432")
    # Tek kaynaktan gelen port aynen okunur (sürücünün gördüğü değer).
    assert parse_target("L", "postgresql+psycopg://u:p@/netkar?host=/tmp&port=6543").port == 6543
    assert parse_target("L", "postgresql+psycopg://u:p@localhost:5432/netkar").port == 5432
    assert parse_target("L", "postgresql+psycopg://u:p@localhost/netkar").port is None


def test_guard_refuses_docker_network_host_names_in_local_mode(settings: Settings) -> None:
    """DT-14: local yalnız loopback. `postgres` ve `db` Docker ağı adlarıdır (özel adrese çözülür)."""
    for name in ("postgres", "db"):
        url = f"postgresql+psycopg://u:p@{name}:5432/netkar_demo"
        remote = settings.model_copy(update={"database_url": url, "worker_database_url": url})
        with pytest.raises(DemoGuardError, match="yerel"):
            guard(remote, environ={"NETKAR_ENV": "local"})
        guard(remote, environ={"NETKAR_ENV": "test"})


async def test_server_side_checks_refuse_wrong_roles_before_any_write(
    settings: Settings, database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    owner = database.owner_url.render_as_string(hide_password=False)
    admin = database.admin_url.render_as_string(hide_password=False)
    with pytest.raises(DemoGuardError, match="netkar_app rolüyle"):
        await seed(
            settings.model_copy(update={"database_url": owner}),
            SeedOptions(as_of=AS_OF),
            demo_flag=True,
            environ=ENV,
        )
    with pytest.raises(DemoGuardError, match="netkar_worker rolüyle"):
        await seed(
            settings.model_copy(update={"worker_database_url": owner}),
            SeedOptions(as_of=AS_OF),
            demo_flag=True,
            environ=ENV,
        )
    for url in (admin,):  # süper kullanıcı hiçbir yerde kabul edilmez (rol adı zaten tutmaz)
        with pytest.raises(DemoGuardError, match="rolüyle"):
            await seed(
                settings.model_copy(update={"database_url": url}),
                SeedOptions(as_of=AS_OF),
                demo_flag=True,
                environ=ENV,
            )
    assert counts(admin_conn) == dict.fromkeys(TABLES, 0)


@pytest.mark.cluster_global  # ALTER ROLE küme düzeyindedir (paylaşılan kümede öteki işçileri etkilerdi)
async def test_super_or_bypassrls_role_is_refused_even_with_expected_name(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    from app.tools.seed_demo import verify_server

    admin_conn.execute("ALTER ROLE netkar_app BYPASSRLS")
    try:
        engine = create_engine(settings.database_url)
        try:
            with pytest.raises(DemoGuardError, match="BYPASSRLS"):
                await verify_server(engine, "DATABASE_URL", "test", expected_role="netkar_app")
        finally:
            await engine.dispose()
    finally:
        admin_conn.execute("ALTER ROLE netkar_app NOBYPASSRLS")


@pytest.mark.parametrize(
    ("address", "local_ok", "other_ok"),
    [
        (None, True, True),  # unix soketi: adres yok (yerel dizin denetimi parse_target'ta)
        ("127.0.0.1", True, True),
        ("::1", True, True),
        ("::ffff:127.0.0.1", True, True),
        ("172.18.0.2", False, True),  # CI: Docker özel ağı
        ("10.0.0.5", False, True),
        ("192.168.1.10", False, True),
        ("fd00::5", False, True),
        ("8.8.8.8", False, False),  # genel adres: hiçbir ortamda
        ("2606:4700:4700::1111", False, False),
    ],
)
def test_server_address_policy_per_environment(address: str | None, local_ok: bool, other_ok: bool) -> None:
    """DT-14: local YALNIZ loopback; özel ağ yalnız test ve staging'de; genel adres hiçbirinde."""
    from app.tools.seed_demo import check_server_address

    def verdict(env: str) -> bool:
        try:
            check_server_address("DATABASE_URL", env, address)
        except DemoGuardError:
            return False
        return True

    assert verdict("local") is local_ok
    assert verdict("test") is other_ok and verdict("staging") is other_ok


async def test_local_mode_requires_loopback_server_address(settings: Settings) -> None:
    """Gerçek sunucu: yerelde unix soketi (adres yok), CI'da Docker ağında TCP (ör. 172.18.0.2).

    `local` yalnız loopback ya da soket kabul eder; sunucu özel ağ adresinden bildiriyorsa REDDEDER ve aynı
    bağlantı `test` ile kabul edilir. Beklenti ortama göre değil, sunucunun bildirdiği adrese göre kurulur.
    """
    from app.tools.seed_demo import verify_server

    engine = create_engine(settings.database_url)
    try:
        identity = await verify_server(engine, "DATABASE_URL", "test", expected_role="netkar_app")
        assert identity.role == "netkar_app" and identity.instance_id
        loopback = identity.address is None or ipaddress.ip_address(identity.address).is_loopback
        if loopback:
            assert (
                await verify_server(engine, "DATABASE_URL", "local", expected_role="netkar_app")
            ) == identity
        else:
            with pytest.raises(DemoGuardError, match="loopback"):
                await verify_server(engine, "DATABASE_URL", "local", expected_role="netkar_app")
    finally:
        await engine.dispose()


async def test_instance_id_is_the_same_on_app_worker_and_admin_connections(
    settings: Settings, database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    """DT-13: sunucu kimliği veritabanındaki `instance_id`; üç bağlantıda da aynı (soket adresi olmasa bile)."""
    from app.tools.seed_demo import verify_server

    stored = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert stored is not None and re.fullmatch(r"[0-9a-f-]{36}", stored[0])
    found = []
    for url, role in (
        (settings.database_url, "netkar_app"),
        (settings.worker_database_url or "", "netkar_worker"),
        (database.admin_url.render_as_string(hide_password=False), None),
    ):
        engine = create_engine(url)
        try:
            found.append(await verify_server(engine, "URL", "test", expected_role=role))
        finally:
            await engine.dispose()
    assert {i.instance_id for i in found} == {stored[0]}
    assert len({i.server_key for i in found}) == 1


def test_server_identity_mismatch_is_refused_even_without_address_and_port() -> None:
    """DT-13: unix soketinde adres ve port NULL; aynı adlı ama başka sunucudaki veritabanı instance_id ile ayrılır."""
    from app.tools.seed_demo import ServerIdentity, check_same_server

    mine = ServerIdentity("netkar", None, None, "netkar_app", "11111111-1111-1111-1111-111111111111")
    redirected = ServerIdentity("netkar", None, None, "netkar_worker", "22222222-2222-2222-2222-222222222222")
    with pytest.raises(DemoGuardError, match="farklı"):
        check_same_server(mine, redirected, "farklı sunucu")
    check_same_server(mine, ServerIdentity("netkar", None, None, "netkar_worker", mine.instance_id), "x")


async def test_missing_instance_id_is_refused(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    saved = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert saved is not None
    admin_conn.execute("DELETE FROM deployment_marks WHERE key = 'instance_id'")
    try:
        with pytest.raises(DemoGuardError, match="instance_id"):
            await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=ENV)
        assert counts(admin_conn) == dict.fromkeys(TABLES, 0)
    finally:
        admin_conn.execute(
            "INSERT INTO deployment_marks (key, value) VALUES ('instance_id', %s)", (saved[0],)
        )


# ------------------------------------------------------------ "üretim değil" işareti (DT-01 c)


def _dsn(url: Any) -> str:
    return str(url.set(drivername="postgresql").render_as_string(hide_password=False))


def _mark_row(conn: psycopg.Connection[Any]) -> tuple[Any, ...] | None:
    return conn.execute("SELECT value FROM deployment_marks WHERE key = 'non_production'").fetchone()


@pytest.fixture
def unmarked(admin_conn: psycopg.Connection[Any]) -> Iterator[None]:
    admin_conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")
    yield
    admin_conn.execute(
        "INSERT INTO deployment_marks (key, value) VALUES ('non_production', 'true') ON CONFLICT DO NOTHING"
    )


async def test_unmarked_database_is_refused_and_seed_never_writes_the_mark(
    settings: Settings, database: DatabaseInfo, admin_conn: psycopg.Connection[Any], unmarked: None
) -> None:
    """DT-14: işaret yoksa tohum durur; yönetici bağlantısı verilse bile TOHUM işareti yazmaz."""
    owner = _dsn(database.owner_url)
    for env in (ENV, {**ENV, "DATABASE_ADMIN_URL": owner}):
        with pytest.raises(DemoGuardError, match="mark-non-prod"):
            await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=env)
    assert counts(admin_conn) == dict.fromkeys(TABLES, 0) and _mark_row(admin_conn) is None
    # `--mark-non-prod` tohumdan kaldırıldı.
    with pytest.raises(SystemExit):
        seed_demo.main(["--demo", "--mark-non-prod"], ENV, io.StringIO())


async def test_mark_non_prod_prints_identity_and_requires_explicit_confirmation(
    settings: Settings, database: DatabaseInfo, admin_conn: psycopg.Connection[Any], unmarked: None
) -> None:
    from app.tools.seed_demo import mark_non_prod_command

    owner_env = {**ENV, "DATABASE_ADMIN_URL": _dsn(database.owner_url)}
    out = io.StringIO()
    instance = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert instance is not None
    expected = f"{database.name}@{instance[0]}"

    # Onay yok: kimlik yazılır ve onay istenir, işaret YAZILMAZ.
    with pytest.raises(DemoGuardError, match="--confirm"):
        await mark_non_prod_command(settings, owner_env, confirm=None, out=out)
    assert expected in out.getvalue() and instance[0] in out.getvalue() and _mark_row(admin_conn) is None
    # Yanlış onay (başka veritabanı ya da başka sunucu kimliği): yazılmaz.
    for wrong in (f"{database.name}@{uuid4()}", f"baska@{instance[0]}", database.name, ""):
        with pytest.raises(DemoGuardError, match="eşleşmiyor"):
            await mark_non_prod_command(settings, owner_env, confirm=wrong, out=io.StringIO())
    assert _mark_row(admin_conn) is None
    # Yönetici bağlantısı olmadan, uygulama rolüyle ve süper kullanıcı olmayan rolle yazılmaz.
    with pytest.raises(DemoGuardError, match="DATABASE_ADMIN_URL gerekir"):
        await mark_non_prod_command(settings, ENV, confirm=expected, out=io.StringIO())
    with pytest.raises(DemoGuardError, match="süper kullanıcı ya da netkar_owner"):
        await mark_non_prod_command(
            settings, {**ENV, "DATABASE_ADMIN_URL": database.app_dsn()}, confirm=expected, out=io.StringIO()
        )
    assert _mark_row(admin_conn) is None
    # Doğru onay: yazılır; ikinci çalıştırma zararsızdır; ardından tohum çalışır.
    out = io.StringIO()
    await mark_non_prod_command(settings, owner_env, confirm=expected, out=out)
    assert _mark_row(admin_conn) == ("true",)
    # DT-17: işaret yazılırken instance_id yenilenir (kopya üretimden ayrışır) ve yeni kimlik yazdırılır.
    renewed = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert renewed is not None and renewed[0] != instance[0]
    assert f"instance_id={renewed[0]}" in out.getvalue()
    # Eski onay artık geçmez; yeni kimlikle ikinci çalıştırma zararsızdır ve kimliği OYNATMAZ.
    with pytest.raises(DemoGuardError, match="eşleşmiyor"):
        await mark_non_prod_command(settings, owner_env, confirm=expected, out=io.StringIO())
    again = io.StringIO()
    await mark_non_prod_command(settings, owner_env, confirm=f"{database.name}@{renewed[0]}", out=again)
    assert (
        admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
        == renewed
    )
    assert "yenilendi" not in again.getvalue()
    result = await seed(settings, SeedOptions(as_of=AS_OF), demo_flag=True, environ=ENV)
    assert len(result.accounts) == 3


def test_mark_non_prod_cli_subcommand(
    cli_env: None,
    database: DatabaseInfo,
    admin_conn: psycopg.Connection[Any],
    capsys: pytest.CaptureFixture[str],
    unmarked: None,
) -> None:
    env = {**ENV, "DATABASE_ADMIN_URL": _dsn(database.owner_url)}
    out = io.StringIO()
    assert seed_demo.main(["mark-non-prod"], env, out) == 3  # onay yok
    assert "--confirm" in capsys.readouterr().err and _mark_row(admin_conn) is None
    instance = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert instance is not None
    flag = f"{database.name}@{instance[0]}"
    assert flag in out.getvalue()
    assert seed_demo.main(["mark-non-prod", "--confirm", flag], env, io.StringIO()) == 0
    assert _mark_row(admin_conn) == ("true",)
    # NETKAR_ENV yoksa alt komut da reddeder.
    assert seed_demo.main(["mark-non-prod", "--confirm", flag], {}, io.StringIO()) == 3


async def test_admin_url_must_point_to_the_same_server(
    settings: Settings, database: DatabaseInfo, unmarked: None
) -> None:
    from app.tools.seed_demo import mark_non_prod_command

    other = with_db(database.admin_dsn(), "postgres")
    with pytest.raises(DemoGuardError, match="aynı sunucu, port ve veritabanına"):
        await mark_non_prod_command(
            settings, {**ENV, "DATABASE_ADMIN_URL": other}, confirm="x@y", out=io.StringIO()
        )


async def test_admin_connection_with_another_instance_id_is_refused(
    settings: Settings, database: DatabaseInfo, admin_conn: psycopg.Connection[Any], unmarked: None
) -> None:
    """DT-13: yönetici bağlantısı aynı adlı ama başka sunucudaki veritabanına gitse, instance_id farkıyla durur."""
    from app.tools.seed_demo import ServerIdentity, mark_non_production

    real = admin_conn.execute("SELECT value FROM deployment_marks WHERE key = 'instance_id'").fetchone()
    assert real is not None
    fake = ServerIdentity(database.name, None, None, "netkar_app", str(uuid4()))
    with pytest.raises(DemoGuardError, match="farklı bir sunucuya"):
        await mark_non_production(_dsn(database.owner_url), fake, "test")
    assert _mark_row(admin_conn) is None


# ------------------------------------------------------- demo hesabı senkron dışı (DT-02)


async def test_demo_accounts_are_flagged_and_invisible_to_the_sync_gate(
    seeded: SeedResult, admin_conn: psycopg.Connection[Any]
) -> None:
    flags = admin_conn.execute("SELECT is_demo FROM marketplace_accounts").fetchall()
    assert flags == [(True,)] * 3
    assert admin_conn.execute("SELECT count(*) FROM sync_gate.syncable_accounts()").fetchone() == (0,)
    # Yeniden çalıştırma bayrağı korur (idempotent).
    assert admin_conn.execute("SELECT bool_and(is_demo) FROM marketplace_accounts").fetchone() == (True,)


def test_app_role_cannot_write_is_demo_or_marks(
    seeded: SeedResult, database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    a, bx = by_key(seeded, "a"), by_key(seeded, "bx")
    with psycopg.connect(database.app_dsn(), autocommit=False) as conn:

        def ctx(tenant: Any) -> None:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))

        ctx(a.tenant_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE marketplace_accounts SET is_demo = false")
        conn.rollback()
        ctx(a.tenant_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO marketplace_accounts (tenant_id, platform, seller_id, status, created_by, "
                "api_key_encrypted, api_secret_encrypted, is_demo) "
                "VALUES (%s, 'trendyol', '1', 'active', %s, 'x', 'y', true)",
                (a.tenant_id, a.user_id),
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("INSERT INTO deployment_marks (key, value) VALUES ('x', 'y')")
        conn.rollback()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE deployment_marks SET value = 'false'")
        conn.rollback()
        # İşaret yokken işlev reddeder; varken yalnız kendi kiracısının hesabına dokunur.
        admin_conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")
        try:
            ctx(a.tenant_id)
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("SELECT public.mark_demo_account(%s)", (a.account_id,))
            conn.rollback()
        finally:
            admin_conn.execute("INSERT INTO deployment_marks (key, value) VALUES ('non_production', 'true')")
        admin_conn.execute("UPDATE marketplace_accounts SET is_demo = false WHERE id = %s", (bx.account_id,))
        ctx(a.tenant_id)
        with pytest.raises(
            psycopg.errors.UndefinedObject
        ):  # başka kiracının hesabı: RLS, sıfır satır, HATA (DT-15)
            conn.execute("SELECT public.mark_demo_account(%s)", (bx.account_id,))
        conn.rollback()
    assert admin_conn.execute(
        "SELECT is_demo FROM marketplace_accounts WHERE id = %s", (bx.account_id,)
    ).fetchone() == (False,)


def test_mark_demo_account_raises_when_no_row_is_updated(
    seeded: SeedResult, database: DatabaseInfo, admin_conn: psycopg.Connection[Any]
) -> None:
    """DT-15: kiracı bağlamı yok, hesap yok ya da başka kiracıda ise işlev sessiz dönmez, 42704 verir."""
    a, bx = by_key(seeded, "a"), by_key(seeded, "bx")
    admin_conn.execute("UPDATE marketplace_accounts SET is_demo = false")
    with psycopg.connect(database.app_dsn(), autocommit=False) as conn:
        for tenant, account in (
            (None, a.account_id),  # bağlam yok
            (a.tenant_id, uuid4()),  # hesap yok
            (a.tenant_id, bx.account_id),  # başka kiracının hesabı
        ):
            if tenant is not None:
                conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant),))
            with pytest.raises(psycopg.errors.UndefinedObject, match="isaretlenemedi"):
                conn.execute("SELECT public.mark_demo_account(%s)", (account,))
            conn.rollback()
        conn.execute("SELECT set_config('app.tenant_id', %s, true)", (str(a.tenant_id),))
        conn.execute("SELECT public.mark_demo_account(%s)", (a.account_id,))  # kendi hesabı: başarılı
        conn.commit()
    assert admin_conn.execute(
        "SELECT is_demo FROM marketplace_accounts WHERE id = %s", (a.account_id,)
    ).fetchone() == (True,)


class _FlagNeverSet:
    """`mark_demo_account` çağrısı hata vermese de bayrak açılmıyormuş gibi davranan sahte oturum."""

    async def execute(self, statement: Any, params: Any = None) -> Any:
        class _Result:
            def scalar_one_or_none(self) -> Any:
                return False

        return _Result()


async def test_seed_verifies_is_demo_after_the_function_call() -> None:
    """DT-15: çağrıdan sonra `is_demo` doğrulanır; açılmadıysa tohum durur (hesap senkrona açık kalmaz)."""
    with pytest.raises(DemoGuardError, match="is_demo ile işaretlenemedi"):
        await seed_demo._mark_demo(_FlagNeverSet(), uuid4())  # type: ignore[arg-type]


async def test_seed_turns_function_refusal_into_a_guard_error(
    settings: Settings, admin_conn: psycopg.Connection[Any]
) -> None:
    from app.tools.seed_demo import _mark_demo

    engine = create_engine(settings.database_url)
    try:
        async with create_sessionmaker(engine)() as db:
            with pytest.raises(DemoGuardError, match="senkron dışı bırakılamadı"):
                await _mark_demo(db, uuid4())  # bağlam yok: 42704
    finally:
        await engine.dispose()


# ----------------------------------------------- yazımdan önce reddet: yabancı e-posta, sürüm, parola


async def test_foreign_tenant_email_is_refused_untouched(
    settings: Settings, make_api: Callable[..., Api], admin_conn: psycopg.Connection[Any]
) -> None:
    api = make_api()
    api.signup_and_login(seed_demo.email_for("bx", 1), tenant="Gerçek Mağaza")
    before = counts(admin_conn)
    for options in (SeedOptions(as_of=AS_OF), SeedOptions(as_of=AS_OF, reset_passwords=True)):
        with pytest.raises(DemoGuardError, match="başka bir kiracıya ait"):
            await seed(settings, options, demo_flag=True, environ=ENV)
    assert counts(admin_conn) == before  # A hesabı dahil hiçbir demo kaydı yazılmadı (ön denetim)
    assert make_api().login(seed_demo.email_for("bx", 1)).status_code == 200  # parola dokunulmadı


async def test_version_mismatch_with_reset_does_not_lock_accounts(
    settings: Settings, seeded: SeedResult, make_api: Callable[..., Api], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(seed_demo, "SEED_VERSION", "999")
    with pytest.raises(DemoGuardError, match="sürümü"):
        await seed(settings, SeedOptions(as_of=AS_OF, reset_passwords=True), demo_flag=True, environ=ENV)
    acc = by_key(seeded, "a")
    assert make_api().login(acc.email, acc.password).status_code == 200  # parola sıfırlanmadı


async def test_env_password_goes_through_the_api_password_policy(
    settings: Settings, fake_pwned: FakePwned, admin_conn: psycopg.Connection[Any]
) -> None:
    fake_pwned.pwned.add("sizmis-parola-12345")
    for bad, match in (("sizmis-parola-12345", "sızıntı"), ("x" * 129, "arasında"), ("kisa", "arasında")):
        with pytest.raises(DemoGuardError, match=match):
            await seed(
                settings,
                SeedOptions(as_of=AS_OF),
                demo_flag=True,
                environ={**ENV, seed_demo.PASSWORD_ENV: bad},
                pwned_checker=fake_pwned,
            )
    assert counts(admin_conn) == dict.fromkeys(TABLES, 0)


def test_cli_writes_card_only_when_asked(
    cli_env: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default = tmp_path / "varsayilan.md"
    monkeypatch.setattr(seed_demo, "_default_card_path", lambda: default)
    out = io.StringIO()
    assert seed_demo.main(["--demo", "--as-of", AS_OF.isoformat()], ENV, out) == 0
    assert not default.exists() and "Doğru cevap kartı yazıldı" not in out.getvalue()
    assert seed_demo.main(["--demo", "--as-of", AS_OF.isoformat(), "--write-card"], ENV, io.StringIO()) == 0
    assert default.is_file()
