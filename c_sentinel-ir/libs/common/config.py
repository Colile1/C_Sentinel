"""
config.py - environment-driven settings for every Sentinel-IR service.

One validated Settings object per service, built by `load_settings`. Secrets
carry no defaults: a missing JWT secret or database URL stops the service at
startup with an error naming the variable, rather than booting insecurely.

Author: Colile
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, ValidationError as PydanticValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.errors import ConfigurationError

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    """
    Purpose: the complete runtime configuration of one service, read from the
             environment and validated once at startup.
    Inputs:  environment variables, listed in `deploy/.env.example`.
    Output:  a frozen settings object. Attribute access after construction is
             guaranteed valid.
    """

    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    service_name: str = Field(description="Identity used in events, logs and Consul.")
    service_port: int = Field(default=8000, ge=1, le=65535)
    service_host: str = Field(
        default="0.0.0.0", description="Bind address inside the container."
    )
    advertise_host: str = Field(
        default="",
        description=(
            "Address other containers reach this service on. Defaults to the "
            "service name, which is the Docker Compose DNS name."
        ),
    )

    database_url: str = Field(description="This service's own database. Never another's.")

    jwt_secret: str = Field(description="HS256 signing key. No default, ever.")
    jwt_algorithm: str = Field(default="HS256")
    jwt_expiry_minutes: int = Field(default=60, ge=1)

    consul_host: str = Field(default="consul")
    consul_port: int = Field(default=8500, ge=1, le=65535)
    consul_enabled: bool = Field(
        default=True, description="Turned off in unit tests and local runs."
    )

    log_level: str = Field(default="INFO")

    asset_service_url: str = Field(
        default="",
        description="Only incident-service sets this. Read via ResilientClient only.",
    )

    # Bootstrap admin — only auth-service reads these. A fresh auth_db has no
    # accounts, and `POST /auth/users` needs an admin token, so without a seeded
    # first admin the system cannot create its first user. auth-service creates
    # this one account, once, at startup when both are set; `scripts/seed_data.py`
    # then logs in as it and creates every other account through the public API.
    # See DECISIONS.md D-23. Left blank elsewhere so no other service acts on it.
    bootstrap_admin_username: str = Field(default="")
    bootstrap_admin_password: str = Field(default="")

    # Resilience — retry and circuit breaker, read by libs/common/http_client.py.
    # Defaults are the demo-friendly values: the breaker opens after three failed
    # requests and re-tests after fifteen seconds, both short enough to show on
    # camera inside the ninety seconds docs/patterns.md budgets for the proof.
    dependency_timeout_seconds: float = Field(default=3.0, gt=0)
    retry_max_attempts: int = Field(default=3, ge=1)
    retry_backoff_seconds: float = Field(default=0.2, gt=0)
    circuit_fail_max: int = Field(default=3, ge=1)
    circuit_reset_seconds: float = Field(default=15.0, gt=0)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        """Purpose: reject a log level the logging module cannot use.
        Inputs: the configured level. Output: the level, upper-cased."""
        level = value.upper()
        if level not in _VALID_LOG_LEVELS:
            raise ValueError(
                f"must be one of {sorted(_VALID_LOG_LEVELS)}, received {value!r}"
            )
        return level

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: str) -> str:
        """Purpose: refuse a signing key short enough to brute force.
        Inputs: the secret. Output: the secret, unchanged."""
        if len(value) < 16:
            raise ValueError("must be at least 16 characters")
        return value

    @property
    def registry_address(self) -> str:
        """
        Purpose: the host other services and Consul health checks reach us on.
        Inputs:  none beyond the instance.
        Output:  `advertise_host` when set, otherwise the service name.
        """
        return self.advertise_host or self.service_name


def load_settings(service_name: str) -> Settings:
    """
    Purpose: build the settings for one service, converting any validation
             failure into a `ConfigurationError` that names the offending
             variables — the caller must not have to read a pydantic traceback.
    Inputs:  service_name - the service's identity, e.g. `auth-service`. It is
             supplied by the caller rather than the environment so a service can
             never mistake itself for another.
    Output:  a validated `Settings`.
    Raises:  `ConfigurationError` naming every missing or invalid variable.
    """
    try:
        return Settings(service_name=service_name)
    except PydanticValidationError as exc:
        problems = []
        for error in exc.errors():
            field = str(error["loc"][0]) if error["loc"] else "unknown"
            problems.append(f"{field.upper()}: {error['msg']}")
        raise ConfigurationError(
            f"Service {service_name} cannot start, its configuration is invalid: "
            + "; ".join(problems),
            {"service": service_name, "problems": problems},
        ) from exc


@lru_cache(maxsize=None)
def get_settings(service_name: str) -> Settings:
    """
    Purpose: the cached accessor services use as a FastAPI dependency, so the
             environment is read and validated exactly once per process.
    Inputs:  service_name - as `load_settings`.
    Output:  the single `Settings` instance for this service.
    """
    return load_settings(service_name)
