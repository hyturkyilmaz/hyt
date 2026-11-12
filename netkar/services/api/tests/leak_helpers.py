"""Yanıt sızıntı kontrolleri için yardımcı.

Hata gövdesindeki ``request_id`` rastgele bir uuid4 hex değeridir (32 karakter, 0-9a-f).
Yalnız rakamdan oluşan kısa bir nöbetçi değer ("1003", "9999") bu rastgele değerin içinde
tesadüfen geçebilir: 4 haneli bir değer için olasılık yaklaşık 29 / 16^4 = %0,044.
Sızıntı kontrolü bu yüzden ``request_id`` dışındaki gövdeye bakar; alanın kendisi ayrıca
biçim olarak doğrulanır, böylece kontrol gerçek bir yansımayı gözden kaçırmaz.
"""

from __future__ import annotations

import json
import re

import httpx

_REQUEST_ID = re.compile(r"^[0-9a-f]{32}$")


def visible_text(response: httpx.Response) -> str:
    """Yanıt gövdesini, rastgele ``request_id`` alanı çıkarılmış metin olarak döndürür.

    JSON nesnesi değilse gövde olduğu gibi döner. ``request_id`` varsa uuid4 hex
    biçiminde olmak zorundadır; aksi halde (alana veri yansıtılmışsa) hata verir.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text
    if not isinstance(body, dict):
        return response.text
    request_id = body.pop("request_id", None)
    if request_id is not None:
        assert isinstance(request_id, str) and _REQUEST_ID.match(request_id), request_id
    return json.dumps(body, ensure_ascii=False)
