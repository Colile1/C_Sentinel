"""
test_rule_abnormal_rate.py - Rule 3 fires on a flood and stays silent on normal
traffic.

Both signals are tested independently, because either alone must be enough: the
gateway-refusal signal fires when Kong absorbs the burst and almost nothing
reaches a service, and the volume signal fires when the traffic gets through.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import timedelta

from common.events import EventType, Severity
from soc.rules.rule_abnormal_rate import (
    RATE_LIMIT_THRESHOLD,
    REQUEST_THRESHOLD,
    AbnormalRequestRateRule,
)
from soc.rules.tests.conftest import NOW, event_at, store_of


def _request(seconds_ago: float, source_ip: str = "203.0.113.77", **overrides):
    """
    Purpose: one inbound request event.
    Inputs:  seconds_ago - how far before `NOW`; source_ip - the client address;
             overrides - other field values.
    Output:  a validated `SecurityEvent`.
    """
    defaults = dict(
        event_type=EventType.REQUEST_RECEIVED,
        source_ip=source_ip,
        user_id=None,
        correlation_id=f"corr-flood-{seconds_ago}",
        message="Request received.",
    )
    defaults.update(overrides)
    return event_at(NOW - timedelta(seconds=seconds_ago), **defaults)


def _throttled(seconds_ago: float, source_ip: str = "203.0.113.77"):
    """
    Purpose: one `RATE_LIMIT_EXCEEDED` event as the gateway emits it.
    Inputs:  seconds_ago - how far before `NOW`; source_ip - the client address.
    Output:  a validated `SecurityEvent`.
    """
    return _request(
        seconds_ago,
        source_ip,
        service_name="api-gateway",
        event_type=EventType.RATE_LIMIT_EXCEEDED,
        severity=Severity.MEDIUM,
        status_code=429,
        message="Request refused: rate limit exceeded.",
    )


def test_fires_on_request_volume(now):
    """
    Purpose: one source exceeding the volume threshold inside the window raises a
             HIGH alert citing every request.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_request(50 - index) for index in range(REQUEST_THRESHOLD)]
    )
    alerts = AbnormalRequestRateRule().evaluate(store, now)

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.severity is Severity.HIGH
    assert alert.rule_name == "Abnormal Request Rate"
    assert alert.affected_entity == "203.0.113.77"
    assert len(alert.related_events) == REQUEST_THRESHOLD
    assert "requests received" in alert.description


def test_fires_on_gateway_rate_limit_refusals_alone(now):
    """
    Purpose: the signal the demo depends on. Kong refuses the burst, so only a
             handful of 429s exist and no service ever sees the volume - and the
             rule must still fire.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_throttled(50 - index) for index in range(RATE_LIMIT_THRESHOLD)]
    )
    alerts = AbnormalRequestRateRule().evaluate(store, now)

    assert len(alerts) == 1
    assert "refused by the gateway" in alerts[0].description
    assert len(alerts[0].related_events) == RATE_LIMIT_THRESHOLD


def test_one_alert_names_both_signals_when_both_fire(now):
    """
    Purpose: a flood that is both high-volume and repeatedly throttled is one
             finding, not two, and the alert says so.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_request(55 - index) for index in range(REQUEST_THRESHOLD)]
        + [_throttled(20 - index) for index in range(RATE_LIMIT_THRESHOLD)]
    )
    alerts = AbnormalRequestRateRule().evaluate(store, now)

    assert len(alerts) == 1
    assert " and " in alerts[0].description
    assert len(alerts[0].related_events) == REQUEST_THRESHOLD + RATE_LIMIT_THRESHOLD


def test_volume_spread_beyond_the_window_does_not_fire(now):
    """
    Purpose: the same number of requests spread over an hour is a working day,
             not a flood. Only the window counts.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [_request(60 + index * 60) for index in range(REQUEST_THRESHOLD)]
    )
    assert AbnormalRequestRateRule().evaluate(store, now) == []


def test_volume_is_measured_per_source_not_per_service(now):
    """
    Purpose: a service busy with many *different* clients is busy, not attacked.
             Splitting the same volume across sources fires nothing.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    store = store_of(
        [
            _request(50 - index * 0.5, source_ip=f"10.0.0.{index % 20}")
            for index in range(REQUEST_THRESHOLD * 2)
        ]
    )
    assert AbnormalRequestRateRule().evaluate(store, now) == []


def test_a_single_throttled_request_does_not_fire(now):
    """
    Purpose: one 429 is a client that mistimed a burst.
    Inputs:  the fixed evaluation moment.
    Output:  assertions.
    """
    assert AbnormalRequestRateRule().evaluate(store_of([_throttled(30)]), now) == []


def test_silent_on_the_normal_workflow(normal_workflow_store, now):
    """
    Purpose: the step-15 verification's silent half - steady analyst traffic
             raises nothing.
    Inputs:  the shared normal-traffic store and the evaluation moment.
    Output:  assertions.
    """
    assert AbnormalRequestRateRule().evaluate(normal_workflow_store, now) == []
