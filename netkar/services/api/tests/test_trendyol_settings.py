"""Trendyol ayarları, istemci fabrikası ve model kimlik dönüşümleri."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.integrations.trendyol.models import ShipmentPackage
from app.services.marketplace_accounts import default_client_factory
from tests.conftest import TEST_KEY
from tests.trendyol_helpers import credentials


def _settings(**overrides: object) -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://x:y@localhost/z",
        data_encryption_key=TEST_KEY,  # type: ignore[arg-type]
        email_backend="memory",
        **overrides,  # type: ignore[arg-type]
    )


def test_settings_default_to_stage_and_product_codename() -> None:
    settings = _settings()
    assert settings.trendyol_environment == "stage"
    assert settings.trendyol_integrator_name == "NetKar"


@pytest.mark.parametrize("name", ["Net Kar", "NetKâr", "a" * 31, ""])
def test_settings_reject_invalid_integrator_name(name: str) -> None:
    with pytest.raises(ValidationError):
        _settings(trendyol_integrator_name=name)


def test_settings_read_trendyol_variables_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRENDYOL_ENVIRONMENT", "live")
    monkeypatch.setenv("TRENDYOL_INTEGRATOR_NAME", "Ornek1")
    settings = _settings()
    assert settings.trendyol_environment == "live" and settings.trendyol_integrator_name == "Ornek1"
    monkeypatch.setenv("TRENDYOL_INTEGRATOR_NAME", "Geçersiz Ad")
    with pytest.raises(ValidationError):
        _settings()


def test_default_factory_builds_client_from_settings() -> None:
    settings = _settings(
        trendyol_environment="live", trendyol_integrator_name="Ornek1", trendyol_max_retries=3
    )
    factory = default_client_factory(settings)
    client = factory(credentials())
    assert client.user_agent == "2738 - Ornek1"
    assert client._http.base_url.host == "apigw.trendyol.com"
    assert client._config.max_retries == 3
    # İstek içi doğrulama için daha az yeniden deneme istenebilir, ama ayarı aşamaz
    assert factory(credentials(), max_retries=1)._config.max_retries == 1
    assert factory(credentials(), max_retries=9)._config.max_retries == 3
    # Hız sınırı kovaları fabrikadan çıkan istemciler arasında paylaşılır
    assert client._limiter is factory(credentials())._limiter


def test_numeric_ids_are_coerced_but_booleans_are_not() -> None:
    package = ShipmentPackage.model_validate(
        {"shipmentPackageId": 1, "orderNumber": "1", "cargoTrackingNumber": 7280027504111111}
    )
    assert package.cargo_tracking_number == "7280027504111111"
    with pytest.raises(ValidationError):
        ShipmentPackage.model_validate(
            {"shipmentPackageId": 1, "orderNumber": "1", "cargoTrackingNumber": True}
        )
    # Eski OpenAPI şemasındaki "id" adı da paket kimliği olarak kabul edilir
    assert ShipmentPackage.model_validate({"id": 5, "orderNumber": "1"}).shipment_package_id == 5
