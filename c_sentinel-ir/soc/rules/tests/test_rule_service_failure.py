"""
test_rule_service_failure.py - Rule 4 fires on a degrading service and stays
silent on normal traffic.

The behaviour worth guarding is the asymmetry: `CIRCUIT_OPENED` fires the rule on
its own, because the breaker has already established the dependency is down,
while `CIRCUIT_CLOSED` must never fire it - a recovery that raised an alarm would
train the responder to ignore the alarms that matter.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import timedelta

from common.events import EventType, Severity
from soc.rules.rule_service_failure import FAILURE_THRESHOLD, ServiceFailureRule
from soc.rules.tests.conftest import NOW, event_at, store_of


def _failure(seconds_ago: int, event_type: EventType, **overrides):
    """
    Purpose: one resilience event as incident-service emits it.
    Inputs:  seconds_ago - how far before `NOW`; event_type - which signal;
             overrides - other field values.
    Output:  a validated `SecurityEvent`.
    """
    defaults = dict(
        service_name="incident-service",
        event_type=event_type,
        severity=Severity.HIGH,
        endpoint="/api/v1/incidents",
        http_method="POST",
        status_code=503,
        user_id=None,
        source_ip=None,
        correlation_id=f"corr-fail-{seconds_ago}",
        affected_entity="asset-service",
        message="Dependency call failed.",
    )
    defaults.update(overrides)
    return event_at(NOW - timedelta(seconds=seconds_ago), **defaults)


def test_an_opened_breaker_fires_on_its_own(now):
    """
    Purpose: `CIRCUIT_OPENED` needs no threshold - `http_client.py` opens the
             breaker only after the configured number of whole failed requests,
             so the judgement has already been made.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of([_failure(60, EventType.CIRCUIT_OPENED)])
    alerts = ServiceFailureRule().evaluate(store, now)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity is Severity.HIGH
    assert alert.rule_name == "Service Failure"
    assert alert.affected_service == "incident-service"
    assert "circuit breaker opened" in alert.description
    assert "circuit breaker" in alert.recommended_action


def test_repeated_dependency_failures_fire_without_a_breaker_event(now):
    """
    Purpose: the counting signal - enough `DEPENDENCY_FAILURE` events fire the
             rule even when no breaker state change was captured.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _failure(200 - index * 30, EventType.DEPENDENCY_FAILURE)
            for index in range(FAILURE_THRESHOLD)
        ]
    )
    alerts = ServiceFailureRule().evaluate(store, now)

    assert len(alerts) == 1
    assert "dependency or server errors" in alerts[0].description
    assert len(alerts[0].related_events) == FAILURE_THRESHOLD


def test_a_closed_breaker_alone_never_fires(now):
    """
    Purpose: recovery is not an incident. A `CIRCUIT_CLOSED` on its own raises
             nothing at all.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _failure(
                60,
                EventType.CIRCUIT_CLOSED,
                severity=Severity.LOW,
                status_code=200,
                message="Dependency recovered.",
            )
        ]
    )
    assert ServiceFailureRule().evaluate(store, now) == []


def test_recovery_is_noted_on_the_alert_not_suppressed(now):
    """
    Purpose: when the breaker opened and then closed, the outage still happened
             and is still reported - with the recovery noted, so the responder
             knows the current state.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _failure(120, EventType.CIRCUIT_OPENED),
            _failure(
                30,
                EventType.CIRCUIT_CLOSED,
                severity=Severity.LOW,
                status_code=200,
                message="Dependency recovered.",
            ),
        ]
    )
    alerts = ServiceFailureRule().evaluate(store, now)

    assert len(alerts) == 1
    assert "has since closed" in alerts[0].description


def test_two_failures_do_not_reach_the_threshold(now):
    """
    Purpose: below the threshold, and with no breaker event, the rule is silent.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _failure(120 - index * 30, EventType.DEPENDENCY_FAILURE)
            for index in range(FAILURE_THRESHOLD - 1)
        ]
    )
    assert ServiceFailureRule().evaluate(store, now) == []


def test_silent_on_the_normal_workflow(normal_workflow_store, now):
    """
    Purpose: the step-15 verification's silent half - a healthy stack raises
             nothing.
    Inputs:  the shared normal-traffic store and the evaluation moment.
    Output:  assertions.
    """
    assert ServiceFailureRule().evaluate(normal_workflow_store, now) == []
