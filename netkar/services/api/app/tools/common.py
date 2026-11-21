"""Anahtar araçlarının ortak parçaları: yapılandırma, yönetici bağlantısı, kayıt gezme, CAS güncelleme.

Araçlar RLS'ye tabi olmayan bir veritabanı rolüyle çalışır (`DATABASE_ADMIN_URL`; üretimde
Postgres yönetici hesabı, yalnız bakım penceresinde). Uygulama rolü (netkar_app) kiracı bağlamı
olmadan satır göremez, bu yüzden bu iş için kullanılamaz. Araç RLS'yi aşamayan bir rolle
çalıştırılırsa "0 kayıt" sessizce yanlış rapor etmesin diye açıkça durur.

Hiçbir çıktı satırı şifreli değer, düz metin, anahtar veya parola içermez: yalnız hesap kimliği,
alan adı ve kid yazılır.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Iterator, Mapping
from dataclasses import dataclass

import psycopg
from psycopg.types.json import Jsonb

from app.core.envelope import KeyRing, KeyRingError

EXIT_OK = 0
EXIT_FAILED = 2  # en az bir kayıt işlenemedi (diğerleri işlendi)
EXIT_CONFIG = 3  # yapılandırma/yetki hatası: hiçbir şeye dokunulmadı

_BATCH = 200


class ToolConfigError(Exception):
    """Araç yapılandırması veya yetkisi geçersiz. İleti sır içermez."""


@dataclass(frozen=True)
class AccountRow:
    """Şifreli sütunları dolu (iptal edilmemiş) bir pazaryeri hesabı."""

    id: str
    tenant_id: str
    platform: str
    seller_id: str
    api_key: str
    api_secret: str


def require_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise ToolConfigError(f"{name} tanımlı değil")
    return value


def load_key_ring(environ: Mapping[str, str]) -> KeyRing:
    """DATA_KEKS ve DATA_KEK_ACTIVE ortam değişkenlerinden KEK halkası."""
    spec = require_env(environ, "DATA_KEKS")
    active = require_env(environ, "DATA_KEK_ACTIVE")
    try:
        return KeyRing.parse(spec, active)
    except KeyRingError as exc:
        raise ToolConfigError(f"DATA_KEKS/DATA_KEK_ACTIVE geçersiz: {exc}") from None


def load_legacy_master_key(environ: Mapping[str, str]) -> bytes:
    """Eski (v1) biçim için DATA_ENCRYPTION_KEY: base64, 32 bayt."""
    raw = require_env(environ, "DATA_ENCRYPTION_KEY")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ToolConfigError("DATA_ENCRYPTION_KEY geçerli base64 değil") from None
    if len(key) != 32:
        raise ToolConfigError("DATA_ENCRYPTION_KEY 32 bayt olmalı")
    return key


def connect_admin(environ: Mapping[str, str]) -> psycopg.Connection[tuple[object, ...]]:
    """RLS'yi aşabilen yönetici bağlantısı (autocommit; satır güncellemeleri kendi işleminde)."""
    dsn = require_env(environ, "DATABASE_ADMIN_URL")
    try:
        return psycopg.connect(dsn, autocommit=True)
    except psycopg.Error:
        # Bağlantı dizesi parola içerebilir: sürücü iletisi aktarılmaz.
        raise ToolConfigError("DATABASE_ADMIN_URL ile veritabanına bağlanılamadı") from None


def ensure_rls_bypass(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """Rol RLS'yi aşamıyorsa (superuser/BYPASSRLS değil) durur: tablo boş görünürdü."""
    row = conn.execute(
        "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if not row or row[0] is not True:
        raise ToolConfigError(
            "bağlantı rolü RLS'yi aşamıyor (superuser veya BYPASSRLS gerekir); kiracı satırları görünmez"
        )


def iter_accounts(conn: psycopg.Connection[tuple[object, ...]]) -> Iterator[AccountRow]:
    """İptal edilmemiş (şifreli sütunları dolu) hesapları kimliğe göre gruplar halinde gezer."""
    last = "00000000-0000-0000-0000-000000000000"
    while True:
        rows = conn.execute(
            "SELECT id::text, tenant_id::text, platform, seller_id, api_key_encrypted, api_secret_encrypted "
            "FROM marketplace_accounts "
            "WHERE api_key_encrypted IS NOT NULL AND api_secret_encrypted IS NOT NULL AND id::text > %s "
            "ORDER BY id::text LIMIT %s",
            (last, _BATCH),
        ).fetchall()
        if not rows:
            return
        for r in rows:
            yield AccountRow(*(str(v) for v in r))
        last = str(rows[-1][0])


def compare_and_set(
    conn: psycopg.Connection[tuple[object, ...]],
    account_id: str,
    old: tuple[str, str],
    new: tuple[str, str],
    audit_action: str,
    audit_meta: Mapping[str, object],
) -> bool:
    """Şifreli sütunları yalnız hâlâ `old` ise günceller ve aynı işlemde denetim kaydı yazar.

    Eşzamanlı bir yazma (yeniden bağlanma, iptal) araçtan önce davrandıysa satıra dokunulmaz ve
    False döner. `updated_at` değişmez: anahtar sarma kullanıcıya görünen bir değişiklik değildir.
    """
    with conn.transaction():
        row = conn.execute(
            "UPDATE marketplace_accounts SET api_key_encrypted = %s, api_secret_encrypted = %s "
            "WHERE id = %s::uuid AND api_key_encrypted = %s AND api_secret_encrypted = %s "
            "RETURNING tenant_id",
            (new[0], new[1], account_id, old[0], old[1]),
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "INSERT INTO audit_log (tenant_id, action, target, meta) VALUES (%s, %s, %s, %s)",
            (row[0], audit_action, account_id, Jsonb(dict(audit_meta))),
        )
    return True
