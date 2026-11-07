"""Şifreleme biçimi geçişi: eski `v1:` (FieldCipher) <-> yeni `v2:` (zarf şifreleme).

Kullanım (operasyon, yönetici bağlantısıyla; ayrıntı docs/adr/0004-zarf-sifreleme.md):

    python -m app.tools.migrate_envelope             # kuru çalıştırma: v1 -> v2
    python -m app.tools.migrate_envelope --apply     # v1 -> v2 uygula
    python -m app.tools.migrate_envelope --apply --revert   # GERİ ALMA: v2 -> v1

Gerekli ortam: DATABASE_ADMIN_URL, DATA_KEKS, DATA_KEK_ACTIVE ve eski biçim için
DATA_ENCRYPTION_KEY (v1'i okumak ve geri almak için gerekir).

Özellikler:
  - Varsayılan KURU ÇALIŞTIRMA; idempotent (hedef biçimdeki alana dokunmaz).
  - Geri alınabilir: `--revert` v2 değerlerini eski v1 biçimine çevirir (düz metin değişmez).
  - Veri silinmez; her dönüşüm yazmadan önce çözme eşitliğiyle doğrulanır.
  - Satır bazında karşılaştır-ve-yaz (CAS): eşzamanlı değişen satıra dokunulmaz.
  - Bir satır işlenemezse (bozuk veri, yanlış anahtar) dokunulmaz, rapor edilir, çıkış kodu 2.
  - Yeni v2 değerleri yeni AAD'yi (kiracı, platform, satıcı, hesap, alan) kullanır; böylece
    denetim D-04 de kapanır.

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

from app.core.crypto import DecryptionError, FieldCipher
from app.core.envelope import EnvelopeCipher
from app.services.marketplace_accounts import build_aad, legacy_aad
from app.tools import common

AUDIT_UPGRADE = "marketplace_account.envelope_migrated"
AUDIT_REVERT = "marketplace_account.envelope_reverted"


@dataclass
class Report:
    """İşlem özeti: yalnız sayılar ve hesap kimlikleri."""

    converted: int = 0  # dönüştürüldü (apply) veya dönüştürülecek (dry-run)
    up_to_date: int = 0
    failed: list[str] = field(default_factory=list)
    skipped_concurrent: int = 0


def _convert(
    value: str,
    row: common.AccountRow,
    field_name: str,
    envelope: EnvelopeCipher,
    legacy: FieldCipher,
    *,
    revert: bool,
) -> str:
    """Tek alanı hedef biçime çevirir; zaten hedefteyse aynen döner. Bozuksa DecryptionError."""
    tenant, account = UUID(row.tenant_id), UUID(row.id)
    v2_aad = build_aad(tenant, row.platform, row.seller_id, account, field_name)
    v1_aad = legacy_aad(account, field_name)
    if revert:
        if value.startswith("v1:"):
            return value
        plain = envelope.decrypt(value, v2_aad)
        converted = legacy.encrypt(plain, v1_aad)
        if legacy.decrypt(converted, v1_aad) != plain:  # yazmadan önce doğrulama
            raise DecryptionError("doğrulama başarısız")
        return converted
    if envelope.is_envelope(value):
        return value
    plain = legacy.decrypt(value, v1_aad)
    converted = envelope.encrypt(plain, v2_aad)
    if envelope.decrypt(converted, v2_aad) != plain:  # yazmadan önce doğrulama
        raise DecryptionError("doğrulama başarısız")
    return converted


def run(
    conn: psycopg.Connection[tuple[object, ...]],
    envelope: EnvelopeCipher,
    legacy: FieldCipher,
    *,
    apply: bool,
    revert: bool,
    out: TextIO,
) -> Report:
    """Tüm hesapları gezer; `apply` ise yazar. Çıktıya sır yazılmaz."""
    report = Report()
    for row in common.iter_accounts(conn):
        try:
            new_key = _convert(row.api_key, row, "api_key", envelope, legacy, revert=revert)
            new_secret = _convert(row.api_secret, row, "api_secret", envelope, legacy, revert=revert)
        except DecryptionError:
            print(f"HATA hesap={row.id}: çözülemedi (satıra dokunulmadı)", file=out)
            report.failed.append(row.id)
            continue
        if (new_key, new_secret) == (row.api_key, row.api_secret):
            report.up_to_date += 1
            continue
        if apply:
            changed = common.compare_and_set(
                conn,
                row.id,
                (row.api_key, row.api_secret),
                (new_key, new_secret),
                AUDIT_REVERT if revert else AUDIT_UPGRADE,
                {"platform": row.platform, "to": "v1" if revert else "v2"},
            )
            if not changed:
                print(f"ATLANDI hesap={row.id}: eşzamanlı değişiklik, sonraki çalıştırmada işlenir", file=out)
                report.skipped_concurrent += 1
                continue
        print(f"hesap={row.id} {'v2 -> v1' if revert else 'v1 -> v2'}", file=out)
        report.converted += 1
    return report


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None, out: TextIO | None = None
) -> int:
    """Komut satırı girişi. `environ` ve `out` testte verilir."""
    parser = argparse.ArgumentParser(prog="python -m app.tools.migrate_envelope")
    parser.add_argument(
        "--apply", action="store_true", help="değişiklikleri yaz (varsayılan: kuru çalıştırma)"
    )
    parser.add_argument("--revert", action="store_true", help="geri al: v2 -> v1")
    args = parser.parse_args(argv)
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    try:
        envelope = EnvelopeCipher(common.load_key_ring(environ))
        legacy = FieldCipher(common.load_legacy_master_key(environ))
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
        report = run(conn, envelope, legacy, apply=args.apply, revert=args.revert, out=out)
    verb = "dönüştürüldü" if args.apply else "dönüştürülecek"
    print(
        f"Özet: {report.converted} kayıt {verb}, {report.up_to_date} kayıt güncel, "
        f"{len(report.failed)} kayıt başarısız, {report.skipped_concurrent} kayıt atlandı",
        file=out,
    )
    return common.EXIT_FAILED if report.failed else common.EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
