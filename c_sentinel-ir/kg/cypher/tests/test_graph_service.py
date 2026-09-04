"""
test_graph_service.py - the graph API's contract, without Neo4j.

`run_query` is patched, so these prove the HTTP surface: the query catalogue
endpoint lists all five, each query endpoint passes the right parameter through,
and a missing required parameter is a 422 through `install_error_handlers`
rather than an empty query against the graph.

The live behaviour - the five actually returning non-empty rows - is
`test_live_queries.py`, marked `neo4j`.

Author: Colile
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import kg.cypher.graph_service as graph_service
from kg.cypher.graph_service import app


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    """
    Purpose: replace `run_query` with a recorder, so a test sees the Cypher and
             parameters the endpoint would have run.
    Inputs:  monkeypatch.
    Output:  a list the recorder appends `{cypher, params}` to.
    """
    calls: list[dict] = []

    def _fake(cypher: str, **params):
        calls.append({"cypher": cypher, "params": params})
        return [{"ok": True}]

    monkeypatch.setattr(graph_service, "run_query", _fake)
    return calls


@pytest.fixture
def client() -> TestClient:
    """Purpose: a client over the graph API. Inputs: none. Output: TestClient."""
    return TestClient(app)


def test_the_catalogue_endpoint_lists_all_five(client: TestClient) -> None:
    """`GET /api/v1/graph/queries` returns the five keys and their parameters."""
    body = client.get("/api/v1/graph/queries").json()
    assert {q["key"] for q in body} == {
        "alerts_for_service",
        "users_high_severity",
        "threats_for_service",
        "controls_for_alert",
        "dependency_impact",
    }
    params = {q["key"]: q["parameters"] for q in body}
    assert params["users_high_severity"] == []
    assert params["alerts_for_service"] == ["service"]


def test_alerts_endpoint_passes_the_service_parameter(
    client: TestClient, captured: list[dict]
) -> None:
    """q1 forwards `?service=` to the query as `$service`."""
    response = client.get("/api/v1/graph/alerts", params={"service": "auth-service"})
    assert response.status_code == 200
    assert captured[-1]["params"] == {"service": "auth-service"}


def test_alert_controls_endpoint_uses_the_alertId_alias(
    client: TestClient, captured: list[dict]
) -> None:
    """q4's query parameter is `alertId`, not `alert_id`."""
    response = client.get(
        "/api/v1/graph/alert-controls", params={"alertId": "alt-000000000000"}
    )
    assert response.status_code == 200
    assert captured[-1]["params"] == {"alertId": "alt-000000000000"}


def test_a_blank_required_parameter_is_422(
    client: TestClient, captured: list[dict]
) -> None:
    """An empty `service` is refused before any query runs."""
    response = client.get("/api/v1/graph/threats", params={"service": "   "})
    assert response.status_code == 422
    assert response.json()["error"] == "VALIDATION_ERROR"
    assert captured == []


def test_a_missing_required_parameter_is_422(client: TestClient) -> None:
    """No `service` at all is FastAPI's own 422."""
    assert client.get("/api/v1/graph/dependency-impact").status_code == 422


def test_the_parameterless_query_needs_no_arguments(
    client: TestClient, captured: list[dict]
) -> None:
    """q2 runs with an empty parameter set."""
    response = client.get("/api/v1/graph/users-high-severity")
    assert response.status_code == 200
    assert captured[-1]["params"] == {}
