"""E-posta gönderim arayüzü. MVP'de gerçek servis yok; sahte uygulamalar vardır."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import re
import stat
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    """Gönderilecek e-posta."""

    to: str
    subject: str
    body: str


class EmailSender(Protocol):
    """E-posta gönderici arayüzü (ileride Resend/SES uygulaması bunu sağlar)."""

    async def send(self, message: EmailMessage) -> None: ...


class InMemoryOutbox:
    """Testler için bellek içi gelen kutusu."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)

    def to(self, address: str) -> list[EmailMessage]:
        """Belirli alıcıya giden iletiler."""
        return [m for m in self.messages if m.to == address]


# Döndürülen dosya adı eki: `<ad>.<UTC zaman damgası>-<sıra>` (örn. outbox.jsonl.20261116T101500Z-0001).
# Yalnız ASCII rakam ve tam eşleşme: Unicode rakamlı ya da eklentili adlar bu arka ucun dosyası sayılmaz.
_ROTATED_SUFFIX = re.compile(r"\.[0-9]{8}T[0-9]{6}Z-[0-9]{4}", re.ASCII)
_FILE_MODE = 0o600
_DIR_MODE = 0o700


class OutboxSecurityError(RuntimeError):
    """Outbox yolu ya da dizini güvenli değil (DT-20, DT-24); yazılmadı."""


