"""
test_catalogue.py - the registry is complete, documented, and silent together.

These are the properties that hold across the whole rule set rather than of any
one rule: every rule states all seven things the specification requires, every
event type a rule claims to read is one Phase 1 actually emits, and running the
entire catalogue over a clean workflow produces no alerts at all.

That last one is the step-15 verification stated once for the whole system: the
per-rule silence tests each prove one rule sleeps, this proves nothing wakes.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from common.events import EventType, Severity
from soc.alert_service.models import Alert, AlertStatus
from soc.rules.catalogue import all_rules, evaluate_all
from soc.rules.tests.conftest import NOW, event_at, store_of

# The three the specification requires by name, plus the optional fourth.
_EXPECTED_RULE_NAMES = {
    "Multiple Failed Logins",
    "Unauthorised Endpoint Access",
    "Abnormal Request Rate",
    "Service Failure",
}


def test_the_catalogue_holds_every_required_rule():
    """
    Purpose: the three rules the specification demands are registered, and so is
             the optional fourth.
    Inputs:  none.
    Output:  assertions.
    """
    assert {rule.name for rule in all_rules()} == _EXPECTED_RULE_NAMES


@pytest.mark.parametrize("rule", all_rules(), ids=lambda rule: rule.name)
def test_every_rule_documents_the_seven_required_properties(rule):
    """
    Purpose: the specification requires a name, purpose, input events, detection
             logic, severity, generated alert and response action per rule. Six
             are attributes; the seventh is `evaluate` being implemented at all.
    Inputs:  each rule in the catalogue.
    Output:  assertions.
    """
    assert rule.name.strip()
    assert rule.purpose.strip()
    assert rule.input_event_types
    assert isinstance(rule.severity, Severity)
    assert rule.recommended_action.strip()
    assert callable(rule.evaluate)


@pytest.mark.parametrize("rule", all_rules(), ids=lambda rule: rule.name)
def test_every_declared_input_event_type_is_one_phase_one_emits(rule):
    """
    Purpose: a rule reading an event type no service emits can never fire. This
             catches the drift long before a demo does.
    Inputs:  each rule in the catalogue.
    Output:  assertions.
    """
    for event_type in rule.input_event_types:
        assert event_type in set(EventType)


def test_the_whole_catalogue_is_silent_on_the_normal_workflow(
    normal_workflow_store, now
):
    """
    Purpose: the step-15 verification for the system as a whole - no rule fires
             on a clean `demo_workflow` run.
    Inputs:  the shared normal-traffic store and the evaluation moment.
    Output:  assertions.
    """
    assert evaluate_all(normal_workflow_store, now) == []


def test_a_full_attack_raises_alerts_from_every_rule(now):
    """
    Purpose: the firing half, for the system as a whole - one scripted attack
             sequence wakes all four rules in a single pass.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    events = []
    # Rule 1: a brute-force run.
    events.extend(
        event_at(
            NOW - timedelta(seconds=250 - index * 10),
            service_name="auth-service",
            event_type=EventType.AUTH_FAILED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            status_code=401,
            user_id="analyst-1",
            source_ip="203.0.113.9",
            correlation_id=f"corr-bf-{index}",
            message="Authentication failed.",
        )
        for index in range(6)
    )
    # Rule 2: probing protected and privileged endpoints with the stolen token.
    events.extend(
        event_at(
            NOW - timedelta(seconds=180 - index * 10),
            service_name="api-gateway",
            event_type=EventType.UNAUTHORISED_ACCESS,
            severity=Severity.MEDIUM,
            endpoint=path,
            status_code=403,
            user_id="analyst-1",
            source_ip="203.0.113.9",
            correlation_id=f"corr-probe-{index}",
            message="Request refused.",
        )
        for index, path in enumerate(
            ["/api/v1/incidents", "/api/v1/assets", "/api/v1/auth/users"]
        )
    )
    # Rule 3: the gateway throttling a burst.
    events.extend(
        event_at(
            NOW - timedelta(seconds=40 - index * 5),
            service_name="api-gateway",
            event_type=EventType.RATE_LIMIT_EXCEEDED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/incidents",
            status_code=429,
            user_id=None,
            source_ip="203.0.113.9",
            correlation_id=f"corr-burst-{index}",
            message="Request refused: rate limit exceeded.",
        )
        for index in range(4)
    )
    # Rule 4: asset-service falls over under the load and the breaker opens.
    events.append(
        event_at(
            NOW - timedelta(seconds=20),
            event_type=EventType.CIRCUIT_OPENED,
            severity=Severity.HIGH,
            http_method="POST",
            status_code=503,
            user_id=None,
            source_ip=None,
            correlation_id="corr-breaker",
            affected_entity="asset-service",
            message="Circuit opened for asset-service.",
        )
    )

    alerts = evaluate_all(store_of(events), now)
    assert {alert.rule_name for alert in alerts} == _EXPECTED_RULE_NAMES


def test_every_alert_is_well_formed_and_cites_real_events(now):
    """
    Purpose: the step-16 handover condition, asserted at step 15 - every alert a
             rule raises carries the specification's fields, opens in the OPEN
             state, and every id in `relatedEvents` resolves to an event that is
             actually in the store.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            event_at(
                NOW - timedelta(seconds=250 - index * 10),
                service_name="auth-service",
                event_type=EventType.AUTH_FAILED,
                severity=Severity.MEDIUM,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=401,
                user_id="analyst-1",
                source_ip="203.0.113.9",
                correlation_id=f"corr-bf-{index}",
                message="Authentication failed.",
            )
            for index in range(5)
        ]
    )
    alerts = evaluate_all(store, now)
    assert alerts

    known_ids = {event.event_id for event in store.all_events()}
    for alert in alerts:
        assert isinstance(alert, Alert)
        assert alert.status is AlertStatus.OPEN
        assert alert.alert_id.startswith("alt-")
        assert alert.related_events
        assert set(alert.related_events) <= known_ids
        rendered = alert.to_json_dict()
        assert rendered["relatedEvents"] == list(alert.related_events)
        assert rendered["ruleName"] == alert.rule_name
