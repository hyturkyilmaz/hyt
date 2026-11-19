"""Test altyapısı: gerçek PostgreSQL 16 (geçici küme veya TEST_DATABASE_URL), migrasyonlar, istemci."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import pwd
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import psycopg
import pyotp
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url

from app.core import clock as clock_module
from app.core import ratelimit as ratelimit_module
from app.core.config import Settings
from app.core.email import InMemoryOutbox
from app.db.provision import provision_roles
from app.main import create_app

# Senkron testlerinin ortak fixture'ları (Env, worker_engine, make_env, worker_env).
pytest_plugins = ["tests.sync_fixtures"]

API_ROOT = Path(__file__).resolve().parent.parent
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
TEST_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
GOOD_PASSWORD = "dogru-at-pil-kalem-42"
# Zarf şifreleme KEK'i: her test oturumunda rastgele üretilir (repoda sabit sır yok).
TEST_KEK = base64.b64encode(os.urandom(32)).decode()


@dataclass(frozen=True)
class DatabaseInfo:
    """Hazırlanmış test veritabanı bağlantıları."""

    admin_url: URL  # superuser, bu veritabanına
    owner_url: URL
    app_url: URL
    worker_url: URL
    name: str

    def admin_dsn(self) -> str:
        return self.admin_url.set(drivername="postgresql").render_as_string(hide_password=False)

    def app_dsn(self) -> str:
        return self.app_url.set(drivername="postgresql").render_as_string(hide_password=False)

    def worker_dsn(self) -> str:
        return self.worker_url.set(drivername="postgresql").render_as_string(hide_password=False)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _run_as_pg_user(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
    """root altında initdb/pg_ctl çalışmaz; postgres OS kullanıcısına geçilir."""
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", "postgres", "--", *cmd]
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


@pytest.fixture(scope="session")
def pg_admin_url() -> Iterator[URL]:
    """Yönetici (superuser) bağlantısı: TEST_DATABASE_URL varsa o, yoksa geçici küme."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        url = make_url(external)
        yield url.set(drivername="postgresql+psycopg")
        return

    base = tempfile.mkdtemp(prefix="nkpg-", dir="/tmp")
    if os.geteuid() == 0:
        pg = pwd.getpwnam("postgres")
        os.chown(base, pg.pw_uid, pg.pw_gid)
    os.chmod(base, 0o700)
    data = os.path.join(base, "data")
    port = _free_port()
    _run_as_pg_user(
        [str(PG_BIN / "initdb"), "-D", data, "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-locale"]
    )
    options = (
        f"-c listen_addresses='' -c unix_socket_directories={base} -c port={port} "
        "-c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=200"
    )
    _run_as_pg_user(
        [str(PG_BIN / "pg_ctl"), "-D", data, "-o", options, "-l", os.path.join(base, "log"), "-w", "start"]
    )
    try:
        yield URL.create(
            "postgresql+psycopg",
            username="postgres",
            database="postgres",
            query={"host": base, "port": str(port)},
        )
    finally:
        subprocess.run(
            (["runuser", "-u", "postgres", "--"] if os.geteuid() == 0 else [])
            + [str(PG_BIN / "pg_ctl"), "-D", data, "-m", "immediate", "stop"],
            check=False,
            capture_output=True,
        )
        shutil.rmtree(base, ignore_errors=True)


