"""
asset_service.py - the business logic of the asset register.

A read of a CRITICAL asset is Phase 2's "access to sensitive asset" signal, so
it is the one read path that emits an event; reading a LOW, MEDIUM or HIGH
asset is routine traffic and stays silent on the security stream.

Pure business logic: it takes a repository and imports no FastAPI. That is
what makes it testable against a fake repository with no database, no
container and no network.

Author: Colile
"""

from __future__ import annotations

from common.errors import NotFoundError
from common.events import EventType, Severity, build_event
from common.logging import emit_event

from app.models import Asset
from app.repositories.asset_repository import AssetRepository
from app.schemas import AssetCreate, AssetUpdate, Criticality

SERVICE_NAME = "asset-service"
ASSETS_ENDPOINT = "/api/v1/assets"


class AssetService:
    """
    Purpose: create, read, update and delete assets, emitting `ASSET_ACCESSED`
             for reads of CRITICAL assets.
    Inputs:  assets - the repository this service reads and writes through.
    Output:  an object whose methods raise typed errors from `common.errors`;
             the HTTP mapping is done once, in `install_error_handlers`.
    """

    def __init__(self, assets: AssetRepository) -> None:
        self._assets = assets

    def get(self, asset_id: int, *, correlation_id: str) -> Asset:
        """
        Purpose: fetch one asset, emitting an event when it is CRITICAL.
        Inputs:  asset_id - the asset's primary key.
                 correlation_id - the current request's id, for the event.
        Output:  the `Asset`.
        Raises:  `NotFoundError` (404) when no such asset exists.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise NotFoundError(
                f"No asset with id {asset_id}.", {"field": "asset_id", "value": asset_id}
            )
        if asset.criticality == Criticality.CRITICAL.value:
            self._emit_critical_access(asset, correlation_id)
        return asset

    def list(self, asset_type: str | None = None) -> list[Asset]:
        """
        Purpose: the register listing, optionally narrowed by type.
        Inputs:  asset_type - when given, only assets of that type are
                  returned.
        Output:  the matching assets.
        """
        return self._assets.list(asset_type)

    def create(self, payload: AssetCreate) -> Asset:
        """
        Purpose: register a new asset.
        Inputs:  payload - the validated creation request.
        Output:  the persisted asset.
        Raises:  `ConflictError` (409) when the name is already taken.
        """
        asset = Asset(
            name=payload.name,
            asset_type=payload.asset_type,
            criticality=payload.criticality.value,
            owner=payload.owner,
            location=payload.location,
        )
        return self._assets.create(asset)

    def update(self, asset_id: int, payload: AssetUpdate) -> Asset:
        """
        Purpose: change one or more fields of an existing asset.
        Inputs:  asset_id - the asset's primary key.
                 payload - the fields to change; unset fields are left as is.
        Output:  the updated asset.
        Raises:  `NotFoundError` (404) when no such asset exists; `ConflictError`
                 (409) when a changed name collides with another asset's.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise NotFoundError(
                f"No asset with id {asset_id}.", {"field": "asset_id", "value": asset_id}
            )
        changes = payload.model_dump(exclude_unset=True)
        if "criticality" in changes:
            changes["criticality"] = changes["criticality"].value
        return self._assets.update(asset, changes)

    def delete(self, asset_id: int) -> None:
        """
        Purpose: remove an asset from the register.
        Inputs:  asset_id - the asset's primary key.
        Output:  None.
        Raises:  `NotFoundError` (404) when no such asset exists.
        """
        asset = self._assets.get(asset_id)
        if asset is None:
            raise NotFoundError(
                f"No asset with id {asset_id}.", {"field": "asset_id", "value": asset_id}
            )
        self._assets.delete(asset)

    def _emit_critical_access(self, asset: Asset, correlation_id: str) -> None:
        """
        Purpose: emit the `ASSET_ACCESSED` event Phase 2's sensitive-access
                 signal reads.
        Inputs:  asset - the CRITICAL asset that was read.
                 correlation_id - the current request's id.
        Output:  None. One JSON line on the event stream.
        """
        emit_event(
            build_event(
                service_name=SERVICE_NAME,
                event_type=EventType.ASSET_ACCESSED,
                severity=Severity.MEDIUM,
                endpoint=f"{ASSETS_ENDPOINT}/{asset.id}",
                http_method="GET",
                status_code=200,
                message=f"Critical asset {asset.name!r} was read.",
                correlation_id=correlation_id,
                affected_entity=f"asset-{asset.id}",
            )
        )
