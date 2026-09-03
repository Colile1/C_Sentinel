"""
test_registry.py - all three services are registered in Consul and healthy.

The mark schedule asks for evidence the registry holds the running instances
with their addresses and passing checks. This asserts it.

Author: Colile
"""

from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.integration

EXPECTED_SERVICES = {"auth-service", "incident-service", "asset-service"}


def test_all_three_services_are_registered(consul_url):
    """
    Purpose: each expected service has at least one registered instance with an
             address and a port.
    Inputs:  the Consul URL fixture.
    Output:  assertions; no return.
    """
    services = httpx.get(f"{consul_url}/v1/agent/services", timeout=5).json()
    registered = {entry["Service"] for entry in services.values()}
    assert EXPECTED_SERVICES <= registered, f"missing: {EXPECTED_SERVICES - registered}"
    for entry in services.values():
        if entry["Service"] in EXPECTED_SERVICES:
            assert entry.get("Address")
            assert entry.get("Port")


def test_no_service_check_is_failing(consul_url):
    """
    Purpose: every health check Consul holds for the three services is passing.
    Inputs:  the Consul URL fixture.
    Output:  assertions; no return.
    """
    checks = httpx.get(f"{consul_url}/v1/agent/checks", timeout=5).json()
    relevant = [c for c in checks.values() if c.get("ServiceName") in EXPECTED_SERVICES]
    assert relevant, "Consul holds no checks for the three services"
    failing = [
        (c["ServiceName"], c["Status"]) for c in relevant if c["Status"] != "passing"
    ]
    assert not failing, f"failing checks: {failing}"
