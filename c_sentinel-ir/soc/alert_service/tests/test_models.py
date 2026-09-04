"""
test_models.py - the alert schema matches the specification and refuses to be
weakened.

The two guards that matter are the ones an ordinary happy-path test would miss:
an alert with no `relatedEvents` cites nothing and must be rejected, and an extra
field must be rejected rather than silently carried, exactly as the event schema
does - because the graph loader reads these keys by name.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from common.events import Severity
from soc.alert_service.models import Alert, AlertStatus, new_alert_id

# The eleven keys the Phase 2 specification names, in its own spelling.
_SCHEMA_KEYS = {
    "alertId",
    "timestamp",
    "ruleName",
    "severity",
    "status",
    "description",
    "relatedEvents",
    "affectedService",
    "affectedUser",
    "affectedEntity",
    "recommendedAction",
}


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
        related_events=("evt-000000000001",),
        affected_service="auth-service",
        affected_user="analyst-1",
        affected_entity="login-endpoint",
        recommended_action="Block the source IP.",
    )
    defaults.update(overrides)
    return Alert(**defaults)


def test_renders_exactly_the_specification_keys():
    """
    Purpose: the JSON an alert renders carries the eleven named keys and nothing
             else - this is what the API serves and the graph loader reads.
    Inputs:  none.
    Output:  assertions.
    """
    assert set(_alert().to_json_dict()) == _SCHEMA_KEYS


def test_an_alert_opens_in_the_open_state():
    """
    Purpose: a newly raised alert is unhandled by definition.
    Inputs:  none.
    Output:  assertions.
    """
    assert _alert().status is AlertStatus.OPEN


def test_a_fresh_identifier_is_minted_and_well_formed():
    """
    Purpose: every alert gets an `alt-` id in the same shape as an event's
             `evt-` id, and two alerts never share one.
    Inputs:  none.
    Output:  assertions.
    """
    first, second = _alert().alert_id, _alert().alert_id
    assert first.startswith("alt-") and len(first) == len("alt-") + 12
    assert first != second
    assert new_alert_id().startswith("alt-")


def test_an_alert_citing_no_events_is_rejected():
    """
    Purpose: `relatedEvents` is the link back to what caused the alert. An empty
             one makes the alert an assertion rather than evidence, so it fails
             at construction rather than at the graph loader weeks later.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(ValidationError, match="at least one event"):
        _alert(related_events=())


def test_an_extra_field_is_rejected():
    """
    Purpose: the schema is a contract, so a typo'd or invented key fails loudly.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(ValidationError):
        _alert(sourceIp="10.0.0.1")


def test_a_malformed_identifier_is_rejected():
    """
    Purpose: an id the graph loader cannot parse is refused at construction.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(ValidationError):
        _alert(alert_id="alert-1")
    with pytest.raises(ValidationError):
        _alert(alert_id="alt-XYZ000000000")


def test_a_blank_required_field_is_rejected():
    """
    Purpose: a present-but-empty required field is a missing one with extra
             steps.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(ValidationError):
        _alert(description="   ")


def test_an_alert_is_immutable():
    """
    Purpose: a raised alert is a record of what was detected. Status changes go
             through the store at step 16, by replacement, never by mutating a
             historical finding in place.
    Inputs:  none.
    Output:  assertions.
    """
    alert = _alert()
    with pytest.raises(ValidationError):
        alert.status = AlertStatus.CLOSED


def test_the_optional_attribution_fields_may_be_absent():
    """
    Purpose: an attack from an unauthenticated source names no user, and the
             alert must still be constructible.
    Inputs:  none.
    Output:  assertions.
    """
    alert = _alert(affected_user=None, affected_service=None, affected_entity=None)
    rendered = alert.to_json_dict()
    assert rendered["affectedUser"] is None
    assert set(rendered) == _SCHEMA_KEYS
