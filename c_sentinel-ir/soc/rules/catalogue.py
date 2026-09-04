"""
catalogue.py - the registry of detection rules, and the runner over it.

`all_rules()` is the single list every consumer iterates: the runner below, the
step-20 rule catalogue in the documentation, and the knowledge-graph loader when
it projects rules into the graph. A rule that is not in this list does not exist
as far as the system is concerned, so adding a rule file is two edits, not one.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime

from soc.alert_service.models import Alert
from soc.collector.store import EventStore
from soc.rules.base import DetectionRule
from soc.rules.rule_abnormal_rate import AbnormalRequestRateRule
from soc.rules.rule_failed_logins import MultipleFailedLoginsRule
from soc.rules.rule_service_failure import ServiceFailureRule
from soc.rules.rule_unauthorised_access import UnauthorisedAccessRule


def all_rules() -> list[DetectionRule]:
    """
    Purpose: every detection rule the SOC layer runs, in the order the
             specification names them.
    Inputs:  none.
    Output:  a new list of freshly constructed `DetectionRule` instances. Fresh
             instances because a rule holds no state between evaluations and
             sharing one across callers would be an invitation to add some.
    """
    return [
        MultipleFailedLoginsRule(),
        UnauthorisedAccessRule(),
        AbnormalRequestRateRule(),
        ServiceFailureRule(),
    ]


def evaluate_all(
    store: EventStore, now: datetime, rules: list[DetectionRule] | None = None
) -> list[Alert]:
    """
    Purpose: run every rule over one store and gather the alerts.
    Inputs:  store - the collector's populated `EventStore`; now - the UTC
             evaluation moment, passed to every rule so one run reasons about
             one instant; rules - an override for tests, defaulting to the whole
             catalogue.
    Output:  every alert raised, in catalogue order.
    """
    alerts: list[Alert] = []
    for rule in rules if rules is not None else all_rules():
        alerts.extend(rule.evaluate(store, now))
    return alerts
