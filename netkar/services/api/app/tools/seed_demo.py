"""Demo veri tohumu: kullanılabilirlik testi ve yerel demo için uydurma satıcı verisi.

Kaynak: docs/ux/kullanici_testi_plani_S4.md §7.1. Hesap A (ayarsız, kısmi dönem), Hesap B (ayarlı; veri seti
X ve Y) ve "doğru cevap kartı" (docs/ux/demo_cevap_karti.md) birlikte üretilir.

Kullanım (ayrıntı services/api/README.md, "Demo veri tohumu"):

    NETKAR_ENV=local make seed-demo                       # netkar/ dizininden
    NETKAR_ENV=local uv run python -m app.tools.seed_demo --demo [--instance 2] [--as-of 2026-11-14] [--write-card]

KORUMA (üretimde çalışmaz). Yapılandırma: `--demo` bayrağı; NETKAR_ENV `local`, `test` ya da `staging`;
ENVIRONMENT `prod` değil; TRENDYOL_ENVIRONMENT `live` değil; bağlantı dizeleri sürücünün okuduğu gibi çözülür
(hedefi değiştiren sorgu anahtarları, boş sunucu ve uzak soketler reddedilir), adlarda prod/canli/live yok,
ikisi aynı sunucu, port ve veritabanı. Bağlandıktan sonra, ilk yazımdan ÖNCE sunucuya sorulur: veritabanı adı,
adres (local iken loopback ya da özel ağ), bağlanılan rol (app: netkar_app, worker: netkar_worker; süper
kullanıcı ya da BYPASSRLS ise durur) ve veritabanında saklanan `deployment_marks.non_production` işareti
(yoksa durur; `--mark-non-prod` ile süper kullanıcı ya da netkar_owner bağlantısı olan DATABASE_ADMIN_URL
üzerinden bir kez yazılır). Demo pazaryeri hesapları `is_demo` ile işaretlenir ve senkron zamanlayıcı ile
çalıştırıcıdan dışlanır.

Yetki yolları: Betik süper kullanıcı KULLANMAZ ve RLS'yi aşmaz (yalnız `--mark-non-prod` işareti için bir kez
DATABASE_ADMIN_URL kullanılır). Kiracı ve kullanıcı `auth_gate.register_account`
ile (API'nin kayıt yolu), pazaryeri hesabı, ürün maliyeti ve kâr ayarları `netkar_app` rolüyle (API'nin
servisleri, kiracı bağlamı kurulu), Trendyol verisi (ürün, sipariş, ekstre, kargo faturası) `netkar_worker`
rolüyle (senkron işçisinin yazma yolu, kiracı bağlamı kurulu) yazılır. Yani her yazma, uygulamanın kendi rolü
ve FORCE RLS politikası altında olur; başka kiracıya yazmak mümkün değildir.

Parolalar depoda YOKTUR: yeni kullanıcı için çalışma anında rastgele üretilir ve bir kez ekrana yazılır;
istenirse NETKAR_DEMO_PASSWORD ortam değişkeninden okunur. Var olan kullanıcının parolası sorulmaz, değişmez
(`--reset-passwords` parola sıfırlama yoluyla yenisini üretir).

Idempotent: doğal anahtarlar sabittir (sipariş no, paket no, barkod, işlem no); yeniden çalıştırma satırları
çoğaltmaz, tarihleri `--as-of` ile kaydırır. Çıkış kodları: 0 başarılı, 3 koruma ya da yapılandırma hatası.
"""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import os
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import SecretStr, ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.clock import today_istanbul
from app.core.config import Settings
from app.core.envelope import EnvelopeCipher
from app.core.pwned import HibpPwnedChecker, NullPwnedChecker, PwnedPasswordChecker
from app.core.security import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, hash_password
from app.db.rls import set_rls_context, tenant_transaction
from app.db.session import create_engine, create_sessionmaker
from app.models import (
    AuditLog,
    CargoInvoiceItem,
    FinancialTransaction,
    MarketplaceAccount,
    Order,
    OrderLine,
    Product,
)
from app.models.enums import MarketplaceAccountStatus, Platform
from app.services import auth as auth_service
from app.services import profit_settings as ps
from app.services.audit import record_audit
from app.services.marketplace_accounts import encrypt_secret, find_live_account
from app.services.product_costs import CostRow, upsert_costs
from app.tools import common
from app.tools.demo_data import (
    EPOCH_DAY,
    MIN_AS_OF,
    SEED_VERSION,
    DatasetKey,
    DemoAccountData,
    DemoOrder,
    a_costs,
    build_account_a,
    build_account_b,
    order_moment,
)

AUDIT_ACTION = "demo_seed.applied"
ALLOWED_ENVS = frozenset({"local", "test", "staging"})
# Veritabanı adında bu sözcüklerden biri (sözcük sınırı gözetmeden) geçerse reddedilir.
PRODUCTION_NAME = re.compile(r"(prod|canli|canlı|live)", re.IGNORECASE)
LOCAL_NAMES = frozenset({"localhost", "127.0.0.1", "::1", "postgres", "db"})
# Bilinen yerel unix soket dizinleri (örn. /cloudsql/... ya da başka bir bağlama noktası uzak sayılır).
LOCAL_SOCKET_DIRS = ("/tmp", "/var/run/postgresql", "/run/postgresql")  # noqa: S108 (soket dizini, geçici dosya değil)
# Bağlantı hedefini URL'nin dışından değiştirebilen sorgu anahtarları: koruma bunları ASLA kabul etmez.
FORBIDDEN_QUERY_KEYS = frozenset({"hostaddr", "dbname", "service", "servicefile"})
NON_PROD_KEY = "non_production"
ADMIN_URL_ENV = "DATABASE_ADMIN_URL"
SEED_AUDIT_ACTIONS = ("demo_seed.tenant_created", "demo_seed.account_created", AUDIT_ACTION)
PASSWORD_ENV = "NETKAR_DEMO_PASSWORD"  # noqa: S105  (ortam değişkeninin ADI, değer değil)
DEMO_EMAIL_DOMAIN = "example.com"
FEE_ACTUAL_PER_ORDER = Decimal("12.00")  # ekstredeki gerçek hizmet bedeli (KDV dahil), tahmin 10,00


