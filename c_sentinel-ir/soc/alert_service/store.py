"""
store.py - the queryable alert store the alert API serves from.

An in-process append-and-query store of `Alert` records, mirroring
`soc.collector.store.EventStore`: the rules are pure functions of an event
store and a clock, and the alert API is a pure function of this store, so
persistence would add a technology without serving step 16 or the demo. Same
reasoning as D-25.

`Alert` is frozen, so a status change is a replacement, never a mutation: the
store swaps the stored record for a copy carrying the new status and keeps the
original identifier. That keeps an alert a faithful record of what a rule saw
while still letting a responder move it through OPEN -> ACKNOWLEDGED -> CLOSED.

Author: Colile
"""

from __future__ import annotations

from common.errors import NotFoundError
from common.events import Severity
from soc.alert_service.models import Alert, AlertStatus


class AlertStore:
    """
    Purpose: hold the alerts the detection rules have raised and answer the
             queries the alert API runs against them.
    Inputs:  alerts are added through `add` or `extend`.
    Output:  each query returns a new list, newest alert first, never the
             internal list.
    """

    def __init__(self) -> None:
        self._alerts: dict[str, Alert] = {}

    def __len__(self) -> int:
        """Purpose: the number of alerts held. Inputs: none. Output: int."""
        return len(self._alerts)

    def add(self, alert: Alert) -> Alert:
        """
        Purpose: store one alert.
        Inputs:  alert - a validated `Alert`.
        Output:  the alert, unchanged.
        Raises:  `ConflictError` is not raised - a rule re-run mints fresh ids,
                 so a collision would be a bug in `new_alert_id`, not user input.
        """
        self._alerts[alert.alert_id] = alert
        return alert

    def extend(self, alerts: list[Alert]) -> int:
        """
        Purpose: store every alert from a list - the rule runner hands a whole
                 evaluation's output in through here.
        Inputs:  alerts - the alerts to store.
        Output:  the number added.
        """
        before = len(self._alerts)
        for alert in alerts:
            self._alerts[alert.alert_id] = alert
        return len(self._alerts) - before

    def get(self, alert_id: str) -> Alert:
        """
        Purpose: one alert by its identifier.
        Inputs:  alert_id - the `alt-` id.
        Output:  the `Alert`.
        Raises:  `NotFoundError` naming the id when no alert carries it.
        """
        try:
            return self._alerts[alert_id]
        except KeyError as exc:
            raise NotFoundError(
                f"No alert with id {alert_id!r}.", {"alertId": alert_id}
            ) from exc

    def list(
        self,
        *,
        severity: Severity | None = None,
        affected_service: str | None = None,
        status: AlertStatus | None = None,
    ) -> list[Alert]:
        """
        Purpose: the alert listing, optionally narrowed by any combination of
                 severity, affected service and status - the three axes the
                 knowledge-graph loader and the demo query on.
        Inputs:  severity / affected_service / status - optional equality
                 filters; a None filter is not applied.
        Output:  a new list, newest first by timestamp then id.
        """
        selected = [
            alert
            for alert in self._alerts.values()
            if (severity is None or alert.severity is severity)
            and (
                affected_service is None
                or alert.affected_service == affected_service
            )
            and (status is None or alert.status is status)
        ]
        return self._newest_first(selected)

    def set_status(self, alert_id: str, status: AlertStatus) -> Alert:
        """
        Purpose: move an alert through its lifecycle by replacing the stored
                 record with a copy carrying the new status.
        Inputs:  alert_id - the alert to change; status - the new `AlertStatus`.
        Output:  the updated `Alert`.
        Raises:  `NotFoundError` when no alert carries the id.
        """
        current = self.get(alert_id)
        updated = current.model_copy(update={"status": status})
        self._alerts[alert_id] = updated
        return updated

    def resolve_events(self, alert_id: str) -> tuple[str, ...]:
        """
        Purpose: the event ids an alert cites - the link `kg/loader` follows to
                 join an alert back to the events that caused it.
        Inputs:  alert_id - the alert.
        Output:  the tuple of `evt-` ids from its `relatedEvents`.
        Raises:  `NotFoundError` when no alert carries the id.
        """
        return self.get(alert_id).related_events

    @staticmethod
    def _newest_first(alerts: list[Alert]) -> list[Alert]:
        """
        Purpose: order alerts newest first, breaking ties on the id so the order
                 is total and a test can assert it.
        Inputs:  alerts - a list of `Alert`.
        Output:  a new sorted list.
        """
        return sorted(
            alerts, key=lambda alert: (alert.timestamp, alert.alert_id), reverse=True
        )
