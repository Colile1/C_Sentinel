"""
test_store.py - the alert store keeps, finds and re-statuses alerts.

The guards that matter beyond the happy path: a status change replaces the
frozen record rather than mutating it and keeps the same id, an unknown id is a
`NotFoundError` naming it rather than a `KeyError`, and `relatedEvents` survives
a status change intact - that tuple is the link `kg/loader` follows.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import NotFoundError
from common.events import Severity
from soc.alert_service.models import Alert, AlertStatus
from soc.alert_service.store import AlertStore


def _alert(**overrides) -> Alert:
    """
    Purpose: a valid alert, with any field overridden.
    Inputs:  overrides - field values to replace.
    Output:  a validated `Alert`.
    """
    defaults = dict(
        timestamp="2026-09-04T12:00:00Z",
        rule_name="Multiple Failed Logins",
        severity=Severity.HIGH,
        description="Five failed logins for one account in five minutes.",
        related_events=("evt-000000000001", "evt-000000000002"),
        affected_service="auth-service",
        affected_user="analyst-1",
        affected_entity="login-endpoint",
        recommended_action="Block the source IP.",
    )
    defaults.update(overrides)
    return Alert(**defaults)


def test_an_added_alert_is_retrievable_by_id():
    """
    Purpose: the store keeps what it is given and hands it back unchanged.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    alert = store.add(_alert())

    assert store.get(alert.alert_id) is alert
    assert len(store) == 1


def test_an_unknown_id_raises_not_found_naming_it():
    """
    Purpose: a missing alert is a typed 404, not a `KeyError`, so the router
             does not have to translate one.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(NotFoundError, match="alt-deadbeef0000"):
        AlertStore().get("alt-deadbeef0000")


def test_list_filters_by_severity_service_and_status():
    """
    Purpose: the three query axes the graph loader and the demo use, each on its
             own and combined.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    high_auth = store.add(_alert(severity=Severity.HIGH, affected_service="auth-service"))
    low_asset = store.add(
        _alert(severity=Severity.LOW, affected_service="asset-service")
    )

    assert store.list(severity=Severity.HIGH) == [high_auth]
    assert store.list(affected_service="asset-service") == [low_asset]
    assert store.list(status=AlertStatus.OPEN) == store.list()
    assert store.list(severity=Severity.LOW, affected_service="auth-service") == []


def test_list_returns_newest_first():
    """
    Purpose: the listing order is newest alert first, tie-broken on the id so it
             is total.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    older = store.add(_alert(timestamp="2026-09-04T12:00:00Z"))
    newer = store.add(_alert(timestamp="2026-09-04T12:05:00Z"))

    assert store.list() == [newer, older]


def test_set_status_replaces_the_record_and_keeps_the_id():
    """
    Purpose: `Alert` is frozen, so a status change is a replacement. The id is
             stable and `relatedEvents` survives intact - that tuple is the link
             back to the events that caused the alert.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    original = store.add(_alert())

    updated = store.set_status(original.alert_id, AlertStatus.ACKNOWLEDGED)

    assert updated is not original
    assert updated.alert_id == original.alert_id
    assert updated.status is AlertStatus.ACKNOWLEDGED
    assert updated.related_events == original.related_events
    assert store.get(original.alert_id).status is AlertStatus.ACKNOWLEDGED


def test_set_status_on_an_unknown_id_raises_not_found():
    """
    Purpose: re-statusing a missing alert fails the same typed way a read does.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(NotFoundError):
        AlertStore().set_status("alt-000000000000", AlertStatus.CLOSED)


def test_extend_stores_a_whole_evaluation_and_counts_the_additions():
    """
    Purpose: the rule runner hands a whole evaluation's alerts in through
             `extend`, which reports how many landed.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    added = store.extend([_alert(), _alert(), _alert()])

    assert added == 3
    assert len(store) == 3


def test_resolve_events_returns_the_cited_event_ids():
    """
    Purpose: `kg/loader` joins an alert to its events through this - it must be
             the alert's own `relatedEvents`, unchanged.
    Inputs:  none.
    Output:  assertions.
    """
    store = AlertStore()
    alert = store.add(_alert(related_events=("evt-00000000000a", "evt-00000000000b")))

    assert store.resolve_events(alert.alert_id) == (
        "evt-00000000000a",
        "evt-00000000000b",
    )
