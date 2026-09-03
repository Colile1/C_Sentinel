"""
dependencies.py - the FastAPI wiring asset-service's routes depend on.

Routers stay HTTP-only by taking their collaborators from here: a session and
an `AssetService` built on it. Nothing here makes a business decision.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from common.correlation import get_correlation_id

from app.database import get_session
from app.repositories.asset_repository import AssetRepository
from app.services.asset_service import AssetService


def get_asset_service(
    session: Annotated[Session, Depends(get_session)],
) -> AssetService:
    """
    Purpose: build the business-logic object for one request.
    Inputs:  the request-scoped session.
    Output:  an `AssetService` over a repository bound to that session.
    """
    return AssetService(AssetRepository(session))


def get_request_correlation_id() -> str:
    """
    Purpose: the correlation id bound to this request by the middleware, so a
             CRITICAL asset read is recorded against the right workflow.
    Inputs:  none.
    Output:  the current correlation id.
    """
    return get_correlation_id()
