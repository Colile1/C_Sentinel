"""
test_asset_gateway.py - the one place incident-service calls asset-service.

Uses httpx's `MockTransport` rather than a real socket, so these tests need no
network and no running asset-service, while still exercising the real
`httpx.get` call path `fetch_asset` makes.

Author: Colile
"""

from __future__ import annotations

import httpx
import pytest

from common.config import Settings

from app.services.asset_gateway import fetch_asset

CORRELATION_ID = "corr-test0000001"


def _settings_with_transport() -> Settings:
    """Purpose: settings carrying a fixed asset-service URL for the tests.
    Inputs: none. Output: a Settings instance."""
    return Settings(
        service_name="incident-service",
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret="test-secret-at-least-16-chars",
        consul_enabled=False,
        asset_service_url="http://asset-service:8003",
    )


def _patch_transport(monkeypatch, handler) -> None:
    """
    Purpose: make `httpx.get` inside `fetch_asset` run against a mock
             transport instead of a real socket.
    Inputs:  monkeypatch - pytest's fixture. handler - the mock transport's
             request handler.
    Output:  None.
    """

    def _fake_get(url, *, headers, timeout):
        """Purpose: stand in for httpx.get. Inputs: url, headers, timeout.
        Output: an httpx.Response built by the mock transport."""
        with httpx.Client(transport=httpx.MockTransport(handler)) as test_client:
            return test_client.get(url, headers=headers, timeout=timeout)

    monkeypatch.setattr("app.services.asset_gateway.httpx.get", _fake_get)


def test_successful_lookup_returns_the_real_name(monkeypatch) -> None:
    """A healthy asset-service response becomes an available AssetSummary."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Purpose: the mock asset-service. Inputs: request. Output: response."""
        assert request.headers["X-Correlation-ID"] == CORRELATION_ID
        return httpx.Response(200, json={"id": 1, "name": "web-01"})

    _patch_transport(monkeypatch, handler)

    summary = fetch_asset(1, correlation_id=CORRELATION_ID, settings=_settings_with_transport())

    assert summary.name == "web-01"
    assert summary.available is True


def test_404_from_asset_service_is_raised(monkeypatch) -> None:
    """An asset that genuinely does not exist is not masked as a fallback."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Purpose: the mock asset-service. Inputs: request. Output: 404."""
        return httpx.Response(404, json={"error": "NOT_FOUND", "message": "gone", "details": {}})

    _patch_transport(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_asset(999, correlation_id=CORRELATION_ID, settings=_settings_with_transport())


def test_connection_failure_returns_the_documented_fallback(monkeypatch) -> None:
    """asset-service being unreachable degrades to a fallback, not an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Purpose: simulate a dead asset-service. Inputs: request. Output: never returns."""
        raise httpx.ConnectError("connection refused", request=request)

    _patch_transport(monkeypatch, handler)

    summary = fetch_asset(1, correlation_id=CORRELATION_ID, settings=_settings_with_transport())

    assert summary.available is False
    assert summary.name == "unknown"


def test_server_error_from_asset_service_returns_the_fallback(monkeypatch) -> None:
    """A 500 from asset-service degrades the same way a dropped connection does."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Purpose: the mock asset-service. Inputs: request. Output: 500."""
        return httpx.Response(500, json={"error": "INTERNAL_ERROR", "message": "boom", "details": {}})

    _patch_transport(monkeypatch, handler)

    summary = fetch_asset(1, correlation_id=CORRELATION_ID, settings=_settings_with_transport())

    assert summary.available is False
