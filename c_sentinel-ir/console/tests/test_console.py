"""
test_console.py - the console's HTTP contract, with no containers running.

Everything here runs against the committed attack capture or against a
deliberately closed port, so the suite proves the console's own behaviour -
the routes exist, the SOC workflow round-trips through the shared alert store,
a missing gateway or graph is a plain error rather than a hang, and the
Operations screen can run nothing outside its catalogue.

Author: Colile
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from console import gateway_proxy, graph_api
from console.actions import ACTIONS
from console.main import app

#: A port nothing listens on, so a call to it fails fast.
_CLOSED = "http://127.0.0.1:9"


@pytest.fixture()
def client() -> TestClient:
    """Purpose: a client over the real ASGI app. Output: a `TestClient`."""
    return TestClient(app)


def test_ui_is_served(client: TestClient) -> None:
    """The single-page shell and its assets are served from /."""
    page = client.get("/")
    assert page.status_code == 200
    assert "Sentinel-IR Console" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/app.css").status_code == 200


def test_rule_catalogue_lists_every_rule(client: TestClient) -> None:
    """The catalogue carries each rule's documented properties."""
    rules = client.get("/console/api/soc/rules").json()
    assert {rule["name"] for rule in rules} >= {"Multiple Failed Logins", "Service Failure"}
    assert all(rule["inputEvents"] and rule["recommendedAction"] for rule in rules)


def test_events_from_capture_with_filter(client: TestClient) -> None:
    """The capture loads, facets count it, and a type filter narrows it."""
    everything = client.get("/console/api/soc/events").json()
    assert everything["total"] == sum(everything["facets"]["eventType"].values())
    failed = client.get("/console/api/soc/events", params={"eventType": "AUTH_FAILED"}).json()
    assert failed["shown"] == everything["facets"]["eventType"]["AUTH_FAILED"]
    assert {event["eventType"] for event in failed["events"]} == {"AUTH_FAILED"}


def test_detection_round_trips_through_the_alert_api(client: TestClient) -> None:
    """A detection run stores alerts the alert service's own routes serve and
    update, and a re-run replaces rather than duplicates them."""
    first = client.post("/console/api/soc/detect", json={"source": "capture"}).json()
    assert first["alertsRaised"] > 0
    listed = client.get("/api/v1/alerts").json()
    assert len(listed) == first["alertsRaised"]

    alert_id = listed[0]["alertId"]
    changed = client.patch(f"/api/v1/alerts/{alert_id}/status", json={"status": "ACKNOWLEDGED"})
    assert changed.json()["status"] == "ACKNOWLEDGED"
    cited = client.get(f"/console/api/soc/alerts/{alert_id}/events").json()
    assert {event["eventId"] for event in cited} == set(listed[0]["relatedEvents"])

    client.post("/console/api/soc/detect", json={"source": "capture"})
    assert len(client.get("/api/v1/alerts").json()) == first["alertsRaised"]


def test_gateway_down_is_a_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable gateway answers in the services' error shape."""
    monkeypatch.setattr(gateway_proxy, "GATEWAY_URL", _CLOSED)
    response = client.get("/gateway/api/v1/incidents")
    assert response.status_code == 502
    assert response.json()["error"] == "GATEWAY_UNREACHABLE"


def test_graph_down_is_a_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """With no Neo4j, every graph call is an immediate 503, not a hang."""
    monkeypatch.setattr(graph_api, "bolt_reachable", lambda: False)
    for response in (
        client.get("/console/api/graph/summary"),
        client.get("/console/api/graph/queries/users_high_severity"),
        client.post("/console/api/graph/rag/ask", json={"question": "Which users?"}),
    ):
        assert response.status_code == 503
        assert response.json()["error"] == "NEO4J_UNREACHABLE"


def test_query_parameters_are_validated(client: TestClient) -> None:
    """A query missing its parameter is a 422 before Neo4j is touched."""
    response = client.get("/console/api/graph/queries/alerts_for_service")
    assert response.status_code == 422


def test_dry_run_load_needs_no_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dry-run load counts writes from the capture without Neo4j."""
    monkeypatch.setattr(graph_api, "bolt_reachable", lambda: False)
    result = client.post("/console/api/graph/load", json={"dry_run": True}).json()
    assert result["exitCode"] == 0
    assert "Dry run: Neo4j not contacted." in result["output"]


def test_only_catalogued_actions_run(client: TestClient) -> None:
    """The Operations screen lists the catalogue and refuses anything else."""
    listed = client.get("/console/api/actions").json()
    assert [item["id"] for item in listed] == [action.id for action in ACTIONS]
    assert client.post("/console/api/actions/rm-rf").status_code == 404


def test_unit_tests_run_suite_by_suite() -> None:
    """D-13: the unit-test action runs each suite separately."""
    action = next(a for a in ACTIONS if a.id == "unit-tests")
    commands = action.commands()
    assert len(commands) > 1
    assert all(command[1:3] == ["-m", "pytest"] and len(command) > 3 for command in commands)
