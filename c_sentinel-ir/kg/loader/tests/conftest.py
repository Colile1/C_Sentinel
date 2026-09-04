"""
conftest.py - a small event and alert store for the loader tests.

The loaders are pure functions of their sources, so these tests never touch
Neo4j: they build a handful of events, run the real detection rules to raise
real alerts, and assert the `Write` lists that come out.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common.events import EventType, Severity, build_event
from soc.alert_service.store import AlertStore
from soc.collector.store import EventStore
from soc.rules.catalogue import evaluate_all

NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


def _event_at(when: datetime, **overrides):
    """Purpose: a `SecurityEvent` stamped at `when`. Inputs: when, overrides.
    Output: a validated `SecurityEvent`."""
    defaults = dict(
        service_name="auth-service",
        event_type=EventType.AUTH_FAILED,
        severity=Severity.MEDIUM,
        endpoint="/api/v1/auth/login",
        http_method="POST",
        status_code=401,
        message="Authentication failed.",
        correlation_id="corr-bf",
        source_ip="203.0.113.9",
        user_id="analyst1",
    )
    defaults.update(overrides)
    return build_event(**defaults).model_copy(
        update={"timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )


@pytest.fixture
def event_store() -> EventStore:
    """
    Purpose: a store holding a six-strong brute-force burst against one account,
             enough to raise the Multiple Failed Logins rule.
    Inputs:  none.
    Output:  a populated `EventStore`.
    """
    store = EventStore()
    store.extend(
        _event_at(NOW - timedelta(seconds=250 - i * 10), correlation_id=f"corr-bf-{i}")
        for i in range(6)
    )
    return store


@pytest.fixture
def alert_store(event_store: EventStore) -> AlertStore:
    """
    Purpose: an `AlertStore` holding the alerts the real rules raise on
             `event_store` - so the loader tests wire genuine alert records.
    Inputs:  the event store fixture.
    Output:  a populated `AlertStore`.
    """
    store = AlertStore()
    store.extend(evaluate_all(event_store, NOW))
    return store
