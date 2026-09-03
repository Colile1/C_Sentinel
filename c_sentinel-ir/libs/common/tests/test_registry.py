"""
test_registry.py - Consul self-registration, without a Consul.

The registry client is faked. What matters is the behaviour the registry/README
promises: registration is skipped cleanly when disabled, a Consul outage at
startup is swallowed with a warning rather than crashing the service, and a
successful registration carries a health check pointing at the service's own
/health with its advertised address.

Author: Colile
"""

from __future__ import annotations

import pytest

from common import registry
from common.config import Settings


def _settings(**overrides) -> Settings:
    """Purpose: a Settings object for one test.
    Inputs: field overrides. Output: Settings."""
    base = dict(
        service_name="asset-service",
        database_url="postgresql+psycopg://a:a@localhost/asset_db",
        jwt_secret="test-secret-at-least-16",
        consul_enabled=True,
        advertise_host="asset-service",
        service_port=8003,
    )
    base.update(overrides)
    return Settings(**base)


class _FakeAgentService:
    """Records what register/deregister were called with."""

    def __init__(self) -> None:
        self.registered: dict | None = None
        self.deregistered: str | None = None

    def register(self, **kwargs) -> None:
        self.registered = kwargs

    def deregister(self, service_id) -> None:
        self.deregistered = service_id


class _FakeConsul:
    def __init__(self, *args, **kwargs) -> None:
        self.agent = type("Agent", (), {"service": _FakeAgentService()})()


def test_registration_skipped_when_disabled(monkeypatch, caplog) -> None:
    """CONSUL_ENABLED=false means no client is even constructed."""
    called = False

    def _boom(_):
        nonlocal called
        called = True
        raise AssertionError("must not build a client when disabled")

    monkeypatch.setattr(registry, "_client", _boom)
    registry.register_service(_settings(consul_enabled=False))
    assert called is False


def test_successful_registration_carries_a_health_check(monkeypatch) -> None:
    """A registration names the service, its address:port and an HTTP /health check."""
    fake = _FakeConsul()
    monkeypatch.setattr(registry, "_client", lambda _: fake)

    registry.register_service(_settings())

    sent = fake.agent.service.registered
    assert sent["name"] == "asset-service"
    assert sent["address"] == "asset-service"
    assert sent["port"] == 8003
    assert sent["service_id"] == "asset-service-asset-service-8003"
    assert sent["check"]["http"] == "http://asset-service:8003/health"


def test_consul_outage_is_swallowed(monkeypatch, caplog) -> None:
    """An unreachable Consul logs a warning and does not raise."""

    def _raises(_):
        raise ConnectionError("no route to consul")

    monkeypatch.setattr(registry, "_client", _raises)
    registry.register_service(_settings())  # must not raise
    assert any("registration failed" in r.message.lower() for r in caplog.records)


def test_deregister_uses_the_same_instance_id(monkeypatch) -> None:
    """Shutdown deregisters exactly the id that was registered."""
    fake = _FakeConsul()
    monkeypatch.setattr(registry, "_client", lambda _: fake)
    settings = _settings()

    registry.register_service(settings)
    registry.deregister_service(settings)

    assert (
        fake.agent.service.deregistered
        == fake.agent.service.registered["service_id"]
    )
