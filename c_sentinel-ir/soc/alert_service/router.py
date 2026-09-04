"""
router.py - the three HTTP endpoints the alert service publishes.

HTTP only: parse the request, delegate to `AlertStore`, shape the response. A
`NotFoundError` raised by the store becomes a 404 in `install_error_handlers`,
the one place that mapping is written, so no handler here writes an error body.

Every response is the specification's alert schema - `Alert.to_json_dict()`,
the eleven camelCase keys `kg/loader` and `rag/retrieval` read - so the API and
the graph loader never disagree about a field name.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from common.events import Severity

from soc.alert_service.dependencies import get_alert_store
from soc.alert_service.models import AlertStatus
from soc.alert_service.schemas import StatusChange
from soc.alert_service.store import AlertStore

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


@router.get("", summary="List alerts")
def list_alerts(
    store: Annotated[AlertStore, Depends(get_alert_store)],
    severity: Annotated[Severity | None, Query()] = None,
    affected_service: Annotated[
        str | None, Query(alias="affectedService")
    ] = None,
    status: Annotated[AlertStatus | None, Query()] = None,
) -> list[dict[str, Any]]:
    """
    Purpose: the alert listing, optionally narrowed by severity, affected
             service and status - newest first.
    Inputs:  severity, affectedService, status - optional query filters.
    Output:  200 with a JSON array of alerts in the specification's schema.
    """
    alerts = store.list(
        severity=severity, affected_service=affected_service, status=status
    )
    return [alert.to_json_dict() for alert in alerts]


@router.get("/{alert_id}", summary="Get one alert")
def get_alert(
    alert_id: str,
    store: Annotated[AlertStore, Depends(get_alert_store)],
) -> dict[str, Any]:
    """
    Purpose: fetch one alert by its `alt-` identifier.
    Inputs:  alert_id - the path parameter.
    Output:  200 with the alert. 404 when no alert carries the id.
    """
    return store.get(alert_id).to_json_dict()


@router.patch("/{alert_id}/status", summary="Change an alert's status")
def change_alert_status(
    alert_id: str,
    payload: StatusChange,
    store: Annotated[AlertStore, Depends(get_alert_store)],
) -> dict[str, Any]:
    """
    Purpose: move an alert through OPEN -> ACKNOWLEDGED -> CLOSED. The stored
             record is replaced, never mutated, so the alert stays a faithful
             record of what the rule saw.
    Inputs:  alert_id - the path parameter; payload - the target status.
    Output:  200 with the updated alert. 404 when no alert carries the id, 422
             when the status value is not one of the three.
    """
    return store.set_status(alert_id, payload.status).to_json_dict()
