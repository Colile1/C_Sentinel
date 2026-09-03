"""
test_incident_service.py - the incident business logic, against fakes.

Pure unit tests: no database, no container, no network - proving the rules
`IncidentService` is responsible for: creation snapshots the asset name and
emits `INCIDENT_CREATED` carrying severity, and escalation to HIGH or CRITICAL
emits exactly one `INCIDENT_ESCALATED`.

Author: Colile
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from common.errors import NotFoundError

from app.schemas import IncidentCreate, Severity
from app.services.incident_service import IncidentService

CORRELATION_ID = "corr-test0000001"


def test_create_snapshots_the_asset_name(
    incident_service: IncidentService,
) -> None:
    """A valid creation request stores the name asset-service reported."""
    created = incident_service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.LOW,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )

    assert created.id is not None
    assert created.asset_name_snapshot == "web-01"
    assert created.status == "OPEN"


def test_create_emits_incident_created_carrying_severity(
    incident_service: IncidentService, captured_events
) -> None:
    """`INCIDENT_CREATED` carries the severity, Phase 2's high-priority signal."""
    incident_service.create(
        IncidentCreate(
            title="Data exfiltration",
            description="Large outbound transfer detected.",
            severity=Severity.CRITICAL,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event["eventType"] == "INCIDENT_CREATED"
    assert event["severity"] == "CRITICAL"
    assert event["correlationId"] == CORRELATION_ID


def test_create_with_unreachable_asset_service_still_creates(
    fake_incidents, fetch_asset_factory
) -> None:
    """The degraded lookup does not block incident creation."""
    service = IncidentService(fake_incidents, fetch_asset_factory(available=False))

    created = service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.LOW,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )

    assert created.id is not None


def test_invalid_severity_is_rejected_naming_the_field() -> None:
    """A severity outside the four values fails validation, naming the field."""
    with pytest.raises(PydanticValidationError) as exc:
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity="SEVERE",
            reported_by="analyst",
            asset_id=1,
        )

    assert exc.value.errors()[0]["loc"] == ("severity",)


def test_get_unknown_id_raises_not_found(incident_service: IncidentService) -> None:
    """An id with no row raises NotFoundError, naming the field."""
    with pytest.raises(NotFoundError) as exc:
        incident_service.get(999)

    assert exc.value.status_code == 404
    assert exc.value.details["field"] == "incident_id"


def test_escalation_to_high_emits_exactly_one_event(
    incident_service: IncidentService, captured_events
) -> None:
    """Escalating LOW to HIGH is the one signal Phase 2's escalation rule reads."""
    created = incident_service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.LOW,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )
    captured_events.clear()

    updated = incident_service.change_severity(
        created.id, "HIGH", correlation_id=CORRELATION_ID
    )

    assert updated.severity == "HIGH"
    assert len(captured_events) == 1
    assert captured_events[0]["eventType"] == "INCIDENT_ESCALATED"


def test_escalation_within_low_severities_emits_nothing(
    incident_service: IncidentService, captured_events
) -> None:
    """Moving LOW to MEDIUM is routine, not an escalation signal."""
    created = incident_service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.LOW,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )
    captured_events.clear()

    incident_service.change_severity(created.id, "MEDIUM", correlation_id=CORRELATION_ID)

    assert captured_events == []


def test_demotion_from_high_emits_nothing(
    incident_service: IncidentService, captured_events
) -> None:
    """A downgrade is never an escalation, whatever severity it lands on."""
    created = incident_service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.HIGH,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )
    captured_events.clear()

    incident_service.change_severity(created.id, "LOW", correlation_id=CORRELATION_ID)

    assert captured_events == []


def test_severity_change_on_unknown_id_raises_not_found(
    incident_service: IncidentService,
) -> None:
    """Escalating a non-existent incident raises the same NotFoundError as get."""
    with pytest.raises(NotFoundError):
        incident_service.change_severity(999, "HIGH", correlation_id=CORRELATION_ID)


def test_delete_unknown_id_raises_not_found(incident_service: IncidentService) -> None:
    """Deleting a non-existent incident raises NotFoundError rather than no-op."""
    with pytest.raises(NotFoundError):
        incident_service.delete(999)


def test_delete_removes_the_incident(incident_service: IncidentService) -> None:
    """A deleted incident can no longer be fetched."""
    created = incident_service.create(
        IncidentCreate(
            title="Suspicious login",
            description="Multiple failed logins from one IP.",
            severity=Severity.LOW,
            reported_by="analyst",
            asset_id=1,
        ),
        correlation_id=CORRELATION_ID,
    )

    incident_service.delete(created.id)

    with pytest.raises(NotFoundError):
        incident_service.get(created.id)
