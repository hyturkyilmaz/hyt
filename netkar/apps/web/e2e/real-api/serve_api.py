"""Gerçek API uçtan uca testi için geçici PostgreSQL + uvicorn başlatıcısı.

Yalnız test altyapısıdır; backend koduna dokunmaz. services/api/tests/conftest.py içindeki
geçici küme mantığını yeniden kullanır (initdb, yalnız unix socket, rastgele port, tmp dizin):

    cd netkar/services/api && uv run python ../../apps/web/e2e/real-api/serve_api.py

Ortam: E2E_API_PORT (varsayılan 8100), PG_BIN (varsayılan /usr/lib/postgresql/16/bin).
Süreç SIGTERM ile durunca PostgreSQL kümesi kapatılır ve tmp dizin silinir.
"""

from __future__ import annotations

import base64
import os
import pwd
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL

from app.core.config import Settings
from app.core.email import InMemoryOutbox
from app.db.provision import provision_roles
from app.main import create_app

API_ROOT = Path(__file__).resolve().parents[4] / "services" / "api"
PG_BIN = Path(os.environ.get("PG_BIN", "/usr/lib/postgresql/16/bin"))
PORT = int(os.environ.get("E2E_API_PORT", "8100"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _pg(cmd: list[str]) -> None:
    """root altında initdb/pg_ctl çalışmaz; postgres OS kullanıcısına geçilir."""
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", "postgres", "--", *cmd]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main() -> None:
    base = tempfile.mkdtemp(prefix="nkpg-e2e-", dir="/tmp")
    if os.geteuid() == 0:
        pg_user = pwd.getpwnam("postgres")
        os.chown(base, pg_user.pw_uid, pg_user.pw_gid)
    os.chmod(base, 0o700)
    data = os.path.join(base, "data")
    port = _free_port()

    def cleanup() -> None:
        stop = [str(PG_BIN / "pg_ctl"), "-D", data, "-m", "immediate", "stop"]
        if os.geteuid() == 0:
            stop = ["runuser", "-u", "postgres", "--", *stop]
        subprocess.run(stop, check=False, capture_output=True)
        shutil.rmtree(base, ignore_errors=True)

    def on_term(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    try:
        _pg([str(PG_BIN / "initdb"), "-D", data, "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-locale"])
        options = (
            f"-c listen_addresses='' -c unix_socket_directories={base} -c port={port} "
            "-c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=100"
        )
        _pg([str(PG_BIN / "pg_ctl"), "-D", data, "-o", options, "-l", os.path.join(base, "log"), "-w", "start"])

        name = "netkar_e2e"
        owner_pw, app_pw = secrets.token_urlsafe(12), secrets.token_urlsafe(12)
        admin = URL.create("postgresql", username="postgres", database="postgres",
                           query={"host": base, "port": str(port)})
        with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
            provision_roles(conn, name, owner_pw, app_pw)

        def role_url(user: str, password: str) -> URL:
            return admin.set(drivername="postgresql+psycopg", username=user, password=password, database=name)

        owner_url = role_url("netkar_owner", owner_pw)
        app_url = role_url("netkar_app", app_pw)

        cfg = Config(str(API_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", owner_url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(cfg, "head")

        settings = Settings(
            environment="test",
            database_url=app_url.render_as_string(hide_password=False),
            # Yalnız bu geçici süreç için rastgele anahtar; repoya veya log'a yazılmaz.
            data_encryption_key=base64.b64encode(secrets.token_bytes(32)).decode(),  # type: ignore[arg-type]
            email_backend="memory",
            log_level="WARNING",
            web_base_url="http://127.0.0.1:3101",
        )
        app = create_app(settings, email_sender=InMemoryOutbox())
        print(f"gecici API hazir: http://127.0.0.1:{PORT}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    finally:
        cleanup()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"API başlatılamadı: {exc}", file=sys.stderr)
        sys.exit(1)
