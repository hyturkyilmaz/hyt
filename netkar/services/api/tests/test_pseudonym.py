"""Takma adlı müşteri anahtarı çekirdeği (üretim yolunda kullanılmıyor; ADR-0005 §8)."""

from __future__ import annotations

from uuid import UUID

from app.core.pseudonym import customer_key

MASTER = bytes(range(32))
T1, T2 = UUID(int=1), UUID(int=2)
A1, A2 = UUID(int=11), UUID(int=12)


def test_key_is_stable_hex_and_hides_the_raw_value() -> None:
    key = customer_key(MASTER, T1, A1, 888888888)
    assert key == customer_key(MASTER, T1, A1, "888888888")  # tamsayı ve metin aynı anahtarı verir
    assert len(key) == 64 and int(key, 16) >= 0 and "888888888" not in key


def test_key_is_bound_to_tenant_account_and_master_key() -> None:
    base = customer_key(MASTER, T1, A1, 42)
    assert customer_key(MASTER, T2, A1, 42) != base  # aynı müşteri başka kiracıda eşleşmez
    assert customer_key(MASTER, T1, A2, 42) != base  # ... ve başka hesapta da
    assert customer_key(bytes(32), T1, A1, 42) != base  # ana anahtar bilinmeden değerden müşteriye gidilemez
    assert customer_key(MASTER, T1, A1, 43) != base
