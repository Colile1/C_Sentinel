"""
store.py - the queryable event store the detection rules read.

An in-process append-and-query store. It holds every `SecurityEvent` the
collector has ingested and exposes exactly the four query shapes the Phase 2
rules need: by user, by source IP, by service, and by correlation ID. The
first three take an optional `since` cut-off because every rule reasons over a
time window ("five failed logins in five minutes").

In-process, not a database: the rules are pure functions of the store's
contents and a clock, so persistence would add a technology without serving
step 15 or the demo. Recorded as D-25 in DECISIONS.md.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from common.events import SecurityEvent

# The exact format `common.events.utc_now_iso` writes for every timestamp.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def parse_timestamp(value: str) -> datetime:
    """
    Purpose: turn an event's ISO-8601 `Z` timestamp string into a timezone-aware
             UTC datetime, so windows can be compared.
    Inputs:  value - the `timestamp` field of a `SecurityEvent`.
    Output:  a `datetime` in UTC.
    Raises:  `ValueError` if the string is not in the schema's format.
    """
    return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


class EventStore:
    """
    Purpose: hold ingested security events and answer the queries the detection
             rules run against them.
    Inputs:  events are added through `append` or `extend`.
    Output:  each query returns a new list, oldest event first, never the
             internal list.
    """

    def __init__(self) -> None:
        self._events: list[SecurityEvent] = []

    def __len__(self) -> int:
        """Purpose: the number of events held. Inputs: none. Output: int."""
        return len(self._events)

    def append(self, event: SecurityEvent) -> None:
        """
        Purpose: add one event to the store.
        Inputs:  event - a validated `SecurityEvent`.
        Output:  None.
        """
        self._events.append(event)

    def extend(self, events: Iterable[SecurityEvent]) -> int:
        """
        Purpose: add every event from an iterable - the collector feeds a whole
                 stream in through here.
        Inputs:  events - an iterable of `SecurityEvent`.
        Output:  the number of events added.
        """
        before = len(self._events)
        self._events.extend(events)
        return len(self._events) - before

    def all_events(self) -> list[SecurityEvent]:
        """
        Purpose: every event held, oldest first - the whole-stream view a rule
                 uses when it is not filtering by subject.
        Inputs:  none.
        Output:  a new list of `SecurityEvent`.
        """
        return self._sorted(self._events)

    def events_for_user(
        self, user_id: str, since: datetime | None = None
    ) -> list[SecurityEvent]:
        """
        Purpose: every event whose `userId` is this user, optionally only those
                 at or after `since`. Feeds Rule 1 (multiple failed logins) and
                 Rule 2 (unauthorised endpoint access).
        Inputs:  user_id - the subject; since - an optional UTC cut-off.
        Output:  a new list, oldest first.
        """
        return self._query(lambda e: e.user_id == user_id, since)

    def events_for_ip(
        self, ip: str, since: datetime | None = None
    ) -> list[SecurityEvent]:
        """
        Purpose: every event from this client IP, optionally windowed. Rule 1
                 also keys on source IP, since a brute-force run may invent a
                 fresh username each attempt.
        Inputs:  ip - the client address; since - an optional UTC cut-off.
        Output:  a new list, oldest first.
        """
        return self._query(lambda e: e.source_ip == ip, since)

    def events_for_service(
        self, name: str, since: datetime | None = None
    ) -> list[SecurityEvent]:
        """
        Purpose: every event emitted by this service, optionally windowed. Feeds
                 Rule 3 (abnormal request rate) and Rule 4 (service failure).
        Inputs:  name - the `serviceName`; since - an optional UTC cut-off.
        Output:  a new list, oldest first.
        """
        return self._query(lambda e: e.service_name == name, since)

    def by_correlation(self, correlation_id: str) -> list[SecurityEvent]:
        """
        Purpose: every event carrying this correlation ID, across all services -
                 the whole journey of one request. This is the query the build
                 order names for step 14's verification.
        Inputs:  correlation_id - the value threaded through `X-Correlation-ID`.
        Output:  a new list, oldest first.
        """
        return self._query(lambda e: e.correlation_id == correlation_id, None)

    def _query(self, predicate, since: datetime | None) -> list[SecurityEvent]:
        """
        Purpose: shared filter body - apply a predicate and an optional lower
                 time bound, then sort.
        Inputs:  predicate - a callable `SecurityEvent -> bool`; since - an
                 optional inclusive UTC cut-off.
        Output:  a new sorted list.
        """
        selected = [event for event in self._events if predicate(event)]
        if since is not None:
            selected = [
                event
                for event in selected
                if parse_timestamp(event.timestamp) >= since
            ]
        return self._sorted(selected)

    @staticmethod
    def _sorted(events: list[SecurityEvent]) -> list[SecurityEvent]:
        """
        Purpose: order events oldest first by their schema timestamp.
        Inputs:  events - a list of `SecurityEvent`.
        Output:  a new sorted list.
        """
        return sorted(events, key=lambda event: parse_timestamp(event.timestamp))
