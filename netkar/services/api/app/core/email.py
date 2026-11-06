"""E-posta gönderim arayüzü. MVP'de gerçek servis yok; sahte uygulamalar vardır."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
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


class FileEmailSender:
    """Geliştirme için JSONL dosyasına yazar. Gövde maskesizdir (dosyada), log'a token yazılmaz."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def send(self, message: EmailMessage) -> None:
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(message), ensure_ascii=False) + "\n")
        # Log'a yalnız meta yazılır: gövde ve token yok.
        logger.info("dev e-postası dosyaya yazıldı", extra={"subject": message.subject})
