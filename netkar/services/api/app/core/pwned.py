"""Sızmış parola kontrolü (HIBP Pwned Passwords, k-anonimlik)."""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/"


class PwnedPasswordChecker(Protocol):
    """Parolanın bilinen sızıntılarda geçip geçmediğini söyler."""

    async def is_pwned(self, password: str) -> bool: ...


class NullPwnedChecker:
    """Varsayılan: kontrol kapalı."""

    async def is_pwned(self, password: str) -> bool:
        return False


class HibpPwnedChecker:
    """SHA-1 önekinin ilk 5 hanesi gönderilir; parola ve tam özet ağdan çıkmaz."""

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 3.0) -> None:
        self._client = client
        self._timeout = timeout

    async def is_pwned(self, password: str) -> bool:
        # SHA-1, HIBP Pwned Passwords k-anonimlik protokolünün zorunlu biçimidir; parola
        # saklama veya imza için kullanılmaz (parola özeti argon2id). Bu satırda Semgrep
        # kuralı insecure-hash-algorithm-sha1 bilinçli olarak muaf tutulur.
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()  # nosemgrep
        prefix, suffix = digest[:5], digest[5:]
        try:
            client = self._client or httpx.AsyncClient(timeout=self._timeout)
            try:
                resp = await client.get(HIBP_RANGE_URL + prefix, headers={"Add-Padding": "true"})
            finally:
                if self._client is None:
                    await client.aclose()
            resp.raise_for_status()
        except httpx.HTTPError:
            # Servis erişilemezse kayıt akışı kesilmez (açık risk olarak belgelenmiştir).
            logger.warning("HIBP erişilemedi, kontrol atlandı")
            return False
        for line in resp.text.splitlines():
            candidate, _, count = line.partition(":")
            if candidate.strip() == suffix and count.strip() not in {"", "0"}:
                return True
        return False
