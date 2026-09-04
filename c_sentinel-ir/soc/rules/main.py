"""
main.py - run the detection rules over a collected event stream.

Reuses `soc.collector.main` for the source and the store, then evaluates the
whole catalogue against it and prints every alert in `Description: value` style.
This is the command the demo runs after a scripted attack.

  python -m soc.rules.main --file docs/evidence/step15-attack-events.jsonl
  python -m soc.rules.main                    # the running stack's logs

`--now` pins the evaluation moment for a reproducible run over a captured file;
without it the rules reason from the current clock, which is what a live run
wants.

Author: Colile
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from soc.alert_service.dependencies import get_alert_store
from soc.alert_service.models import Alert
from soc.collector.main import build_store, select_source
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.catalogue import all_rules, evaluate_all


def persist_alerts(alerts: list[Alert], store: EventStore) -> int:
    """
    Purpose: hand every raised alert to the process-wide `AlertStore` the alert
             API serves from, and confirm each one's `relatedEvents` resolve to
             events actually in the collector's store - the step-16 "done when".
    Inputs:  alerts - the alerts the rules raised; store - the populated event
             store they were raised from.
    Output:  the number of alerts stored.
    Raises:  `ValueError` if an alert cites an event id the store does not hold,
             which would mean a rule built evidence that does not exist.
    """
    known_ids = {event.event_id for event in store.all_events()}
    for alert in alerts:
        dangling = set(alert.related_events) - known_ids
        if dangling:
            raise ValueError(
                f"alert {alert.alert_id} cites unknown event ids {sorted(dangling)}"
            )
    return get_alert_store().extend(alerts)


def latest_event_time(store: EventStore) -> datetime | None:
    """
    Purpose: the timestamp of the newest event held - the sensible evaluation
             moment for a captured file, whose events are all in the past.
    Inputs:  store - the populated event store.
    Output:  a UTC datetime, or None when the store is empty.
    """
    events = store.all_events()
    return parse_timestamp(events[-1].timestamp) if events else None


def _print_alert(alert: Alert) -> None:
    """
    Purpose: print one alert in the project's output style.
    Inputs:  alert - the alert to render.
    Output:  None; writes to stdout.
    """
    print("")
    print(f"Alert ID: {alert.alert_id}")
    print(f"Rule: {alert.rule_name}")
    print(f"Severity: {alert.severity.value}")
    print(f"Status: {alert.status.value}")
    print(f"Description: {alert.description}")
    print(f"Affected service: {alert.affected_service or 'not attributed'}")
    print(f"Affected user: {alert.affected_user or 'not attributed'}")
    print(f"Affected entity: {alert.affected_entity or 'not attributed'}")
    print(f"Related events: {len(alert.related_events)}")
    print(f"Recommended action: {alert.recommended_action}")


def _print_catalogue() -> None:
    """
    Purpose: print the rule catalogue - the seven documented properties of every
             rule, straight from the code rather than from a document that can
             drift away from it.
    Inputs:  none.
    Output:  None; writes to stdout.
    """
    for rule in all_rules():
        types = ", ".join(t.value for t in rule.input_event_types)
        print("")
        print(f"Rule: {rule.name}")
        print(f"Purpose: {rule.purpose}")
        print(f"Input events: {types}")
        print(f"Severity: {rule.severity.value}")
        print(f"Recommended action: {rule.recommended_action}")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """
    Purpose: define and parse the command line.
    Inputs:  argv - the argument list, or None for `sys.argv`.
    Output:  the parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="soc.rules.main",
        description="Run the SOC detection rules over a collected event stream.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="read newline-JSON events from this file instead of docker",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read events from standard input instead of docker",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="pin the evaluation moment, e.g. 2026-09-04T12:05:00Z; defaults to "
        "the newest event's timestamp for a file and the clock otherwise",
    )
    parser.add_argument(
        "--catalogue",
        action="store_true",
        help="print the rule catalogue and exit without evaluating",
    )
    return parser.parse_args(argv)


def _resolve_now(args: argparse.Namespace, store: EventStore) -> datetime:
    """
    Purpose: decide the moment the rules reason from.
    Inputs:  args - the parsed command line; store - the populated store.
    Output:  a timezone-aware UTC datetime.
    Raises:  `ValueError` when `--now` is not in the schema's timestamp format.
    """
    if args.now is not None:
        return parse_timestamp(args.now)
    if args.file is not None:
        return latest_event_time(store) or datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    """
    Purpose: wire the entry point together - collect, evaluate, report.
    Inputs:  argv - the argument list, or None for `sys.argv`.
    Output:  a process exit code: 0 when the run completed, 1 on a failure.
             Alerts raised are not a failure; a rule firing is the tool working.
    """
    args = _parse_args(argv)
    if args.catalogue:
        _print_catalogue()
        return 0
    try:
        store = build_store(select_source(args))
        now = _resolve_now(args, store)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Detection failed: {exc}", file=sys.stderr)
        return 1

    alerts = evaluate_all(store, now)
    try:
        stored = persist_alerts(alerts, store)
    except ValueError as exc:
        print(f"Detection failed: {exc}", file=sys.stderr)
        return 1
    print(f"Events evaluated: {len(store)}")
    print(f"Evaluation moment: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"Alerts raised: {len(alerts)}")
    print(f"Alerts stored: {stored} (every related event resolves)")
    for alert in alerts:
        _print_alert(alert)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
