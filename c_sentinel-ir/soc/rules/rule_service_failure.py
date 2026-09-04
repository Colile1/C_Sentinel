"""
rule_service_failure.py - Rule 4, Service Failure.

Detects a service degrading: repeated `DEPENDENCY_FAILURE` or `SERVICE_ERROR`
events from one service inside five minutes, or a `CIRCUIT_OPENED` event, which
needs no threshold at all.

A breaker opening is already a considered judgement. `libs/common/http_client.py`
opens it only after the configured number of *whole* requests failed, each one
having exhausted its retries first (D-16), so by the time `CIRCUIT_OPENED` is
emitted the system has independently established that a dependency is down.
Requiring this rule to see it happen three more times would delay the alert past
the point where it is useful.

The counterpart matters as much: this rule must stay silent when the breaker
closes again. `CIRCUIT_CLOSED` is read only to note recovery in the alert
description, never as a firing signal - a recovery that raised an alarm would
train the responder to ignore the ones that matter.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta

from common.events import EventType, SecurityEvent, Severity
from soc.alert_service.models import Alert
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.base import DetectionRule, window_start

# Failures from one service inside the window before the count signal fires.
FAILURE_THRESHOLD = 3
DETECTION_WINDOW = timedelta(minutes=5)

# Failures that are counted towards the threshold.
_FAILURE_EVENT_TYPES = (
    EventType.DEPENDENCY_FAILURE,
    EventType.SERVICE_ERROR,
)


class ServiceFailureRule(DetectionRule):
    """
    Purpose: raise an alert when a service is failing - by an opened circuit
             breaker, or by repeated dependency and server errors.
    Inputs:  the collector's store and the evaluation moment.
    Output:  one alert per affected service; an empty list otherwise.
    """

    name = "Service Failure"
    purpose = (
        "Detect a service losing a dependency or returning server errors, so "
        "the outage is investigated before it reaches every caller."
    )
    input_event_types = (
        EventType.CIRCUIT_OPENED,
        EventType.DEPENDENCY_FAILURE,
        EventType.SERVICE_ERROR,
    )
    severity = Severity.HIGH
    recommended_action = (
        "Check the health of the failing dependency and the circuit breaker's "
        "state, confirm the documented fallback is being served, and restart "
        "the dependency if it is down."
    )

    def evaluate(self, store: EventStore, now: datetime) -> list[Alert]:
        """
        Purpose: run the rule - alert on any service whose breaker opened in the
                 window, or which accumulated enough failures in it.
        Inputs:  store - the populated `EventStore`; now - the UTC evaluation
                 moment.
        Output:  a list of `Alert`, empty when every service is healthy.
        """
        since = window_start(now, DETECTION_WINDOW)
        windowed = [
            event
            for event in store.all_events()
            if since <= parse_timestamp(event.timestamp) <= now
        ]

        grouped: dict[str, list[SecurityEvent]] = {}
        for event in windowed:
            if event.event_type is EventType.CIRCUIT_OPENED or (
                event.event_type in _FAILURE_EVENT_TYPES
            ):
                grouped.setdefault(event.service_name, []).append(event)

        recovered = {
            event.service_name
            for event in windowed
            if event.event_type is EventType.CIRCUIT_CLOSED
        }

        alerts = []
        for service, events in sorted(grouped.items()):
            breaker_opened = any(
                event.event_type is EventType.CIRCUIT_OPENED for event in events
            )
            failures = [
                event
                for event in events
                if event.event_type in _FAILURE_EVENT_TYPES
            ]
            if not breaker_opened and len(failures) < FAILURE_THRESHOLD:
                continue
            alerts.append(
                self._alert_for(
                    service=service,
                    events=events,
                    breaker_opened=breaker_opened,
                    failure_count=len(failures),
                    recovered=service in recovered,
                    now=now,
                )
            )
        return alerts

    def _alert_for(
        self,
        *,
        service: str,
        events: list[SecurityEvent],
        breaker_opened: bool,
        failure_count: int,
        recovered: bool,
        now: datetime,
    ) -> Alert:
        """
        Purpose: build one service's alert, naming which signal fired and whether
                 the breaker has since closed.
        Inputs:  service - the failing service; events - its evidence;
                 breaker_opened / failure_count - the signals; recovered -
                 whether a `CIRCUIT_CLOSED` followed; now - the moment.
        Output:  a validated `Alert`.
        """
        reasons = []
        if breaker_opened:
            reasons.append("its circuit breaker opened")
        if failure_count:
            reasons.append(
                f"{failure_count} dependency or server "
                f"error{'s' if failure_count != 1 else ''}"
            )
        recovery = (
            " The breaker has since closed, so the dependency has recovered."
            if recovered
            else ""
        )
        last = events[-1]
        return self.build_alert(
            now=now,
            description=(
                f"{service} is failing: {' and '.join(reasons)} within "
                f"{int(DETECTION_WINDOW.total_seconds() // 60)} minutes."
                f"{recovery}"
            ),
            related_events=events,
            affected_service=service,
            affected_user=None,
            affected_entity=last.affected_entity or last.endpoint,
        )
