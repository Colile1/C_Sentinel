"""
test_config.py - unit tests for environment-driven settings.

Proves build step 2's verification: a missing required setting raises an error
that names the field, and secrets have no usable default.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.config import Settings, load_settings
from common.errors import ConfigurationError

_COMPLETE_ENV = {
    "DATABASE_URL": "postgresql+psycopg://asset:pw@asset-db:5432/assetdb",
    "JWT_SECRET": "a-sufficiently-long-test-secret",
    "SERVICE_PORT": "8003",
}


def _apply_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    """Purpose: install exactly the given environment, clearing every setting
    the model reads. Inputs: monkeypatch, the variables to set. Output: None."""
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_loads_a_complete_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fully specified environment produces a valid Settings object."""
    _apply_env(monkeypatch, _COMPLETE_ENV)

    settings = load_settings("asset-service")

    assert settings.service_name == "asset-service"
    assert settings.service_port == 8003
    assert settings.jwt_algorithm == "HS256"
    assert settings.log_level == "INFO"


def test_missing_database_url_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The failure must tell the operator which variable to set."""
    env = dict(_COMPLETE_ENV)
    del env["DATABASE_URL"]
    _apply_env(monkeypatch, env)

    with pytest.raises(ConfigurationError) as caught:
        load_settings("asset-service")

    assert "DATABASE_URL" in caught.value.message
    assert "asset-service" in caught.value.message


def test_missing_jwt_secret_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret has no default: its absence must stop the service."""
    env = dict(_COMPLETE_ENV)
    del env["JWT_SECRET"]
    _apply_env(monkeypatch, env)

    with pytest.raises(ConfigurationError) as caught:
        load_settings("auth-service")

    assert "JWT_SECRET" in caught.value.message


def test_every_missing_variable_is_reported_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fixing configuration one error per restart is a waste of the operator."""
    _apply_env(monkeypatch, {})

    with pytest.raises(ConfigurationError) as caught:
        load_settings("incident-service")

    assert "DATABASE_URL" in caught.value.message
    assert "JWT_SECRET" in caught.value.message
    assert len(caught.value.details["problems"]) == 2


def test_short_jwt_secret_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key short enough to brute force is a configuration error, not a warning."""
    _apply_env(monkeypatch, {**_COMPLETE_ENV, "JWT_SECRET": "short"})

    with pytest.raises(ConfigurationError) as caught:
        load_settings("auth-service")

    assert "JWT_SECRET" in caught.value.message
    assert "16 characters" in caught.value.message


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unusable log level must fail loudly at startup, not silently default."""
    _apply_env(monkeypatch, {**_COMPLETE_ENV, "LOG_LEVEL": "CHATTY"})

    with pytest.raises(ConfigurationError) as caught:
        load_settings("asset-service")

    assert "LOG_LEVEL" in caught.value.message


def test_log_level_is_normalised_to_upper_case(monkeypatch: pytest.MonkeyPatch) -> None:
    """Operators write `debug`; the logging module needs `DEBUG`."""
    _apply_env(monkeypatch, {**_COMPLETE_ENV, "LOG_LEVEL": "debug"})

    assert load_settings("asset-service").log_level == "DEBUG"


def test_registry_address_defaults_to_the_service_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In Compose the service name is the DNS name, so it is the right default."""
    _apply_env(monkeypatch, _COMPLETE_ENV)
    assert load_settings("asset-service").registry_address == "asset-service"


def test_advertise_host_overrides_the_registry_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A host running outside Compose must be able to say where it really is."""
    _apply_env(monkeypatch, {**_COMPLETE_ENV, "ADVERTISE_HOST": "10.0.0.7"})
    assert load_settings("asset-service").registry_address == "10.0.0.7"


def test_settings_are_immutable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration must not drift at runtime."""
    _apply_env(monkeypatch, _COMPLETE_ENV)
    settings = load_settings("asset-service")

    with pytest.raises(Exception):
        settings.jwt_secret = "replaced-at-runtime-secret"
