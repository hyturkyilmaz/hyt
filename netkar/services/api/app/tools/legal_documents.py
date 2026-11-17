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
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg

from app.tools.common import EXIT_CONFIG, EXIT_OK, ToolConfigError, connect_admin, ensure_rls_bypass

_VERSION_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_TYPES = ("terms", "privacy_notice")


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_published_at(value: str | None, now: datetime | None = None) -> datetime | None:
    """`--published-at` ISO 8601 (saat dilimi yoksa UTC). Geçmiş tarih reddedilir (kayıt geriye yazılmaz)."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ToolConfigError("--published-at ISO 8601 olmalı, ör. 2026-12-01T09:00:00+03:00") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    if parsed < (now or datetime.now(UTC)) - timedelta(minutes=1):
        raise ToolConfigError("--published-at geçmişte olamaz (yayın kaydı geriye yazılmaz)")
    return parsed


def publish_document(
    conn: psycopg.Connection[tuple[object, ...]],
    doc_type: str,
    version: str,
    content: bytes,
    published_at: datetime | None = None,
    dry_run: bool = False,
) -> str:
    """Yeni sürüm satırı ekler ve içerik özetini döner. Aynı (tür, sürüm) ikinci kez eklenemez (UNIQUE).

    `dry_run`: doğrulamalar ve yinelenme denetimi yapılır, satır EKLENMEZ.
    """
    if doc_type not in _TYPES:
        raise ToolConfigError(f"tür {', '.join(_TYPES)} olmalı")
    if not _VERSION_RE.fullmatch(version):
        raise ToolConfigError(
            "sürüm kodu küçük harf, rakam, nokta, alt çizgi ve tireden oluşmalı (en çok 64)"
        )
    if not content.strip():
        raise ToolConfigError("belge dosyası boş")
    digest = sha256_of(content)
    if conn.execute(
        "SELECT 1 FROM legal_documents WHERE doc_type = %s AND version = %s", (doc_type, version)
    ).fetchone():
        raise ToolConfigError(f"{doc_type} sürüm {version} zaten yayınlanmış (satırlar değişmez)")
    if dry_run:
        return digest
    try:
        conn.execute(
            "INSERT INTO legal_documents (doc_type, version, content_sha256, published_at) "
            "VALUES (%s, %s, %s, COALESCE(%s, now()))",
            (doc_type, version, digest, published_at),
        )
    except psycopg.errors.UniqueViolation:
        raise ToolConfigError(f"{doc_type} sürüm {version} zaten yayınlanmış (satırlar değişmez)") from None
    return digest


_REMINDER = (
    "HATIRLATMA: bu sürüm yeniden kabul ister. Yazmayı kabule kadar kapatmak için "
    "LEGAL_REACCEPTANCE_ENFORCED=true gerekir (varsayılan kapalı; karar Hasan/avukat). "
    "Web sayfası aynı sürümle canlıda olmalıdır."
)


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    ask: Callable[[str], str] = input,
) -> int:
    parser = argparse.ArgumentParser(prog="legal_documents")
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish", help="yeni belge sürümü yayınla")
    pub.add_argument("--type", required=True, choices=_TYPES)
    pub.add_argument("--version", required=True)
    pub.add_argument("--file", required=True, type=Path)
    pub.add_argument("--published-at", help="ileri tarihli yayın (ISO 8601); verilmezse şimdi")
    pub.add_argument("--dry-run", action="store_true", help="doğrula, özeti yaz, hiçbir şey ekleme")
    pub.add_argument("--yes", action="store_true", help="onay sorusunu atla (otomasyon)")
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        content = args.file.read_bytes()
        published_at = parse_published_at(args.published_at)
        conn = connect_admin(env)
        try:
            ensure_rls_bypass(conn)
            digest = publish_document(conn, args.type, args.version, content, published_at, dry_run=True)
            when = published_at.isoformat() if published_at else "şimdi"
            print(f"{args.type} {args.version} sha256={digest} yayın={when}")
            if args.dry_run:
                print("dry-run: hiçbir kayıt eklenmedi.")
                return EXIT_OK
            if not args.yes and ask(f"Yayınlamak için '{args.type} {args.version}' yazın: ").strip() != (
                f"{args.type} {args.version}"
            ):
                print("İptal edildi: onay eşleşmedi.", file=sys.stderr)
                return EXIT_CONFIG
            publish_document(conn, args.type, args.version, content, published_at)
        finally:
            conn.close()
    except (ToolConfigError, OSError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print(f"yayınlandı: {args.type} {args.version} sha256={digest}")
    if not args.version.startswith("taslak-"):
        print(_REMINDER)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
