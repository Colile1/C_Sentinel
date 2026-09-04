"""
conftest.py - fixture rows shaped exactly as the five `.cypher` files return.

Every row here mirrors one query's RETURN clause, so the retrieval and
generation tests run with no Neo4j. The shapes are not invented: they are the
column names in `kg/cypher/q1..q5_*.cypher`, and `test_row_shapes.py` asserts
they still match those files - so if a query renames a column, these fixtures
fail rather than silently testing a shape the system no longer produces.

Author: Colile
"""

from __future__ import annotations

from typing import Any

import pytest

ALERT_ID = "alt-0123456789ab"


@pytest.fixture
def q4_rows() -> list[dict[str, Any]]:
    """
    Purpose: a `controls_for_alert` result - the demo question's evidence.
    Inputs:  none.
    Output:  one row, as q4 returns it.
    """
    return [
        {
            "alertId": ALERT_ID,
            "ruleName": "Multiple Failed Logins",
            "techniqueId": "T1110",
            "technique": "Brute Force",
            "controls": ["Account Lockout Policy", "Multi-Factor Authentication"],
            "runbooks": ["Runbook: Credential Attack Response"],
            "ruleRecommendedAction": "Lock the account and review the source address",
        }
    ]


@pytest.fixture
def q1_rows() -> list[dict[str, Any]]:
    """
    Purpose: an `alerts_for_service` result.
    Inputs:  none.
    Output:  two rows, as q1 returns them.
    """
    return [
        {
            "alertId": ALERT_ID,
            "ruleName": "Multiple Failed Logins",
            "severity": "HIGH",
            "status": "OPEN",
            "description": "5 failed logins for analyst1 within 5 minutes",
            "recommendedAction": "Lock the account",
            "timestamp": "2026-09-04T10:00:00Z",
        },
        {
            "alertId": "alt-ffffffffffff",
            "ruleName": "Abnormal Request Rate",
            "severity": "MEDIUM",
            "status": "OPEN",
            "description": "90 requests in 60 seconds from 10.0.0.5",
            "recommendedAction": "Throttle the source address",
            "timestamp": "2026-09-04T09:00:00Z",
        },
    ]


@pytest.fixture
def q3_rows() -> list[dict[str, Any]]:
    """
    Purpose: a `threats_for_service` result.
    Inputs:  none.
    Output:  one row, as q3 returns it.
    """
    return [
        {
            "techniqueId": "T1110",
            "technique": "Brute Force",
            "tactic": "Credential Access",
            "exploitsVulnerabilities": ["Weak password policy"],
            "mitigatedBy": ["Account Lockout Policy", "Multi-Factor Authentication"],
        }
    ]


@pytest.fixture
def q2_rows() -> list[dict[str, Any]]:
    """
    Purpose: a `users_high_severity` result.
    Inputs:  none.
    Output:  one row, as q2 returns it.
    """
    return [
        {
            "username": "analyst1",
            "role": "ANALYST",
            "ruleName": "Multiple Failed Logins",
            "severity": "HIGH",
            "evidenceEvents": ["evt-aaaaaaaaaaaa", "evt-bbbbbbbbbbbb"],
            "alertCount": 1,
        }
    ]


@pytest.fixture
def q5_rows() -> list[dict[str, Any]]:
    """
    Purpose: a `dependency_impact` result.
    Inputs:  none.
    Output:  one row, as q5 returns it.
    """
    return [{"impactedService": "incident-service", "hops": 1}]


@pytest.fixture
def runner_for():
    """
    Purpose: build a `retrieve` runner that returns fixed rows and records the
             query text and parameters it was called with - so a test asserts
             the parameters were bound, not interpolated.
    Inputs:  none.
    Output:  a factory taking rows and returning (runner, calls list).
    """

    def factory(rows: list[dict[str, Any]]):
        calls: list[tuple[str, dict[str, Any]]] = []

        def runner(cypher: str, **parameters: Any) -> list[dict[str, Any]]:
            calls.append((cypher, parameters))
            return rows

        return runner, calls

    return factory
