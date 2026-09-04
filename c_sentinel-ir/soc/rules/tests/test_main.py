"""
test_main.py - the rule runner collects, evaluates and reports.

The two tests that carry weight are at the end: the committed scripted attack
raises all four rules, and the committed *real* workflow capture from step 12 -
lines taken off the running stack, not written for this test - raises nothing.
That pair is the build order's step-15 verification against real data.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from soc.alert_service.dependencies import get_alert_store
from soc.collector.main import build_store
from soc.rules.catalogue import evaluate_all
from soc.rules.main import main, persist_alerts

_EVIDENCE = Path(__file__).resolve().parents[3] / "docs" / "evidence"
_ATTACK_STREAM = _EVIDENCE / "step15-attack-events.jsonl"
_WORKFLOW_STREAM = _EVIDENCE / "step12-correlated-logs.jsonl"


def _store_from(path: Path):
    """
    Purpose: build an `EventStore` from a committed evidence file.
    Inputs:  path - the newline-JSON file to read.
    Output:  a populated `EventStore`.
    """
    with path.open(encoding="utf-8") as handle:
        return build_store(handle)


def test_catalogue_option_prints_every_documented_property(capsys):
    """
    Purpose: `--catalogue` prints the rule catalogue from the code, so the
             documentation of the rules cannot drift away from the rules.
    Inputs:  capsys.
    Output:  assertions.
    """
    assert main(["--catalogue"]) == 0
    out = capsys.readouterr().out
    for heading in ("Rule:", "Purpose:", "Input events:", "Severity:",
                    "Recommended action:"):
        assert heading in out
    assert "Multiple Failed Logins" in out
    assert "Service Failure" in out


def test_main_reports_failure_on_a_missing_file(tmp_path, capsys):
    """
    Purpose: a missing source is a failure, exit 1, message on stderr.
    Inputs:  tmp_path, capsys.
    Output:  assertions.
    """
    assert main(["--file", str(tmp_path / "nope.jsonl")]) == 1
    assert "Detection failed" in capsys.readouterr().err


def test_main_rejects_a_malformed_now(capsys):
    """
    Purpose: a `--now` the schema cannot parse fails loudly rather than silently
             evaluating against the wrong instant.
    Inputs:  capsys.
    Output:  assertions.
    """
    assert main(["--file", str(_ATTACK_STREAM), "--now", "yesterday"]) == 1
    assert "Detection failed" in capsys.readouterr().err


@pytest.mark.skipif(
    not _ATTACK_STREAM.exists(),
    reason="regenerate with python scripts/capture_attack_evidence.py",
)
def test_the_committed_attack_raises_every_rule(capsys):
    """
    Purpose: the firing half of the step-15 verification, run through the command
             the demo runs, over the committed scripted attack.
    Inputs:  capsys.
    Output:  assertions.
    """
    assert main(["--file", str(_ATTACK_STREAM)]) == 0
    out = capsys.readouterr().out
    assert "Events evaluated: 22" in out
    assert "every related event resolves" in out
    for rule_name in (
        "Multiple Failed Logins",
        "Unauthorised Endpoint Access",
        "Abnormal Request Rate",
        "Service Failure",
    ):
        assert rule_name in out


def test_persist_alerts_stores_every_alert_and_its_events_resolve():
    """
    Purpose: the step-16 handover, run through the CLI's own helper - every
             alert a real attack raises lands in the alert store, and every id
             in its `relatedEvents` is an event the collector actually holds.
    Inputs:  none.
    Output:  assertions.
    """
    store = _store_from(_ATTACK_STREAM)
    events = store.all_events()
    latest = datetime.strptime(
        events[-1].timestamp, "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    alerts = evaluate_all(store, latest)
    assert alerts

    stored = persist_alerts(alerts, store)
    assert stored == len(alerts)

    alert_store = get_alert_store()
    known_event_ids = {event.event_id for event in events}
    for alert in alerts:
        held = alert_store.get(alert.alert_id)
        assert held.related_events
        assert set(held.related_events) <= known_event_ids


def test_persist_alerts_rejects_an_alert_citing_an_unknown_event():
    """
    Purpose: a rule that built evidence from an event not in the store is a bug,
             and `persist_alerts` refuses it rather than storing a dangling
             citation the graph loader would later trip over.
    Inputs:  none.
    Output:  assertions.
    """
    from datetime import datetime as _dt, timezone as _tz

    from common.events import Severity
    from soc.alert_service.models import Alert
    from soc.collector.store import EventStore

    orphan = Alert(
        timestamp="2026-09-04T12:00:00Z",
        rule_name="Multiple Failed Logins",
        severity=Severity.HIGH,
        description="cites an event that is not in the store",
        related_events=("evt-ffffffffffff",),
        recommended_action="none",
    )
    with pytest.raises(ValueError, match="unknown event ids"):
        persist_alerts([orphan], EventStore())


@pytest.mark.skipif(
    not _WORKFLOW_STREAM.exists(),
    reason="regenerate with python scripts/capture_evidence.py against the stack",
)
def test_no_rule_fires_on_the_real_captured_workflow():
    """
    Purpose: the silent half, against real data - the step-12 capture is a live
             `demo_workflow` run taken off the running stack's logs, so this
             proves the rules sleep through genuine traffic rather than through
             traffic written to make them sleep.
    Inputs:  none.
    Output:  assertions.
    """
    store = _store_from(_WORKFLOW_STREAM)
    assert len(store) > 0, "the step-12 capture should hold events"
    events = store.all_events()
    latest = datetime.strptime(
        events[-1].timestamp, "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=timezone.utc)
    assert evaluate_all(store, latest) == []
