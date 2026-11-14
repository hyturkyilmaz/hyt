"""Son müşteri için takma adlı anahtar (tuzlu HMAC).

DURUM: Üretim yolunda KULLANILMIYOR. Trendyol'un `customerId` değeri istemci modellerine alınmaz
(ADR-0003 §5) ve `orders.customer_key` sütunu BOŞ kalır; hukuk onayı bekler (ADR-0003 K-N07 madde
16: takma adlı müşteri anahtarı EK-6 md. 4.2 "kayıt yaratma yasağı" karşısında kabul edilebilir mi).
Onay gelirse HMAC, ham değer model katmanına girmeden İSTEMCİ İÇİNDE hesaplanmalıdır. Bu işlev o
günün çekirdeğidir ve davranışı testle sabitlenmiştir (`tests/test_pseudonym.py`).

Takma adlı veri anonim DEĞİLDİR (KVKK): anahtar kiracıya ve hesaba bağlıdır, böylece aynı müşteri
farklı satıcılarda eşleştirilemez ve ana anahtar bilinmeden değerden müşteriye gidilemez.
"""

from __future__ import annotations

import hashlib
import hmac
from uuid import UUID

from app.core.crypto import derive_key


def customer_key(master_key: bytes, tenant_id: UUID, account_id: UUID, raw_customer_id: str | int) -> str:
    """(kiracı, hesap, ham müşteri kimliği) için kararlı, geri döndürülemez 64 haneli hex anahtar."""
    key = derive_key(master_key, f"customer-key:{tenant_id}:{account_id}")
    return hmac.new(key, str(raw_customer_id).encode(), hashlib.sha256).hexdigest()
