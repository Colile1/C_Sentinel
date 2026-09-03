"""
test_events.py - unit tests for the security event schema.

Proves build step 3's verification: every field in docs/soc-events.md round
trips, and an off-schema event is rejected rather than emitted partially. These
tests are the guard on the Phase 1 to Phase 2 contract - if one fails, the event
stream has drifted from the published schema.

Author: Colile
"""

from __future__ import annotations

import json
import re

import pytest
from pydantic import ValidationError as PydanticValidationError

from common.events import (
    EventType,
    SecurityEvent,
    ServiceName,
    Severity,
    build_event,
    new_event_id,
    utc_now_iso,
)

# The published schema, field for field, in the order docs/soc-events.md lists.
_SCHEMA_KEYS = [
    "eventId",
    "timestamp",
    "serviceName",
    "eventType",
    "severity",
    "userId",
    "sourceIp",
    "endpoint",
    "httpMethod",
    "statusCode",
    "message",
    "correlationId",
    "affectedEntity",
]

# The worked example from docs/soc-events.md, minus the generated fields.
_WORKED_EXAMPLE = {
    "service_name": "incident-service",
    "event_type": EventType.UNAUTHORISED_ACCESS,
    "severity": Severity.HIGH,
    "user_id": "user-14",
    "source_ip": "192.168.1.25",
    "endpoint": "/api/v1/incidents/42",
    "http_method": "GET",
    "status_code": 403,
    "message": "User attempted to read an incident outside their role scope",
    "correlation_id": "corr-8842",
    "affected_entity": "incident-42",
}


def _minimal_event(**overrides: object) -> SecurityEvent:
    """Purpose: build a valid event, overriding named fields.
    Inputs: field overrides. Output: a SecurityEvent."""
    fields: dict[str, object] = {
        "service_name": "auth-service",
        "event_type": EventType.AUTH_SUCCESS,
        "severity": Severity.LOW,
        "endpoint": "/api/v1/auth/login",
        "http_method": "POST",
        "status_code": 200,
        "message": "Analyst signed in",
        "correlation_id": "corr-000000000001",
    }
    fields.update(overrides)
    return build_event(**fields)  # type: ignore[arg-type]


class TestSchemaShape:
    """The rendered event must match docs/soc-events.md exactly."""

    def test_every_schema_field_is_present(self) -> None:
        """A missing key breaks Phase 2's parser."""
        assert sorted(build_event(**_WORKED_EXAMPLE).to_json_dict()) == sorted(
            _SCHEMA_KEYS
        )

    def test_fields_are_emitted_in_the_documented_order(self) -> None:
        """Not required for correctness, but it makes the demo log readable."""
        assert list(build_event(**_WORKED_EXAMPLE).to_json_dict()) == _SCHEMA_KEYS

    def test_no_extra_field_is_emitted(self) -> None:
        """An unexpected key means the schema and the code have diverged."""
        rendered = build_event(**_WORKED_EXAMPLE).to_json_dict()
        assert set(rendered) - set(_SCHEMA_KEYS) == set()

    def test_the_worked_example_round_trips(self) -> None:
        """The documented example must survive build, render and re-parse."""
        rendered = build_event(**_WORKED_EXAMPLE).to_json_dict()
        reparsed = json.loads(json.dumps(rendered))

        assert reparsed["serviceName"] == "incident-service"
        assert reparsed["eventType"] == "UNAUTHORISED_ACCESS"
        assert reparsed["severity"] == "HIGH"
        assert reparsed["userId"] == "user-14"
        assert reparsed["sourceIp"] == "192.168.1.25"
        assert reparsed["endpoint"] == "/api/v1/incidents/42"
        assert reparsed["httpMethod"] == "GET"
        assert reparsed["statusCode"] == 403
        assert reparsed["correlationId"] == "corr-8842"
        assert reparsed["affectedEntity"] == "incident-42"

    def test_enums_render_as_plain_strings(self) -> None:
        """Phase 2 reads JSON, so an enum must not leak its Python repr."""
        rendered = build_event(**_WORKED_EXAMPLE).to_json_dict()

        assert isinstance(rendered["eventType"], str)
        assert isinstance(rendered["severity"], str)

    def test_optional_fields_render_as_null_not_absent(self) -> None:
        """"Where known" means null when unknown, never a missing key."""
        rendered = _minimal_event().to_json_dict()

        assert rendered["userId"] is None
        assert rendered["sourceIp"] is None
        assert rendered["affectedEntity"] is None


class TestGeneratedFields:
    """The library owns the id and timestamp; a caller may never supply them."""

    def test_event_id_matches_the_documented_format(self) -> None:
        """`evt-` plus 12 hex characters, as the schema states."""
        assert re.fullmatch(r"evt-[0-9a-f]{12}", new_event_id())

    def test_event_ids_are_unique(self) -> None:
        """Phase 2 keys nodes on the event id, so collisions merge two events."""
        assert len({new_event_id() for _ in range(1000)}) == 1000

    def test_timestamp_is_iso_8601_utc(self) -> None:
        """A varying timestamp format breaks time-window detection rules."""
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", utc_now_iso())

    def test_build_event_rejects_a_caller_supplied_id(self) -> None:
        """`build_event` is keyword-only and owns these two fields."""
        with pytest.raises(TypeError):
            build_event(event_id="evt-deadbeef1234", **_WORKED_EXAMPLE)  # type: ignore[call-arg]


