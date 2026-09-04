"""
test_router.py - the three alert endpoints over the real ASGI stack.

`test_store.py` proves the store logic; this proves the HTTP contract it is
published under - the endpoints exist, they serve the specification's eleven
keys, a missing alert really does arrive as a 404 through
`install_error_handlers`, and an unknown status value is a 422.

The store is seeded through a dependency override rather than by running the
rules, so a router test stays a router test.

Author: Colile
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from common.events import Severity
from soc.alert_service.dependencies import get_alert_store
from soc.alert_service.main import app
from soc.alert_service.models import Alert, AlertStatus
from soc.alert_service.store import AlertStore

_SCHEMA_KEYS = {
    "alertId",
    "timestamp",
    "ruleName",
    "severity",
    "status",
    "description",
    "relatedEvents",
    "affectedService",
    "affectedUser",
    "affectedEntity",
    "recommendedAction",
}


def _alert(**overrides) -> Alert:
    """Purpose: a valid alert with any field overridden. Inputs: overrides.
    Output: an `Alert`."""
    defaults = dict(
        timestamp="2026-09-04T12:00:00Z",
        rule_name="Multiple Failed Logins",
        severity=Severity.HIGH,
        description="Five failed logins for one account in five minutes.",
        related_events=("evt-000000000001",),
        affected_service="auth-service",
        affected_user="analyst-1",
        affected_entity="login-endpoint",
        recommended_action="Block the source IP.",
    )
    defaults.update(overrides)
    return Alert(**defaults)


@pytest.fixture
def seeded_store() -> AlertStore:
    """
    Purpose: an `AlertStore` wired in as the API's store for one test, holding a
             known HIGH auth-service alert and a LOW asset-service one.
    Inputs:  none.
    Output:  the store; the override is removed on teardown.
    """
    store = AlertStore()
    store.add(_alert())
    store.add(
        _alert(
            severity=Severity.LOW,
            affected_service="asset-service",
            rule_name="Service Failure",
        )
    )
    app.dependency_overrides[get_alert_store] = lambda: store
    yield store
    app.dependency_overrides.clear()


@pytest.fixture
def client(seeded_store: AlertStore) -> TestClient:
    """Purpose: a test client over the app with the seeded store. Inputs: the
    fixture. Output: a `TestClient`."""
    return TestClient(app)


def test_list_returns_every_alert_in_the_schema(client: TestClient) -> None:
    """Every listed alert carries exactly the eleven specification keys."""
    response = client.get("/api/v1/alerts")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert set(body[0]) == _SCHEMA_KEYS


def test_list_filters_by_severity_and_affected_service(client: TestClient) -> None:
    """The query parameters narrow the listing the way the store does."""
    high = client.get("/api/v1/alerts", params={"severity": "HIGH"}).json()
    assert len(high) == 1
    assert high[0]["affectedService"] == "auth-service"

    asset = client.get(
        "/api/v1/alerts", params={"affectedService": "asset-service"}
    ).json()
    assert len(asset) == 1
    assert asset[0]["ruleName"] == "Service Failure"


def test_get_one_alert_by_id(client: TestClient, seeded_store: AlertStore) -> None:
    """An alert is fetchable by its `alt-` id."""
    known = seeded_store.list()[0]

    response = client.get(f"/api/v1/alerts/{known.alert_id}")

    assert response.status_code == 200
    assert response.json()["alertId"] == known.alert_id


def test_get_a_missing_alert_is_404(client: TestClient) -> None:
    """A missing alert arrives as a typed 404, not a 500."""
    response = client.get("/api/v1/alerts/alt-deadbeef0000")

    assert response.status_code == 404
    assert response.json()["error"] == "NOT_FOUND"


def test_patch_status_moves_the_alert_and_returns_it(
    client: TestClient, seeded_store: AlertStore
) -> None:
    """A status change is reflected in the response and on the next read."""
    known = seeded_store.list()[0]

    response = client.patch(
        f"/api/v1/alerts/{known.alert_id}/status", json={"status": "ACKNOWLEDGED"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ACKNOWLEDGED"
    assert seeded_store.get(known.alert_id).status is AlertStatus.ACKNOWLEDGED


def test_patch_status_rejects_an_unknown_value(
    client: TestClient, seeded_store: AlertStore
) -> None:
    """A status outside the three is a 422 from FastAPI's own validation."""
    known = seeded_store.list()[0]

    response = client.patch(
        f"/api/v1/alerts/{known.alert_id}/status", json={"status": "PENDING"}
    )

    assert response.status_code == 422


def test_patch_status_on_a_missing_alert_is_404(client: TestClient) -> None:
    """Re-statusing a missing alert is the same typed 404 a read gives."""
    response = client.patch(
        "/api/v1/alerts/alt-000000000000/status", json={"status": "CLOSED"}
    )

    assert response.status_code == 404
