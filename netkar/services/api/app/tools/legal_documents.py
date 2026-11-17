"""Hukuki belge sürümü yayınlama aracı (kullanım koşulları, aydınlatma metni).

    python -m app.tools.legal_documents publish --type terms --version 2026-12-a --file belge.md

Belge dosyasının SHA-256 özeti hesaplanıp YENİ bir `legal_documents` satırı eklenir (satırlar değişmez; 0021).
Metin veritabanına yazılmaz, yalnız özet. Yayın zamanı şimdidir: yayın, web sayfasındaki metin canlıya
alındıktan HEMEN SONRA yapılmalıdır (sürüm kaydı ile sayfa aynı sürümü göstermeli).
`DATABASE_ADMIN_URL` gerekir (RLS'yi aşan rol; yalnız bakım penceresi).
Metin onayı (avukat) bu aracın işi değildir.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import psycopg

from app.tools.common import EXIT_CONFIG, EXIT_OK, ToolConfigError, connect_admin, ensure_rls_bypass

_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TYPES = ("terms", "privacy_notice")


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def publish_document(
    conn: psycopg.Connection[tuple[object, ...]], doc_type: str, version: str, content: bytes
) -> str:
    """Yeni sürüm satırı ekler ve içerik özetini döner. Aynı (tür, sürüm) ikinci kez eklenemez (UNIQUE)."""
    if doc_type not in _TYPES:
        raise ToolConfigError(f"tür {', '.join(_TYPES)} olmalı")
    if not _VERSION_RE.fullmatch(version):
        raise ToolConfigError(
            "sürüm kodu küçük harf, rakam, nokta, alt çizgi ve tireden oluşmalı (en çok 64)"
        )
    if not content.strip():
        raise ToolConfigError("belge dosyası boş")
    digest = sha256_of(content)
    try:
        conn.execute(
            "INSERT INTO legal_documents (doc_type, version, content_sha256) VALUES (%s, %s, %s)",
            (doc_type, version, digest),
        )
    except psycopg.errors.UniqueViolation:
        raise ToolConfigError(f"{doc_type} sürüm {version} zaten yayınlanmış (satırlar değişmez)") from None
    return digest


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legal_documents")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish", help="yeni belge sürümü yayınla")
    pub.add_argument("--type", required=True, choices=_TYPES)
    pub.add_argument("--version", required=True)
    pub.add_argument("--file", required=True, type=Path)
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        content = args.file.read_bytes()
        conn = connect_admin(env)
        try:
            ensure_rls_bypass(conn)
            digest = publish_document(conn, args.type, args.version, content)
        finally:
            conn.close()
    except (ToolConfigError, OSError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print(f"yayınlandı: {args.type} {args.version} sha256={digest}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
