"""
test_event_emission.py - captured log samples must validate as SecurityEvents.

This is the test that catches a service inventing its own log format. It reads
the committed event samples under `docs/evidence/*.jsonl` - real output from
earlier build steps - and asserts every line carrying `eventType` reloads
cleanly as a `SecurityEvent` with the schema's field names.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "libs"))

from common.events import SecurityEvent  # noqa: E402

EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"

# Reverse of the serialization aliases: the camelCase key written to the log
# back to the model field name `model_validate` expects.
_ALIAS_TO_FIELD = {
    (field.serialization_alias or name): name
    for name, field in SecurityEvent.model_fields.items()
}


def _event_lines() -> list[tuple[str, dict]]:
    """
    Purpose: every JSON object carrying `eventType` across the evidence files.
    Inputs:  none.
    Output:  a list of (source_file_name, parsed_object).
    """
    found: list[tuple[str, dict]] = []
    for path in sorted(EVIDENCE_DIR.glob("*.jsonl")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and "eventType" in obj:
                found.append((path.name, obj))
    return found


ALL_EVENT_LINES = _event_lines()


def test_evidence_samples_exist():
    """
    Purpose: there is at least one captured event sample to check - an empty
             glob would make every other test here vacuously pass.
    Inputs:  none.
    Output:  assertions; no return.
    """
    assert ALL_EVENT_LINES, f"no event lines found under {EVIDENCE_DIR}"


@pytest.mark.parametrize(
    "source, payload",
    ALL_EVENT_LINES,
    ids=[f"{name}#{i}" for i, (name, _) in enumerate(ALL_EVENT_LINES)],
)
def test_each_captured_event_validates(source, payload):
    """
    Purpose: every captured line reloads as a `SecurityEvent` - it carries the
             documented field names, no extras, and passes every field
             validator.
    Inputs:  the source file name and the parsed line.
    Output:  assertions; no return.
    """
    unknown = set(payload) - set(_ALIAS_TO_FIELD)
    assert not unknown, f"{source}: line carries non-schema keys {sorted(unknown)}"
    by_field = {_ALIAS_TO_FIELD[key]: value for key, value in payload.items()}
    event = SecurityEvent.model_validate(by_field)
    # Re-rendering must reproduce the captured line exactly.
    assert event.to_json_dict() == payload


def test_samples_cover_more_than_one_service():
    """
    Purpose: the captured evidence spans multiple emitters, so the check is not
             just exercising auth-service's format.
    Inputs:  none.
    Output:  assertions; no return.
    """
    services = {payload["serviceName"] for _, payload in ALL_EVENT_LINES}
    assert len(services) >= 2, f"only these services captured: {sorted(services)}"
