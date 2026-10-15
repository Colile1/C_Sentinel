"""
health.py - service health as a collected event source.

A service that has stopped answering cannot log that it is unhealthy, so its
own event stream goes quiet at exactly the moment it matters. Consul already
polls every service's `/health` endpoint (registry/consul-config.json); this
module asks Consul which checks are critical and turns each one into a
`HEALTH_CHECK_FAILED` event on the same schema as every other event, named for
the failing service, so Rule 4 can alert on it.

`events_from_checks` is pure and tested without Consul; `critical_checks` is
the one network call.

Author: Colile
"""

from __future__ import annotations

import os
from typing import Any, Iterable

import httpx

from common.events import EventType, SecurityEvent, ServiceName, Severity, build_event

DEFAULT_CONSUL_URL = "http://localhost:8500"
_CRITICAL_CHECKS_PATH = "/v1/health/state/critical"
_KNOWN_SERVICES = {member.value for member in ServiceName}


def consul_url() -> str:
    """
    Purpose: where Consul's HTTP API answers, overridable for another host.
    Inputs:  none; reads CONSUL_URL.
    Output:  the base URL.
    """
    return os.environ.get("CONSUL_URL") or DEFAULT_CONSUL_URL


def critical_checks(base_url: str | None = None, timeout: float = 5.0) -> list[dict[str, Any]]:
    """
    Purpose: every health check Consul currently reports as critical.
    Inputs:  base_url - Consul's HTTP API; timeout - seconds.
    Output:  Consul's check objects (Name, ServiceName, Status, Output, ...).
    Raises:  `httpx.HTTPError` when Consul cannot be reached.
    """
    response = httpx.get(f"{base_url or consul_url()}{_CRITICAL_CHECKS_PATH}", timeout=timeout)
    response.raise_for_status()
    return response.json()


def events_from_checks(checks: Iterable[dict[str, Any]]) -> list[SecurityEvent]:
    """
    Purpose: one `HEALTH_CHECK_FAILED` event per critical check on a service
             this system runs. Node-level checks and other services' checks
             carry no service of ours and are skipped.
    Inputs:  checks - Consul check objects.
    Output:  validated `SecurityEvent`s, HIGH severity, one per check.
    """
    events = []
    for check in checks:
        service = check.get("ServiceName") or ""
        if service not in _KNOWN_SERVICES or check.get("Status") != "critical":
            continue
        detail = " ".join(str(check.get("Output") or "no output").split())[:200]
        events.append(
            build_event(
                service_name=service,
                event_type=EventType.HEALTH_CHECK_FAILED,
                severity=Severity.HIGH,
                endpoint="/health",
                http_method="GET",
                status_code=503,
                message=f"Consul health check {check.get('Name') or check.get('CheckID')!r} "
                f"is critical for {service}: {detail}",
                correlation_id=f"health-{check.get('CheckID') or service}",
                affected_entity=service,
            )
        )
    return events


def health_events(base_url: str | None = None) -> list[SecurityEvent]:
    """
    Purpose: the health source end to end - read Consul, emit events.
    Inputs:  base_url - Consul's HTTP API, or the configured default.
    Output:  the events; empty when every check passes.
    Raises:  `httpx.HTTPError` when Consul cannot be reached.
    """
    return events_from_checks(critical_checks(base_url))
