"""
test_rule_unauthorised_access.py - Rule 2 fires on endpoint probing and stays
silent on normal traffic.

Both directions, plus the two behaviours that are easy to get wrong: the rise to
HIGH on a privileged route, and the deliberate exclusion of `AUTH_FAILED`, which
also carries a 401 but belongs to Rule 1.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import timedelta

from common.events import EventType, Severity
from soc.rules.rule_unauthorised_access import (
    REFUSAL_THRESHOLD,
    UnauthorisedAccessRule,
)
from soc.rules.tests.conftest import NOW, event_at, store_of


def _refusal(seconds_ago: int, endpoint: str, status_code: int = 403, **overrides):
    """
    Purpose: one refusal event as the gateway or a service emits it.
    Inputs:  seconds_ago - how far before `NOW`; endpoint - the probed path;
             status_code - 401 or 403; overrides - other field values.
    Output:  a validated `SecurityEvent`.
    """
    defaults = dict(
        service_name="api-gateway",
        event_type=EventType.UNAUTHORISED_ACCESS,
        severity=Severity.MEDIUM,
        endpoint=endpoint,
        http_method="GET",
        status_code=status_code,
        user_id="analyst-9",
        source_ip="203.0.113.44",
        correlation_id=f"corr-probe-{seconds_ago}",
        message="Request refused.",
    )
    defaults.update(overrides)
    return event_at(NOW - timedelta(seconds=seconds_ago), **defaults)


def test_fires_on_repeated_refusals_from_one_user(now):
    """
    Purpose: three refusals from one subject inside the window raise a MEDIUM
             alert citing all three.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _refusal(300, "/api/v1/incidents"),
            _refusal(200, "/api/v1/assets"),
            _refusal(100, "/api/v1/incidents/7"),
        ]
    )
    alerts = UnauthorisedAccessRule().evaluate(store, now)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity is Severity.MEDIUM
    assert alert.rule_name == "Unauthorised Endpoint Access"
    assert len(alert.related_events) == REFUSAL_THRESHOLD
    assert alert.affected_user == "analyst-9"
    assert "3 endpoints" in alert.description


def test_rises_to_high_on_a_privileged_route(now):
    """
    Purpose: probing the admin surface is a materially worse finding, so the
             severity rises and the alert names the privileged path.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _refusal(300, "/api/v1/incidents"),
            _refusal(200, "/api/v1/assets"),
            _refusal(100, "/api/v1/auth/users"),
        ]
    )
    alerts = UnauthorisedAccessRule().evaluate(store, now)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity is Severity.HIGH
    assert "/api/v1/auth/users" in alert.description
    assert alert.affected_entity == "/api/v1/auth/users"


def test_a_service_raised_403_counts_even_though_the_gateway_never_saw_it(now):
    """
    Purpose: an analyst refused by `require_admin` inside auth-service produces a
             403 with no `UNAUTHORISED_ACCESS` event, because the gateway passed
             the request through. The rule must still see it - that is the
             privilege-escalation attempt it exists to catch.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _refusal(
                300 - index * 100,
                "/api/v1/auth/users",
                service_name="auth-service",
                event_type=EventType.REQUEST_COMPLETED,
            )
            for index in range(3)
        ]
    )
    alerts = UnauthorisedAccessRule().evaluate(store, now)
    assert len(alerts) == 1
    assert alerts[0].severity is Severity.HIGH


def test_failed_logins_are_left_to_rule_one(now):
    """
    Purpose: `AUTH_FAILED` carries a 401 but is an authentication failure, not an
             authorisation refusal. Counting it here would make every brute-force
             run fire two rules for one attack.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _refusal(
                300 - index * 50,
                "/api/v1/auth/login",
                status_code=401,
                service_name="auth-service",
                event_type=EventType.AUTH_FAILED,
                http_method="POST",
            )
            for index in range(6)
        ]
    )
    assert UnauthorisedAccessRule().evaluate(store, now) == []


def test_a_request_with_no_token_is_grouped_by_source_address(now):
    """
    Purpose: a request refused for carrying no token names no user, so the rule
             falls back to the source address rather than losing the evidence.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _refusal(300 - index * 100, "/api/v1/incidents", user_id=None)
            for index in range(3)
        ]
    )
    alerts = UnauthorisedAccessRule().evaluate(store, now)
    assert len(alerts) == 1
    assert "203.0.113.44" in alerts[0].description


def test_two_refusals_do_not_fire(now):
    """
    Purpose: below the threshold the rule stays silent - two refusals are an
             expired token, not a probe.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of([_refusal(300, "/api/v1/incidents"), _refusal(200, "/api/v1/assets")])
    assert UnauthorisedAccessRule().evaluate(store, now) == []


def test_silent_on_the_normal_workflow(normal_workflow_store, now):
    """
    Purpose: the step-15 verification's silent half - a clean workflow with one
             expired-token bounce raises nothing.
    Inputs:  the shared normal-traffic store and the evaluation moment.
    Output:  assertions.
    """
    assert UnauthorisedAccessRule().evaluate(normal_workflow_store, now) == []
