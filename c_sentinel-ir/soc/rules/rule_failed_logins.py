"""
rule_failed_logins.py - Rule 1, Multiple Failed Logins.

Detects a brute-force or credential-stuffing run against the login endpoint:
five or more `AUTH_FAILED` events for the same subject inside five minutes.

The subject is keyed two ways, because an attacker controls one of them. Keying
only on `userId` misses a run that invents a fresh username each attempt; keying
only on `sourceIp` misses a distributed run against one account. Both are
checked, and a burst that trips both raises one alert per key - deliberately, not
by accident: they are different findings ("this account is under attack" and
"this address is attacking"), and the responder acts on each differently.

The events it reads exist because `auth_service.py` emits `AUTH_FAILED` on every
failure path including an unknown username, recording the attempted name as the
`userId`. That was decided at step 5 (D-11) precisely so this rule can see an
attack on names that were never real accounts.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta

from common.events import EventType, SecurityEvent, Severity
from soc.alert_service.models import Alert
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.base import DetectionRule, window_start

# The specification's threshold: five failures in five minutes.
FAILURE_THRESHOLD = 5
DETECTION_WINDOW = timedelta(minutes=5)


class MultipleFailedLoginsRule(DetectionRule):
    """
    Purpose: raise an alert when one user account or one source address
             accumulates five failed logins inside five minutes.
    Inputs:  the collector's store and the evaluation moment.
    Output:  one alert per subject over the threshold; an empty list otherwise.
    """

    name = "Multiple Failed Logins"
    purpose = (
        "Detect a brute-force or credential-stuffing attempt against the "
        "authentication endpoint before an account is compromised."
    )
    input_event_types = (EventType.AUTH_FAILED,)
    severity = Severity.HIGH
    recommended_action = (
        "Temporarily block the source IP at the gateway and verify whether the "
        "targeted account is compromised; force a password reset if it is."
    )

    def evaluate(self, store: EventStore, now: datetime) -> list[Alert]:
        """
        Purpose: run the rule - count `AUTH_FAILED` events per user and per
                 source IP inside the window, and alert on each subject at or
                 over the threshold.
        Inputs:  store - the populated `EventStore`; now - the UTC evaluation
                 moment.
        Output:  a list of `Alert`, empty when no subject reaches the threshold.
        """
        since = window_start(now, DETECTION_WINDOW)
        failures = [
            event
            for event in store.all_events()
            if event.event_type is EventType.AUTH_FAILED
        ]
        recent = [
            event
            for event in failures
            if _timestamp_in_window(event, since, now)
        ]

        alerts: list[Alert] = []
        alerts.extend(self._alerts_for_users(recent, now))
        alerts.extend(self._alerts_for_ips(recent, now))
        return alerts

    def _alerts_for_users(
        self, recent: list[SecurityEvent], now: datetime
    ) -> list[Alert]:
        """
        Purpose: alert on each account that reached the threshold.
        Inputs:  recent - the windowed `AUTH_FAILED` events; now - the moment.
        Output:  a list of `Alert`, one per over-threshold account.
        """
        grouped = _group_by(recent, lambda event: event.user_id)
        alerts = []
        for user_id, events in sorted(grouped.items()):
            if len(events) < FAILURE_THRESHOLD:
                continue
            addresses = sorted({e.source_ip for e in events if e.source_ip})
            alerts.append(
                self.build_alert(
                    now=now,
                    description=(
                        f"{len(events)} failed logins for user {user_id!r} "
                        f"within {_window_minutes()} minutes, from "
                        f"{len(addresses) or 'no recorded'} source "
                        f"address{'es' if len(addresses) != 1 else ''}."
                    ),
                    related_events=events,
                    affected_service=events[-1].service_name,
                    affected_user=user_id,
                    affected_entity="login-endpoint",
                )
            )
        return alerts

    def _alerts_for_ips(
        self, recent: list[SecurityEvent], now: datetime
    ) -> list[Alert]:
        """
        Purpose: alert on each source address that reached the threshold - the
                 half of the rule that catches a run inventing a new username
                 every attempt.
        Inputs:  recent - the windowed `AUTH_FAILED` events; now - the moment.
        Output:  a list of `Alert`, one per over-threshold address.
        """
        grouped = _group_by(recent, lambda event: event.source_ip)
        alerts = []
        for source_ip, events in sorted(grouped.items()):
            if len(events) < FAILURE_THRESHOLD:
                continue
            usernames = sorted({e.user_id for e in events if e.user_id})
            alerts.append(
                self.build_alert(
                    now=now,
                    description=(
                        f"{len(events)} failed logins from {source_ip} within "
                        f"{_window_minutes()} minutes, against "
                        f"{len(usernames)} username"
                        f"{'s' if len(usernames) != 1 else ''}."
                    ),
                    related_events=events,
                    affected_service=events[-1].service_name,
                    affected_user=usernames[0] if len(usernames) == 1 else None,
                    affected_entity="login-endpoint",
                )
            )
        return alerts


def _window_minutes() -> int:
    """
    Purpose: the window in whole minutes, for the alert's description.
    Inputs:  none.
    Output:  an integer number of minutes.
    """
    return int(DETECTION_WINDOW.total_seconds() // 60)


def _timestamp_in_window(
    event: SecurityEvent, since: datetime, now: datetime
) -> bool:
    """
    Purpose: whether an event falls inside the detection window.
    Inputs:  event - the candidate; since - the inclusive lower bound; now - the
             inclusive upper bound.
    Output:  True when the event's timestamp lies within.
    """
    return since <= parse_timestamp(event.timestamp) <= now


def _group_by(events: list[SecurityEvent], key) -> dict[str, list[SecurityEvent]]:
    """
    Purpose: bucket events by a key, skipping those whose key is absent - an
             event with no `sourceIp` is not evidence about any address.
    Inputs:  events - the events to group; key - a callable returning the bucket
             key or None.
    Output:  a dict of key to the events carrying it, in the order given.
    """
    grouped: dict[str, list[SecurityEvent]] = {}
    for event in events:
        value = key(event)
        if value is None:
            continue
        grouped.setdefault(value, []).append(event)
    return grouped
