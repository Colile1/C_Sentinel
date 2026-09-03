"""
test_skeleton.py - the shared application shell, on incident-service.

Proves the shared skeleton is wired: /health reports database reachability and
switches to 503 when the database is down, /health/live stays up regardless,
/metrics returns Prometheus exposition, the correlation-id middleware echoes
the header, and unknown routes come back in the one error shape. Mirrors
auth-service's and asset-service's equivalent test, run here because
incident-service builds the shell for the first time at this step.

Author: Colile
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from common.correlation import CORRELATION_ID_HEADER


def test_health_ok_when_database_reachable(client: TestClient) -> None:
    """A reachable database gives 200 and names the service."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["service"] == "incident-service"
    assert body["checks"]["database"] == "ok"


def test_health_503_when_database_unreachable(make_app) -> None:
    """A configured but unreachable database makes the instance unhealthy."""
    with TestClient(make_app(False)) as client:
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unreachable"


def test_health_live_ignores_the_database(make_app) -> None:
    """Liveness must not flap when the database is down."""
    with TestClient(make_app(False)) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive", "service": "incident-service"}


def test_metrics_returns_prometheus_text(client: TestClient) -> None:
    """/metrics is Prometheus exposition, not JSON."""
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP" in response.text


def test_correlation_id_is_echoed(client: TestClient) -> None:
    """The middleware echoes a supplied correlation id back on the response."""
    supplied = "corr-abc123def456"
    response = client.get("/health", headers={CORRELATION_ID_HEADER: supplied})
    assert response.headers[CORRELATION_ID_HEADER] == supplied


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    """A request without the header still leaves with one."""
    response = client.get("/health")
    assert response.headers[CORRELATION_ID_HEADER].startswith("corr-")


def test_unknown_route_uses_the_shared_error_shape(client: TestClient) -> None:
    """A 404 comes back as {"error", "message", "details"}, not FastAPI's default."""
    response = client.get("/api/v1/incidents/does-not-exist-yet")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error", "message", "details"}
