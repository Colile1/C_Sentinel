"""
conftest.py - the scripted attacks and the normal workflow the rules are tested
against.

Every rule is tested in both directions, which is the build order's verification
for step 15: it fires on its attack, and it stays silent on a clean
`demo_workflow` run. A rule that never sleeps is as useless as one that never
fires, so `normal_workflow_store` is built once here and every rule's silence is
asserted against the same traffic.

The events are constructed through `build_event` and then re-stamped, because the
library generates the timestamp itself. That is deliberate in `common.events` -
no caller may supply a timestamp - so a test that needs a controlled clock copies
the model instead of bypassing the builder.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common.events import EventType, SecurityEvent, Severity, build_event
from soc.collector.store import EventStore

#: The instant every scripted scenario is written around.
NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


def event_at(when: datetime, **overrides) -> SecurityEvent:
    """
    Purpose: a `SecurityEvent` stamped at a chosen moment.
    Inputs:  when - the UTC time to stamp; overrides - any field values, over
             a benign `REQUEST_COMPLETED` default.
    Output:  a validated `SecurityEvent`.
    """
    defaults = dict(
        service_name="incident-service",
        event_type=EventType.REQUEST_COMPLETED,
        severity=Severity.LOW,
        endpoint="/api/v1/incidents",
        http_method="GET",
        status_code=200,
        message="Request completed.",
        correlation_id="corr-normal",
        source_ip="10.0.0.5",
        user_id="analyst-1",
    )
    defaults.update(overrides)
    return build_event(**defaults).model_copy(
        update={"timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )


def store_of(events: list[SecurityEvent]) -> EventStore:
    """
    Purpose: an `EventStore` holding exactly these events.
    Inputs:  events - the events to load.
    Output:  a populated `EventStore`.
    """
    store = EventStore()
    store.extend(events)
    return store


def _normal_workflow_events() -> list[SecurityEvent]:
    """
    Purpose: the events one clean `client/demo_workflow.py` run produces - login,
             list assets, create an incident, read it back, escalate it - plus a
             second analyst working normally and one isolated mistyped password.
    Inputs:  none.
    Output:  a list of `SecurityEvent` spread over a few minutes.
    """
    events = [
        event_at(
            NOW - timedelta(minutes=4),
            service_name="auth-service",
            event_type=EventType.AUTH_SUCCESS,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            correlation_id="corr-demo",
            message="Authentication succeeded.",
        ),
        event_at(
            NOW - timedelta(minutes=3, seconds=50),
            service_name="asset-service",
            endpoint="/api/v1/assets",
            correlation_id="corr-demo",
        ),
        event_at(
            NOW - timedelta(minutes=3, seconds=40),
            event_type=EventType.INCIDENT_CREATED,
            severity=Severity.MEDIUM,
            http_method="POST",
            status_code=201,
            correlation_id="corr-demo",
            affected_entity="incident-1",
            message="Incident created.",
        ),
        event_at(
            NOW - timedelta(minutes=3, seconds=30),
            endpoint="/api/v1/incidents/1",
            correlation_id="corr-demo",
        ),
        event_at(
            NOW - timedelta(minutes=3, seconds=20),
            event_type=EventType.INCIDENT_ESCALATED,
            severity=Severity.HIGH,
            endpoint="/api/v1/incidents/1/severity",
            http_method="PATCH",
            correlation_id="corr-demo",
            affected_entity="incident-1",
            message="Incident escalated to HIGH.",
        ),
        event_at(
            NOW - timedelta(minutes=3),
            service_name="asset-service",
            event_type=EventType.ASSET_ACCESSED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/assets/2",
            correlation_id="corr-demo",
            affected_entity="asset-2",
            message="Critical asset read.",
        ),
        # One analyst mistypes a password once. A single failure is not an attack.
        event_at(
            NOW - timedelta(minutes=2),
            service_name="auth-service",
            event_type=EventType.AUTH_FAILED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            status_code=401,
            user_id="analyst-2",
            source_ip="10.0.0.6",
            correlation_id="corr-typo",
            message="Authentication failed.",
        ),
        # One expired token bounces off the gateway. Also not an attack.
        event_at(
            NOW - timedelta(minutes=1),
            service_name="api-gateway",
            event_type=EventType.UNAUTHORISED_ACCESS,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/incidents",
            status_code=401,
            user_id=None,
            source_ip="10.0.0.6",
            correlation_id="corr-expired",
            message="Request rejected: no valid token.",
        ),
    ]
    # A second analyst working steadily: well under every volume threshold.
    events.extend(
        event_at(
            NOW - timedelta(seconds=50 - index * 5),
            event_type=EventType.REQUEST_RECEIVED,
            user_id="analyst-2",
            source_ip="10.0.0.6",
            correlation_id=f"corr-work-{index}",
            message="Request received.",
        )
        for index in range(8)
    )
    return events


@pytest.fixture
def normal_workflow_store() -> EventStore:
    """
    Purpose: the store every rule's silence test runs against - a clean workflow
             run with ordinary background traffic and no attack in it.
    Inputs:  none.
    Output:  a populated `EventStore`.
    """
    return store_of(_normal_workflow_events())


@pytest.fixture
def now() -> datetime:
    """
    Purpose: the fixed evaluation moment, so no test depends on the wall clock.
    Inputs:  none.
    Output:  a timezone-aware UTC datetime.
    """
    return NOW
