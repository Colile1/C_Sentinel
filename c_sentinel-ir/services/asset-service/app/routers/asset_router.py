"""
asset_router.py - the five HTTP endpoints asset-service publishes.

HTTP only: parse the request, delegate to `AssetService`, shape the response.
No business logic and no error handling live here - a typed error raised below
becomes its status code in `install_error_handlers`, which is the one place
that mapping is written.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.routers.dependencies import get_asset_service, get_request_correlation_id
from app.schemas import AssetCreate, AssetRead, AssetUpdate
from app.services.asset_service import AssetService

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead], summary="List assets")
def list_assets(
    service: Annotated[AssetService, Depends(get_asset_service)],
    asset_type: Annotated[str | None, Query()] = None,
) -> list[AssetRead]:
    """
    Purpose: the register listing, optionally narrowed by type.
    Inputs:  asset_type - optional query filter.
    Output:  200 with the matching assets.
    """
    return [AssetRead.model_validate(asset) for asset in service.list(asset_type)]


@router.get("/{asset_id}", response_model=AssetRead, summary="Get one asset")
def get_asset(
    asset_id: int,
    service: Annotated[AssetService, Depends(get_asset_service)],
    correlation_id: Annotated[str, Depends(get_request_correlation_id)],
) -> AssetRead:
    """
    Purpose: fetch one asset by id.
    Inputs:  asset_id - the path parameter.
    Output:  200 with the asset. 404 when it does not exist. Reading a
             CRITICAL asset also emits one `ASSET_ACCESSED` event.
    """
    return AssetRead.model_validate(
        service.get(asset_id, correlation_id=correlation_id)
    )


@router.post(
    "",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new asset",
)
def create_asset(
    payload: AssetCreate,
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> AssetRead:
    """
    Purpose: add a new asset to the register.
    Inputs:  payload - the new asset's details.
    Output:  201 with the created asset. 409 when the name is taken.
    """
    return AssetRead.model_validate(service.create(payload))


@router.put("/{asset_id}", response_model=AssetRead, summary="Update an asset")
def update_asset(
    asset_id: int,
    payload: AssetUpdate,
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> AssetRead:
    """
    Purpose: change one or more fields of an existing asset.
    Inputs:  asset_id - the path parameter. payload - the fields to change.
    Output:  200 with the updated asset. 404 when it does not exist, 409 on a
             name collision.
    """
    return AssetRead.model_validate(service.update(asset_id, payload))


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an asset",
)
def delete_asset(
    asset_id: int,
    service: Annotated[AssetService, Depends(get_asset_service)],
) -> None:
    """
    Purpose: remove an asset from the register.
    Inputs:  asset_id - the path parameter.
    Output:  204 on success. 404 when it does not exist.
    """
    service.delete(asset_id)
