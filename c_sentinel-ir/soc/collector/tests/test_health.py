"""
test_health.py - Consul's critical checks become HEALTH_CHECK_FAILED events
for this system's services, and nothing else does.

Consul is never contacted: the check objects are written out here in the shape
its `/v1/health/state/critical` endpoint returns.

Author: Colile
"""

from __future__ import annotations

from common.events import EventType, Severity
from soc.collector.health import events_from_checks


def _check(service: str, status: str = "critical", **extra) -> dict:
    """Purpose: one Consul check object. Inputs: the service, its status.
    Output: a dict shaped like Consul's API response."""
    check = {
        "CheckID": f"service:{service}",
        "Name": f"Service '{service}' check",
        "Status": status,
        "Output": "HTTP GET http://asset-service:8003/health: 503 Service Unavailable",
        "ServiceName": service,
    }
    check.update(extra)
    return check


def test_a_critical_check_becomes_one_event_named_for_its_service():
    [event] = events_from_checks([_check("asset-service")])
    assert event.event_type is EventType.HEALTH_CHECK_FAILED
    assert event.service_name == "asset-service"
    assert event.severity is Severity.HIGH
    assert event.affected_entity == "asset-service"
    assert "503 Service Unavailable" in event.message


def test_node_checks_and_foreign_services_are_skipped():
    checks = [_check(""), _check("some-other-service"), _check("auth-service")]
    assert [event.service_name for event in events_from_checks(checks)] == ["auth-service"]


def test_only_critical_checks_count():
    assert events_from_checks([_check("asset-service", status="passing")]) == []


def test_all_passing_means_no_events():
    assert events_from_checks([]) == []
