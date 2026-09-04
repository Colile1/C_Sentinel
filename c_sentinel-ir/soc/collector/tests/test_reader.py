"""
test_reader.py - the reader filters the mixed log stream correctly.

Proves: an application log line is skipped, a valid event line becomes a
`SecurityEvent`, a line that claims to be an event but breaks the schema
raises, and the committed evidence samples still parse.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.events import EventType, build_event
from soc.collector.reader import (
    MalformedEventError,
    parse_event_line,
    stream_events,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"


def _event_json_line(**overrides) -> str:
    """
    Purpose: a valid event line in the on-the-wire camelCase schema.
    Inputs:  overrides - fields to replace on the default event.
    Output:  a JSON string, no trailing newline.
    """
    defaults = dict(
        service_name="auth-service",
        event_type=EventType.AUTH_FAILED,
        severity="MEDIUM",
        endpoint="/api/v1/auth/login",
        http_method="POST",
        status_code=401,
        message="Authentication failed for user alice.",
        correlation_id="corr-test-0001",
        user_id="alice",
        source_ip="10.0.0.5",
    )
    defaults.update(overrides)
    event = build_event(**defaults)
    return json.dumps(event.to_json_dict())


def test_application_log_line_is_skipped():
    """
    Purpose: a line with `level` and `logger` but no `eventType` is not an
             event and yields nothing.
    Inputs:  none.
    Output:  assertions.
    """
    app_line = json.dumps(
        {
            "timestamp": "2026-09-04T05:05:19Z",
            "level": "INFO",
            "serviceName": "incident-service",
            "logger": "httpx",
            "message": "HTTP Request: GET http://asset-service:8003/... 200 OK",
            "correlationId": "corr-332de1db16a547a4",
        }
    )
    assert parse_event_line(app_line) is None


def test_blank_and_non_json_lines_are_skipped():
    """
    Purpose: empty lines and plain-text noise in the stream are ignored.
    Inputs:  none.
    Output:  assertions.
    """
    assert parse_event_line("") is None
    assert parse_event_line("   ") is None
    assert parse_event_line("incident-service  | Uvicorn running") is None


def test_valid_event_line_becomes_a_security_event():
    """
    Purpose: a well-formed event line parses to a `SecurityEvent` with its
             fields intact.
    Inputs:  none.
    Output:  assertions.
    """
    event = parse_event_line(_event_json_line())
    assert event is not None
    assert event.event_type is EventType.AUTH_FAILED
    assert event.user_id == "alice"
    assert event.correlation_id == "corr-test-0001"


def test_line_with_eventtype_but_bad_severity_raises():
    """
    Purpose: a line that identifies as an event and fails validation raises
             `MalformedEventError` rather than being dropped.
    Inputs:  none.
    Output:  assertions.
    """
    obj = json.loads(_event_json_line())
    obj["severity"] = "WHENEVER"
    with pytest.raises(MalformedEventError):
        parse_event_line(json.dumps(obj))


def test_line_with_extra_key_raises():
    """
    Purpose: an event line carrying a key outside the schema is malformed, not
             merely ignored - the schema forbids extras.
    Inputs:  none.
    Output:  assertions.
    """
    obj = json.loads(_event_json_line())
    obj["attackerNote"] = "hello"
    with pytest.raises(MalformedEventError):
        parse_event_line(json.dumps(obj))


def test_stream_events_filters_a_mixed_stream():
    """
    Purpose: `stream_events` over a realistic mix yields only the events, in
             order.
    Inputs:  none.
    Output:  assertions.
    """
    lines = [
        "",
        json.dumps({"level": "INFO", "logger": "uvicorn", "message": "start"}),
        _event_json_line(correlation_id="corr-a", message="First failure."),
        "incident-service | plain text line",
        _event_json_line(correlation_id="corr-b", message="Second failure."),
    ]
    events = list(stream_events(lines))
    assert [e.correlation_id for e in events] == ["corr-a", "corr-b"]


@pytest.mark.parametrize(
    "sample_file",
    sorted(p.name for p in EVIDENCE_DIR.glob("*.jsonl")),
)
def test_committed_evidence_samples_parse(sample_file):
    """
    Purpose: every event line in the real captured evidence still reads through
             the collector unchanged - a regression guard shared with
             tests/contract/test_event_emission.py.
    Inputs:  sample_file - one *.jsonl file name under docs/evidence.
    Output:  assertions.
    """
    raw = (EVIDENCE_DIR / sample_file).read_text(encoding="utf-8")
    events = list(stream_events(raw.splitlines()))
    # Each file holds at least one event line among the application lines.
    assert events, f"{sample_file}: no events recovered"
    for event in events:
        assert event.correlation_id
