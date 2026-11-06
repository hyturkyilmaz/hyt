"""Test altyapısı: gerçek PostgreSQL 16 (geçici küme veya TEST_DATABASE_URL), migrasyonlar, istemci."""

from __future__ import annotations

import base64
import os
import pwd
import secrets
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL, make_url

from app.core.config import Settings
from app.core.email import InMemoryOutbox
from app.db.provision import provision_roles
from app.main import create_app

API_ROOT = Path(__file__).resolve().parent.parent
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
TEST_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
GOOD_PASSWORD = "dogru-at-pil-kalem-42"


@dataclass(frozen=True)
class DatabaseInfo:
    """Hazırlanmış test veritabanı bağlantıları."""

    admin_url: URL  # superuser, bu veritabanına
    owner_url: URL
    app_url: URL
    name: str

    def admin_dsn(self) -> str:
        return self.admin_url.set(drivername="postgresql").render_as_string(hide_password=False)

    def app_dsn(self) -> str:
        return self.app_url.set(drivername="postgresql").render_as_string(hide_password=False)


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


@pytest.fixture(scope="session")
def database(pg_admin_url: URL) -> Iterator[DatabaseInfo]:
    """Rastgele adlı veritabanı: roller kurulur, migrasyonlar owner rolüyle çalışır."""
    name = f"netkar_test_{secrets.token_hex(4)}"
    owner_pw, app_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
    admin_dsn = pg_admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
        provision_roles(conn, name, owner_pw, app_pw)
    info = DatabaseInfo(
        admin_url=pg_admin_url.set(database=name),
        owner_url=pg_admin_url.set(username="netkar_owner", password=owner_pw, database=name),
        app_url=pg_admin_url.set(username="netkar_app", password=app_pw, database=name),
        name=name,
    )
    command.upgrade(_alembic_config(info.owner_url), "head")
    yield info
    if os.environ.get("TEST_DATABASE_URL"):
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def alembic_cfg(database: DatabaseInfo) -> Config:
    return _alembic_config(database.owner_url)


@pytest.fixture
def admin_conn(database: DatabaseInfo) -> Iterator[psycopg.Connection[Any]]:
    """Superuser bağlantısı (RLS'yi aşar): doğrulama ve zaman kaydırma için."""
    with psycopg.connect(database.admin_dsn(), autocommit=True) as conn:
        yield conn


@pytest.fixture(autouse=True)
def _clean_tables(database: DatabaseInfo) -> None:
    """Her testten önce tabloları boşaltır (yalnız test veritabanında, superuser ile)."""
    with psycopg.connect(database.admin_dsn(), autocommit=True) as conn:
        conn.execute(
            "TRUNCATE tenants, users, memberships, sessions, password_reset_tokens, "
            "audit_log, rate_limits RESTART IDENTITY CASCADE"
        )


@pytest.fixture
def settings(database: DatabaseInfo) -> Settings:
    return Settings(
        environment="test",
        database_url=database.app_url.render_as_string(hide_password=False),
        data_encryption_key=TEST_KEY,  # type: ignore[arg-type]
        email_backend="memory",
        log_level="WARNING",
        web_base_url="https://app.test.invalid",
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

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def csrf(self) -> str:
        return str(self.client.get("/v1/auth/csrf").json()["csrf_token"])

    def post(self, url: str, json: Any = None, csrf: bool = True, **kw: Any) -> Any:
        headers = dict(kw.pop("headers", {}))
        if csrf:
            token = self.client.cookies.get("__Host-nk_csrf") or self.csrf()
            headers["X-CSRF-Token"] = token
        return self.client.post(url, json=json, headers=headers, **kw)

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, **kw)

    def register(self, email: str, password: str = GOOD_PASSWORD, tenant: str = "Test Mağaza") -> Any:
        return self.post("/v1/auth/register", {"email": email, "password": password, "tenant_name": tenant})

    def login(self, email: str, password: str = GOOD_PASSWORD) -> Any:
        return self.post("/v1/auth/login", {"email": email, "password": password})

    def signup_and_login(self, email: str, tenant: str = "Test Mağaza") -> None:
        assert self.register(email, tenant=tenant).status_code == 202
        assert self.login(email).status_code == 200


AppFactory = Callable[..., FastAPI]


@pytest.fixture
def make_app(settings: Settings, outbox: InMemoryOutbox, fake_pwned: FakePwned) -> Callable[..., FastAPI]:
    def _make(**overrides: Any) -> FastAPI:
        return create_app(
            settings.model_copy(update=overrides), email_sender=outbox, pwned_checker=fake_pwned
        )

    return _make


@pytest.fixture
def make_api(make_app: Callable[..., FastAPI]) -> Iterator[Callable[..., Api]]:
    clients: list[TestClient] = []

    def _make(**overrides: Any) -> Api:
        client = TestClient(make_app(**overrides), base_url="https://testserver")
        client.__enter__()
        clients.append(client)
        return Api(client)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def api(make_api: Callable[..., Api]) -> Api:
    return make_api()
