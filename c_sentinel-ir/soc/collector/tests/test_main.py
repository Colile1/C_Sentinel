"""
test_main.py - the entry point streams a file into a populated store.

Only the file and stdin paths are exercised; the docker path shells out and is
covered by the step-14 live evidence capture, not a unit test.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.events import EventType, build_event
from soc.collector.main import build_store, main


def _write_stream(path: Path) -> None:
    """
    Purpose: write a small mixed log stream - two events and one app line.
    Inputs:  path - the file to create.
    Output:  None.
    """
    first = build_event(
        service_name="auth-service",
        event_type=EventType.AUTH_SUCCESS,
        severity="LOW",
        endpoint="/api/v1/auth/login",
        http_method="POST",
        status_code=200,
        message="User admin authenticated successfully.",
        correlation_id="corr-file-1",
        user_id="admin",
    )
    second = build_event(
        service_name="incident-service",
        event_type=EventType.INCIDENT_CREATED,
        severity="MEDIUM",
        endpoint="/api/v1/incidents",
        http_method="POST",
        status_code=201,
        message="Incident 1 created with severity MEDIUM.",
        correlation_id="corr-file-1",
        affected_entity="incident-1",
    )
    lines = [
        json.dumps(first.to_json_dict()),
        json.dumps({"level": "INFO", "logger": "uvicorn", "message": "ready"}),
        json.dumps(second.to_json_dict()),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_build_store_from_file_lines(tmp_path):
    """
    Purpose: `build_store` turns a stream into a populated `EventStore`.
    Inputs:  tmp_path - pytest's temp directory.
    Output:  assertions.
    """
    stream = tmp_path / "events.jsonl"
    _write_stream(stream)
    with stream.open(encoding="utf-8") as handle:
        store = build_store(handle)
    assert len(store) == 2
    assert len(store.by_correlation("corr-file-1")) == 2


def test_main_with_file_prints_summary(tmp_path, capsys):
    """
    Purpose: `main --file` exits 0 and prints the `Description: value` summary.
    Inputs:  tmp_path, capsys - pytest fixtures.
    Output:  assertions.
    """
    stream = tmp_path / "events.jsonl"
    _write_stream(stream)
    code = main(["--file", str(stream)])
    assert code == 0
    out = capsys.readouterr().out
    assert "Events collected: 2" in out
    assert "Distinct correlation IDs: 1" in out
    assert "auth-service" in out and "incident-service" in out


def test_main_reports_failure_on_missing_file(tmp_path, capsys):
    """
    Purpose: a missing file is a collection failure, exit 1, message on stderr.
    Inputs:  tmp_path, capsys.
    Output:  assertions.
    """
    code = main(["--file", str(tmp_path / "nope.jsonl")])
    assert code == 1
    assert "Collection failed" in capsys.readouterr().err
