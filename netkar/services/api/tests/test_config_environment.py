"""ENVIRONMENT değerlerine göre ayar doğrulaması (dev, test, staging, prod). Veritabanı gerekmez."""

from __future__ import annotations

import base64
import os
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import HARDENED_ENVIRONMENTS, Settings

KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
KEK = base64.b64encode(os.urandom(32)).decode()


def make(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "postgresql://u:p@localhost/db",
        "data_encryption_key": KEY,
        "email_backend": "file",
        "web_base_url": "https://app.example.invalid",
    }
    values.update(overrides)
    return Settings.model_validate(values)


def kek() -> dict[str, str]:
    return {"data_keks": f"k1:{KEK}", "data_kek_active": "k1"}


def test_hardened_set_is_staging_and_prod() -> None:
    assert HARDENED_ENVIRONMENTS == {"staging", "prod"}


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make(environment="canary")


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_dev_and_test_stay_permissive(environment: str) -> None:
    for backend in ("file", "memory"):
        settings = make(
            environment=environment, email_backend=backend, debug=True, trendyol_environment="live"
        )
        assert settings.environment == environment and settings.debug is True
    assert make(environment=environment).key_ring is not None  # KEK verilmeden türetilmiş geliştirme KEK'i


OUTBOX = "/var/lib/netkar/outbox/outbox.jsonl"


def test_staging_accepts_file_email_with_explicit_keks() -> None:
    settings = make(environment="staging", email_backend="file", email_dev_outbox_path=OUTBOX, **kek())
    assert settings.environment == "staging" and settings.trendyol_environment == "stage"


@pytest.mark.parametrize("path", ["var/outbox.jsonl", "./outbox.jsonl", "/var/lib/../outbox.jsonl", ""])
def test_staging_rejects_relative_or_traversing_outbox_path(path: str) -> None:
    """DT-20: göreli yol (varsayılan dahil) sürecin çalışma dizinine bağlıdır; mutlak yol zorunlu."""
    with pytest.raises(ValidationError, match="EMAIL_DEV_OUTBOX_PATH"):
        make(environment="staging", email_dev_outbox_path=path, **kek())
    with pytest.raises(ValidationError, match="EMAIL_DEV_OUTBOX_PATH"):
        make(environment="staging", **kek())  # varsayılan yol göreli


def test_outbox_path_is_not_checked_when_backend_is_not_file_or_env_not_hardened() -> None:
    # memory ayrı kuralla reddedilir; yol iletisi eklenmez.
    with pytest.raises(ValidationError) as exc:
        make(environment="staging", email_backend="memory", **kek())
    assert "EMAIL_DEV_OUTBOX_PATH" not in str(exc.value)
    for environment in ("dev", "test"):  # geliştirmede göreli yol serbest
        assert (
            make(environment=environment, email_dev_outbox_path="var/outbox.jsonl").environment == environment
        )


def test_outbox_retention_settings_are_bounded_below() -> None:
    for field in ("email_outbox_max_bytes", "email_outbox_max_files", "email_outbox_retention_days"):
        with pytest.raises(ValidationError):
            make(**{field: 0})
    s = make()
    assert (s.email_outbox_max_bytes, s.email_outbox_max_files, s.email_outbox_retention_days) == (
        256 * 1024,
        5,
        7,
    )


def test_staging_requires_the_kek_ring() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT=staging iken DATA_KEKS"):
        make(environment="staging")
    with pytest.raises(ValidationError, match="birlikte verilmeli"):
        make(environment="staging", data_keks=f"k1:{KEK}")


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"debug": True}, "ENVIRONMENT=staging iken DEBUG"),
        ({"email_dev_outbox_path": "gorece/outbox.jsonl"}, "EMAIL_DEV_OUTBOX_PATH"),
        ({"email_backend": "memory"}, "EMAIL_BACKEND=memory"),
        ({"trendyol_environment": "live"}, "TRENDYOL_ENVIRONMENT=live"),
    ],
)
def test_staging_rejects_unsafe_settings(overrides: dict[str, Any], needle: str) -> None:
    base: dict[str, Any] = {"email_dev_outbox_path": OUTBOX, **kek()}
    with pytest.raises(ValidationError, match=needle):
        make(environment="staging", **{**base, **overrides})


def test_staging_reports_every_problem_at_once() -> None:
    with pytest.raises(ValidationError) as exc:
        make(environment="staging", debug=True, email_backend="memory", trendyol_environment="live", **kek())
    text = str(exc.value)
    assert "DEBUG" in text and "EMAIL_BACKEND" in text and "TRENDYOL_ENVIRONMENT" in text


def test_prod_requires_kek_ring_and_rejects_file_and_memory_email() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT=prod iken DATA_KEKS"):
        make(environment="prod")
    for backend in ("file", "memory"):
        with pytest.raises(ValidationError, match="EMAIL_BACKEND"):
            make(environment="prod", email_backend=backend, **kek())
    with pytest.raises(ValidationError, match="DEBUG"):
        make(environment="prod", debug=True, **kek())


def test_prod_with_live_trendyol_is_not_blocked_by_the_staging_rule() -> None:
    """TRENDYOL live yasağı yalnız staging'e özgü; prod'u e-posta arka ucu gibi başka kurallar korur."""
    with pytest.raises(ValidationError) as exc:
        make(environment="prod", trendyol_environment="live", **kek())
    assert "TRENDYOL_ENVIRONMENT" not in str(exc.value)


@pytest.mark.parametrize("environment", sorted(HARDENED_ENVIRONMENTS))
def test_hardened_environments_reject_a_web_base_url_that_is_not_a_real_https_url(environment: str) -> None:
    # prod'da `file` e-posta arka ucu da reddedilir; doğrulayıcı sorunları BİRLİKTE bildirdiğinden https
    # iletisi her iki ortamda da aranabilir (staging'de tek sorun budur).
    extra: dict[str, Any] = {"email_backend": "file", "email_dev_outbox_path": OUTBOX, **kek()}
    for bad in (
        "http://app.example.invalid",
        "ftp://x",
        "app.example.invalid",
        "",
        "https://",
        "https:///yol",
        "https://:443",
    ):
        with pytest.raises(ValidationError, match="WEB_BASE_URL https"):
            make(environment=environment, web_base_url=bad, **extra)


def test_staging_accepts_an_https_web_base_url_in_any_letter_case() -> None:
    extra: dict[str, Any] = {"email_backend": "file", "email_dev_outbox_path": OUTBOX, **kek()}
    for good in (
        "https://app.example.invalid",
        "HTTPS://App.Example.Invalid",
        "https://app.example.invalid:8443/x",
    ):
        assert make(environment="staging", web_base_url=good, **extra).environment == "staging"


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_http_web_base_url_stays_allowed_outside_hardened_environments(environment: str) -> None:
    assert (
        make(environment=environment, web_base_url="http://localhost:3000").web_base_url
        == "http://localhost:3000"
    )


@pytest.mark.parametrize("backend", ["file", "memory"])
@pytest.mark.parametrize("environment", ["dev", "test"])
def test_live_notifications_flag_is_rejected_without_a_real_email_backend(
    environment: str, backend: str
) -> None:
    with pytest.raises(ValidationError, match="ALERT_NOTIFICATIONS_ENABLED"):
        make(environment=environment, email_backend=backend, alert_notifications_enabled=True)
    assert make(environment=environment, email_backend=backend).alert_notifications_enabled is False
