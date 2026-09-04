"""
test_correlation.py - one correlation id, three services' logs.

The central invariant: a request that crosses the system carries one
`X-Correlation-ID`, and it can be found in every service that handled it. This
runs a workflow with a known id and greps the container logs for it.

Author: Colile
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.integration

SERVICES = ("auth-service", "incident-service", "asset-service")


def _log_lines_with(compose, correlation_id: str) -> list[dict]:
    """
    Purpose: the JSON log objects carrying this id, across the three services.
    Inputs:  the compose runner and the id.
    Output:  a list of parsed log objects; non-JSON lines are skipped.
    """
    result = compose("logs", "--no-log-prefix", *SERVICES)
    lines = []
    for raw in result.stdout.splitlines():
        if correlation_id not in raw:
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return lines


def test_one_correlation_id_appears_in_all_three_service_logs(
    auth_client, seeded_asset_id, correlation_id, compose
):
    """
    Purpose: after a workflow driven with one client-supplied correlation id,
             that id is present in auth-service, incident-service and
             asset-service logs.
    Inputs:  the authenticated client (already sending `correlation_id`), an
             asset id, the id itself, and the compose runner.
    Output:  assertions; no return.
    """
    # auth-service already logged the id at login (auth_client's token fixture).
    # Drive incident-service, which calls asset-service, with the same id.
    created = auth_client.post(
        "/incidents",
        json={
            "title": "Correlation check",
            "description": "Driven by test_one_correlation_id_appears_in_all_three.",
            "severity": "LOW",
            "reported_by": "integration-tests",
            "asset_id": seeded_asset_id,
        },
    )
    assert created.status_code == 201, created.text

    entries = _log_lines_with(compose, correlation_id)
    # The JSON log formatter emits `serviceName` (libs/common/logging.py), not
    # `service`. Reading the wrong key makes every entry look unattributed, so
    # all three services report as missing even when the id is in every log.
    services_seen = {entry.get("serviceName") for entry in entries}
    missing = [s for s in SERVICES if s not in services_seen]
    assert not missing, (
        f"correlation id {correlation_id} missing from: {missing}; "
        f"saw {sorted(s for s in services_seen if s)}"
    )
