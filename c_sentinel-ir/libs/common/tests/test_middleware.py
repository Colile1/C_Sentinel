"""
test_middleware.py - tests for correlation propagation and the event pair.

Runs the middleware against a real FastAPI application, because the invariant
being proved - every request carries one correlation id, and every request
produces a REQUEST_RECEIVED and REQUEST_COMPLETED pair - only holds inside the
ASGI stack.

Author: Colile
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from common.correlation import CORRELATION_ID_HEADER, get_correlation_id
from common.error_handlers import install_error_handlers
from common.errors import NotFoundError
from common.logging import EVENT_STREAM_LOGGER, configure_logging
from common.middleware import CorrelationIdMiddleware, SecurityEventMiddleware


@pytest.fixture(autouse=True)
def _reset_logging():
    """Purpose: keep handlers from leaking between tests.
    Inputs: none. Output: None."""
    yield
    logging.getLogger().handlers.clear()
    logging.getLogger(EVENT_STREAM_LOGGER).handlers.clear()


@pytest.fixture
def client() -> TestClient:
    """
    Purpose: a service-shaped application wired exactly as a real service is.
    Inputs:  none.
    Output:  a TestClient over that application.
    """
    app = FastAPI()
    # Installed outermost-last: CorrelationIdMiddleware must run first so the
    # id is bound before SecurityEventMiddleware builds any event.
    app.add_middleware(SecurityEventMiddleware, service_name="asset-service")
    app.add_middleware(CorrelationIdMiddleware)
    install_error_handlers(app)

    @app.get("/api/v1/assets")
    def list_assets() -> dict[str, object]:
        """A normal endpoint that also reports the id it can see."""
        return {"assets": [], "seenCorrelationId": get_correlation_id()}

    @app.get("/api/v1/assets/{asset_id}")
    def get_asset(asset_id: int) -> dict[str, int]:
        """An endpoint that raises a typed error."""
        raise NotFoundError(f"Asset {asset_id} does not exist", {"assetId": asset_id})

    @app.get("/boom")
    def boom() -> None:
        """An endpoint that fails in a way nothing anticipated."""
        raise RuntimeError("the disk caught fire")

    @app.get("/health")
    def health() -> dict[str, str]:
        """Platform endpoint, deliberately untracked."""
        return {"status": "healthy"}

    return TestClient(app, raise_server_exceptions=False)


def _events(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """Purpose: read back only the security events from stdout.
    Inputs: capsys. Output: the parsed event dicts."""
    output = capsys.readouterr().out.strip()
    parsed = [json.loads(line) for line in output.splitlines() if line.strip()]
    return [line for line in parsed if "eventId" in line]


class TestCorrelationPropagation:
    """The X-Correlation-ID invariant."""

    def test_a_supplied_correlation_id_is_used(self, client: TestClient) -> None:
        """The gateway stamps the id; services must honour it, not replace it."""
        response = client.get(
            "/api/v1/assets", headers={CORRELATION_ID_HEADER: "corr-fromgateway"}
        )

        assert response.json()["seenCorrelationId"] == "corr-fromgateway"

    def test_a_supplied_correlation_id_is_echoed_back(self, client: TestClient) -> None:
        """The caller must be able to quote the id when reporting a problem."""
        response = client.get(
            "/api/v1/assets", headers={CORRELATION_ID_HEADER: "corr-fromgateway"}
        )

        assert response.headers[CORRELATION_ID_HEADER] == "corr-fromgateway"

    def test_a_missing_correlation_id_is_generated(self, client: TestClient) -> None:
        """A direct call bypassing the gateway must still be traceable."""
        response = client.get("/api/v1/assets")

        generated = response.headers[CORRELATION_ID_HEADER]

        assert generated.startswith("corr-")
        assert response.json()["seenCorrelationId"] == generated

    def test_two_requests_receive_different_generated_ids(
        self, client: TestClient
    ) -> None:
        """Two workflows sharing a trace would be indistinguishable in Phase 2."""
        first = client.get("/api/v1/assets").headers[CORRELATION_ID_HEADER]
        second = client.get("/api/v1/assets").headers[CORRELATION_ID_HEADER]

        assert first != second

    def test_the_id_is_echoed_on_an_error_response(self, client: TestClient) -> None:
        """A failure is exactly when the caller most needs the trace id."""
        response = client.get("/api/v1/assets/99")

        assert response.status_code == 404
        assert response.headers[CORRELATION_ID_HEADER].startswith("corr-")


class TestRequestEventPair:
    """Every tracked request produces the documented baseline pair."""

    def test_a_request_emits_received_then_completed(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """This pair is Phase 2's request-rate signal."""
        configure_logging("asset-service")
        client.get("/api/v1/assets", headers={CORRELATION_ID_HEADER: "corr-pair00000000"})

        types = [event["eventType"] for event in _events(capsys)]

        assert types == ["REQUEST_RECEIVED", "REQUEST_COMPLETED"]

    def test_both_events_share_the_request_correlation_id(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The pair must be joinable, or the graph cannot link them."""
        configure_logging("asset-service")
        client.get("/api/v1/assets", headers={CORRELATION_ID_HEADER: "corr-pair00000000"})

        assert {event["correlationId"] for event in _events(capsys)} == {
            "corr-pair00000000"
        }

    def test_the_completed_event_carries_the_real_status(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A 404 must be visible in the event stream as a 404."""
        configure_logging("asset-service")
        client.get("/api/v1/assets/99")

        completed = [
            event for event in _events(capsys)
            if event["eventType"] == "REQUEST_COMPLETED"
        ]

        assert completed[0]["statusCode"] == 404

    def test_the_client_ip_is_recorded(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Rate-based rules group by source address."""
        configure_logging("asset-service")
        client.get("/api/v1/assets", headers={"X-Forwarded-For": "203.0.113.7, 10.0.0.1"})

        assert _events(capsys)[0]["sourceIp"] == "203.0.113.7"

    def test_platform_endpoints_emit_no_events(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Consul polls /health every few seconds; those are not user traffic."""
        configure_logging("asset-service")
        client.get("/health")

        assert _events(capsys) == []


class TestServiceErrorEvents:
    """A 5xx is a security-relevant signal, not merely a log line."""

    def test_an_unhandled_error_emits_a_service_error_event(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Phase 2 rule 4 watches for service failure."""
        configure_logging("asset-service")
        client.get("/boom")

        types = [event["eventType"] for event in _events(capsys)]

        assert "SERVICE_ERROR" in types

    def test_a_service_error_event_is_high_severity(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A crashing service must not be triaged as routine traffic."""
        configure_logging("asset-service")
        client.get("/boom")

        errors = [
            event for event in _events(capsys) if event["eventType"] == "SERVICE_ERROR"
        ]

        assert errors[0]["severity"] == "HIGH"

    def test_a_typed_404_does_not_emit_a_service_error(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A missing asset is a normal outcome, not a fault. Emitting one here
        would flood the stream and desensitise the detection rules."""
        configure_logging("asset-service")
        client.get("/api/v1/assets/99")

        types = [event["eventType"] for event in _events(capsys)]

        assert "SERVICE_ERROR" not in types


class TestErrorHandlerShape:
    """One error body shape across all three services."""

    def test_a_typed_error_renders_the_documented_body(
        self, client: TestClient
    ) -> None:
        """Routers never build this by hand, so it is identical everywhere."""
        response = client.get("/api/v1/assets/99")

        assert response.status_code == 404
        assert response.json() == {
            "error": "NOT_FOUND",
            "message": "Asset 99 does not exist",
            "details": {"assetId": 99},
        }

    def test_an_unexpected_error_leaks_no_internals(self, client: TestClient) -> None:
        """The client is told the service failed, never how."""
        response = client.get("/boom")

        assert response.status_code == 500
        assert "disk caught fire" not in response.text
        assert response.json()["error"] == "INTERNAL_ERROR"