class DemoGuardError(Exception):
    """Koruma reddetti ya da yapılandırma geçersiz. İleti sır (parola, anahtar) içermez."""


@dataclass(frozen=True, slots=True)
class Target:
    """Bağlantı dizesinin sürücünün yorumladığı gibi çözülmüş hedefi (sunucu, port, veritabanı)."""

    host: str
    port: int | None
    database: str


def _is_local_host(host: str) -> bool:
    if host in LOCAL_NAMES:
        return True
    if not host.startswith("/") or ".." in host:
        return False
    return any(host == d or host.startswith(d + "/") for d in LOCAL_SOCKET_DIRS)


def parse_target(label: str, url: str) -> Target:
    """Bağlantı dizesini psycopg'nin yorumladığı gibi okur (DT-01).

    psycopg URL sorgusundaki anahtarları URL alanlarının üstüne yazar; bu yüzden hedefi değiştiren anahtarlar
    (`hostaddr`, `dbname`, `service`, `servicefile`) reddedilir, `host` yalnız URL'de sunucu YOKKEN sorguda
    verilebilir (unix soket dizini) ve boş sunucu (PGHOST'a düşer) kabul edilmez.
    """
    parsed = make_url(url)
    query = {k: v for k, v in parsed.query.items()}
    bad = sorted(FORBIDDEN_QUERY_KEYS & query.keys())
    if bad:
        raise DemoGuardError(f"{label} sorgusunda bağlantı hedefini değiştiren anahtar var: {', '.join(bad)}")
    query_host = query.get("host")
    if query_host is not None and parsed.host:
        raise DemoGuardError(f"{label} hem URL'de hem sorguda sunucu veriyor (belirsiz hedef)")
    host = parsed.host or (query_host if isinstance(query_host, str) else "")
    if not host:
        raise DemoGuardError(f"{label} açık bir sunucu içermiyor (boş sunucu PGHOST ortam değişkenine düşer)")
    if "," in host:
        raise DemoGuardError(f"{label} birden çok sunucu içeremez")
    raw_port = parsed.port if parsed.port is not None else query.get("port")
    try:
        port = None if raw_port is None else int(str(raw_port))
    except ValueError:
        raise DemoGuardError(f"{label} portu geçersiz") from None
    if not parsed.database:
        raise DemoGuardError(f"{label} veritabanı adı içermiyor")
    return Target(host, port, parsed.database)


def check_guard(*, demo_flag: bool, environ: Mapping[str, str], settings: Settings) -> None:
    """Üretim dışı olduğuna dair TÜM yapılandırma koşullarını denetler; biri bile tutmazsa `DemoGuardError`.

    Burada bağlantı kurulmaz; bağlandıktan sonraki sunucu denetimleri `verify_server` içindedir.
    """
    if not demo_flag:
        raise DemoGuardError("--demo bayrağı verilmeden demo veri yazılmaz")
    env = environ.get("NETKAR_ENV", "").strip().lower()
    if env not in ALLOWED_ENVS:
        raise DemoGuardError(
            f"NETKAR_ENV {'tanımsız' if not env else 'geçersiz'}: yalnız {', '.join(sorted(ALLOWED_ENVS))} kabul edilir"
        )
    if settings.environment == "prod":
        raise DemoGuardError("ENVIRONMENT=prod iken demo veri yazılmaz")
    if settings.trendyol_environment == "live":
        raise DemoGuardError("TRENDYOL_ENVIRONMENT=live iken demo veri yazılmaz")
    if settings.worker_database_url is None:
        raise DemoGuardError(
            "WORKER_DATABASE_URL tanımlı değil (Trendyol verisi netkar_worker rolüyle yazılır)"
        )
    urls = {"DATABASE_URL": settings.database_url, "WORKER_DATABASE_URL": settings.worker_database_url}
    admin = environ.get(ADMIN_URL_ENV, "")
    if admin:
        urls[ADMIN_URL_ENV] = admin
    targets: dict[str, Target] = {}
    for label, url in urls.items():
        target = parse_target(label, url)
        if PRODUCTION_NAME.search(target.database):
            raise DemoGuardError(f"{label} veritabanı adı üretim adına benziyor; demo veri yazılmaz")
        if env == "local" and not _is_local_host(target.host):
            raise DemoGuardError(f"NETKAR_ENV=local iken {label} yerel bir sunucuya işaret etmeli")
        targets[label] = target
    if len(set(targets.values())) != 1:
        raise DemoGuardError("Bağlantı dizeleri aynı sunucu, port ve veritabanına işaret etmeli")


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    """Sunucunun kendi bildirdiği kimlik (bağlantı dizesine değil, bağlanılan sunucuya güvenilir)."""

    database: str
    address: str | None  # None: unix soketi
    port: int | None
    role: str


_IDENTITY_SQL = text(
    "SELECT current_database(), host(inet_server_addr()), inet_server_port(), current_user, session_user, "
    "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user), "
    "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
)


