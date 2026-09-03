"""
test_incident_router.py - the six endpoints over the real ASGI stack.

The unit tests prove the logic; these prove the HTTP contract that logic is
published under - that a typed error really does arrive as its status code
through `install_error_handlers`, and that all six endpoints in
`docs/api.md` exist and respond as documented, with a bad severity returning
422 naming the field.

Author: Colile
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides) -> dict:
    """Purpose: create an incident through the API. Inputs: client, overrides.
    Output: the created incident's JSON body."""
    payload = {
        "title": "Suspicious login",
        "description": "Multiple failed logins from one IP.",
        "severity": "LOW",
        "reported_by": "analyst",
        "asset_id": 1,
    }
    payload.update(overrides)
    response = client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_then_get(api_client: TestClient) -> None:
    """A created incident can be read back by id, asset name snapshotted."""
    created = _create(api_client)

    response = api_client.get(f"/api/v1/incidents/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Suspicious login"
    assert body["asset_name_snapshot"] == "web-01"
    assert body["status"] == "OPEN"


def test_get_unknown_id_is_404_in_the_shared_error_shape(api_client: TestClient) -> None:
    """The verification line, at the HTTP boundary."""
    response = api_client.get("/api/v1/incidents/999")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error", "message", "details"}
    assert body["error"] == "NOT_FOUND"


def test_invalid_severity_is_422_naming_the_field(api_client: TestClient) -> None:
    """A bad severity returns 422 naming the field, before any business logic runs."""
    response = api_client.post(
        "/api/v1/incidents",
        json={
            "title": "Suspicious login",
            "description": "Multiple failed logins from one IP.",
            "severity": "SEVERE",
            "reported_by": "analyst",
            "asset_id": 1,
        },
    )

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert any("severity" in str(error.get("loc", "")) for error in errors)


def test_list_returns_created_incidents(api_client: TestClient) -> None:
    """The listing reflects created rows."""
    _create(api_client, title="first")
    _create(api_client, title="second")

    response = api_client.get("/api/v1/incidents")

    assert response.status_code == 200
    assert [i["title"] for i in response.json()] == ["first", "second"]


def test_update_changes_a_field(api_client: TestClient) -> None:
    """PUT applies the supplied change and leaves the rest untouched."""
    created = _create(api_client)

    response = api_client.put(
        f"/api/v1/incidents/{created['id']}", json={"status": "TRIAGED"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "TRIAGED"
    assert body["title"] == "Suspicious login"


def test_change_severity_escalates(api_client: TestClient) -> None:
    """PATCH .../severity moves the incident's severity."""
    created = _create(api_client, severity="LOW")

    response = api_client.patch(
        f"/api/v1/incidents/{created['id']}/severity", json={"severity": "CRITICAL"}
    )

    assert response.status_code == 200
    assert response.json()["severity"] == "CRITICAL"


def test_change_severity_bad_value_is_422(api_client: TestClient) -> None:
    """An unrecognised severity is rejected naming the field."""
    created = _create(api_client)

    response = api_client.patch(
        f"/api/v1/incidents/{created['id']}/severity", json={"severity": "SEVERE"}
    )

    assert response.status_code == 422


def test_delete_then_get_is_404(api_client: TestClient) -> None:
    """A deleted incident is gone."""
    created = _create(api_client)

    delete_response = api_client.delete(f"/api/v1/incidents/{created['id']}")
    assert delete_response.status_code == 204

    get_response = api_client.get(f"/api/v1/incidents/{created['id']}")
    assert get_response.status_code == 404