class FileEmailSender:
    """JSONL dosyasına yazar (geliştirme ve staging). Gövde maskesizdir (dosyada), log'a token yazılmaz.

    Dosya gizli veridir (alıcı adresi ve ham sıfırlama bağlantısı içerir; denetim DT-20): dosya 0600 ile
    açılır, eksik dizinlerin HER BİRİ 0700 ile oluşturulur (var olan dizinlerin izni değiştirilmez). Etkin
    dosya simgesel bağ izlenmeden (O_NOFOLLOW) açılır ve düz dosya, bu sürecin sahipliğinde, tek bağlı olmalı
    (DT-24); sertleşen ortamda üst dizin grup/diğer yazılabilir ise kurucu hata verir. Saklama sınırlıdır:
    etkin dosya `max_bytes`'ı aşınca döndürülür, döndürülmüş dosyalar `retention_days` günden eskiyse ya da
    sayısı `max_files`'ı aşıyorsa (en eskiden başlayarak) silinir.
    """

    def __init__(
        self,
        path: str,
        *,
        max_bytes: int = 256 * 1024,
        max_files: int = 5,
        retention_days: int = 7,
        hardened: bool = False,
    ) -> None:
        self._path = Path(path)
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._retention_seconds = retention_days * 86400
        self._lock = asyncio.Lock()
        if hardened:
            self._require_private_parent()
        # Var olan etkin dosyanın izni açılışta 0600'e çekilir (aynı simgesel bağ/sahiplik denetimleriyle).
        if os.path.lexists(self._path):
            self._close(self._open_active(create=False))
        # Boşta kalmış eski kayıtlar yeniden başlatmada da süresi dolunca silinsin.
        self._prune()

    async def send(self, message: EmailMessage) -> None:
        async with self._lock:
            self._write_line(json.dumps(asdict(message), ensure_ascii=False) + "\n")
        # Log'a yalnız meta yazılır: gövde ve token yok.
        logger.info("dev e-postası dosyaya yazıldı", extra={"subject": message.subject})

    def _require_private_parent(self) -> None:
        """Sertleşen ortamda var olan üst dizin grup ya da diğerleri tarafından yazılabilir olamaz."""
        try:
            mode = self._path.parent.stat().st_mode
        except FileNotFoundError:
            return  # yoksa 0700 ile biz oluştururuz
        if mode & 0o022:
            raise OutboxSecurityError(
                "outbox üst dizini grup ya da diğerleri tarafından yazılabilir; reddedildi"
            )

    def _ensure_dir(self) -> None:
        """Eksik dizinleri üstten aşağı tek tek 0700 ile oluşturur (mkdir(mode) yalnız sonuncuyu etkiler)."""
        missing: list[Path] = []
        current = self._path.parent
        while not current.exists():
            missing.append(current)
            if current.parent == current:
                break
            current = current.parent
        for directory in reversed(missing):
            try:
                os.mkdir(directory, _DIR_MODE)
            except FileExistsError:
                continue
            # umask daraltabilir ama genişletemez; yine de açıkça 0700'e sabitlenir. Dizin
            # O_NOFOLLOW ile açılır: mkdir ile chmod arasında simgesel bağa çevrilirse hedefi
            # değiştirilmez, açılış hata verir.
            dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                # Semgrep insecure-file-permissions yanlış alarm: 0o700 yalnız sahibe izin
                # verir; dizine girmek için sahip çalıştırma biti gereklidir.
                os.fchmod(dir_fd, _DIR_MODE)  # nosemgrep
            finally:
                os.close(dir_fd)

    def _open_active(self, *, create: bool) -> int:
        """Etkin dosyayı açar; simgesel bağ, düz olmayan dosya, başka sahip ya da çok bağ varsa reddeder."""
        flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC
        if create:
            flags |= os.O_CREAT
        try:
            fd = os.open(self._path, flags, _FILE_MODE)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise OutboxSecurityError("outbox yolu simgesel bağ; reddedildi") from None
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise OutboxSecurityError(
                    "outbox dosyası güvenli değil (düz dosya, bu sürecin sahipliğinde ve tek bağlı olmalı); "
                    "yazılmadı"
                )
            # 0600 oluşturulurken verilir; var olan dosyanın izni de daraltılır (kontrollerden SONRA).
            os.fchmod(fd, _FILE_MODE)
        except BaseException:
            os.close(fd)
            raise
        return fd

    @staticmethod
    def _close(fd: int) -> None:
        os.close(fd)

    def _write_line(self, line: str) -> None:
        self._ensure_dir()
        self._rotate_if_needed()
        fd = self._open_active(create=True)
        with os.fdopen(fd, "a", encoding="utf-8") as fh:
            fh.write(line)
        self._prune()

    def _rotate_if_needed(self) -> None:
        try:
            info = self._path.lstat()
        except FileNotFoundError:
            return
        # Düz olmayan (ör. simgesel bağ) etkin yol döndürülmez; açılışta reddedilir.
        if not stat.S_ISREG(info.st_mode) or info.st_size < self._max_bytes:
            return
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        for seq in range(1, 10_000):
            target = self._path.with_name(f"{self._path.name}.{stamp}-{seq:04d}")
            if not target.exists():
                self._path.rename(target)
                return

    def _rotated(self) -> list[Path]:
        """Yalnız bu arka ucun döndürdüğü dosyalar: ad kalıbı `<outbox adı>.<damga>-<sıra>` ve düz dosya."""
        parent = self._path.parent
        if not parent.is_dir():
            return []
        prefix = self._path.name
        found = [
            entry
            for entry in parent.iterdir()
            if entry.name.startswith(prefix)
            and _ROTATED_SUFFIX.fullmatch(entry.name[len(prefix) :])
            and entry.is_file()
            and not entry.is_symlink()
        ]
        # Ad (UTC damga + sıra) kronolojiktir: sıralama dosya sistemi zaman çözünürlüğüne bağlı değildir.
        return sorted(found, key=lambda entry: entry.name)

    def _prune(self) -> None:
        """Süresi dolan ve sayı sınırını aşan DÖNDÜRÜLMÜŞ dosyaları siler (en eskiden başlayarak).

        Bilinçli kapsam: yalnız yapılandırılan dizinde, adı `<outbox adı>.<damga>-<sıra>` kalıbına uyan düz
        dosyalar silinir (bu arka ucun kendi yazdıkları); dizindeki başka dosyalara, simgesel bağlara ve etkin
        outbox dosyasına dokunulmaz. Silme hataları e-posta gönderimini bozmaz.
        """
        try:
            files = self._rotated()
            cutoff = time.time() - self._retention_seconds
            keep = [f for f in files if f.stat().st_mtime >= cutoff]
            expired = [f for f in files if f not in keep]
            excess = keep[: max(0, len(keep) - self._max_files)]
            for victim in [*expired, *excess]:
                victim.unlink(missing_ok=True)
        except OSError:
            logger.warning("outbox eski dosya temizliği yapılamadı")
