"""
test_asset_router.py - the five endpoints over the real ASGI stack.

The unit tests prove the logic; these prove the HTTP contract that logic is
published under - that a typed error really does arrive as its status code
through `install_error_handlers`, and that the five endpoints exist and
respond as documented in `docs/api.md`.

Author: Colile
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _create(client: TestClient, name: str = "web-01", **overrides) -> dict:
    """Purpose: create an asset through the API. Inputs: client, name,
    overrides. Output: the created asset's JSON body."""
    payload = {
        "name": name,
        "asset_type": "server",
        "criticality": "LOW",
        "owner": "platform-team",
        "location": "eu-west-1",
    }
    payload.update(overrides)
    response = client.post("/api/v1/assets", json=payload)
    assert response.status_code == 201
    return response.json()


def test_create_then_get(api_client: TestClient) -> None:
    """A created asset can be read back by id."""
    created = _create(api_client)

    response = api_client.get(f"/api/v1/assets/{created['id']}")

    assert response.status_code == 200
    assert response.json()["name"] == "web-01"


def test_get_unknown_id_is_404_in_the_shared_error_shape(api_client: TestClient) -> None:
    """The verification line, at the HTTP boundary."""
    response = api_client.get("/api/v1/assets/999")

    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error", "message", "details"}
    assert body["error"] == "NOT_FOUND"


def test_duplicate_name_is_409(api_client: TestClient) -> None:
    """Registering the same name twice is a conflict."""
    _create(api_client, name="web-01")

    response = api_client.post(
        "/api/v1/assets",
        json={
            "name": "web-01",
            "asset_type": "server",
            "criticality": "LOW",
            "owner": "platform-team",
            "location": "eu-west-1",
        },
    )

    assert response.status_code == 409


def test_invalid_criticality_is_422(api_client: TestClient) -> None:
    """A criticality outside the four values is rejected before it reaches the service."""
    response = api_client.post(
        "/api/v1/assets",
        json={
            "name": "web-01",
            "asset_type": "server",
            "criticality": "SEVERE",
            "owner": "platform-team",
            "location": "eu-west-1",
        },
    )

    assert response.status_code == 422


def test_list_returns_created_assets(api_client: TestClient) -> None:
    """The listing reflects created rows."""
    _create(api_client, name="web-01")
    _create(api_client, name="app-01", asset_type="application")

    response = api_client.get("/api/v1/assets")

    assert response.status_code == 200
    assert [a["name"] for a in response.json()] == ["web-01", "app-01"]


def test_update_changes_a_field(api_client: TestClient) -> None:
    """PUT applies the supplied change and leaves the rest untouched."""
    created = _create(api_client)

    response = api_client.put(
        f"/api/v1/assets/{created['id']}", json={"owner": "sre-team"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["owner"] == "sre-team"
    assert body["name"] == "web-01"


def test_delete_then_get_is_404(api_client: TestClient) -> None:
    """A deleted asset is gone."""
    created = _create(api_client)

    delete_response = api_client.delete(f"/api/v1/assets/{created['id']}")
    assert delete_response.status_code == 204

    get_response = api_client.get(f"/api/v1/assets/{created['id']}")
    assert get_response.status_code == 404
