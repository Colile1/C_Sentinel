"""
rule_unauthorised_access.py - Rule 2, Unauthorised Endpoint Access.

Detects a caller probing endpoints it has no right to reach: repeated 401 or 403
responses on protected routes from one subject inside ten minutes. A single 403
is an expired token or a mistyped URL; a run of them is reconnaissance, or a
compromised analyst token being tested for what it can reach.

Severity rises from MEDIUM to HIGH when any of the refusals landed on a
privileged route, because a caller probing the admin surface is a materially
different finding from one bouncing off an ordinary endpoint. The privileged
paths are listed here rather than inferred: `/api/v1/auth/users` is the one
endpoint set behind `require_admin` in Phase 1.

Input is `UNAUTHORISED_ACCESS` from the gateway, which is where a request without
a valid token is refused, plus any event carrying a 401 or 403 status - a 403
raised inside a service (an analyst on an admin route) never reaches the gateway
plugin, and missing it would leave the rule blind to exactly the privilege-
escalation attempt it exists to catch.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta

from common.events import EventType, SecurityEvent, Severity
from soc.alert_service.models import Alert
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.base import DetectionRule, window_start

# Three refusals in ten minutes. Lower than Rule 1's threshold: a failed login
# is a routine typo, an authorisation refusal on a protected route is not.
REFUSAL_THRESHOLD = 3
DETECTION_WINDOW = timedelta(minutes=10)

# The HTTP statuses that mean "refused", as opposed to "not found" or "invalid".
REFUSAL_STATUS_CODES = frozenset({401, 403})

# Endpoint prefixes that require the admin role in Phase 1.
PRIVILEGED_PATH_PREFIXES = ("/api/v1/auth/users",)


class UnauthorisedAccessRule(DetectionRule):
    """
    Purpose: raise an alert when one subject is repeatedly refused on protected
             endpoints, and raise it higher when a privileged route was probed.
    Inputs:  the collector's store and the evaluation moment.
    Output:  one alert per over-threshold subject; an empty list otherwise.
    """

    name = "Unauthorised Endpoint Access"
    purpose = (
        "Detect a caller probing endpoints outside its authorisation - "
        "reconnaissance, or a stolen token being tested for reach."
    )
    input_event_types = (
        EventType.UNAUTHORISED_ACCESS,
        EventType.REQUEST_COMPLETED,
    )
    severity = Severity.MEDIUM
    recommended_action = (
        "Review the subject's role assignment, audit the endpoints it was "
        "refused on, and revoke the token if the access pattern is not "
        "explainable by a legitimate client."
    )

    def evaluate(self, store: EventStore, now: datetime) -> list[Alert]:
        """
        Purpose: run the rule - group refusals by subject inside the window and
                 alert on each subject at or over the threshold.
        Inputs:  store - the populated `EventStore`; now - the UTC evaluation
                 moment.
        Output:  a list of `Alert`, empty when no subject reaches the threshold.
        """
        since = window_start(now, DETECTION_WINDOW)
        refusals = [
            event
            for event in store.all_events()
            if _is_refusal(event) and since <= parse_timestamp(event.timestamp) <= now
        ]

        grouped: dict[str, list[SecurityEvent]] = {}
        for event in refusals:
            grouped.setdefault(_subject_of(event), []).append(event)

        alerts = []
        for subject, events in sorted(grouped.items()):
            if len(events) < REFUSAL_THRESHOLD:
                continue
            alerts.append(self._alert_for(subject, events, now))
        return alerts

    def _alert_for(
        self, subject: str, events: list[SecurityEvent], now: datetime
    ) -> Alert:
        """
        Purpose: build one subject's alert, escalating to HIGH when a privileged
                 route is among the endpoints it was refused on.
        Inputs:  subject - the user id or source IP; events - that subject's
                 windowed refusals; now - the evaluation moment.
        Output:  a validated `Alert`.
        """
        endpoints = sorted({event.endpoint for event in events})
        privileged = sorted(
            endpoint for endpoint in endpoints if _is_privileged(endpoint)
        )
        severity = Severity.HIGH if privileged else self.severity
        detail = (
            f" including the privileged route{'s' if len(privileged) != 1 else ''} "
            f"{', '.join(privileged)}"
            if privileged
            else ""
        )
        last = events[-1]
        return self.build_alert(
            now=now,
            severity=severity,
            description=(
                f"{len(events)} unauthorised requests from {subject} within "
                f"{int(DETECTION_WINDOW.total_seconds() // 60)} minutes across "
                f"{len(endpoints)} endpoint{'s' if len(endpoints) != 1 else ''}"
                f"{detail}."
            ),
            related_events=events,
            affected_service=last.service_name,
            affected_user=last.user_id,
            affected_entity=privileged[0] if privileged else endpoints[0],
        )


def _is_refusal(event: SecurityEvent) -> bool:
    """
    Purpose: whether an event records a request that was refused on authorisation
             grounds.
    Inputs:  event - the candidate.
    Output:  True for an `UNAUTHORISED_ACCESS` event, or any event carrying a
             401 or 403 status - which catches a service-raised 403 the gateway
             never sees. `AUTH_FAILED` is excluded although it carries a 401: a
             rejected password is an *authentication* failure and belongs to
             Rule 1. Counting it here would make every brute-force run fire both
             rules and double the responder's work for one attack.
    """
    if event.event_type is EventType.AUTH_FAILED:
        return False
    if event.event_type is EventType.UNAUTHORISED_ACCESS:
        return True
    return event.status_code in REFUSAL_STATUS_CODES


def _is_privileged(endpoint: str) -> bool:
    """
    Purpose: whether an endpoint is one Phase 1 restricts to the admin role.
    Inputs:  endpoint - the request path.
    Output:  True when the path is under a privileged prefix.
    """
    return any(endpoint.startswith(prefix) for prefix in PRIVILEGED_PATH_PREFIXES)


def _subject_of(event: SecurityEvent) -> str:
    """
    Purpose: identify who was refused. The user id when the token named one; the
             source address otherwise, since a request refused for having no
             token carries no user at all.
    Inputs:  event - the refusal event.
    Output:  a grouping key.
    """
    if event.user_id:
        return event.user_id
    if event.source_ip:
        return event.source_ip
    return "unattributed"
