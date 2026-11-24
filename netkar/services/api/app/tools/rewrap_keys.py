"""KEK döndürme: aktif olmayan kid ile sarılmış DEK'leri aktif KEK'e taşır.

Kullanım (operasyon, yönetici bağlantısıyla; ayrıntı docs/adr/0004-zarf-sifreleme.md):

    # Ortam: DATABASE_ADMIN_URL, DATA_KEKS, DATA_KEK_ACTIVE
    python -m app.tools.rewrap_keys            # kuru çalıştırma
    python -m app.tools.rewrap_keys --apply    # uygula

Özellikler:
  - Varsayılan KURU ÇALIŞTIRMA: hiçbir şey yazmaz, ne yapılacağını raporlar.
  - İdempotent: aktif kid ile sarılı değerlere dokunmaz; ikinci çalıştırma 0 kayıt taşır.
  - Yalnız sarılı DEK yeniden sarılır; veri gövdesi aynı kalır. Her değişiklik, yazmadan önce
    çözme eşitliğiyle doğrulanır (eski ve yeni değer aynı düz metni verir).
  - Satır bazında karşılaştır-ve-yaz (CAS): eşzamanlı değişen satıra dokunulmaz.
  - Bir satır işlenemezse (kid halkada yok, bozuk veri) diğerlerine devam eder, çıkış kodu 2.
  - Veri silinmez. Aktif olmayan KEK'i halkadan çıkarmadan önce çıktının "0 başarısız" ve ikinci
    çalıştırmanın "0 kayıt taşındı" demesini bekleyin.

Çıkış kodları: 0 başarılı, 2 bazı kayıtlar işlenemedi, 3 yapılandırma veya yetki hatası.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TextIO
from uuid import UUID

import psycopg

from app.core.crypto import DecryptionError
from app.core.envelope import EnvelopeCipher
from app.services.marketplace_accounts import build_aad
from app.tools import common

AUDIT_ACTION = "marketplace_account.keys_rewrapped"


@dataclass
class Report:
    """İşlem özeti: yalnız sayılar ve hesap kimlikleri."""

    moved: int = 0  # taşındı (apply) veya taşınacak (dry-run)
    up_to_date: int = 0
    failed: list[str] = field(default_factory=list)
    skipped_concurrent: int = 0


def _rewrap_row(envelope: EnvelopeCipher, row: common.AccountRow) -> tuple[tuple[str, str], str] | None:
    """(yeni değerler, eski kid) döndürür; zaten güncelse None. Bozuksa DecryptionError."""
    old_kid = envelope.key_id(row.api_key)
    secret_kid = envelope.key_id(row.api_secret)
    if old_kid == envelope.active_kid and secret_kid == envelope.active_kid:
        return None
    new_key = envelope.rewrap(row.api_key)
    new_secret = envelope.rewrap(row.api_secret)
    # Yazmadan önce doğrulama: eski ve yeni değer aynı düz metni vermeli.
    for field_name, old, new in (
        ("api_key", row.api_key, new_key),
        ("api_secret", row.api_secret, new_secret),
    ):
        aad = build_aad(UUID(row.tenant_id), row.platform, row.seller_id, UUID(row.id), field_name)
        if envelope.decrypt(old, aad) != envelope.decrypt(new, aad):
            raise DecryptionError("doğrulama başarısız")
    return (new_key, new_secret), old_kid


def run(
    conn: psycopg.Connection[tuple[object, ...]], envelope: EnvelopeCipher, *, apply: bool, out: TextIO
) -> Report:
    """Tüm hesapları gezer; `apply` ise yazar. Çıktıya sır yazılmaz."""
    report = Report()
    for row in common.iter_accounts(conn):
        try:
            result = _rewrap_row(envelope, row)
        except DecryptionError:
            hint = " (eski v1 biçimi: önce migrate_envelope)" if row.api_key.startswith("v1:") else ""
            kid = row.api_key.split(":")[1] if row.api_key.startswith("v2:") else "?"
            print(f"HATA hesap={row.id} kid={kid}: çözülemedi{hint}", file=out)
            report.failed.append(row.id)
            continue
        if result is None:
            report.up_to_date += 1
            continue
        (new_key, new_secret), old_kid = result
        if apply:
            changed = common.compare_and_set(
                conn,
                row.id,
                (row.api_key, row.api_secret),
                (new_key, new_secret),
                AUDIT_ACTION,
                {"from": old_kid, "to": envelope.active_kid, "platform": row.platform},
            )
            if not changed:
                print(f"ATLANDI hesap={row.id}: eşzamanlı değişiklik, sonraki çalıştırmada işlenir", file=out)
                report.skipped_concurrent += 1
                continue
        print(f"hesap={row.id} {old_kid} -> {envelope.active_kid}", file=out)
        report.moved += 1
    return report


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None, out: TextIO | None = None
) -> int:
    """Komut satırı girişi. `environ` ve `out` testte verilir."""
    parser = argparse.ArgumentParser(
        prog="python -m app.tools.rewrap_keys", description=__doc__.split("\n")[0]
    )
    parser.add_argument(
        "--apply", action="store_true", help="değişiklikleri yaz (varsayılan: kuru çalıştırma)"
    )
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    try:
        envelope = EnvelopeCipher(common.load_key_ring(environ))
        conn = common.connect_admin(environ)
    except common.ToolConfigError as exc:
        print(f"HATA: {exc}", file=out)
        return common.EXIT_CONFIG
    with conn:
        try:
            common.ensure_rls_bypass(conn)
        except common.ToolConfigError as exc:
            print(f"HATA: {exc}", file=out)
            return common.EXIT_CONFIG
        if not args.apply:
            print("[DRY-RUN] hiçbir şey yazılmayacak; uygulamak için --apply verin", file=out)
        report = run(conn, envelope, apply=args.apply, out=out)
    verb = "taşındı" if args.apply else "taşınacak"
    print(
        f"Özet: {report.moved} kayıt {verb}, {report.up_to_date} kayıt güncel, "
        f"{len(report.failed)} kayıt başarısız, {report.skipped_concurrent} kayıt atlandı",
        file=out,
    )
    return common.EXIT_FAILED if report.failed else common.EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
