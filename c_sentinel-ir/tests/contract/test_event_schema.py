"""
test_event_schema.py - the event model may not drift from docs/soc-events.md.

`libs/common/tests/test_events.py` already proves the model works. This file is
the other half of the contract: it *parses* `docs/soc-events.md` and asserts
the code and the document still agree, so renaming a field or an event type in
one without the other fails here.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "libs"))

from common.events import (  # noqa: E402
    EventType,
    SecurityEvent,
    ServiceName,
    Severity,
    build_event,
)

DOC = (REPO_ROOT / "docs" / "soc-events.md").read_text(encoding="utf-8")


def _first_column_values(section: str) -> set[str]:
    """
    Purpose: pull every back-ticked token from the first column of each table
             row in a slice of the document. A cell may hold more than one, e.g.
             `` `REQUEST_RECEIVED` / `REQUEST_COMPLETED` ``.
    Inputs:  section - the markdown text to scan.
    Output:  the set of tokens, e.g. `{"AUTH_SUCCESS", "AUTH_FAILED", ...}`.
    """
    values: set[str] = set()
    for line in section.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        first_cell = line.split("|")[1] if line.count("|") >= 2 else ""
        values.update(re.findall(r"`([^`]+)`", first_cell))
    return values


def _documented_field_names() -> set[str]:
    """Purpose: the camelCase field names from the "## Fields" table.
    Inputs: none. Output: the set of documented field names."""
    start = DOC.index("## Fields")
    end = DOC.index("## Event types")
    # The field table lists names like `eventId`, `serviceName`, split off any
    # `| null` union noise by taking only the leading identifier.
    names = set()
    for token in _first_column_values(DOC[start:end]):
        names.add(token.split()[0])
    return names


def _documented_event_types() -> set[str]:
    """Purpose: every `eventType` value tabulated in the document.
    Inputs: none. Output: the set of event-type strings."""
    start = DOC.index("## Event types")
    section = DOC[start:]
    tokens: set[str] = set()
    for token in _first_column_values(section):
        # Rows like `REQUEST_RECEIVED` / `REQUEST_COMPLETED` share one cell.
        for part in re.split(r"\s*/\s*", token):
            if part.isupper():
                tokens.add(part)
    return tokens


def test_every_documented_field_maps_to_a_model_alias():
    """
    Purpose: each field name in the document is a serialization alias on
             `SecurityEvent` - a renamed field fails here.
    Inputs:  none.
    Output:  assertions; no return.
    """
    aliases = {
        field.serialization_alias or name
        for name, field in SecurityEvent.model_fields.items()
    }
    documented = _documented_field_names()
    assert documented, "parsed no field names from docs/soc-events.md"
    missing = documented - aliases
    assert not missing, f"documented but not on the model: {sorted(missing)}"


def test_model_emits_no_field_the_document_does_not_list():
    """
    Purpose: the model has no alias the document omits - an added field must be
             documented in the same change.
    Inputs:  none.
    Output:  assertions; no return.
    """
    aliases = {
        field.serialization_alias or name
        for name, field in SecurityEvent.model_fields.items()
    }
    undocumented = aliases - _documented_field_names()
    assert not undocumented, f"on the model but undocumented: {sorted(undocumented)}"


def test_documented_and_enumerated_event_types_match_exactly():
    """
    Purpose: `EventType` and the document's event-type table are the same set.
    Inputs:  none.
    Output:  assertions; no return.
    """
    documented = _documented_event_types()
    enumerated = {member.value for member in EventType}
    assert documented == enumerated, (
        f"only in docs: {sorted(documented - enumerated)}; "
        f"only in code: {sorted(enumerated - documented)}"
    )


def test_a_valid_event_round_trips_through_json_unchanged():
    """
    Purpose: an event rendered to JSON and reloaded is byte-for-byte the same.
    Inputs:  none.
    Output:  assertions; no return.
    """
    event = build_event(
        service_name=ServiceName.INCIDENT.value,
        event_type=EventType.INCIDENT_CREATED,
        severity=Severity.HIGH,
        endpoint="/api/v1/incidents",
        http_method="POST",
        status_code=201,
        message="Incident raised against asset-7.",
        correlation_id="corr-contract-0001",
        user_id="user-1",
        affected_entity="incident-1",
    )
    rendered = event.to_json_dict()
    reloaded = SecurityEvent.model_validate(
        {name: rendered[alias] for name, alias in _alias_map().items()}
    )
    assert reloaded.to_json_dict() == rendered


def test_an_event_with_an_unknown_field_is_rejected():
    """
    Purpose: `extra="forbid"` holds - a stray field raises rather than emitting.
    Inputs:  none.
    Output:  assertions; no return.
    """
    with pytest.raises(PydanticValidationError):
        SecurityEvent(
            event_id="evt-0123456789ab",
            timestamp="2026-09-07T10:45:00Z",
            service_name=ServiceName.AUTH.value,
            event_type=EventType.AUTH_SUCCESS,
            severity=Severity.LOW,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            status_code=200,
            message="ok",
            correlation_id="corr-1",
            surprise="unexpected",
        )


def test_an_event_missing_a_required_field_raises():
    """
    Purpose: a required field left out raises rather than emitting a partial.
    Inputs:  none.
    Output:  assertions; no return.
    """
    with pytest.raises(PydanticValidationError):
        SecurityEvent(
            event_id="evt-0123456789ab",
            timestamp="2026-09-07T10:45:00Z",
            service_name=ServiceName.AUTH.value,
            event_type=EventType.AUTH_SUCCESS,
            severity=Severity.LOW,
            # endpoint missing
            http_method="POST",
            status_code=200,
            message="ok",
            correlation_id="corr-1",
        )


def _alias_map() -> dict[str, str]:
    """Purpose: model field name -> serialization alias.
    Inputs: none. Output: the mapping."""
    return {
        name: (field.serialization_alias or name)
        for name, field in SecurityEvent.model_fields.items()
    }