async def verify_server(
    engine: AsyncEngine, label: str, env: str, *, expected_role: str | None
) -> ServerIdentity:
    """Bağlandıktan hemen sonra, HİÇBİR yazımdan önce: veritabanı adı, sunucu adresi ve rol (DT-01, DT-04)."""
    async with engine.connect() as conn:
        row = (await conn.execute(_IDENTITY_SQL)).one()
        await conn.rollback()
    database, address, port, role, session_role, is_super, bypass = row
    if PRODUCTION_NAME.search(str(database)):
        raise DemoGuardError(f"{label}: sunucudaki veritabanı adı üretim adına benziyor")
    if env == "local" and address is not None:
        ip = ipaddress.ip_address(address)
        if not (ip.is_loopback or ip.is_private):
            raise DemoGuardError(f"NETKAR_ENV=local iken {label} sunucu adresi yerel ya da özel ağ olmalı")
    if expected_role is not None:
        if role != expected_role or session_role != expected_role:
            raise DemoGuardError(f"{label} {expected_role} rolüyle bağlanmalı (bağlanılan rol farklı)")
        if is_super or bypass:
            raise DemoGuardError(f"{label} rolü süper kullanıcı ya da BYPASSRLS olamaz")
    return ServerIdentity(str(database), address, None if port is None else int(port), str(role))


async def require_non_production_mark(engine: AsyncEngine) -> None:
    """Veritabanında saklanan "üretim değil" işareti (`deployment_marks.non_production`) yoksa durur."""
    async with engine.connect() as conn:
        value = (
            await conn.execute(text("SELECT value FROM deployment_marks WHERE key = :k"), {"k": NON_PROD_KEY})
        ).scalar_one_or_none()
        await conn.rollback()
    if value != "true":
        raise DemoGuardError(
            "Bu veritabanında üretim dışı işareti yok (deployment_marks.non_production). Süper kullanıcı ya da "
            f"migrasyon sahibi bağlantısını {ADMIN_URL_ENV} ile verip --mark-non-prod ekleyerek bir kez işaretleyin"
        )


