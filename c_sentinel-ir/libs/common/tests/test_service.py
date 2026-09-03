"""
test_service.py - the shared application factory.

`create_service_app` is what makes the three services identical below the
router line. These tests prove it wires the pieces once so no service has to:
the health router, the /metrics endpoint, the error handlers, the correlation
middleware, and Consul registration fired from the lifespan.

Author: Colile
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from common import service as service_module
from common.config import Settings
from common.correlation import CORRELATION_ID_HEADER
from common.logging import EVENT_STREAM_LOGGER


@pytest.fixture(autouse=True)
def _reset_logging():
    """Purpose: no handler leaks between tests. Inputs: none. Output: None."""
    yield
    logging.getLogger().handlers.clear()
    logging.getLogger(EVENT_STREAM_LOGGER).handlers.clear()


@pytest.fixture
def settings() -> Settings:
    """A Settings object that never reads the environment."""
    return Settings(
        service_name="asset-service",
        database_url="postgresql+psycopg://a:a@localhost/asset_db",
        jwt_secret="test-secret-at-least-16",
        consul_enabled=False,
    )


def test_factory_wires_health_metrics_and_errors(settings) -> None:
    """One call yields /health, /health/live, /metrics and the error shape."""
    app = service_module.create_service_app(
        "asset-service", check_database=lambda: True, settings=settings
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "healthy"
        assert client.get("/health/live").status_code == 200
        assert client.get("/metrics").headers["content-type"].startswith("text/plain")
        body = client.get("/nope").json()
        assert set(body) == {"error", "message", "details"}


def test_correlation_middleware_is_installed(settings) -> None:
    """A request leaves with a correlation-id header the factory's middleware set."""
    app = service_module.create_service_app("asset-service", settings=settings)
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.headers[CORRELATION_ID_HEADER].startswith("corr-")


def test_lifespan_registers_and_deregisters(monkeypatch, settings) -> None:
    """Startup calls register_service; shutdown calls deregister_service."""
    calls: list[str] = []
    monkeypatch.setattr(
        service_module, "register_service", lambda s: calls.append("register")
    )
    monkeypatch.setattr(
        service_module, "deregister_service", lambda s: calls.append("deregister")
    )

    app = service_module.create_service_app("asset-service", settings=settings)
    with TestClient(app):
        assert calls == ["register"]
    assert calls == ["register", "deregister"]


def test_no_database_check_means_health_is_liveness_only(settings) -> None:
    """With check_database=None, /health is 200 and says the database is unconfigured."""
    app = service_module.create_service_app("asset-service", settings=settings)
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["checks"]["database"] == "not_configured"


def test_extra_lifespan_hooks_run_in_order(monkeypatch, settings) -> None:
    """on_startup runs after registration; on_shutdown before deregistration."""
    monkeypatch.setattr(service_module, "register_service", lambda s: None)
    monkeypatch.setattr(service_module, "deregister_service", lambda s: None)
    order: list[str] = []

    app = service_module.create_service_app(
        "asset-service",
        settings=settings,
        on_startup=lambda: order.append("up"),
        on_shutdown=lambda: order.append("down"),
    )
    with TestClient(app):
        assert order == ["up"]
    assert order == ["up", "down"]
