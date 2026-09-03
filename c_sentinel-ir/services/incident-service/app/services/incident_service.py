"""
incident_service.py - the business logic of the incident lifecycle.

Creating an incident is not a plain insert: it validates the named asset
through `asset_gateway`, snapshots its name, and emits `INCIDENT_CREATED`
carrying the severity - Phase 2's "creation of a high-priority incident"
signal comes free from that one field. Escalating to HIGH or CRITICAL emits
`INCIDENT_ESCALATED`, which a demotion never does.

Pure business logic besides the one HTTP call in `asset_gateway`: it takes a
repository and settings, and imports no FastAPI. That is what makes it
testable against a fake repository with no database, no container and no
network for everything except the asset lookup itself.

Author: Colile
"""

from __future__ import annotations

from typing import Callable

from common.errors import NotFoundError
from common.events import EventType, Severity, build_event
from common.logging import emit_event

from app.models import Incident
from app.repositories.incident_repository import IncidentRepository
from app.schemas import IncidentCreate, IncidentUpdate, Status
from app.services.asset_gateway import AssetSummary

SERVICE_NAME = "incident-service"
INCIDENTS_ENDPOINT = "/api/v1/incidents"

# Escalating into one of these severities is the signal Phase 2 reads;
# escalating within LOW/MEDIUM, or moving down, is routine and stays silent.
_ESCALATION_SEVERITIES = {Severity.HIGH.value, Severity.CRITICAL.value}

FetchAsset = Callable[..., AssetSummary]


class IncidentService:
    """
    Purpose: create, read, update and delete incidents, and run the severity
             workflow, emitting the incident events Phase 2 consumes.
    Inputs:  incidents - the repository this service reads and writes through.
             fetch_asset - the asset lookup, injected so tests can fake it
                           without a network.
    Output:  an object whose methods raise typed errors from `common.errors`;
             the HTTP mapping is done once, in `install_error_handlers`.
    """

    def __init__(self, incidents: IncidentRepository, fetch_asset: FetchAsset) -> None:
        self._incidents = incidents
        self._fetch_asset = fetch_asset

    def get(self, incident_id: int) -> Incident:
        """
        Purpose: fetch one incident by id.
        Inputs:  incident_id - the incident's primary key.
        Output:  the `Incident`.
        Raises:  `NotFoundError` (404) when no such incident exists.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise self._not_found(incident_id)
        return incident

    def list(
        self, status: str | None = None, severity: str | None = None
    ) -> list[Incident]:
        """
        Purpose: the incident listing, optionally narrowed by status and/or
                 severity.
        Inputs:  status, severity - optional filters.
        Output:  the matching incidents.
        """
        return self._incidents.list(status, severity)

    def create(
        self, payload: IncidentCreate, *, correlation_id: str
    ) -> Incident:
        """
        Purpose: raise a new incident against a named asset.
        Inputs:  payload - the validated creation request.
                 correlation_id - the current request's id, for the asset
                                  lookup and the emitted event.
        Output:  the persisted incident, its asset name snapshotted from
                 asset-service (or the documented fallback when it could not
                 be reached).
        """
        asset = self._fetch_asset(
            payload.asset_id, correlation_id=correlation_id
        )
        incident = Incident(
            title=payload.title,
            description=payload.description,
            severity=payload.severity.value,
            status=Status.OPEN.value,
            reported_by=payload.reported_by,
            asset_id=payload.asset_id,
            asset_name_snapshot=asset.name,
        )
        created = self._incidents.create(incident)
        self._emit_created(created, correlation_id)
        return created

    def update(self, incident_id: int, payload: IncidentUpdate) -> Incident:
        """
        Purpose: change one or more fields of an existing incident.
        Inputs:  incident_id - the incident's primary key.
                 payload - the fields to change; unset fields are left as is.
        Output:  the updated incident.
        Raises:  `NotFoundError` (404) when no such incident exists.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise self._not_found(incident_id)
        changes = payload.model_dump(exclude_unset=True)
        if "status" in changes:
            changes["status"] = changes["status"].value
        return self._incidents.update(incident, changes)

    def change_severity(
        self, incident_id: int, new_severity: str, *, correlation_id: str
    ) -> Incident:
        """
        Purpose: move an incident to a new severity, emitting
                 `INCIDENT_ESCALATED` when the move raises it to HIGH or
                 CRITICAL.
        Inputs:  incident_id - the incident's primary key.
                 new_severity - the target severity, already validated as one
                                of the four values by `SeverityChange`.
                 correlation_id - the current request's id, for the event.
        Output:  the updated incident.
        Raises:  `NotFoundError` (404) when no such incident exists.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise self._not_found(incident_id)
        previous_severity = incident.severity
        updated = self._incidents.update(incident, {"severity": new_severity})
        if new_severity in _ESCALATION_SEVERITIES and new_severity != previous_severity:
            self._emit_escalated(updated, previous_severity, correlation_id)
        return updated

    def delete(self, incident_id: int) -> None:
        """
        Purpose: remove an incident.
        Inputs:  incident_id - the incident's primary key.
        Output:  None.
        Raises:  `NotFoundError` (404) when no such incident exists.
        """
        incident = self._incidents.get(incident_id)
        if incident is None:
            raise self._not_found(incident_id)
        self._incidents.delete(incident)

    def _not_found(self, incident_id: int) -> NotFoundError:
        """Purpose: the one NotFoundError shape this service raises.
        Inputs: incident_id. Output: the error, not yet raised."""
        return NotFoundError(
            f"No incident with id {incident_id}.",
            {"field": "incident_id", "value": incident_id},
        )

    def _emit_created(self, incident: Incident, correlation_id: str) -> None:
        """
        Purpose: emit `INCIDENT_CREATED`, carrying the incident's severity so
                 Phase 2's high-priority-creation signal reads it directly.
        Inputs:  incident - the persisted incident.
                 correlation_id - the current request's id.
        Output:  None. One JSON line on the event stream.
        """
        emit_event(
            build_event(
                service_name=SERVICE_NAME,
                event_type=EventType.INCIDENT_CREATED,
                severity=Severity(incident.severity),
                user_id=incident.reported_by,
                endpoint=INCIDENTS_ENDPOINT,
                http_method="POST",
                status_code=201,
                message=f"Incident {incident.id} created with severity {incident.severity}.",
                correlation_id=correlation_id,
                affected_entity=f"incident-{incident.id}",
            )
        )

    def _emit_escalated(
        self, incident: Incident, previous_severity: str, correlation_id: str
    ) -> None:
        """
        Purpose: emit `INCIDENT_ESCALATED`, Phase 2's escalation signal.
        Inputs:  incident - the incident after the severity change.
                 previous_severity - the severity it moved from.
                 correlation_id - the current request's id.
        Output:  None. One JSON line on the event stream.
        """
        emit_event(
            build_event(
                service_name=SERVICE_NAME,
                event_type=EventType.INCIDENT_ESCALATED,
                severity=Severity(incident.severity),
                endpoint=f"{INCIDENTS_ENDPOINT}/{incident.id}/severity",
                http_method="PATCH",
                status_code=200,
                message=(
                    f"Incident {incident.id} escalated from {previous_severity} "
                    f"to {incident.severity}."
                ),
                correlation_id=correlation_id,
                affected_entity=f"incident-{incident.id}",
            )
        )
