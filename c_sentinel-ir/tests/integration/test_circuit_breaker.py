"""
test_circuit_breaker.py - the second pattern, demonstrated as a test.

With `asset-service` stopped, incident creation still succeeds carrying the
degraded asset summary rather than a 500, and `CIRCUIT_OPENED` appears in
incident-service's log. This file stops and starts a container, so it runs last
and restarts asset-service in a teardown that runs even on failure.

Author: Colile
"""

from __future__ import annotations

import json
import time

import pytest

# `_last` marks this module to be sorted after the others by the hook in
# conftest.py: it stops and restarts a container, so it must not run before a
# test that assumes the whole stack is up.
pytestmark = [pytest.mark.integration, pytest.mark.stack_mutating]

CREATE_ATTEMPTS = 8


@pytest.fixture
def asset_service_stopped(compose):
    """
    Purpose: stop asset-service for the duration of a test and guarantee it is
             started again afterwards, whatever happens.
    Inputs:  the compose runner.
    Output:  yields once asset-service is stopped.
    """
    assert compose("stop", "asset-service").returncode == 0, "could not stop asset-service"
    try:
        yield
    finally:
        compose("start", "asset-service")
        # Give it a moment to come back before the next test's readiness check.
        time.sleep(5)


def _incident_logs(compose) -> str:
    """Purpose: incident-service's recent log text.
    Inputs: the compose runner. Output: the log tail as one string."""
    return compose("logs", "--no-log-prefix", "--tail", "300", "incident-service").stdout


def test_creation_degrades_and_breaker_opens(
    auth_client, seeded_asset_id, asset_service_stopped, compose
):
    """
    Purpose: with the dependency down, incident creation still returns 201 with
             the documented degraded snapshot, and CIRCUIT_OPENED is logged.
    Inputs:  the authenticated client, an asset id, the stop fixture, compose.
    Output:  assertions; no return.
    """
    got_degraded_success = False
    for number in range(1, CREATE_ATTEMPTS + 1):
        response = auth_client.post(
            "/incidents",
            json={
                "title": f"Breaker test {number}",
                "description": "Created while asset-service is down.",
                "severity": "LOW",
                "reported_by": "integration-tests",
                "asset_id": seeded_asset_id,
            },
        )
        assert response.status_code == 201, (
            f"attempt {number} returned {response.status_code}, not a degraded 201: "
            f"{response.text}"
        )
        got_degraded_success = True

    assert got_degraded_success

    # The breaker should have opened within those attempts (fail_max defaults
    # to 3). Poll the log briefly - the state-change event is emitted async of
    # the response.
    deadline = time.time() + 20
    opened = False
    while time.time() < deadline:
        for raw in _incident_logs(compose).splitlines():
            if "CIRCUIT_OPENED" not in raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if event.get("eventType") == "CIRCUIT_OPENED":
                opened = True
                break
        if opened:
            break
        time.sleep(2)

    assert opened, "CIRCUIT_OPENED was not found in incident-service's log"
