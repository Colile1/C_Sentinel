"""
dependencies.py - the FastAPI wiring incident-service's routes depend on.

Routers stay HTTP-only by taking their collaborators from here: a session, an
`IncidentService` built on it and bound to the real `asset_gateway.fetch_asset`,
and the correlation id. Nothing here makes a business decision.

Author: Colile
"""

from __future__ import annotations

from functools import partial
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from common.config import Settings, get_settings
from common.correlation import get_correlation_id

from app.database import SERVICE_NAME, get_session
from app.repositories.incident_repository import IncidentRepository
from app.services.asset_gateway import fetch_asset
from app.services.incident_service import IncidentService


def get_service_settings() -> Settings:
    """
    Purpose: this service's settings, as a dependency so tests can override it
             without touching the environment.
    Inputs:  none.
    Output:  the cached `Settings` for incident-service.
    """
    return get_settings(SERVICE_NAME)


def get_incident_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_service_settings)],
) -> IncidentService:
    """
    Purpose: build the business-logic object for one request.
    Inputs:  the request-scoped session and the service settings.
    Output:  an `IncidentService` over a repository bound to that session, and
             the asset lookup bound to this service's `asset_service_url`.
    """
    return IncidentService(
        IncidentRepository(session), partial(fetch_asset, settings=settings)
    )


def get_request_correlation_id() -> str:
    """
    Purpose: the correlation id bound to this request by the middleware, so
             incident events and the asset lookup join the right workflow.
    Inputs:  none.
    Output:  the current correlation id.
    """
    return get_correlation_id()