def _alembic_config(owner_url: URL) -> Config:
    cfg = Config(str(API_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", owner_url.render_as_string(hide_password=False).replace("%", "%%"))
    return cfg


# Roller küme düzeyindedir: paylaşılan kümede (TEST_DATABASE_URL) tüm xdist işçileri aynı üç giriş rolünü
# kullanır. İki kilit anahtarı veritabanından bağımsız `postgres` bakım veritabanında alınır
# (advisory kilitler veritabanı başınadır).
PROVISION_LOCK_KEY = 0x4E4B5052  # rol kurulumunu sıraya sokar
CLUSTER_LOCK_KEY = 0x4E4B434C  # paylaşılan (testler) ve özel (cluster_global testleri) kilit


def _xdist_worker() -> str:
    """xdist işçi kimliği (gw0, gw1, ...); seri koşuda boş."""
    return os.environ.get("PYTEST_XDIST_WORKER", "")


def _role_passwords() -> tuple[str, str, str]:
    """owner/app/worker şifreleri.

    xdist altında tüm işçiler aynı koşunun şifrelerini türetir (PYTEST_XDIST_TESTRUNUID ortak): paylaşılan
    kümede her işçi `ALTER ROLE ... PASSWORD` çalıştırır, farklı şifre üretselerdi sonraki işçi şifreyi
    değiştirir ve öteki işçilerin YENİ bağlantılarının kimlik doğrulaması bozulurdu (açık bağlantılar kopmaz).
    Seri koşuda her oturum rastgele şifre üretir.
    """
    run_uid = os.environ.get("PYTEST_XDIST_TESTRUNUID")
    if not run_uid:
        owner, app, worker = (secrets.token_urlsafe(12) for _ in range(3))
        return owner, app, worker
    owner, app, worker = (
        hmac.new(run_uid.encode(), role.encode(), hashlib.sha256).hexdigest()[:24]
        for role in ("owner", "app", "worker")
    )
    return owner, app, worker


@pytest.fixture(scope="session")
def database(pg_admin_url: URL) -> Iterator[DatabaseInfo]:
    """Rastgele adlı veritabanı: roller kurulur, migrasyonlar owner rolüyle çalışır.

    xdist altında her işçinin kendi veritabanı vardır (`netkar_test_<hex>_<gw>`).
    """
    worker = _xdist_worker()
    name = f"netkar_test_{secrets.token_hex(4)}" + (f"_{worker}" if worker else "")
    owner_pw, app_pw, worker_pw = _role_passwords()
    admin_dsn = pg_admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        # Roller küme düzeyindedir. CREATE ROLE / GRANT rol üyeliği eşzamanlı çalışınca "tuple concurrently
        # updated" ya da "role already exists" ile düşer (var mı sorgusu ile CREATE arasında yarış). IF NOT
        # EXISTS rol için yok ve hata yakalayıp yeniden denemek yarımış kurulumu gizler; bu yüzden tüm kurulum
        # tek bir advisory kilidiyle sıraya sokulur: kilidi alan işçi bitirir, sonrakiler ALTER yoluna girer.
        # Kurulum ve migrasyon, cluster_global testlerinin özel kilidine karşı paylaşılan küme kilidi altında
        # çalışır (rol yeniden adlandırma/BYPASSRLS ile yarışmasın). Sıra: önce küme kilidi (paylaşılan), sonra
        # kurulum kilidi. Kilit, ilk testin `_cluster_lock` fixture'ından ÖNCE bırakılır (o fixture `database`
        # fixture'ına bağımlıdır), böylece bekleyen özel kilit ile bu bağlantı birbirini beklemez.
        conn.execute("SET lock_timeout = '10min'")
        conn.execute("SELECT pg_advisory_lock_shared(%s)", (CLUSTER_LOCK_KEY,))
        try:
            conn.execute("SELECT pg_advisory_lock(%s)", (PROVISION_LOCK_KEY,))
            try:
                provision_roles(conn, name, owner_pw, app_pw, worker_pw)
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s)", (PROVISION_LOCK_KEY,))
            info = DatabaseInfo(
                admin_url=pg_admin_url.set(database=name),
                owner_url=pg_admin_url.set(username="netkar_owner", password=owner_pw, database=name),
                app_url=pg_admin_url.set(username="netkar_app", password=app_pw, database=name),
                worker_url=pg_admin_url.set(username="netkar_worker", password=worker_pw, database=name),
                name=name,
            )
            command.upgrade(_alembic_config(info.owner_url), "head")
        finally:
            conn.execute("SELECT pg_advisory_unlock_shared(%s)", (CLUSTER_LOCK_KEY,))
    yield info
    if os.environ.get("TEST_DATABASE_URL"):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def _cluster_lock_conn(pg_admin_url: URL) -> Iterator[psycopg.Connection[Any] | None]:
    """Paylaşılan kümede (TEST_DATABASE_URL) küme kilidi bağlantısı; geçici kümede (işçi başına) gerekmez."""
    if not os.environ.get("TEST_DATABASE_URL"):
        yield None
        return
    dsn = pg_admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        # Askıda kalan bir test tüm işçileri sessizce durdurmasın: 10 dk sonra anlaşılır hatayla düşer.
        conn.execute("SET lock_timeout = '10min'")
        yield conn


@pytest.fixture(autouse=True)
def _cluster_lock(
    request: pytest.FixtureRequest,
    _cluster_lock_conn: psycopg.Connection[Any] | None,
    database: DatabaseInfo,  # yalnız sıralama: oturum kurulumu (kendi paylaşılan kilidi) önce bitsin
) -> Iterator[None]:
    """Küme düzeyinde etkisi olan testleri öteki işçilerden yalıtır (yalnız paylaşılan kümede).

    Her test paylaşılan kilidi tutar; `@pytest.mark.cluster_global` testleri (rol değiştirme/oluşturma,
    yeniden adlandırma) özel kilidi alır: başka işçilerin çalışan testleri bitene kadar bekler ve o sürede
    yeni test başlamaz. Aksi halde bir işçinin `ALTER ROLE netkar_app BYPASSRLS` çağrısı ötekilerin RLS
    testlerini bozardı. Geçici kümede her işçinin kendi kümesi olduğundan kilit alınmaz.
    """
    conn = _cluster_lock_conn
    if conn is None:
        yield
        return
    exclusive = request.node.get_closest_marker("cluster_global") is not None
    lock, unlock = (
        ("pg_advisory_lock", "pg_advisory_unlock")
        if exclusive
        else ("pg_advisory_lock_shared", "pg_advisory_unlock_shared")
    )
    conn.execute(f"SELECT {lock}(%s)", (CLUSTER_LOCK_KEY,))
    try:
        yield
    finally:
        conn.execute(f"SELECT {unlock}(%s)", (CLUSTER_LOCK_KEY,))


@pytest.fixture(scope="session")
def alembic_cfg(database: DatabaseInfo) -> Config:
    return _alembic_config(database.owner_url)


@pytest.fixture
def admin_conn(database: DatabaseInfo) -> Iterator[psycopg.Connection[Any]]:
    """Superuser bağlantısı (RLS'yi aşar): doğrulama ve zaman kaydırma için."""
    with psycopg.connect(database.admin_dsn(), autocommit=True) as conn:
        yield conn


def _set_mark(conn: psycopg.Connection[Any], value: str | None) -> Iterator[None]:
    """İşaret satırını ayarlar (None: siler); testten sonra ÖNCEKİ durumu geri koyar (var olan işaret silinmez)."""
    row = conn.execute("SELECT value FROM deployment_marks WHERE key = 'non_production'").fetchone()
    before = None if row is None else row[0]
    conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")
    if value is not None:
        conn.execute("INSERT INTO deployment_marks (key, value) VALUES ('non_production', %s)", (value,))
    try:
        yield
    finally:
        conn.execute("DELETE FROM deployment_marks WHERE key = 'non_production'")
        if before is not None:
            conn.execute("INSERT INTO deployment_marks (key, value) VALUES ('non_production', %s)", (before,))


@pytest.fixture
def marked(admin_conn: psycopg.Connection[Any]) -> Iterator[None]:
    """Veritabanı 'üretim dışı' işaretli (non_production = 'true')."""
    yield from _set_mark(admin_conn, "true")


@pytest.fixture
def unmarked(admin_conn: psycopg.Connection[Any]) -> Iterator[None]:
    """Veritabanında işaret satırı yok."""
    yield from _set_mark(admin_conn, None)


@pytest.fixture(autouse=True)
def _clean_tables(database: DatabaseInfo) -> None:
    """Her testten önce tabloları boşaltır (yalnız test veritabanında, superuser ile)."""
    with psycopg.connect(database.admin_dsn(), autocommit=True) as conn:
        # Belge/kabul tabloları TRUNCATE tetikleyicisiyle korunur (0022); CASCADE onlara da uzanır. Testlerde
        # tetikleyici yalnız superuser'ın atlayabildiği replica rolüyle devre dışı bırakılır.
        conn.execute("SET session_replication_role = replica")
        conn.execute(
            "TRUNCATE tenants, users, memberships, sessions, password_reset_tokens, "
            "audit_log, rate_limits, marketplace_accounts, report_data_revisions, procrastinate_jobs "
            "RESTART IDENTITY CASCADE"
        )
        # Belge sürüm kaydı değişmezdir; testlerin yayınladığı sürümler aynı replica oturumunda temizlenir.
        conn.execute("DELETE FROM legal_documents WHERE version <> 'taslak-2026-11'")
        conn.execute("SET session_replication_role = DEFAULT")


@pytest.fixture(autouse=True)
def _reset_legal_current_cache() -> None:
    """Herkese açık güncel belge önbelleği süreç içidir; testler birbirini etkilemesin diye her testten önce boşalır."""
    from app.services import legal as legal_service

    legal_service.reset_current_cache()


@pytest.fixture
def settings(database: DatabaseInfo) -> Settings:
    return Settings(
        environment="test",
        database_url=database.app_url.render_as_string(hide_password=False),
        worker_database_url=database.worker_url.render_as_string(hide_password=False),
        data_encryption_key=TEST_KEY,  # type: ignore[arg-type]
        data_keks=f"kek1:{TEST_KEK}",  # type: ignore[arg-type]
        data_kek_active="kek1",
        email_backend="memory",
        log_level="WARNING",
        web_base_url="https://app.test.invalid",
        # Dönem sonucu önbelleği testlerde kapalıdır: testler veriyi doğrudan SQL ile değiştirir ve motor
        # çalışma sayısını sayar; önbellek testleri (test_report_cache.py) onu açıkça açar.
        profit_report_cache_ttl_seconds=0,
    )


@pytest.fixture
def outbox() -> InMemoryOutbox:
    return InMemoryOutbox()


class FakePwned:
    """Sahte sızmış parola denetleyicisi: listedeki parolalar sızmış sayılır."""

    def __init__(self) -> None:
        self.pwned: set[str] = set()

    async def is_pwned(self, password: str) -> bool:
        return password in self.pwned


@pytest.fixture
def fake_pwned() -> FakePwned:
    return FakePwned()


class Api:
    """TestClient sarmalayıcısı: CSRF çerezini ve başlığını otomatik yönetir."""

    def __init__(self, client: TestClient, outbox: InMemoryOutbox | None = None) -> None:
        self.client = client
        self.outbox = outbox

    def csrf(self) -> str:
        return str(self.client.get("/v1/auth/csrf").json()["csrf_token"])

    def post(self, url: str, json: Any = None, csrf: bool = True, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        if csrf:
            token = self.client.cookies.get("__Host-nk_csrf") or self.csrf()
            headers["X-CSRF-Token"] = token
        return self.client.post(url, json=json, headers=headers, **kw)

    def put(self, url: str, json: Any = None, csrf: bool = True, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        if csrf:
            headers["X-CSRF-Token"] = self.client.cookies.get("__Host-nk_csrf") or self.csrf()
        return self.client.put(url, json=json, headers=headers, **kw)

    def delete(self, url: str, csrf: bool = True, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        if csrf:
            headers["X-CSRF-Token"] = self.client.cookies.get("__Host-nk_csrf") or self.csrf()
        return self.client.delete(url, headers=headers, **kw)

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, **kw)

    def register(
        self,
        email: str,
        password: str = GOOD_PASSWORD,
        tenant: str = "Test Mağaza",
        accept_terms: Any = True,
        acknowledge_privacy_notice: Any = True,
        terms_version: Any = "current",
        privacy_notice_version: Any = "current",
    ) -> Any:
        """Kayıt isteği; onay kutuları varsayılan işaretli, sürümler sunucudan alınır ("current").

        `None`: alan hiç gönderilmez. Başka bir değer olduğu gibi gönderilir.
        """
        body: dict[str, Any] = {"email": email, "password": password, "tenant_name": tenant}
        if "current" in (terms_version, privacy_notice_version):
            current = {d["doc_type"]: d["version"] for d in self.get("/v1/legal/current").json()}
            terms_version = current["terms"] if terms_version == "current" else terms_version
            if privacy_notice_version == "current":
                privacy_notice_version = current["privacy_notice"]
        if terms_version is not None:
            body["terms_version"] = terms_version
        if privacy_notice_version is not None:
            body["privacy_notice_version"] = privacy_notice_version
        if accept_terms is not None:
            body["accept_terms"] = accept_terms
        if acknowledge_privacy_notice is not None:
            body["acknowledge_privacy_notice"] = acknowledge_privacy_notice
        return self.post("/v1/auth/register", body)

    def login(self, email: str, password: str = GOOD_PASSWORD) -> Any:
        return self.post("/v1/auth/login", {"email": email, "password": password})

    def verification_token(self, email: str) -> str:
        """Gelen kutusundaki EN SON doğrulama bağlantısının token'ı (e-posta akışı gerçek yoldan okunur)."""
        assert self.outbox is not None, "Api bir gelen kutusuyla kurulmadı"
        for message in reversed(self.outbox.to(email)):
            match = re.search(r"/e-posta-dogrula\?token=([A-Za-z0-9_\-]+)", message.body)
            if match:
                return match.group(1)
        raise AssertionError(f"{email} için doğrulama bağlantısı yok")

    def verify_email(self, email: str) -> Any:
        """Doğrulama bağlantısındaki token'ı gerçek uç noktaya gönderir (oturum açık olmalı)."""
        return self.post("/v1/auth/email/verify", {"token": self.verification_token(email)})

    def signup_and_login(self, email: str, tenant: str = "Test Mağaza", verified: bool = True) -> None:
        """Kayıt + giriş. Varsayılan: e-posta gerçek akıştan doğrulanır (yazma uçları doğrulanmış hesap ister).

        `verified=False`: doğrulanmamış hesap (kısıt testleri için).
        """
        assert self.register(email, tenant=tenant).status_code == 202
        assert self.login(email).status_code == 200
        if verified:
            # Doğrulama oturumlu ve token'ın sahibi kullanıcıyla yapılır (gerçek akış).
            assert self.verify_email(email).status_code == 204


AppFactory = Callable[..., FastAPI]


class RecordingJobQueue:
    """Sahte iş kuyruğu: eklenen backfill işlerini kaydeder; `fail` açıksa kuyruk hata verir."""

    def __init__(self) -> None:
        self.backfills: list[UUID] = []
        self.fail = False

    async def enqueue_backfill(self, account_id: UUID) -> None:
        if self.fail:
            raise RuntimeError("kuyruk erişilemez")
        self.backfills.append(account_id)


@pytest.fixture
def job_queue() -> RecordingJobQueue:
    return RecordingJobQueue()


@pytest.fixture
def make_app(
    settings: Settings, outbox: InMemoryOutbox, fake_pwned: FakePwned, job_queue: RecordingJobQueue
) -> Callable[..., FastAPI]:
    def _make(trendyol_client_factory: Any = None, **overrides: Any) -> FastAPI:
        return create_app(
            settings.model_copy(update=overrides),
            email_sender=outbox,
            pwned_checker=fake_pwned,
            trendyol_client_factory=trendyol_client_factory,
            job_queue=job_queue,
        )

    return _make


@pytest.fixture
def make_api(make_app: Callable[..., FastAPI], outbox: InMemoryOutbox) -> Iterator[Callable[..., Api]]:
    clients: list[TestClient] = []

    def _make(peer: str = "testclient", **overrides: Any) -> Api:
        """`peer`: bağlantının eş adresi (güvenilir vekil testlerinde vekil adresi gibi davranır)."""
        client = TestClient(make_app(**overrides), base_url="https://testserver", client=(peer, 50000))
        client.__enter__()
        clients.append(client)
        return Api(client, outbox)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


class FakeClock:
    """Dondurulmuş zaman: TOTP zaman adımları testte deterministik olur (sınır yarışı yok)."""

    def __init__(self) -> None:
        # Adım ortasında bir an; böylece +-1 adım penceresi kenarına denk gelmez.
        self.now = float(int(time.time()) // 30 * 30 + 10)

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def code(self, secret: str, steps: int = 0) -> str:
        """Şu anki (veya `steps` adım ilerisi) için geçerli TOTP kodu."""
        return pyotp.TOTP(secret).at(int(self.now) + steps * 30)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(clock_module, "unix_time", lambda: fake.now)
    return fake


@pytest.fixture
def api(make_api: Callable[..., Api]) -> Api:
    return make_api()


# Sabit pencereli sınırlayıcının (ADR-0001) saati: sayaç değerini kesin bekleyen testler bir pencere
# sınırına denk gelince sayaç sıfırlanır ve test rastgele kırılır (CI'da iki kez görüldü). Bu sabit an
# 60, 900, 3600 ve 86400 sn pencerelerinin hepsinde sınırdan uzaktır.
FROZEN_RATELIMIT_NOW = 1_800_000_000.0 + 450.0


@pytest.fixture
def frozen_ratelimit_clock(monkeypatch: pytest.MonkeyPatch) -> float:
    """Sınırlayıcının saatini sabitler; yalnız app.core.ratelimit etkilenir."""
    monkeypatch.setattr(ratelimit_module, "time", SimpleNamespace(time=lambda: FROZEN_RATELIMIT_NOW))
    return FROZEN_RATELIMIT_NOW


def legal_loss_flag(conn: psycopg.Connection[Any]) -> str:
    """0022 downgrade korumasının beklediği tam değer (`accepted=N,published=M`) şu anki kayıtlardan."""
    accepted = conn.execute("SELECT count(*) FROM user_legal_acceptances").fetchone()
    published = conn.execute(
        "SELECT count(*) FROM legal_documents WHERE version <> 'taslak-2026-11'"
    ).fetchone()
    assert accepted is not None and published is not None
    return f"accepted={accepted[0]},published={published[0]}"