async def mark_non_production(admin_url: str, expected: ServerIdentity, env: str) -> None:
    """İşareti yazar (süper kullanıcı ya da netkar_owner ile, açıkça istenirse). Başka sunucuya yazmaz."""
    url = admin_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_size=1, max_overflow=0)
    try:
        found = await verify_server(engine, ADMIN_URL_ENV, env, expected_role=None)
        if (found.database, found.address, found.port) != (
            expected.database,
            expected.address,
            expected.port,
        ):
            raise DemoGuardError(
                f"{ADMIN_URL_ENV} uygulamanın bağlandığı sunucudan farklı bir sunucuya gidiyor"
            )
        async with engine.begin() as conn:
            privileged = (
                await conn.execute(
                    text(
                        "SELECT rolsuper OR current_user = 'netkar_owner' FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).scalar_one()
            if not privileged:
                raise DemoGuardError(f"{ADMIN_URL_ENV} süper kullanıcı ya da netkar_owner olmalı")
            await conn.execute(
                text(
                    "INSERT INTO deployment_marks (key, value) VALUES (:k, 'true') ON CONFLICT (key) DO NOTHING"
                ),
                {"k": NON_PROD_KEY},
            )
    finally:
        await engine.dispose()


@dataclass(slots=True)
class SeededAccount:
    """Tohumlanmış bir hesap: kimlikler ve (yalnız yeni kullanıcıda) bir kez gösterilecek parola."""

    data: DemoAccountData
    email: str
    tenant_id: UUID
    user_id: UUID
    account_id: UUID
    seller_id: str
    password: str | None = field(default=None, repr=False)
    # Parolanın kaynağı: "generated" (ekrana bir kez yazılır), "env" (NETKAR_DEMO_PASSWORD, yazılmaz) ya da None.
    password_source: str | None = None


@dataclass(frozen=True, slots=True)
class SeedOptions:
    as_of: date
    instance: int = 1
    datasets: tuple[DatasetKey, ...] = ("x", "y")
    a_variant: Literal["positive", "negative"] = "positive"
    reset_passwords: bool = False
    mark_non_prod: bool = False


@dataclass(slots=True)
class SeedResult:
    accounts: list[SeededAccount]
    options: SeedOptions


async def validate_env_password(environ: Mapping[str, str], pwned: PwnedPasswordChecker) -> None:
    """NETKAR_DEMO_PASSWORD, API'nin parola politikasından geçmeli (uzunluk sınırları ve sızmış parola denetimi)."""
    fixed = environ.get(PASSWORD_ENV, "")
    if not fixed:
        return
    if not PASSWORD_MIN_LENGTH <= len(fixed) <= PASSWORD_MAX_LENGTH:
        raise DemoGuardError(
            f"{PASSWORD_ENV} {PASSWORD_MIN_LENGTH} ile {PASSWORD_MAX_LENGTH} karakter arasında olmalı"
        )
    if await pwned.is_pwned(fixed):
        raise DemoGuardError(f"{PASSWORD_ENV} bilinen sızıntılarda geçiyor; başka bir parola seçin")


def _new_password(environ: Mapping[str, str]) -> tuple[str, str]:
    """(parola, kaynak): NETKAR_DEMO_PASSWORD verilmişse o (önceden doğrulanmış), yoksa rastgele üretilir."""
    fixed = environ.get(PASSWORD_ENV, "")
    if fixed:
        return fixed, "env"
    return secrets.token_urlsafe(18), "generated"


def seller_id_for(key: str, instance: int) -> str:
    """Obviously fake satıcı numarası (9 ile başlayan 7 hane); doğrulama deseni ^[1-9][0-9]{0,17}$."""
    slot = {"a": 1, "bx": 2, "by": 3}[key]
    return f"9{instance:03d}{slot:03d}"


def email_for(key: str, instance: int) -> str:
    return f"demo-{key}-{instance}@{DEMO_EMAIL_DOMAIN}"


@dataclass(frozen=True, slots=True)
class Existing:
    """Önceden tohumla oluşturulmuş (tanınan) demo kullanıcısı ve kiracısı."""

    user_id: UUID
    tenant_id: UUID


async def _inspect_user(sessions: async_sessionmaker[AsyncSession], email: str) -> Existing | None:
    """E-posta kayıtlıysa kiracısının TOHUMLA oluşturulduğunu (seed denetim işareti) doğrular; değilse durur.

    Salt okuma. Yabancı bir kullanıcıya (örn. staging'de önceden alınmış e-posta) dokunulmaz, parolası sıfırlanmaz
    (DT-07). Aynı çağrıda tohum sürümü de denetlenir (DT-06): hiçbir yazımdan önce reddedilir.
    """
    async with sessions() as db:
        candidate = await auth_service.find_user_for_login(db, email)
        await db.rollback()
        if candidate is None:
            return None
        if candidate.tenant_id is None:
            raise DemoGuardError(f"{email} kayıtlı ama kiracısı yok; tohumla oluşturulmamış, dokunulmadı")
        await set_rls_context(db, candidate.tenant_id, candidate.user_id)
        actions = (
            await db.execute(
                select(AuditLog.action, AuditLog.meta)
                .where(AuditLog.tenant_id == candidate.tenant_id, AuditLog.action.in_(SEED_AUDIT_ACTIONS))
                .order_by(AuditLog.id)
            )
        ).all()
        await db.rollback()
    if not actions:
        raise DemoGuardError(
            f"{email} başka bir kiracıya ait (demo tohumu oluşturmamış); parolasına ve verisine dokunulmadı"
        )
    versions = [m.get("version") for a, m in actions if a == AUDIT_ACTION and m.get("version") is not None]
    if versions and versions[-1] != SEED_VERSION:
        raise DemoGuardError(
            f"{email} kiracısı tohum sürümü {versions[-1]} ile oluşturulmuş, betik sürümü {SEED_VERSION}: "
            "betik silmez; temiz bir veritabanı ya da başka bir --instance kullanın"
        )
    return Existing(candidate.user_id, candidate.tenant_id)


async def _register_user(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    email: str,
    tenant_name: str,
    password: str,
) -> Existing:
    """Kiracı + kullanıcı + owner üyeliği (API kayıt yolu) ve aynı işlemde tohum işareti (denetim kaydı)."""
    async with sessions() as db:
        created = await auth_service.register_account(
            db, email, hash_password(password), tenant_name, settings.trial_days
        )
        if created is None:
            await db.rollback()
            raise DemoGuardError(f"{email} bu arada başkası tarafından kaydedildi; dokunulmadı")
        user_id, tenant_id = created
        await set_rls_context(db, tenant_id, user_id)
        await record_audit(db, tenant_id, "demo_seed.tenant_created", user_id=user_id, meta={"demo": True})
        await db.commit()
    return Existing(user_id, tenant_id)


async def _reset_password(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, email: str, new: str
) -> bool:
    """Parolayı API'nin sıfırlama yoluyla (auth_gate) yeniler; oturumlar iptal olur."""
    async with sessions() as db:
        issued = await auth_service.create_password_reset(db, email, settings.reset_token_ttl_minutes)
        if issued is None:
            await db.rollback()
            return False
        await db.commit()
    async with sessions() as db:
        done = await auth_service.consume_password_reset(db, issued[1], hash_password(new))
        await db.commit()
    return done is not None


async def _mark_demo(db: AsyncSession, account_id: UUID) -> None:
    """Hesabı senkron dışı bırakır (DT-02): yalnız veritabanında üretim dışı işareti varsa çalışan dar işlev."""
    await db.execute(text("SELECT public.mark_demo_account(:id)"), {"id": account_id})


async def _ensure_account(
    sessions: async_sessionmaker[AsyncSession],
    envelope: EnvelopeCipher,
    tenant_id: UUID,
    user_id: UUID,
    seller_id: str,
) -> UUID:
    """Pazaryeri hesabı: SAHTE anahtarlarla (şifreli), doğrulama çağrısı YOK. Var olan hesap yeniden kullanılır."""
    async with sessions() as db:
        await set_rls_context(db, tenant_id, user_id)
        account = await find_live_account(db, tenant_id, seller_id)
        if account is not None:
            account_id = account.id
            await _mark_demo(db, account_id)
            await db.commit()
            return account_id
        account = MarketplaceAccount(
            id=uuid4(),
            tenant_id=tenant_id,
            platform=Platform.TRENDYOL.value,
            seller_id=seller_id,
            created_by=user_id,
            status=MarketplaceAccountStatus.ACTIVE.value,
        )
        fake_key = SecretStr(
            "demo-sahte-anahtar-0000"
        )  # gitleaks:allow (uydurma yer tutucu, gerçek sır değil)
        fake_secret = SecretStr(
            "demo-sahte-sir-0000"
        )  # gitleaks:allow (uydurma yer tutucu, gerçek sır değil)
        account.api_key_encrypted = encrypt_secret(envelope, account, "api_key", fake_key)
        account.api_secret_encrypted = encrypt_secret(envelope, account, "api_secret", fake_secret)
        account.api_key_last4 = "0000"
        db.add(account)
        await db.flush()
        await record_audit(
            db,
            tenant_id,
            "demo_seed.account_created",
            user_id=user_id,
            target=str(account.id),
            meta={"demo": True},
        )
        await _mark_demo(db, account.id)
        await db.commit()
        return account.id


async def _write_settings(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    data: DemoAccountData,
) -> None:
    """Kâr ayarları, API'nin yazma servisleriyle (sürüm, günlük). Zaten varsa dokunulmaz (katılımcı düzenlemesi korunur)."""
    cfg = data.settings
    today = today_istanbul()

    async def one(write: Any) -> None:
        async with sessions() as db:
            await set_rls_context(db, tenant_id, user_id)
            ticket = await ps.begin_write(db, tenant_id, account_id, user_id, None)
            outcome = await write(db, ticket)
            if outcome is not None and outcome.changed:
                await db.commit()
            else:
                await db.rollback()

    async with sessions() as db:
        await set_rls_context(db, tenant_id, user_id)
        bundle = await ps.load_bundle(db, tenant_id, account_id)
        has_tariff = any(t.agreement == "trendyol" for t in bundle.tariffs)
        has_fee, has_desi, has_expense = (
            bool(bundle.fees),
            bundle.default_desi is not None,
            bool(bundle.expenses),
        )
        await db.rollback()

    if cfg.tariff and not has_tariff:
        tariff = ps.TariffInput("trendyol", "Trendyol Express", EPOCH_DAY, True, tuple(cfg.tariff))
        await one(
            lambda db, t: ps.write_cargo_tariff(db, tenant_id, account_id, user_id, t, tariff, today, None)
        )
    if cfg.service_fee is not None and not has_fee:
        fee = cfg.service_fee
        await one(
            lambda db, t: ps.write_service_fee(
                db, tenant_id, account_id, user_id, t, EPOCH_DAY, fee, True, today, None
            )
        )
    if cfg.default_desi is not None and not has_desi:
        desi = cfg.default_desi
        await one(lambda db, t: ps.write_default_desi(db, tenant_id, account_id, user_id, t, desi, None))
    if cfg.expense_name is not None and cfg.expense_amount is not None and not has_expense:
        expense = ps.ExpenseInput(
            cfg.expense_name, "siparis_basi", cfg.expense_amount, None, Decimal(20), EPOCH_DAY, None
        )
        # Geçmiş tarihli gider onay ister (K43): onay değeri etki tarihidir (paneldeki "Değişikliği uygula").
        await one(
            lambda db, t: ps.create_expense(db, tenant_id, account_id, user_id, t, expense, today, EPOCH_DAY)
        )


async def _write_costs(
    sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    account_id: UUID,
    user_id: UUID,
    costs: Mapping[str, tuple[Decimal, int]],
) -> None:
    rows = [CostRow(barcode, EPOCH_DAY, cost, Decimal(vat)) for barcode, (cost, vat) in costs.items()]
    async with sessions() as db:
        await set_rls_context(db, tenant_id, user_id)
        await upsert_costs(db, tenant_id, account_id, user_id, rows)
        await db.commit()


def _upsert(model: Any, rows: Sequence[dict[str, Any]], keys: Sequence[str], skip: Sequence[str] = ()) -> Any:
    stmt = pg_insert(model).values(list(rows))
    excluded = {c.name for c in model.__table__.columns} - {
        "id",
        "tenant_id",
        "marketplace_account_id",
        "created_at",
        *keys,
        *skip,
    }
    present = set(rows[0])
    update = {name: stmt.excluded[name] for name in excluded if name in present}
    return stmt.on_conflict_do_update(index_elements=list(keys), set_=update)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _order_rows(order: DemoOrder, as_of: date, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
    moment = order_moment(as_of, order.days_ago, order.hour)
    gross = sum((ln.unit_gross * ln.quantity for ln in order.lines), Decimal(0))
    return {
        "id": uuid4(),
        "tenant_id": tenant_id,
        "marketplace_account_id": account_id,
        "order_number": order.number,
        "shipment_package_id": order.package_id,
        "ordered_at": moment,
        "last_modified_at": moment,
        "status": order.status,
        "carrier": order.carrier,
        "cargo_deci": order.cargo_deci,
        "who_pays": order.who_pays,
        "commercial": False,
        "package_gross_amount": _money(gross),
        "package_seller_discount": Decimal(0),
        "package_ty_discount": Decimal(0),
        "package_total_price": _money(gross),
    }


def _financial_rows(
    data: DemoAccountData, as_of: date, tenant_id: UUID, account_id: UUID, instance_key: str
) -> list[dict[str, Any]]:
    """Ekstre (Sale/Return) ve ödeme emri düzeyi platform hizmet bedeli satırları."""
    rows: list[dict[str, Any]] = []
    base = {"tenant_id": tenant_id, "marketplace_account_id": account_id, "source": "settlements"}
    per_payment: dict[int, int] = {}
    for order in data.orders:
        if not order.settled or order.status == "Cancelled":
            continue
        moment = order_moment(as_of, order.days_ago, order.hour)
        returned = dict(order.returned_units)
        for line in order.lines:
            rate = order.statement_rate if order.statement_rate is not None else line.commission
            credit = line.unit_gross * line.quantity
            commission = _money(credit * rate / 100)
            rows.append(
                {
                    **base,
                    "id": uuid4(),
                    "request_type": "Sale",
                    "request_sub_type": "",
                    "transaction_id": f"DEMO-S-{order.number}-{line.line_id}",
                    "type_text": "Satış",
                    "description": "Satış",
                    "transaction_date": moment + timedelta(days=5),
                    "order_date": moment,
                    "barcode": line.barcode,
                    "order_number": order.number,
                    "shipment_package_id": order.package_id,
                    "payment_order_id": order.payment_order_id,
                    "debt": Decimal(0),
                    "credit": _money(credit),
                    "commission_rate": rate,
                    "commission_amount": commission,
                    "seller_revenue": _money(credit) - commission,
                }
            )
            units = returned.get(line.line_id, 0)
            if units:
                refund = line.unit_gross * units
                refund_commission = _money(refund * line.commission / 100)
                rows.append(
                    {
                        **base,
                        "id": uuid4(),
                        "request_type": "Return",
                        "request_sub_type": "",
                        "transaction_id": f"DEMO-R-{order.number}-{line.line_id}",
                        "type_text": "İade",
                        "description": "İade",
                        "transaction_date": moment + timedelta(days=9),
                        "order_date": moment,
                        "barcode": line.barcode,
                        "order_number": order.number,
                        "shipment_package_id": order.package_id,
                        "payment_order_id": order.payment_order_id,
                        "debt": _money(refund),
                        "credit": Decimal(0),
                        "commission_rate": line.commission,
                        "commission_amount": refund_commission,
                        "seller_revenue": _money(refund) - refund_commission,
                    }
                )
        invoiced = [spec for spec in (order.invoice_outbound, order.invoice_return) if spec is not None]
        if invoiced:
            # Kargo faturası ekstre satırı (K08): kimliği fatura seri numarası, borcu kalem toplamı (KDV dahil).
            rows.append(
                {
                    **base,
                    "id": uuid4(),
                    "source": "other_financials",
                    "request_type": "DeductionInvoices",
                    "request_sub_type": "",
                    "transaction_id": _invoice_serial(data, instance_key, order),
                    "type_text": "Kargo Faturası",
                    "description": "Kargo Faturası",
                    "transaction_date": moment + timedelta(days=9),
                    "payment_order_id": order.payment_order_id,
                    "debt": _money(sum((spec[0] for spec in invoiced), Decimal(0))),
                    "credit": Decimal(0),
                }
            )
        if order.payment_order_id is not None:
            per_payment[order.payment_order_id] = per_payment.get(order.payment_order_id, 0) + 1
    if data.settings.service_fee is not None:
        # Ödeme emri başına tek "Platform Hizmet Bedeli" kesintisi (siparişe bağsız, K14); sipariş sayısıyla çarpılır.
        for payment_order, count in sorted(per_payment.items()):
            rows.append(
                {
                    **base,
                    "id": uuid4(),
                    "source": "other_financials",
                    "request_type": "DeductionInvoices",
                    "request_sub_type": "PlatformServiceFee",
                    "transaction_id": f"DEMO-FEE-{payment_order}",
                    "type_text": "Platform Hizmet Bedeli",
                    "description": "Platform Hizmet Bedeli",
                    "transaction_date": None,
                    "payment_order_id": payment_order,
                    "debt": _money(FEE_ACTUAL_PER_ORDER * count),
                    "credit": Decimal(0),
                }
            )
    return rows


def _invoice_serial(data: DemoAccountData, instance_key: str, order: DemoOrder) -> str:
    return f"DEMO-KRG-{data.key.upper()}-{instance_key}-{order.number}"


def _cargo_rows(
    data: DemoAccountData, tenant_id: UUID, account_id: UUID, instance_key: str
) -> list[dict[str, Any]]:
    """Kargo faturası kalemleri: sipariş başına ayrı fatura (seri numarası sipariş numarasını içerir)."""
    rows: list[dict[str, Any]] = []
    for order in data.orders:
        for kind, spec in (("out", order.invoice_outbound), ("ret", order.invoice_return)):
            if spec is None:
                continue
            rows.append(
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "marketplace_account_id": account_id,
                    "invoice_serial_number": _invoice_serial(data, instance_key, order),
                    "item_key": f"DEMO-{order.number}-{kind}",
                    "shipment_package_type": "Gönderi Kargo Bedeli" if kind == "out" else "İade Kargo Bedeli",
                    "parcel_unique_id": 7_000_000_000_000_000
                    + order.package_id * 10
                    + (0 if kind == "out" else 1),
                    "order_number": order.number,
                    "amount": _money(spec[0]),
                    "desi": spec[1],
                }
            )
    return rows


async def _write_trendyol_data(
    worker_sessions: async_sessionmaker[AsyncSession],
    tenant_id: UUID,
    account_id: UUID,
    data: DemoAccountData,
    as_of: date,
    instance_key: str,
) -> None:
    """Katalog, sipariş, ekstre ve kargo faturası: senkron işçisinin yazma yolu (netkar_worker, kiracı bağlamı)."""
    async with tenant_transaction(worker_sessions, tenant_id) as db:
        products = [
            {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "marketplace_account_id": account_id,
                "barcode": p.barcode,
                "stock_code": p.stock_code,
                "title": p.title,
                "category_name": p.category,
                "vat_rate": Decimal(p.vat),
                "commission_rate": p.commission,
                "unit_desi": p.unit_desi,
            }
            for p in data.products
        ]
        await db.execute(_upsert(Product, products, ["marketplace_account_id", "barcode"]))
        order_rows = [_order_rows(o, as_of, tenant_id, account_id) for o in data.orders]
        returned = await db.execute(
            _upsert(Order, order_rows, ["marketplace_account_id", "shipment_package_id"]).returning(
                Order.shipment_package_id, Order.id
            )
        )
        ids = {int(package): order_id for package, order_id in returned.all()}
        line_rows: list[dict[str, Any]] = []
        for order in data.orders:
            for line in order.lines:
                line_rows.append(
                    {
                        "id": uuid4(),
                        "tenant_id": tenant_id,
                        "marketplace_account_id": account_id,
                        "order_id": ids[order.package_id],
                        "line_id": line.line_id,
                        "barcode": line.barcode,
                        "quantity": line.quantity,
                        "line_gross_amount": _money(line.unit_gross),
                        "line_seller_discount": Decimal(0),
                        "line_ty_discount": Decimal(0),
                        "vat_rate": line.vat,
                        "commission_rate": line.commission,
                        "status": order.status,
                        "items": [
                            {"id": f"{line.line_id}-{i}", "seller_discount": "0", "ty_discount": "0"}
                            for i in range(line.quantity)
                        ],
                        "removed_at": None,
                    }
                )
        await db.execute(_upsert(OrderLine, line_rows, ["order_id", "line_id"]))
        financial = _financial_rows(data, as_of, tenant_id, account_id, instance_key)
        # Her ifadede sütun kümesi sabit olmalı: kaynak başına ayrı ifade, eksik anahtarlar None.
        natural = ["marketplace_account_id", "source", "request_type", "request_sub_type", "transaction_id"]
        for source in ("settlements", "other_financials"):
            subset = [r for r in financial if r["source"] == source]
            if subset:
                await db.execute(_upsert(FinancialTransaction, _normalize(subset), natural))
        cargo = _cargo_rows(data, tenant_id, account_id, instance_key)
        if cargo:
            await db.execute(
                _upsert(
                    CargoInvoiceItem, cargo, ["marketplace_account_id", "invoice_serial_number", "item_key"]
                )
            )


def _normalize(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Çok satırlı INSERT için her satırın aynı anahtar kümesine sahip olmasını sağlar (eksik anahtar None)."""
    keys: set[str] = set()
    for row in rows:
        keys.update(row)
    return [{key: row.get(key) for key in sorted(keys)} for row in rows]


async def _audit_applied(
    sessions: async_sessionmaker[AsyncSession], seeded: SeededAccount, options: SeedOptions
) -> None:
    async with sessions() as db:
        await set_rls_context(db, seeded.tenant_id, seeded.user_id)
        await record_audit(
            db,
            seeded.tenant_id,
            AUDIT_ACTION,
            user_id=seeded.user_id,
            target=str(seeded.account_id),
            meta={
                "version": SEED_VERSION,
                "account": seeded.data.key,
                "as_of": options.as_of.isoformat(),
                "instance": options.instance,
            },
        )
        await db.commit()


def plan_accounts(options: SeedOptions) -> list[DemoAccountData]:
    plan = [build_account_a(options.instance)]
    plan.extend(build_account_b(ds, options.instance) for ds in options.datasets)
    return plan


async def seed(
    settings: Settings,
    options: SeedOptions,
    *,
    demo_flag: bool,
    environ: Mapping[str, str] | None = None,
    pwned_checker: PwnedPasswordChecker | None = None,
) -> SeedResult:
    """Koruma denetimini geçerse demo kiracılarını, hesaplarını ve verilerini idempotent olarak yazar.

    Sıra: yapılandırma koruması, bağlan, sunucu ve rol doğrulaması, "üretim dışı" işareti, SONRA tüm hesaplar
    için salt okuma ön denetim (yabancı e-posta, tohum sürümü, parola politikası), ancak ondan sonra ilk yazım.
    """
    env = os.environ if environ is None else environ
    check_guard(demo_flag=demo_flag, environ=env, settings=settings)
    if options.as_of < MIN_AS_OF:
        raise DemoGuardError(f"--as-of {MIN_AS_OF.isoformat()} tarihinden önce olamaz")
    if not 1 <= options.instance <= 99:
        raise DemoGuardError("--instance 1 ile 99 arasında olmalı")
    assert settings.worker_database_url is not None  # check_guard doğruladı
    checker = pwned_checker or (HibpPwnedChecker() if settings.pwned_check_enabled else NullPwnedChecker())
    await validate_env_password(env, checker)
    env_name = env.get("NETKAR_ENV", "").strip().lower()
    app_engine = create_engine(settings.database_url, pool_size=2, max_overflow=0)
    worker_engine = create_engine(settings.worker_database_url, pool_size=2, max_overflow=0)
    sessions = create_sessionmaker(app_engine)
    worker_sessions = create_sessionmaker(worker_engine)
    envelope = EnvelopeCipher(settings.key_ring)
    result = SeedResult([], options)
    try:
        app_id = await verify_server(app_engine, "DATABASE_URL", env_name, expected_role="netkar_app")
        worker_id = await verify_server(
            worker_engine, "WORKER_DATABASE_URL", env_name, expected_role="netkar_worker"
        )
        if (app_id.database, app_id.address, app_id.port) != (
            worker_id.database,
            worker_id.address,
            worker_id.port,
        ):
            raise DemoGuardError("DATABASE_URL ve WORKER_DATABASE_URL sunucusu farklı sunuculara gidiyor")
        if options.mark_non_prod:
            admin_url = env.get(ADMIN_URL_ENV, "")
            if not admin_url:
                raise DemoGuardError(f"--mark-non-prod için {ADMIN_URL_ENV} gerekir")
            await mark_non_production(admin_url, app_id, env_name)
        await require_non_production_mark(app_engine)
        plan = plan_accounts(options)
        # Ön denetim (salt okuma): bir hesap reddedilirse hiçbir şey yazılmamış olur.
        existing = {d.key: await _inspect_user(sessions, email_for(d.key, options.instance)) for d in plan}
        for data in plan:
            email = email_for(data.key, options.instance)
            tenant_name = f"Demo Mağaza {data.title} #{options.instance}"
            candidate, source = _new_password(env)
            found = existing[data.key]
            password: str | None = None
            if found is None:
                found = await _register_user(sessions, settings, email, tenant_name, candidate)
                password = candidate
            elif options.reset_passwords and await _reset_password(sessions, settings, email, candidate):
                password = candidate
            user_id, tenant_id = found.user_id, found.tenant_id
            seller_id = seller_id_for(data.key, options.instance)
            account_id = await _ensure_account(sessions, envelope, tenant_id, user_id, seller_id)
            seeded = SeededAccount(
                data, email, tenant_id, user_id, account_id, seller_id, password, source if password else None
            )
            await _write_settings(sessions, tenant_id, account_id, user_id, data)
            costs = {p.barcode: (p.cost, p.vat) for p in data.products if p.cost is not None}
            if data.key == "a":
                variant = a_costs(options.a_variant)
                vat = {p.barcode: p.vat for p in data.products}
                costs = {b: (c, vat[b]) for b, c in variant.items()}
            await _write_costs(sessions, tenant_id, account_id, user_id, costs)
            await _write_trendyol_data(
                worker_sessions, tenant_id, account_id, data, options.as_of, str(options.instance)
            )
            await _audit_applied(sessions, seeded, options)
            result.accounts.append(seeded)
    finally:
        await app_engine.dispose()
        await worker_engine.dispose()
    return result


# ------------------------------------------------------------------------------------------------ CLI


def _default_card_path() -> Path:
    here = Path(__file__).resolve()
    docs = here.parents[4] / "docs" / "ux"
    return docs / "demo_cevap_karti.md" if docs.is_dir() else Path("demo_cevap_karti.md")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.seed_demo", description=__doc__.split("\n\n")[0]
    )
    parser.add_argument(
        "--demo", action="store_true", help="Zorunlu: bunun bir demo tohumu olduğunu onaylar."
    )
    parser.add_argument(
        "--instance", type=int, default=1, help="Katılımcı/oturum numarası (1-99); her biri ayrı kiracı."
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        help="Verinin 'bugün'ü (YYYY-AA-GG); varsayılan bugün.",
    )
    parser.add_argument("--dataset", choices=("x", "y", "all"), default="all", help="Hesap B veri seti.")
    parser.add_argument("--a-variant", choices=("positive", "negative"), default="positive")
    parser.add_argument(
        "--reset-passwords", action="store_true", help="Var olan demo kullanıcılarına yeni parola üretir."
    )
    parser.add_argument(
        "--write-card",
        action="store_true",
        help="Doğru cevap kartını varsayılan yola (docs/ux/demo_cevap_karti.md) yazar; verilmezse kart yazılmaz.",
    )
    parser.add_argument(
        "--card-path", type=Path, default=None, help="Kartı bu dosyaya yazar (kendiliğinden --write-card)."
    )
    parser.add_argument(
        "--mark-non-prod",
        action="store_true",
        help=f"Veritabanına 'üretim değil' işaretini yazar ({ADMIN_URL_ENV}: süper kullanıcı ya da netkar_owner).",
    )
    return parser


def format_credentials(result: SeedResult) -> str:
    """Parola tablosu: yalnız ekrana yazılır (dosyaya değil), bir kez gösterilir."""
    lines = ["Demo girişleri (parolalar bir kez gösterilir, hiçbir yere kaydedilmez):"]
    for account in result.accounts:
        if account.password is None:
            shown = "(var olan hesap, parola değişmedi)"
        elif account.password_source == "env":  # noqa: S105
            shown = f"({PASSWORD_ENV} değeri)"
        else:
            shown = account.password
        lines.append(f"  {account.data.title:<34} {account.email:<28} {shown}")
    return "\n".join(lines)


async def _run(args: argparse.Namespace, environ: Mapping[str, str], out: Any) -> int:
    try:
        settings = Settings()
    except ValidationError as exc:
        print(f"Yapılandırma hatası: {len(exc.errors())} alan geçersiz (ayrıntı yazılmaz)", file=sys.stderr)
        return common.EXIT_CONFIG
    datasets: tuple[DatasetKey, ...] = ("x", "y") if args.dataset == "all" else (args.dataset,)
    options = SeedOptions(
        as_of=args.as_of or today_istanbul(),
        instance=args.instance,
        datasets=datasets,
        a_variant=args.a_variant,
        reset_passwords=args.reset_passwords,
        mark_non_prod=args.mark_non_prod,
    )
    try:
        result = await seed(settings, options, demo_flag=args.demo, environ=environ)
        # Parolalar kayıp olmasın diye kart (başarısız olabilir) yazılmadan ÖNCE gösterilir.
        print(format_credentials(result), file=out)
        if args.write_card or args.card_path:
            from app.tools.demo_card import (
                write_card,
            )  # geç içe aktarma: kart motoru yalnız gerektiğinde yüklenir

            path = args.card_path or _default_card_path()
            await write_card(settings, result, path)
            print(f"Doğru cevap kartı yazıldı: {path}", file=out)
    except DemoGuardError as exc:
        print(f"Reddedildi: {exc}", file=sys.stderr)
        return common.EXIT_CONFIG
    print(
        f"Tohum sürümü {SEED_VERSION}, veri tarihi {options.as_of.isoformat()}, oturum {options.instance}.",
        file=out,
    )
    return common.EXIT_OK


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None, out: Any = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(_run(args, os.environ if environ is None else environ, out or sys.stdout))


if __name__ == "__main__":
    raise SystemExit(main())
