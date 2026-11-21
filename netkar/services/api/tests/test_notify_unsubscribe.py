"""Tek tık kapatma token'ı (ADR-0009 §7.5, §12 madde 26): saf testler (veritabanı yok).

Kapsam: başka kullanıcı, kiracı, kural ve kanal için geçersizlik; süresi dolmuş token; bozulmuş yük ve imza; `*`
(tüm kurallar) token'ı; anahtarın ana anahtardan amaç bazlı türetilmesi. Testlerde SABİT test anahtarı kullanılır
(repoda gerçek sır yok).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.alerts import AlertRule
from app.core.config import Settings
from app.core.crypto import derive_key
from app.services.notify_unsubscribe import ALL_RULES, UnsubscribeSigner

TEST_KEY = b"sabit-test-anahtari-0123456789ab"  # yalnız testler için, 32 bayt
OTHER_KEY = b"baska-test-anahtari-0123456789ab"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
USER = UUID("11111111-1111-1111-1111-111111111111")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
LOSS = AlertRule.LOSS_MAKING_SALE.value
RETURNS = AlertRule.RETURN_RATE_INCREASE.value


def signer(key: bytes = TEST_KEY, days: int = 90) -> UnsubscribeSigner:
    return UnsubscribeSigner(key, ttl=timedelta(days=days))


def token(rule: str = LOSS, channel: str = "email", at: datetime = NOW) -> str:
    return signer().sign(USER, TENANT, rule, channel, at)


def forged(payload: str, key: bytes = TEST_KEY) -> str:
    """Geçerli biçimde ama verilen anahtarla imzalanmış token (yük elle kurulur)."""
    import hashlib
    import hmac

    raw = payload.encode()
    mac = hmac.new(key, b"notify-unsub\x00" + raw, hashlib.sha256).digest()
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return f"{enc(raw)}.{enc(mac)}"


def test_roundtrip_returns_the_signed_identity_and_expiry() -> None:
    claim = signer().verify(token(), NOW)
    assert claim is not None
    assert (claim.user_id, claim.tenant_id, claim.rule, claim.channel) == (USER, TENANT, LOSS, "email")
    assert claim.expires_at == NOW + timedelta(days=90) and claim.rules == (LOSS,)


def test_token_is_valid_only_for_its_own_user_tenant_rule_and_channel() -> None:
    s, t = signer(), token()
    assert s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule=LOSS, channel="email")
    assert not s.allows(
        t, NOW, user_id=uuid4(), tenant_id=TENANT, rule=LOSS, channel="email"
    )  # başka kullanıcı
    assert not s.allows(t, NOW, user_id=USER, tenant_id=uuid4(), rule=LOSS, channel="email")  # başka kiracı
    assert not s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule=RETURNS, channel="email")  # başka kural
    assert not s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule=LOSS, channel="push")  # başka kanal
    assert not s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule="UYDURMA", channel="email")


def test_wildcard_token_covers_every_rule_of_its_channel_only() -> None:
    s, t = signer(), token(ALL_RULES)
    for rule in AlertRule:
        assert s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule=rule.value, channel="email")
        assert not s.allows(t, NOW, user_id=USER, tenant_id=TENANT, rule=rule.value, channel="push")
    claim = s.verify(t, NOW)
    assert claim is not None and claim.rules == tuple(rule.value for rule in AlertRule)


def test_expired_token_is_invalid_and_the_boundary_is_exclusive() -> None:
    t = token()
    expires = NOW + timedelta(days=90)
    assert signer().verify(t, expires - timedelta(seconds=1)) is not None
    assert signer().verify(t, expires) is None  # tam bitiş anı geçersiz
    assert signer().verify(t, expires + timedelta(days=1)) is None
    assert not signer().allows(
        t, expires + timedelta(seconds=1), user_id=USER, tenant_id=TENANT, rule=LOSS, channel="email"
    )
    assert (
        signer(days=1).verify(signer(days=1).sign(USER, TENANT, LOSS, "email", NOW), NOW + timedelta(days=2))
        is None
    )


def test_signature_from_another_key_or_tampered_parts_is_invalid() -> None:
    t = token()
    assert signer(OTHER_KEY).verify(t, NOW) is None  # başka anahtar
    body, sig = t.split(".")
    assert signer().verify(f"{body}.{sig[:-2]}AA", NOW) is None  # imza bozuk
    assert signer().verify(f"{sig}.{body}", NOW) is None  # parçalar yer değiştirdi
    # Başka kurala çevrilmiş yük, eski imzayla geçersiz.
    payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()
    swapped = payload.replace(LOSS, RETURNS)
    assert swapped != payload
    swapped_body = base64.urlsafe_b64encode(swapped.encode()).decode().rstrip("=")
    assert signer().verify(f"{swapped_body}.{sig}", NOW) is None
    # Süre uzatma denemesi (imza yükü kapsar).
    longer = payload.rsplit("|", 1)[0] + "|" + str(int((NOW + timedelta(days=900)).timestamp()))
    longer_body = base64.urlsafe_b64encode(longer.encode()).decode().rstrip("=")
    assert signer().verify(f"{longer_body}.{sig}", NOW) is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "tek-parca",
        "a.b.c",
        ".",
        "a.",
        ".b",
        "x" * 600,
        "çğş.üö",
        "AAAA.%%%%",
        "AAAA BBBB.CCCC",
    ],
)
def test_malformed_tokens_are_invalid_without_raising(bad: str) -> None:
    assert signer().verify(bad, NOW) is None


@pytest.mark.parametrize(
    "payload",
    [
        f"v2|{USER}|{TENANT}|{LOSS}|email|{int((NOW + timedelta(days=1)).timestamp())}",  # sürüm
        f"v1|degil-uuid|{TENANT}|{LOSS}|email|{int((NOW + timedelta(days=1)).timestamp())}",
        f"v1|{USER}|{TENANT}|UYDURMA_KURAL|email|{int((NOW + timedelta(days=1)).timestamp())}",
        f"v1|{USER}|{TENANT}|{LOSS}|sms|{int((NOW + timedelta(days=1)).timestamp())}",
        f"v1|{USER}|{TENANT}|{LOSS}|email|gecmis-degil",
        f"v1|{USER}|{TENANT}|{LOSS}|email|99999999999999999999",
        f"v1|{USER}|{TENANT}|{LOSS}|email",
        f"v1|{USER}|{TENANT}|{LOSS}|email|1|fazla",
    ],
)
def test_correctly_signed_but_invalid_payloads_are_rejected(payload: str) -> None:
    assert signer().verify(forged(payload), NOW) is None


def test_sign_rejects_unknown_rule_or_channel_and_constructor_rejects_weak_settings() -> None:
    with pytest.raises(ValueError, match="bilinmeyen kural"):
        signer().sign(USER, TENANT, "UYDURMA", "email", NOW)
    with pytest.raises(ValueError, match="bilinmeyen kural"):
        signer().sign(USER, TENANT, LOSS, "sms", NOW)
    with pytest.raises(ValueError, match="en az 16 bayt"):
        UnsubscribeSigner(b"kisa")
    with pytest.raises(ValueError, match="pozitif"):
        UnsubscribeSigner(TEST_KEY, ttl=timedelta(0))


def test_sign_normalises_the_clock_to_utc() -> None:
    istanbul = NOW.astimezone(timezone(timedelta(hours=3)))  # aynı an, İstanbul saatiyle
    assert istanbul.hour == 15 and signer().sign(USER, TENANT, LOSS, "email", istanbul) == token()


def test_signing_key_is_derived_from_the_master_key_with_its_own_purpose(settings: Settings) -> None:
    from_settings = UnsubscribeSigner.from_settings(settings)
    manual = UnsubscribeSigner(derive_key(settings.master_key, "notify-unsub"), ttl=timedelta(days=90))
    assert manual.verify(from_settings.sign(USER, TENANT, LOSS, "email", NOW), NOW) is not None
    # Başka amaçla türetilen anahtar (ör. IP özeti) bu token'ı doğrulayamaz.
    other_purpose = UnsubscribeSigner(derive_key(settings.master_key, "ip-hash"))
    assert other_purpose.verify(from_settings.sign(USER, TENANT, LOSS, "email", NOW), NOW) is None
    # Süre ayardan gelir.
    short = UnsubscribeSigner.from_settings(settings.model_copy(update={"notify_unsubscribe_ttl_days": 1}))
    claim = short.verify(short.sign(USER, TENANT, LOSS, "email", NOW), NOW)
    assert claim is not None and claim.expires_at == NOW + timedelta(days=1)


@given(st.text(max_size=300))
def test_arbitrary_text_never_verifies_and_never_raises(garbage: str) -> None:
    assert signer().verify(garbage, NOW) is None
