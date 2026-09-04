"""
test_rule_failed_logins.py - Rule 1 fires on a brute-force run and stays silent
on normal traffic.

Both directions, as the build order requires. The attack scenarios are the two
shapes a real brute-force run takes: one account hammered from one address, and
one address trying a fresh invented username each attempt.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import timedelta

from common.events import EventType, Severity
from soc.rules.rule_failed_logins import (
    DETECTION_WINDOW,
    FAILURE_THRESHOLD,
    MultipleFailedLoginsRule,
)
from soc.rules.tests.conftest import NOW, event_at, store_of


def _failed_login(seconds_ago: int, user_id: str, source_ip: str):
    """
    Purpose: one `AUTH_FAILED` event as auth-service emits it.
    Inputs:  seconds_ago - how far before `NOW`; user_id - the attempted
             username; source_ip - the client address.
    Output:  a validated `SecurityEvent`.
    """
    return event_at(
        NOW - timedelta(seconds=seconds_ago),
        service_name="auth-service",
        event_type=EventType.AUTH_FAILED,
        severity=Severity.MEDIUM,
        endpoint="/api/v1/auth/login",
        http_method="POST",
        status_code=401,
        user_id=user_id,
        source_ip=source_ip,
        correlation_id=f"corr-attack-{seconds_ago}",
        message="Authentication failed.",
    )


def test_fires_on_five_failures_against_one_account(now):
    """
    Purpose: the specification's threshold - five failed logins for one user
             inside five minutes raises a HIGH alert citing all five.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_failed_login(200 - i * 20, "analyst-1", "203.0.113.9") for i in range(5)]
    )
    alerts = MultipleFailedLoginsRule().evaluate(store, now)

    # Two alerts: one keyed on the account, one on the address. Take the
    # account's - it is the one whose description names the user.
    account_alerts = [a for a in alerts if "'analyst-1'" in a.description]
    assert len(account_alerts) == 1
    alert = account_alerts[0]
    assert alert.severity is Severity.HIGH
    assert alert.rule_name == "Multiple Failed Logins"
    assert len(alert.related_events) == FAILURE_THRESHOLD
    assert alert.affected_entity == "login-endpoint"
    assert "block the source IP" in alert.recommended_action


def test_fires_on_one_address_trying_invented_usernames(now):
    """
    Purpose: the half of the rule that keys on source IP. Five failures from one
             address against five *different* usernames trips no per-account
             threshold, but is unmistakably an attack.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _failed_login(200 - i * 20, f"invented-{i}", "203.0.113.9")
            for i in range(5)
        ]
    )
    alerts = MultipleFailedLoginsRule().evaluate(store, now)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.affected_entity == "login-endpoint"
    assert alert.affected_user is None
    assert "203.0.113.9" in alert.description
    assert "5 username" in alert.description


def test_stays_below_the_threshold_at_four_failures(now):
    """
    Purpose: the threshold is a threshold - four failures raise nothing, so the
             rule cannot be firing on a count it was not given.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_failed_login(200 - i * 20, "analyst-1", "203.0.113.9") for i in range(4)]
    )
    assert MultipleFailedLoginsRule().evaluate(store, now) == []


def test_failures_spread_beyond_the_window_do_not_fire(now):
    """
    Purpose: five failures spread over an hour are a forgetful user, not an
             attack. Only the ones inside the window count.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    window_seconds = int(DETECTION_WINDOW.total_seconds())
    store = store_of(
        [
            _failed_login(window_seconds * (i + 1), "analyst-1", "203.0.113.9")
            for i in range(5)
        ]
    )
    assert MultipleFailedLoginsRule().evaluate(store, now) == []


def test_one_burst_from_one_address_reports_both_findings(now):
    """
    Purpose: a burst against one account from one address is two findings - the
             account is under attack, and the address is attacking - and the rule
             says so explicitly rather than collapsing them.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_failed_login(200 - i * 20, "analyst-1", "203.0.113.9") for i in range(5)]
    )
    alerts = MultipleFailedLoginsRule().evaluate(store, now)
    assert len(alerts) == 2
    assert {a.affected_user for a in alerts} == {"analyst-1"}
    assert any("203.0.113.9" in a.description for a in alerts)


def test_silent_on_the_normal_workflow(normal_workflow_store, now):
    """
    Purpose: the other half of the step-15 verification - a clean demo workflow,
             including one mistyped password, raises nothing.
    Inputs:  the shared normal-traffic store and the evaluation moment.
    Output:  assertions.
    """
    assert MultipleFailedLoginsRule().evaluate(normal_workflow_store, now) == []
