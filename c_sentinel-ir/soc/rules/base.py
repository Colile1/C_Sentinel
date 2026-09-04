"""
base.py - the interface every detection rule implements.

A rule is a pure function of the event store's contents and a clock. It owns no
state, opens no connection and reads no wall clock of its own: `evaluate(store,
now)` is given the moment to reason from, which is what makes a scripted attack
reproducible in a test and on camera.

The specification requires seven things documented per rule - name, purpose,
input events, detection logic, severity, generated alert and response action.
Six of them are attributes here and the seventh is `evaluate`'s body, so a rule
cannot be written without stating all seven.

Author: Colile
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from common.events import EventType, SecurityEvent, Severity
from soc.alert_service.models import Alert
from soc.collector.store import EventStore, parse_timestamp


class DetectionRule(ABC):
    """
    Purpose: the contract every rule in the catalogue obeys.
    Inputs:  subclasses set the seven documented attributes and implement
             `evaluate`.
    Output:  `evaluate` returns the alerts the rule raises, newest subject last;
             an empty list when the rule stays silent.
    """

    #: The rule's name, as it appears on the alert and in the rule catalogue.
    name: str = ""
    #: One sentence: what this rule is looking for and why it matters.
    purpose: str = ""
    #: The event types the rule reads. Documentation, and the catalogue's
    #: cross-check that Phase 1 actually emits what Phase 2 consumes.
    input_event_types: tuple[EventType, ...] = ()
    #: The severity carried by the alerts this rule raises. A rule that varies
    #: its severity per firing states its highest here and overrides per alert.
    severity: Severity = Severity.MEDIUM
    #: What a responder should do about a firing.
    recommended_action: str = ""

    @abstractmethod
    def evaluate(self, store: EventStore, now: datetime) -> list[Alert]:
        """
        Purpose: run the rule's detection logic over the store.
        Inputs:  store - the collector's populated `EventStore`; now - the UTC
                 moment to treat as the present, so windows are deterministic.
        Output:  a list of `Alert`, empty when nothing is detected.
        """

    def build_alert(
        self,
        *,
        now: datetime,
        description: str,
        related_events: list[SecurityEvent],
        severity: Severity | None = None,
        affected_service: str | None = None,
        affected_user: str | None = None,
        affected_entity: str | None = None,
    ) -> Alert:
        """
        Purpose: assemble this rule's alert, so every rule names itself, its
                 action and its evidence the same way.
        Inputs:  now - the evaluation moment, stamped as the alert timestamp;
                 description - one sentence naming what was seen; related_events
                 - the events that caused the firing, whose ids become the
                 alert's evidence; severity - an override for a rule that rises;
                 the three affected_* fields where known.
        Output:  a validated `Alert`.
        """
        return Alert(
            timestamp=format_timestamp(now),
            rule_name=self.name,
            severity=severity or self.severity,
            description=description,
            related_events=tuple(event.event_id for event in related_events),
            affected_service=affected_service,
            affected_user=affected_user,
            affected_entity=affected_entity,
            recommended_action=self.recommended_action,
        )


def format_timestamp(moment: datetime) -> str:
    """
    Purpose: stamp an alert in the same format the event schema uses, so an
             alert and the events it cites sort together.
    Inputs:  moment - a timezone-aware UTC datetime.
    Output:  an ISO-8601 UTC string ending in `Z`.
    """
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def window_start(now: datetime, window: timedelta) -> datetime:
    """
    Purpose: the inclusive lower bound of a detection window, for the store's
             `since` argument.
    Inputs:  now - the evaluation moment; window - how far back the rule looks.
    Output:  a timezone-aware UTC datetime.
    """
    return now - window


def within_window(
    events: list[SecurityEvent], now: datetime, window: timedelta
) -> list[SecurityEvent]:
    """
    Purpose: keep only the events inside a rule's window. The store filters on
             `since` for its keyed queries; a rule scanning `all_events` needs
             the same cut applied here.
    Inputs:  events - candidate events; now - the evaluation moment; window -
             how far back to look.
    Output:  a new list, in the order given.
    """
    lower = window_start(now, window)
    return [
        event
        for event in events
        if lower <= parse_timestamp(event.timestamp) <= now
    ]
