"""
rule_abnormal_rate.py - Rule 3, Abnormal Request Rate.

Detects a source driving traffic far above the normal working rate: a denial-of-
service attempt, a runaway client, or an automated scan. Two independent signals
raise this alert, and either alone is enough.

  1. Volume. One source address exceeding the request threshold inside a one-
     minute window. The rate is measured per source, not per service: a service
     under load from fifty legitimate analysts is busy, one address producing the
     same volume is not.
  2. Gateway refusal. Any `RATE_LIMIT_EXCEEDED` event. Kong's rate-limiting
     plugin has already made the judgement that a client crossed the configured
     limit, and a rule that ignored its own gateway saying so would be detecting
     the attack more slowly than the infrastructure already did.

Signal 2 exists because the demo's burst is refused by the gateway before most
of it ever reaches a service - so the events that prove the attack are 429s, not
a pile of `REQUEST_RECEIVED`. A volume-only rule would stay silent through the
very scenario it is written for.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta

from common.events import EventType, SecurityEvent, Severity
from soc.alert_service.models import Alert
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.base import DetectionRule, window_start

# Requests from one source inside the window before the volume signal fires.
# Kong's own limit is 60/minute (gateway/kong.yml), so a source seen making more
# than 30 in a minute is already at half the gateway's ceiling.
REQUEST_THRESHOLD = 30
DETECTION_WINDOW = timedelta(minutes=1)

# A single 429 is a client that mistimed a burst; several mean sustained abuse.
RATE_LIMIT_THRESHOLD = 3

# The event types that represent one inbound request, counted for volume. Both
# ends of a request are emitted, so counting either alone avoids double-counting.
_REQUEST_EVENT_TYPES = (EventType.REQUEST_RECEIVED,)


class AbnormalRequestRateRule(DetectionRule):
    """
    Purpose: raise an alert when one source floods the system, by volume or by
             repeatedly tripping the gateway's rate limit.
    Inputs:  the collector's store and the evaluation moment.
    Output:  one alert per offending source; an empty list otherwise.
    """

    name = "Abnormal Request Rate"
    purpose = (
        "Detect a possible denial-of-service attempt, runaway client or "
        "automated scan driving request volume far above the working rate."
    )
    input_event_types = (
        EventType.RATE_LIMIT_EXCEEDED,
        EventType.REQUEST_RECEIVED,
    )
    severity = Severity.HIGH
    recommended_action = (
        "Rate-limit or block the source address at the gateway, then check "
        "upstream capacity and confirm the affected services recovered."
    )

    def evaluate(self, store: EventStore, now: datetime) -> list[Alert]:
        """
        Purpose: run the rule - measure per-source request volume and per-source
                 rate-limit refusals inside the window, and alert on each source
                 that breaches either threshold.
        Inputs:  store - the populated `EventStore`; now - the UTC evaluation
                 moment.
        Output:  a list of `Alert`, empty when no source breaches a threshold.
        """
        since = window_start(now, DETECTION_WINDOW)
        windowed = [
            event
            for event in store.all_events()
            if since <= parse_timestamp(event.timestamp) <= now
        ]

        throttled = _group_by_source(
            [e for e in windowed if e.event_type is EventType.RATE_LIMIT_EXCEEDED]
        )
        volume = _group_by_source(
            [e for e in windowed if e.event_type in _REQUEST_EVENT_TYPES]
        )

        alerts = []
        for source in sorted(set(throttled) | set(volume)):
            refusals = throttled.get(source, [])
            requests = volume.get(source, [])
            reasons = []
            if len(refusals) >= RATE_LIMIT_THRESHOLD:
                reasons.append(
                    f"{len(refusals)} requests refused by the gateway's rate limit"
                )
            if len(requests) >= REQUEST_THRESHOLD:
                reasons.append(
                    f"{len(requests)} requests received in "
                    f"{int(DETECTION_WINDOW.total_seconds())} seconds"
                )
            if not reasons:
                continue
            alerts.append(self._alert_for(source, refusals + requests, reasons, now))
        return alerts

    def _alert_for(
        self,
        source: str,
        events: list[SecurityEvent],
        reasons: list[str],
        now: datetime,
    ) -> Alert:
        """
        Purpose: build one source's alert, naming every signal that fired and
                 citing all the events behind them.
        Inputs:  source - the offending address; events - its windowed evidence;
                 reasons - the human-readable signals; now - the moment.
        Output:  a validated `Alert`.
        """
        ordered = sorted(events, key=lambda event: parse_timestamp(event.timestamp))
        services = sorted({event.service_name for event in ordered})
        return self.build_alert(
            now=now,
            description=(
                f"Abnormal request rate from {source}: {' and '.join(reasons)}, "
                f"affecting {', '.join(services)}."
            ),
            related_events=ordered,
            affected_service=services[0] if len(services) == 1 else None,
            affected_user=_single_user(ordered),
            affected_entity=source,
        )


def _group_by_source(events: list[SecurityEvent]) -> dict[str, list[SecurityEvent]]:
    """
    Purpose: bucket events by source address, skipping those with none - an
             event without a client address is not evidence about any source.
    Inputs:  events - the events to group.
    Output:  a dict of source address to its events, in the order given.
    """
    grouped: dict[str, list[SecurityEvent]] = {}
    for event in events:
        if not event.source_ip:
            continue
        grouped.setdefault(event.source_ip, []).append(event)
    return grouped


def _single_user(events: list[SecurityEvent]) -> str | None:
    """
    Purpose: name the user behind the flood when every event agrees on one, so
             the alert can point at an account rather than only an address.
    Inputs:  events - the evidence.
    Output:  the user id when exactly one is present, otherwise None.
    """
    users = {event.user_id for event in events if event.user_id}
    return users.pop() if len(users) == 1 else None
