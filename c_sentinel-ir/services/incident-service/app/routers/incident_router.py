"""
incident_router.py - the six HTTP endpoints incident-service publishes.

HTTP only: parse the request, delegate to `IncidentService`, shape the
response. No business logic and no error handling live here - a typed error
raised below becomes its status code in `install_error_handlers`, which is the
one place that mapping is written.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.routers.dependencies import get_incident_service, get_request_correlation_id
from app.schemas import IncidentCreate, IncidentRead, IncidentUpdate, SeverityChange
from app.services.incident_service import IncidentService

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.get("", response_model=list[IncidentRead], summary="List incidents")
def list_incidents(
    service: Annotated[IncidentService, Depends(get_incident_service)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    severity: Annotated[str | None, Query()] = None,
) -> list[IncidentRead]:
    """
    Purpose: the incident listing, optionally narrowed by status and/or
             severity.
    Inputs:  status_filter, severity - optional query filters.
    Output:  200 with the matching incidents.
    """
    return [
        IncidentRead.model_validate(incident)
        for incident in service.list(status_filter, severity)
    ]


@router.get("/{incident_id}", response_model=IncidentRead, summary="Get one incident")
def get_incident(
    incident_id: int,
    service: Annotated[IncidentService, Depends(get_incident_service)],
) -> IncidentRead:
    """
    Purpose: fetch one incident by id.
    Inputs:  incident_id - the path parameter.
    Output:  200 with the incident. 404 when it does not exist.
    """
    return IncidentRead.model_validate(service.get(incident_id))


@router.post(
    "",
    response_model=IncidentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a new incident",
)
def create_incident(
    payload: IncidentCreate,
    service: Annotated[IncidentService, Depends(get_incident_service)],
    correlation_id: Annotated[str, Depends(get_request_correlation_id)],
) -> IncidentRead:
    """
    Purpose: raise a new incident against a named asset.
    Inputs:  payload - the new incident's details.
    Output:  201 with the created incident, its asset name snapshotted from
             asset-service. One `INCIDENT_CREATED` event is emitted.
    """
    return IncidentRead.model_validate(
        service.create(payload, correlation_id=correlation_id)
    )


@router.put("/{incident_id}", response_model=IncidentRead, summary="Update an incident")
def update_incident(
    incident_id: int,
    payload: IncidentUpdate,
    service: Annotated[IncidentService, Depends(get_incident_service)],
) -> IncidentRead:
    """
    Purpose: change one or more fields of an existing incident.
    Inputs:  incident_id - the path parameter. payload - the fields to change.
    Output:  200 with the updated incident. 404 when it does not exist.
    """
    return IncidentRead.model_validate(service.update(incident_id, payload))


@router.patch(
    "/{incident_id}/severity",
    response_model=IncidentRead,
    summary="Change an incident's severity",
)
def change_severity(
    incident_id: int,
    payload: SeverityChange,
    service: Annotated[IncidentService, Depends(get_incident_service)],
    correlation_id: Annotated[str, Depends(get_request_correlation_id)],
) -> IncidentRead:
    """
    Purpose: move an incident to a new severity.
    Inputs:  incident_id - the path parameter.
             payload - the target severity; an unrecognised value is rejected
                       as 422 naming the `severity` field before this runs.
    Output:  200 with the updated incident. 404 when it does not exist. An
             escalation to HIGH or CRITICAL emits one `INCIDENT_ESCALATED`
             event.
    """
    return IncidentRead.model_validate(
        service.change_severity(
            incident_id, payload.severity.value, correlation_id=correlation_id
        )
    )


@router.delete(
    "/{incident_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an incident",
)
def delete_incident(
    incident_id: int,
    service: Annotated[IncidentService, Depends(get_incident_service)],
) -> None:
    """
    Purpose: remove an incident.
    Inputs:  incident_id - the path parameter.
    Output:  204 on success. 404 when it does not exist.
    """
    service.delete(incident_id)
