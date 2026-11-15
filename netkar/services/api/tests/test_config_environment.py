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


def test_staging_accepts_file_email_with_explicit_keks() -> None:
    settings = make(environment="staging", email_backend="file", **kek())
    assert settings.environment == "staging" and settings.trendyol_environment == "stage"


def test_staging_requires_the_kek_ring() -> None:
    with pytest.raises(ValidationError, match="ENVIRONMENT=staging iken DATA_KEKS"):
        make(environment="staging")
    with pytest.raises(ValidationError, match="birlikte verilmeli"):
        make(environment="staging", data_keks=f"k1:{KEK}")


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        ({"debug": True}, "ENVIRONMENT=staging iken DEBUG"),
        ({"email_backend": "memory"}, "EMAIL_BACKEND=memory"),
        ({"trendyol_environment": "live"}, "TRENDYOL_ENVIRONMENT=live"),
    ],
)
def test_staging_rejects_unsafe_settings(overrides: dict[str, Any], needle: str) -> None:
    with pytest.raises(ValidationError, match=needle):
        make(environment="staging", **kek(), **overrides)


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
