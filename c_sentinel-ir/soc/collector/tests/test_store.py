"""
test_store.py - the event store answers the rules' four queries correctly.

Proves build step 14's verification (a workflow's events are queryable by
correlation ID) and the collector README's done-when (all five failed logins
for one user inside a five-minute window are returned).

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from common.events import EventType, SecurityEvent, build_event
from soc.collector.store import EventStore, parse_timestamp

_BASE = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


def _event_at(when: datetime, **overrides) -> SecurityEvent:
    """
    Purpose: a `SecurityEvent` with a chosen timestamp - `build_event` stamps
             the clock itself, so overwrite it on a model copy.
    Inputs:  when - the UTC time to stamp; overrides - other field values.
    Output:  a validated `SecurityEvent`.
    """
    defaults = dict(
        service_name="auth-service",
        event_type=EventType.AUTH_FAILED,
        severity="MEDIUM",
        endpoint="/api/v1/auth/login",
        http_method="POST",
        status_code=401,
        message="Authentication failed.",
        correlation_id="corr-x",
    )
    defaults.update(overrides)
    event = build_event(**defaults)
    return event.model_copy(
        update={"timestamp": when.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )


def test_parse_timestamp_round_trips():
    """
    Purpose: the store's timestamp parser is the inverse of the library's
             formatter.
    Inputs:  none.
    Output:  assertions.
    """
    assert parse_timestamp("2026-09-04T12:00:00Z") == _BASE


def test_append_and_len():
    """
    Purpose: appended events are counted.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    assert len(store) == 0
    store.append(_event_at(_BASE))
    assert len(store) == 1


def test_extend_reports_count_and_orders_oldest_first():
    """
    Purpose: `extend` returns how many it added and `all_events` is sorted.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    added = store.extend(
        [
            _event_at(_BASE + timedelta(minutes=2), message="second"),
            _event_at(_BASE, message="first"),
        ]
    )
    assert added == 2
    assert [e.message for e in store.all_events()] == ["first", "second"]


def test_by_correlation_gathers_a_whole_workflow():
    """
    Purpose: the step-14 verification - one correlation ID returns every event
             of that request across services, and nothing from another request.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    store.extend(
        [
            _event_at(
                _BASE,
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity="LOW",
                status_code=200,
                correlation_id="corr-run-1",
            ),
            _event_at(
                _BASE + timedelta(seconds=1),
                service_name="incident-service",
                event_type=EventType.INCIDENT_CREATED,
                endpoint="/api/v1/incidents",
                status_code=201,
                correlation_id="corr-run-1",
            ),
            _event_at(
                _BASE + timedelta(seconds=2),
                service_name="asset-service",
                event_type=EventType.ASSET_ACCESSED,
                endpoint="/api/v1/assets/1",
                http_method="GET",
                status_code=200,
                correlation_id="corr-run-1",
            ),
            _event_at(_BASE, correlation_id="corr-other"),
        ]
    )
    journey = store.by_correlation("corr-run-1")
    assert [e.service_name for e in journey] == [
        "auth-service",
        "incident-service",
        "asset-service",
    ]


def test_five_failed_logins_for_one_user_in_a_five_minute_window():
    """
    Purpose: the collector README's done-when - the store returns all five
             `AUTH_FAILED` events for one user inside five minutes, and excludes
             an earlier one outside the window.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    # One stale failure well before the window.
    store.append(_event_at(_BASE - timedelta(minutes=30), user_id="mallory"))
    # Five inside a five-minute burst.
    for offset in range(5):
        store.append(
            _event_at(_BASE + timedelta(seconds=offset * 30), user_id="mallory")
        )
    # An unrelated user's failure in the same window.
    store.append(_event_at(_BASE, user_id="alice"))

    window_start = _BASE - timedelta(minutes=1)
    hits = store.events_for_user("mallory", since=window_start)
    assert len(hits) == 5
    assert all(e.user_id == "mallory" for e in hits)


def test_events_for_ip_and_service_filter_and_window():
    """
    Purpose: `events_for_ip` and `events_for_service` filter on their key and
             honour `since`.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    store.append(_event_at(_BASE - timedelta(hours=1), source_ip="1.1.1.1"))
    store.append(_event_at(_BASE, source_ip="1.1.1.1"))
    store.append(_event_at(_BASE, source_ip="2.2.2.2"))
    store.append(
        _event_at(_BASE, service_name="incident-service", status_code=201)
    )

    recent_ip = store.events_for_ip("1.1.1.1", since=_BASE - timedelta(minutes=5))
    assert len(recent_ip) == 1

    auth_events = store.events_for_service("auth-service")
    assert len(auth_events) == 3
    incident_events = store.events_for_service("incident-service")
    assert len(incident_events) == 1


def test_queries_return_copies_not_the_internal_list():
    """
    Purpose: mutating a query result must not corrupt the store.
    Inputs:  none.
    Output:  assertions.
    """
    store = EventStore()
    store.append(_event_at(_BASE))
    result = store.all_events()
    result.clear()
    assert len(store) == 1
