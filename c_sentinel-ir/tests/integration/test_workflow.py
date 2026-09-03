"""
test_workflow.py - the marked business workflow, end to end through the gateway.

Log in, list assets, raise an incident against one, read it back, escalate its
severity. Every request goes to the gateway on `localhost:8000`; no service
port is touched. This is the same sequence `client/demo_workflow.py` runs on
camera, asserted here so a regression fails a test rather than a demo.

Author: Colile
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_full_workflow_through_the_gateway(auth_client, seeded_asset_id, correlation_id):
    """
    Purpose: the whole workflow completes with the expected status at each step
             and the client's correlation id is echoed back.
    Inputs:  the authenticated client, an existing asset id, the per-test id.
    Output:  assertions; no return.
    """
    # List assets.
    listing = auth_client.get("/assets")
    assert listing.status_code == 200
    assert any(a["id"] == seeded_asset_id for a in listing.json())

    # Raise an incident against one.
    create = auth_client.post(
        "/incidents",
        json={
            "title": "Integration workflow incident",
            "description": "Raised by test_full_workflow_through_the_gateway.",
            "severity": "MEDIUM",
            "reported_by": "integration-tests",
            "asset_id": seeded_asset_id,
        },
    )
    assert create.status_code == 201, create.text
    incident = create.json()
    assert incident["asset_id"] == seeded_asset_id
    assert incident["asset_name_snapshot"]
    assert create.headers.get("X-Correlation-ID") == correlation_id

    # Read it back.
    read = auth_client.get(f"/incidents/{incident['id']}")
    assert read.status_code == 200
    assert read.json()["severity"] == "MEDIUM"

    # Escalate its severity.
    escalate = auth_client.patch(
        f"/incidents/{incident['id']}/severity", json={"severity": "HIGH"}
    )
    assert escalate.status_code == 200
    assert escalate.json()["severity"] == "HIGH"


def test_every_workflow_response_carries_a_correlation_id(auth_client, seeded_asset_id):
    """
    Purpose: every response on the path, success or not, carries the
             correlation-id header - the central invariant.
    Inputs:  the authenticated client and an asset id.
    Output:  assertions; no return.
    """
    for response in (
        auth_client.get("/assets"),
        auth_client.get(f"/assets/{seeded_asset_id}"),
        auth_client.get("/incidents"),
    ):
        assert response.headers.get("X-Correlation-ID")
