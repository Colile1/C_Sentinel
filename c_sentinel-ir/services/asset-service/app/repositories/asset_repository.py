"""
asset_repository.py - every SQL statement asset-service runs, in one file.

SQLAlchemy lives here and nowhere else in this service: the business logic in
app/services/ takes a repository and never a Session, which is what keeps it
unit-testable against a fake with no database at all.

Author: Colile
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import ConflictError

from app.models import Asset


class AssetRepository:
    """
    Purpose: read and write the `assets` table.
    Inputs:  session - the request-scoped SQLAlchemy session.
    Output:  a repository whose methods return `Asset` rows or None. It raises
             only `ConflictError`; every other failure belongs to the caller.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, asset_id: int) -> Asset | None:
        """
        Purpose: fetch one asset by id.
        Inputs:  asset_id - the asset's primary key.
        Output:  the `Asset`, or None when no such row exists.
        """
        return self._session.get(Asset, asset_id)

    def list(self, asset_type: str | None = None) -> list[Asset]:
        """
        Purpose: the register listing, optionally narrowed by type.
        Inputs:  asset_type - when given, only assets of that type are
                  returned.
        Output:  matching assets, oldest first, so the ordering is stable
                 between calls rather than whatever the database returns.
        """
        statement = select(Asset).order_by(Asset.id)
        if asset_type is not None:
            statement = statement.where(Asset.asset_type == asset_type)
        return list(self._session.scalars(statement))

    def create(self, asset: Asset) -> Asset:
        """
        Purpose: persist a new asset.
        Inputs:  asset - an `Asset` not yet in the database.
        Output:  the persisted asset, with its generated id populated.
        Raises:  `ConflictError` when the name is already taken - the unique
                 constraint is the authority, not a prior SELECT, which two
                 concurrent requests could both pass.
        """
        self._session.add(asset)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(
                f"An asset named {asset.name!r} already exists.",
                {"field": "name", "value": asset.name},
            ) from exc
        self._session.refresh(asset)
        return asset

    def update(self, asset: Asset, changes: dict[str, object]) -> Asset:
        """
        Purpose: apply a set of field changes to an existing asset.
        Inputs:  asset - the row to change, already loaded in this session.
                 changes - attribute name to new value, already validated by
                           the caller.
        Output:  the updated asset.
        Raises:  `ConflictError` when a changed name collides with another
                 asset's.
        """
        for field, value in changes.items():
            setattr(asset, field, value)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(
                f"An asset named {asset.name!r} already exists.",
                {"field": "name", "value": asset.name},
            ) from exc
        self._session.refresh(asset)
        return asset

    def delete(self, asset: Asset) -> None:
        """
        Purpose: remove an asset permanently.
        Inputs:  asset - the row to delete, already loaded in this session.
        Output:  None.
        """
        self._session.delete(asset)
        self._session.commit()