class TestOffSchemaEventsAreRejected:
    """The step 3 verification: a malformed event raises rather than emits."""

    def test_an_extra_field_is_rejected(self) -> None:
        """Extra fields are forbidden by docs/soc-events.md."""
        with pytest.raises(PydanticValidationError, match="extra_forbidden"):
            SecurityEvent(
                event_id=new_event_id(),
                timestamp=utc_now_iso(),
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=200,
                message="Analyst signed in",
                correlation_id="corr-000000000001",
                attacker_score=99,
            )

    def test_a_missing_required_field_is_rejected(self) -> None:
        """A partial event is worse than a loud failure."""
        with pytest.raises(PydanticValidationError, match="correlation_id"):
            SecurityEvent(
                event_id=new_event_id(),
                timestamp=utc_now_iso(),
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=200,
                message="Analyst signed in",
            )

    def test_an_unknown_service_name_is_rejected(self) -> None:
        """Only the four documented emitters may write to the stream."""
        with pytest.raises(PydanticValidationError, match="must be one of"):
            _minimal_event(service_name="rogue-service")

    @pytest.mark.parametrize("service", [member.value for member in ServiceName])
    def test_every_documented_service_is_accepted(self, service: str) -> None:
        """The four names in the schema must all work."""
        assert _minimal_event(service_name=service).service_name == service

    def test_an_unknown_event_type_is_rejected(self) -> None:
        """A type Phase 2 has no rule for must not reach the stream."""
        with pytest.raises(PydanticValidationError):
            _minimal_event(event_type="EVERYTHING_IS_FINE")

    def test_an_unknown_severity_is_rejected(self) -> None:
        """Severity drives alert triage, so it may not be free text."""
        with pytest.raises(PydanticValidationError):
            _minimal_event(severity="CATASTROPHIC")

    def test_an_impossible_status_code_is_rejected(self) -> None:
        """A status outside 100-599 means the caller passed the wrong value."""
        with pytest.raises(PydanticValidationError, match="valid HTTP status"):
            _minimal_event(status_code=9000)

    def test_an_unknown_http_method_is_rejected(self) -> None:
        """Detection rules match on the method, so it must be a real one."""
        with pytest.raises(PydanticValidationError, match="must be one of"):
            _minimal_event(http_method="EXFILTRATE")

    @pytest.mark.parametrize("field", ["endpoint", "message", "correlation_id"])
    def test_a_blank_required_field_is_rejected(self, field: str) -> None:
        """Present but empty is a missing field with extra steps."""
        with pytest.raises(PydanticValidationError, match="must not be blank"):
            _minimal_event(**{field: "   "})

    def test_a_malformed_event_id_is_rejected(self) -> None:
        """Phase 2 parses the id, so its format is part of the contract."""
        with pytest.raises(PydanticValidationError):
            SecurityEvent(
                event_id="event-not-in-the-right-shape",
                timestamp=utc_now_iso(),
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=200,
                message="Analyst signed in",
                correlation_id="corr-000000000001",
            )


class TestNormalisation:
    """Values callers get slightly wrong are corrected, not silently kept."""

    def test_http_method_is_upper_cased(self) -> None:
        """`get` and `GET` must produce the same event for a rule to match."""
        assert _minimal_event(http_method="get").http_method == "GET"

    def test_an_event_is_immutable_once_built(self) -> None:
        """An emitted event is a record of the past and may not be edited."""
        event = _minimal_event()
        with pytest.raises(PydanticValidationError):
            event.status_code = 500


class TestEventTypeCoverage:
    """Every type docs/soc-events.md tabulates must exist in the enum."""

    @pytest.mark.parametrize(
        "event_type",
        [
            "AUTH_SUCCESS",
            "AUTH_FAILED",
            "UNAUTHORISED_ACCESS",
            "RATE_LIMIT_EXCEEDED",
            "REQUEST_RECEIVED",
            "REQUEST_COMPLETED",
            "INCIDENT_CREATED",
            "INCIDENT_ESCALATED",
            "ASSET_ACCESSED",
            "DEPENDENCY_FAILURE",
            "CIRCUIT_OPENED",
            "CIRCUIT_CLOSED",
            "SERVICE_ERROR",
        ],
    )
    def test_documented_event_type_exists(self, event_type: str) -> None:
        """A type in the document but not the enum cannot be emitted."""
        assert EventType(event_type).value == event_type

    def test_the_enum_holds_no_undocumented_type(self) -> None:
        """A type in the enum but not the document is an undocumented signal."""
        documented = {
            "AUTH_SUCCESS", "AUTH_FAILED", "UNAUTHORISED_ACCESS",
            "RATE_LIMIT_EXCEEDED", "REQUEST_RECEIVED", "REQUEST_COMPLETED",
            "INCIDENT_CREATED", "INCIDENT_ESCALATED", "ASSET_ACCESSED",
            "DEPENDENCY_FAILURE", "CIRCUIT_OPENED", "CIRCUIT_CLOSED",
            "SERVICE_ERROR",
        }
        assert {member.value for member in EventType} == documented

    @pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    def test_documented_severity_exists(self, severity: str) -> None:
        """The four documented severities, no more and no fewer."""
        assert Severity(severity).value == severity
