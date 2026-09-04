"""
test_gateway_source.py - the gateway is a live collector source (D-36).

Proves the contract between `gateway/kong.yml`'s file-log plugin and
`soc/collector/reader.py`: the lines Kong actually emitted during the step-21
capture parse into gateway `SecurityEvent`s, and the plugin's Lua still names
every field the schema requires and prunes every field Kong would otherwise
add.

The regression these guard against is specific and was hit twice while the
plugin was being written. `libs/common/events.py` sets `extra="forbid"`, so a
single unpruned key - Kong's own `source`, or the correlation-id plugin's
snake_case `correlation_id` - makes the reader raise `MalformedEventError` on
*every* gateway line, which takes the whole collector run down with it. A
future plugin that adds a serializer field will break the same way, so the
prune list is asserted here rather than left to a live run to discover.

Runs without a container, a network or a database: the Kong config is read as
text and the event lines come from the committed evidence capture.

Author: Colile
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.events import EventType, ServiceName
from soc.collector.reader import parse_event_line, stream_events

REPO_ROOT = Path(__file__).resolve().parents[3]
KONG_CONFIG = REPO_ROOT / "gateway" / "kong.yml"
EVIDENCE = REPO_ROOT / "docs" / "evidence" / "step21-gateway-source.txt"

# The statuses the plugin turns into events, and the type each one carries.
_REFUSAL_EVENT_TYPES = {
    401: EventType.UNAUTHORISED_ACCESS,
    403: EventType.UNAUTHORISED_ACCESS,
    429: EventType.RATE_LIMIT_EXCEEDED,
}


def _gateway_lines() -> list[str]:
    """
    Purpose: the real Kong event lines from the step-21 capture.
    Inputs:  none; reads the committed evidence file.
    Output:  a list of raw JSON lines, each one a gateway event.
    """
    text = EVIDENCE.read_text(encoding="utf-8")
    return [
        line
        for line in text.splitlines()
        if line.startswith("{") and '"eventType"' in line
    ]


def test_the_capture_holds_both_gateway_event_types():
    """The evidence is only evidence if it covers both refusal kinds."""
    types = {json.loads(line)["eventType"] for line in _gateway_lines()}
    assert types == {"UNAUTHORISED_ACCESS", "RATE_LIMIT_EXCEEDED"}


def test_real_kong_lines_parse_as_gateway_events():
    """
    Purpose: the whole point - a line Kong actually wrote is a SecurityEvent.
    """
    lines = _gateway_lines()
    assert lines, "the step-21 capture holds no gateway event lines"

    events = list(stream_events(lines))
    assert len(events) == len(lines), "a gateway line failed to parse"

    for event in events:
        assert event.service_name == ServiceName.GATEWAY.value
        assert event.event_type is _REFUSAL_EVENT_TYPES[event.status_code]
        assert event.correlation_id, "a gateway event must thread onto a workflow"


def test_an_unpruned_kong_field_would_be_rejected():
    """
    Purpose: pin *why* the prune list matters. This is the exact failure the
             plugin hit on `source` and again on `correlation_id`.
    """
    payload = json.loads(_gateway_lines()[0])
    payload["source"] = "kong"
    with pytest.raises(Exception) as excinfo:
        parse_event_line(json.dumps(payload))
    assert "source" in str(excinfo.value)


def test_the_plugin_prunes_every_field_kong_would_add():
    """
    Purpose: the prune list must still name every field Kong's serializer and
             the correlation-id plugin inject. Read from the config text, so
             deleting one is a test failure rather than a broken live run.
    """
    config = KONG_CONFIG.read_text(encoding="utf-8")
    # The default `root` table in kong/pdk/log.lua, plus the correlation-id
    # plugin's own snake_case field.
    must_prune = (
        "latencies", "request", "response", "route", "service",
        "client_ip", "started_at", "upstream_uri", "workspace",
        "workspace_name", "consumer", "authenticated_entity",
        "tries", "upstream_status", "source", "correlation_id",
    )
    for field in must_prune:
        assert f'"{field}"' in config, f"{field} is no longer pruned in kong.yml"


def test_permitted_traffic_emits_no_event():
    """
    Purpose: a 200 must not become an event, or Rule 3's volume signal counts
             the same request at the gateway and at the upstream service.
    """
    assert parse_event_line("{}") is None
    # And the capture records that no stub line was emitted.
    text = EVIDENCE.read_text(encoding="utf-8")
    assert "Stub lines carrying eventId but no eventType: 0" in text
